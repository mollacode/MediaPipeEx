#!/usr/bin/env python3
"""Rebuild MediaPipe 1.2.2's no-op Java logging boundary deterministically."""
from pathlib import Path
import argparse
import hashlib
import io
import json
import shutil
import subprocess
import tempfile
import zipfile

INPUT_SHA256 = '7ed8d0d473af0ad62914401226199f595683001a6930f0f46a0d32af70eeb048'
LOGGING = 'com/google/mediapipe/tasks/core/logging/'
FACTORY = LOGGING + 'TasksStatsLoggerFactory.class'
REMOVED = {LOGGING + name + '.class' for name in (
    'LoggingClient', 'RemoteLoggingClient', 'TasksStatsProtoLogger')}
PROTO_PREFIXES = ('com/google/mediapipe/proto/MediaPipeLoggingEnumsProto',
                  'com/google/mediapipe/proto/MediaPipeLoggingProto')
SOURCE = '''/*
 * Copyright 2026 The MediaPipe Authors.
 * Licensed under the Apache License, Version 2.0.
 * Find Wig modification: use the public no-op logger and retain the public ABI.
 */
package com.google.mediapipe.tasks.core.logging;
import android.content.Context;
public final class TasksStatsLoggerFactory {
  public TasksStatsLoggerFactory() {}
  public static TasksStatsLogger create(Context context, String task, String mode) {
    return TasksStatsDummyLogger.create(context, task, mode);
  }
}
'''
NOTICE = '''MediaPipe Tasks Core 1.2.2 / Find Wig no-op metrics derivative
The public TasksStatsLoggerFactory.create signature and constructor are retained.
The factory delegates only to the upstream TasksStatsDummyLogger.
Remote logging client/proto implementation classes and logging-only protobufs
are excluded. Upstream native libraries and all other payload bytes are retained.
Source, input SHA-256 and reproducible recipe accompany this artifact.
Upstream license: Apache-2.0. Modification: Find Wig, 2026.
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def archive(files):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as dest:
        for name, data in sorted(files.items()):
            path = Path(name)
            if path.is_absolute() or '..' in path.parts:
                raise RuntimeError('unsafe upstream archive entry')
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            dest.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED,
                          compresslevel=9)
    return stream.getvalue()


def contents(data):
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        names = [i.filename for i in source.infolist() if not i.is_dir()]
        if len(names) != len(set(names)):
            raise RuntimeError('duplicate archive entry')
        return {name: source.read(name) for name in names}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--android-jar', type=Path, required=True)
    parser.add_argument('--license', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.with_suffix('.json').exists():
        raise RuntimeError('refusing to overwrite an existing artifact')
    if shutil.disk_usage(args.output.parent).free < 20 * 1024**3:
        raise RuntimeError('approved disk reserve reached')
    original = args.input.read_bytes()
    if sha(original) != INPUT_SHA256:
        raise RuntimeError('unrecognized upstream 1.2.2 artifact')
    aar = contents(original)
    classes = contents(aar['classes.jar'])
    workspace = Path(__file__).resolve().parent / 'workspace' / 'tmp'
    workspace.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='core-', dir=workspace) as work:
        work = Path(work)
        jar = work / 'upstream.jar'
        jar.write_bytes(aar['classes.jar'])
        source = work / 'TasksStatsLoggerFactory.java'
        source.write_text(SOURCE)
        dest = work / 'compiled'
        dest.mkdir()
        subprocess.run(['javac', '--release', '8', '-cp',
                        str(jar) + ':' + str(args.android_jar), '-d', str(dest),
                        str(source)], check=True, timeout=60)
        compiled = (dest / FACTORY).read_bytes()
    deleted = sorted(n for n in classes if n in REMOVED or
                     any(n.startswith(prefix) for prefix in PROTO_PREFIXES))
    for name in deleted:
        del classes[name]
    classes[FACTORY] = compiled
    forbidden_refs = [name for name, data in classes.items()
                      if name.endswith('.class') and any(ref in data for ref in (
                          b'com/google/android/datatransport',
                          b'com/google/mediapipe/tasks/core/logging/RemoteLoggingClient',
                          b'com/google/mediapipe/tasks/core/logging/TasksStatsProtoLogger',
                          b'com/google/mediapipe/proto/MediaPipeLogging'))]
    if forbidden_refs:
        raise RuntimeError('residual remote metrics references: ' + str(forbidden_refs))
    aar['classes.jar'] = archive(classes)
    aar['META-INF/LICENSE'] = args.license.read_bytes()
    aar['META-INF/FIND_WIG_MODIFICATIONS.txt'] = NOTICE.encode()
    result = archive(aar)
    native = {name: sha(data) for name, data in aar.items() if name.endswith('.so')}
    args.output.write_bytes(result)
    manifest = {'upstream': 'google-ai-edge/mediapipe v1.2.2',
                'inputSha256': INPUT_SHA256, 'artifactSha256': sha(result),
                'bytes': len(result), 'deletedClasses': deleted,
                'nativeSha256': native, 'factorySourceSha256': sha(SOURCE.encode()),
                'publicFactoryConstructorPreserved': True,
                'forbiddenReferences': forbidden_refs}
    args.output.with_suffix('.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
