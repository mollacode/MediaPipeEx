#!/usr/bin/env python3
"""Approved 1.2.2 public-source iOS build; no consumer installation."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import shutil
import signal
import sys
import subprocess
import time

# Canonical recipe and owned inputs live below MediaPipe/1.2.2/.
ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / 'source/findwig'
WORK = ROOT / 'ios/workspace'
EXPECTED = '2c2d4a7454d6358e0d6f0b54e254d231fe4cc78f'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    assert subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'],
                                   text=True).strip() == EXPECTED
    assert (SOURCE / '.bazelversion').read_text().strip() == '7.7.0'
    parser = argparse.ArgumentParser()
    parser.add_argument('--cohort', type=Path, help='Optional approved execution ledger')
    parser.add_argument('--graphs-only', action='store_true', help='Resume only the already-prepared Graphs archive')
    parser.add_argument('--jobs', type=int, choices=(1,2,3,4), default=2, help='Compiler parallelism, within the unchanged 6GiB resource pool')
    args = parser.parse_args()
    cohort = args.cohort.resolve(strict=True) if args.cohort else None
    budget = json.loads((cohort/'budget.json').read_text()) if cohort else None
    deadline = (datetime.datetime.fromisoformat(budget['deadline'])
                if budget is not None and not budget.get('limitsWaivedByUser', False) else None)
    reserve = budget['freeBytesMinimum'] if budget else 20*1024**3
    storage = None
    if cohort:
        import importlib.util
        spec = importlib.util.spec_from_file_location('cohort_storage', cohort/'storage_accounting.py')
        storage = importlib.util.module_from_spec(spec); spec.loader.exec_module(storage)
        storage.check(budget)
    elif shutil.disk_usage(ROOT).free < reserve:
        raise RuntimeError('operational disk reserve before source SDK build')
    for sub in ('tmp', 'cache/repository', 'logs', 'output'):
        (WORK / sub).mkdir(parents=True, exist_ok=True)
    cv = ROOT / 'ios/inputs/source-built-opencv2.xcframework.zip'
    manifest = json.loads((ROOT / 'ios/inputs/source-built-opencv2.json').read_text())
    assert sha(cv) == manifest['sha256']
    recipe = ROOT / 'ios/inputs/opencv_ios_source.BUILD.source-build'
    toolchain = subprocess.check_output(['xcodebuild', '-version'])
    for platform in ('iphoneos', 'iphonesimulator'):
        toolchain += subprocess.check_output(['xcrun', '--sdk', platform, '--show-sdk-version'])
    fingerprint = hashlib.sha256(toolchain + recipe.read_bytes() +
        (ROOT / 'ios/inputs/opencv_zlib_modern_apple.patch').read_bytes() +
        b'opencv4.5.3;cmake3.24.0;iOS15;Xcode26.2').hexdigest()
    assert fingerprint == manifest['inputFingerprint']
    workspace_text = (SOURCE / 'WORKSPACE').read_text()
    assert 'a61e7a4618d353140c857f25843f39b2abe5f451b018aab1604ef0bc34cd23d5' in workspace_text
    seed = SOURCE / 'third_party/find_wig_source_built_opencv.zip'
    if not seed.exists():
        shutil.copy2(cv, seed)
    assert sha(seed) == manifest['sha256']
    cv_build = SOURCE / 'third_party/opencv_ios_source.BUILD'
    original_cv = subprocess.check_output(['git', '-C', str(SOURCE), 'show',
        'HEAD:third_party/opencv_ios_source.BUILD'], text=True)
    start = original_cv.index('    cmd = "&&".join([')
    end = original_cv.index('    ]),', start) + len('    ]),')
    changed_cv = original_cv[:start] + '    cmd = "cp $(location @//third_party:find_wig_source_built_opencv.zip) $@",' + original_cv[end:]
    changed_cv = changed_cv.replace('srcs = glob(["opencv-4.5.3/**"])',
        'srcs = ["@//third_party:find_wig_source_built_opencv.zip"]', 1)
    cv_build.write_text(changed_cv)
    third = SOURCE / 'third_party/BUILD'
    export = 'exports_files(["find_wig_source_built_opencv.zip"], visibility = ["//visibility:public"])'
    if export not in third.read_text():
        third.write_text(third.read_text() + '\n' + export + '\n')
    rules = SOURCE / 'mediapipe/tasks/ios/ios_build_rules.bzl'
    original_rules = subprocess.check_output(['git', '-C', str(SOURCE), 'show',
        'HEAD:mediapipe/tasks/ios/ios_build_rules.bzl'], text=True)
    anchor = '"simulator": [\n                "arm64",\n            ],'
    assert original_rules.count(anchor) == 1
    rules.write_text(original_rules.replace(anchor,
        '"simulator": [\n                "arm64",\n                "x86_64",\n            ],'))
    # The public v1.2.2 archive references a non-exported interactive_segmenter package.
    # Remove only that unavailable API; retain legacy segmentation and the complete Face graph.
    ios_build = SOURCE / 'mediapipe/tasks/ios/BUILD'
    original_build = subprocess.check_output(['git', '-C', str(SOURCE), 'show',
        'HEAD:mediapipe/tasks/ios/BUILD'], text=True)
    unavailable = ('//mediapipe/tasks/ios/vision/interactive_segmenter:',
                   '//mediapipe/tasks/cc/vision/interactive_segmenter:')
    excluded_headers = ('":MPPInteractiveSegmenter.h"', '":MPPInteractiveSegmenterOptions.h"', '":MPPStroke.h"')
    changed_build = ''.join(line for line in original_build.splitlines(keepends=True)
        if not any(item in line for item in unavailable + excluded_headers))
    # Retrieval is not a Find Wig/Vision API. Its newly added private prebuilt
    # SQLite stores require iOS26.4 and internal proto2/Abseil symbols unavailable
    # in this public source closure. Keep the source, but do not ship those deps.
    common_start = changed_build.index('MEDIAPIPE_TASKS_COMMON_DEPS = ')
    common_end = changed_build.index('\n]\n', common_start) + len('\n]\n')
    common_body = changed_build[common_start:common_end]
    retrieval_deps = [line for line in common_body.splitlines(keepends=True)
        if '//mediapipe/tasks/ios/retrieval/' in line]
    assert len(retrieval_deps) == 5
    common_body = ''.join(line for line in common_body.splitlines(keepends=True)
        if '//mediapipe/tasks/ios/retrieval/' not in line)
    ios_build.write_text(changed_build[:common_start] + common_body + changed_build[common_end:])
    # Preserve strict host module checking; only clarify existing header ownership.
    abseil_patch = ROOT / 'ios/inputs/abseil_apple_strict_header_ownership.patch'
    patch_name = 'find_wig_abseil_apple_strict_header_ownership.patch'
    shutil.copy2(abseil_patch, SOURCE / 'third_party' / patch_name)
    patch_export = 'exports_files(["' + patch_name + '"], visibility = ["//visibility:public"])'
    if patch_export not in third.read_text():
        third.write_text(third.read_text() + '\n' + patch_export + '\n')
    module = SOURCE / 'MODULE.bazel'
    original_module = subprocess.check_output(['git', '-C', str(SOURCE), 'show',
        'HEAD:MODULE.bazel'], text=True)
    module_anchor = '    strip_prefix = "abseil-cpp-20260526.0",'
    assert original_module.count(module_anchor) == 1
    module.write_text(original_module.replace(module_anchor, module_anchor +
        '\n    patches = ["//third_party:' + patch_name + '"],\n    patch_strip = 1,'))
    # The public Metal path calls absl::MakeCleanup without its defining header.
    # Declare that existing API and its direct Bazel dependency; no runtime logic changes.
    runner_path = 'mediapipe/calculators/tensor/inference_runner_litert.cc'
    original_runner = subprocess.check_output(['git', '-C', str(SOURCE), 'show',
        'HEAD:' + runner_path], text=True)
    include_anchor = '#include "absl/base/nullability.h"'
    assert original_runner.count(include_anchor) == 1
    line_end = original_runner.index('\n', original_runner.index(include_anchor)) + 1
    (SOURCE / runner_path).write_text(original_runner[:line_end] +
        '#include "absl/cleanup/cleanup.h"  // from @com_google_absl\n' + original_runner[line_end:])
    tensor_build = 'mediapipe/calculators/tensor/BUILD'
    original_tensor_build = subprocess.check_output(['git', '-C', str(SOURCE), 'show',
        'HEAD:' + tensor_build], text=True)
    target_start = original_tensor_build.index('    name = "inference_runner_litert",')
    target_end = original_tensor_build.index('\ncc_library(', target_start)
    target_body = original_tensor_build[target_start:target_end]
    dep_anchor = '        "@com_google_absl//absl/container:flat_hash_map",'
    assert target_body.count(dep_anchor) == 1
    target_body = target_body.replace(dep_anchor,
        '        "@com_google_absl//absl/cleanup",\n' + dep_anchor)
    (SOURCE / tensor_build).write_text(original_tensor_build[:target_start] +
        target_body + original_tensor_build[target_end:])
    # The actual linked1.2.2 iPhone probe reproduced missing VIDEO stream mode.
    # Use the existing public helper overload; IMAGE explicitly remains false.
    helper_path = 'mediapipe/tasks/ios/vision/face_landmarker/utils/sources/MPPFaceLandmarkerOptions+Helpers.mm'
    original_helper = subprocess.check_output(['git', '-C', str(SOURCE), 'show',
        'HEAD:' + helper_path], text=True)
    helper_anchor = '  [self.baseOptions copyToProto:faceLandmarkerGraphOptions->mutable_base_options()];'
    assert original_helper.count(helper_anchor) == 1
    (SOURCE / helper_path).write_text(original_helper.replace(helper_anchor,
        '  [self.baseOptions copyToProto:faceLandmarkerGraphOptions->mutable_base_options()\n'
        '             withUseStreamMode:self.runningMode != MPPRunningModeImage];'))
    (ROOT / 'ios/face_landmarker_stream_mode.patch').write_bytes(subprocess.check_output(
        ['git', '-C', str(SOURCE), 'diff', '--', helper_path]))
    factory = SOURCE / 'mediapipe/tasks/cc/core/logging/factory/logging_factory.cc'
    assert 'return TasksDummyLogger::Create();' in factory.read_text()
    patch = subprocess.check_output(['git', '-C', str(SOURCE), 'diff', '--',
        'MODULE.bazel', 'third_party/BUILD', 'third_party/opencv_ios_source.BUILD',
        'mediapipe/tasks/ios/ios_build_rules.bzl', 'mediapipe/tasks/ios/BUILD',
        'mediapipe/calculators/tensor/inference_runner_litert.cc',
        'mediapipe/calculators/tensor/BUILD'])
    (ROOT / 'ios/public_source_build_compatibility.patch').write_bytes(patch)
    env = os.environ.copy()
    python = (ROOT / 'ios/tools') / 'cpython-3.11.14-macos-x86_64-none/bin/python3.11'
    cmake = (ROOT / 'ios/tools') / 'cmake-3.24.0-macos-universal/CMake.app/Contents/bin'
    assert python.is_file() and (cmake / 'cmake').is_file()
    env.update({'PATH': str(cmake) + os.pathsep + str(python.parent) + os.pathsep + env['PATH'],
        'HERMETIC_PYTHON_VERSION': '3.11', 'PYTHON_BIN_PATH': str(python),
        'PYTHON_LIB_PATH': str(python.parent.parent / 'lib/python3.11/site-packages'),
        'TMPDIR': str(WORK / 'tmp'), 'XDG_CACHE_HOME': str(WORK / 'cache/xdg')})
    bazel = ROOT / 'ios/tools/bazel-7.7.0-darwin-x86_64'
    command = [str(bazel), '--batch', '--output_user_root=' + str(WORK / 'cache/bazel'),
        '--host_jvm_args=-Xmx2g', 'build', '-c', 'opt', '--apple_generate_dsym=false',
        '--apple_crosstool_top=@local_config_apple_cc//:toolchain', '--define=OPENCV=source',
        '--jobs=' + str(args.jobs), '--local_resources=memory=6144',
        '--distdir=' + str(ROOT / 'ios/inputs/distdir'),
        '--repository_cache=' + str(WORK / 'cache/repository'),
        '--config=ios_sim_device_fat', '--verbose_failures',
]
    results_file = WORK / 'build-results.json'
    records = json.loads(results_file.read_text()) if results_file.exists() else []
    targets = ('MediaPipeTaskGraphs_library',) if args.graphs_only else (
        'MediaPipeTasksCommon_framework', 'MediaPipeTasksVision_framework',
        'MediaPipeTaskGraphs_library')
    for target in targets:
        cmd = command + ['//mediapipe/tasks/ios:' + target]
        log = WORK / 'logs' / (target + '.log')
        started = time.monotonic()
        reason = None
        with log.open('ab') as output:
            process = subprocess.Popen(cmd, cwd=SOURCE, env=env, stdout=output,
                stderr=subprocess.STDOUT, start_new_session=True)
            last_storage_check = time.monotonic()
            try:
                while process.poll() is None:
                    free = shutil.disk_usage(ROOT).free
                    if deadline is not None and datetime.datetime.now().astimezone() >= deadline:
                        reason = 'approved wall deadline reached'
                    elif free < reserve:
                        reason = 'approved free-space reserve reached'
                    elif storage is not None and time.monotonic()-last_storage_check >= (600 if budget.get('limitsWaivedByUser', False) else 20):
                        last_storage_check=time.monotonic()
                        measured=storage.snapshot(budget)
                        (cohort/'storage-current.json').write_text(json.dumps(measured,indent=2)+'\n')
                        if not measured['safe']:
                            reason='approved task-owned generated-data allowance reached'
                    if reason:
                        raise RuntimeError(reason)
                    time.sleep(5)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=10)
                elapsed=time.monotonic()-started
                records.append({'target': target, 'exit': process.returncode,
                    'seconds': elapsed, 'log': str(log.relative_to(ROOT)), 'stopReason':reason})
                results_file.write_text(json.dumps(records, indent=2)+'\n')
                if storage is not None:
                    storage.charge_budget(cohort/'budget.json','heavySecondsUsed',elapsed)
                print(json.dumps(records[-1]),flush=True)

        if process.returncode:
            raise SystemExit(process.returncode)

    if not args.graphs_only:
        query_args = [sys.executable, str(ROOT / 'ios/query_link_inputs.py')]
        subprocess.run(query_args, check=True)


if __name__ == '__main__':
    main()
