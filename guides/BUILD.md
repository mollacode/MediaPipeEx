# MediaPipe 1.2.2 source·의존성 준비

이 저장소에는 빌드된 SDK, 다운로드 archive, 설치형 Python/CMake/Bazel, 모델이 없다. 다음은 기존 관리 recipe가 기대하는 준비 계약이다. 게시 작업에서 compiler를 다시 실행하지 않았으며 새로운 host/toolchain에서 byte-identical SDK를 보장하지 않는다.

## 공통

저장소 루트에서 `python3 tools/prepare_sources.py 1.2.2`를 실행한다. 원본 HEAD를 유지해야 기존 recipe의 `git show HEAD` 기반 원본 대조가 동작한다. SDK source가 아니라 script·문서만 준비됐다는 것을 전체 빌드 성공으로 해석하지 않는다.

## Android

[입력 manifest](../1.2.2/input-manifest.json)의 공식 URL/version/SHA로 tasks-core AAR을 별도 취득한다. 준비된 Android SDK의 android.jar, JDK의 `javac`/`jar`, Python3.11 이상이 필요하다. CLI:

```sh
mkdir -p 1.2.2/android/workspace
python3 1.2.2/android/rebuild_tasks_core.py --help
python3 1.2.2/android/rebuild_tasks_core.py \
  --input 1.2.2/android/inputs/tasks-core-1.2.2.aar \
  --android-jar "$ANDROID_SDK_ROOT/platforms/android-37/android.jar" \
  --license 1.2.2/LICENSE \
  --output 1.2.2/android/workspace/tasks-core-findwig.aar
```

입력·출력은 다른 파일이어야 한다. 출력 경로는 이미 있으면 거절된다. native 추론 library나 얼굴/상체 모델을 변경하는 recipe가 아니다. upstream source commit과 AAR 배포물의 version을 섞지 않는다.

## iOS 도구

기존 검증은 macOS Intel, Xcode26.2, Python3.11.14, CMake3.24.0, Bazel7.7.0, deployment target iOS15를 사용했다. Apple Silicon에서 slice를 만들 수 있다는 사실과 그 host에서 전체 build를 실행했다는 사실은 별개다.

공식 source release/tool 배포처에서 별도 설치하고 recipe가 읽는 다음 위치를 준비한다. 도구 binary는 게시하지 않는다.

- `1.2.2/ios/tools/cpython-3.11.14-macos-x86_64-none/bin/python3.11`: python-build-standalone/공식 Python 배포 정보를 확인하여 설치한 Python3.11.14. 기존 recipe는 이 관리 위치를 사용한다.
- `1.2.2/ios/tools/cmake-3.24.0-macos-universal/CMake.app/Contents/bin/cmake`: [CMake3.24.0](https://github.com/Kitware/CMake/releases/tag/v3.24.0).
- `1.2.2/ios/tools/bazel-7.7.0-darwin-x86_64`: [Bazel7.7.0](https://github.com/bazelbuild/bazel/releases/tag/7.7.0).

독립 도구 재설치·호스트 차이의 새 native build는 이 게시 작업의 실행 범위가 아니다. 공개 입력 manifest의 hash는 과거 확보본 기준이며 현재 URL의 영구 가용성을 보장하지 않는다.

## OpenCV source 빌드 입력

전체 patch에는 local source-built OpenCV ZIP을 사용하는 Bazel 입력 경로가 있다. 필요한 source는 **OpenCV4.5.3**, [공식 source ZIP](https://github.com/opencv/opencv/archive/refs/tags/4.5.3.zip)이며 pinned SHA-256은 `a61e7a4618d353140c857f25843f39b2abe5f451b018aab1604ef0bc34cd23d5`다. 이 값은 고정 upstream WORKSPACE의 `ios_opencv_source`에서 확인할 수 있다.

1. 공식 source ZIP의 SHA를 확인하고 별도 새 작업 폴더로 추출한다. 준비된 source root는 `opencv-4.5.3`이다.
2. [opencv_zlib_modern_apple.patch](../1.2.2/ios/inputs/opencv_zlib_modern_apple.patch)를 source root에서 `git apply -p2 --check`, `git apply -p2`로 적용한다. patch 경로의 `a/opencv-4.5.3/` 두 부분을 제거한다. 기존 사용자 source를 덮어쓰지 않는다.
3. CMake3.24.0과 준비된 Python을 PATH에 두고 다음 명령을 OpenCV source root에서 실행한다. OUT은 존재하지 않는 새 output 디렉터리의 절대 경로로 선택한다.

```sh
IPHONEOS_DEPLOYMENT_TARGET=15.0 python3 platforms/apple/build_xcframework.py \
  --iphonesimulator_archs arm64,x86_64 --iphoneos_archs arm64 \
  --without dnn --without ml --without stitching --without photo \
  --without objdetect --without gapi --without flann --without highgui \
  --without videoio --disable PROTOBUF --disable-bitcode --disable-swift \
  --build_only_specified_archs --out "$OUT"
```

이 명령은 저장소에 포함한 [opencv_ios_source.BUILD.source-build](../1.2.2/ios/inputs/opencv_ios_source.BUILD.source-build)의 source-build 명령과 같다. 생성 framework를 검사하여 device arm64와 simulator arm64/x86_64인지 확인한다. OUT에서 `zip --symlinks -r opencv2.xcframework.zip opencv2.xcframework`로 묶고, 저장소의 `1.2.2/ios/inputs/source-built-opencv2.xcframework.zip`에 **로컬에서만** 저장한다. 기존 파일이 있으면 먼저 보존하고 임의로 덮어쓰지 않는다.

저장소 루트에서 현재 생성 ZIP·도구 fingerprint 기록을 만든다.

```sh
python3 1.2.2/ios/record_opencv_input.py \
  --zip 1.2.2/ios/inputs/source-built-opencv2.xcframework.zip \
  --output 1.2.2/ios/inputs/source-built-opencv2.json
```

이 작은 도구는 SDK를 빌드하거나 다운로드하지 않고 기존 record를 덮어쓰지 않는다. 새 빌드 ZIP의 timestamp/toolchain으로 hash가 달라질 수 있으므로 과거 검증본과 같다고 꾸미지 않는다. slice명 검사는 architecture binary 검사 자체를 대신하지 않는다. 초기 source helper는 생성 ZIP을 요구하지 않지만 **iOS SDK 빌드 recipe는 이 입력과 record가 있어야 실행 가능**하다.

## iOS source SDK 빌드·링크

```sh
python3 1.2.2/ios/build_ios_source.py --jobs 2
python3 1.2.2/ios/query_link_inputs.py
python3 1.2.2/ios/package_source_sdk.py packaged-local
```

첫 단계가 세 source archive를 완료한 뒤 실제 CcInfo 입력을 query하고 마지막으로 새 staging label에 링크·패키지한다. 기존 SDK나 제품 Vendor를 자동 교체하지 않는다. 사용되지 않는 공식 prebuilt iOS SDK를 다운로드할 필요는 없다. Bazel의 transitive source는 고정 MODULE/WORKSPACE에서 별도로 취득되며 캐시는 Git에서 제외한다. recipe의 디스크 여유20GiB 보호선과 archive/architecture/notice 검사를 유지한다.

compiler·network 의존성·서명/배포의 실행은 source 복원과 별도다. 생성물·로컬 도구는 `.gitignore` allowlist 밖에 남고 Git LFS로 게시하지 않는다.
