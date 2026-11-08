# MediaPipeEx — MediaPipe 1.2.2 수정 소스

MediaPipe **v1.2.2**의 iOS Face Landmarker stream 설정 보완과 공개 source 빌드 호환 변경, Android의 deterministic metrics-free core 재구성 recipe를 제공한다. 컴파일된 SDK·모델·다운로드한 archive·캐시·개인 미디어는 포함하지 않는다.

| 항목 | 위치 |
|---|---|
| 공식 고정 원본 | [1.2.2/source/upstream](1.2.2/source/upstream), commit `2c2d4a7454d6358e0d6f0b54e254d231fe4cc78f` |
| 전체 수정 patch | [changes.patch](1.2.2/source-state/changes.patch) |
| 변경된 실제 source | [source-state/files](1.2.2/source-state/files) |
| source 복원 계약 | [manifest.json](1.2.2/source-state/manifest.json) |
| 의존성 준비·빌드·한계 | [guides/BUILD.md](guides/BUILD.md) |
| 공식 Android/iOS 입력 URL·SHA | [input-manifest.json](1.2.2/input-manifest.json) |

## 수정 내용

- iOS Face Landmarker: `runningMode != MPPRunningModeImage`를 공개 base-options helper의 `withUseStreamMode`로 전달한다. IMAGE는 false를 유지한다. VIDEO 그래프의 stream 경로가 설정되지 않는 문제를 대상으로 하며 추적 모델·추론 정밀도를 바꾸지 않는다.
- 공개 source 빌드: simulator x86_64 포함, 사용할 수 없는 interactive segmenter API와 공개 closure에서 링크할 수 없는 retrieval 의존성의 배포 제외, Abseil header ownership, `absl::MakeCleanup`의 include·직접 Bazel 의존성을 보완한다. 제외 API를 제공한다고 주장하지 않는다.
- OpenCV: 로컬에서 source-build한 framework ZIP을 재사용하는 경로가 전체 patch에 포함된다. ZIP은 Git에서 제외한다. [준비 절차](guides/BUILD.md#opencv-source-빌드-입력)로 먼저 생성해야 iOS 빌드가 가능하다.
- Android: 공식 tasks-core AAR에서 remote metrics logger 구현을 제외하고 공개 no-op logger factory로 재구성하는 [source recipe](1.2.2/android/rebuild_tasks_core.py)를 제공한다. 결과 AAR을 게시하거나 공식 AAR을 덮어쓰지 않는다.

관련 upstream 보고: [google-ai-edge/mediapipe#6393의 보완 댓글](https://github.com/google-ai-edge/mediapipe/issues/6393#issuecomment-6718374135).

## source 준비

Python **3.11 이상**, Git을 사용한다.

```sh
git clone --recurse-submodules https://github.com/mollacode/MediaPipeEx.git
cd MediaPipeEx
python3 tools/prepare_sources.py 1.2.2
python3 tools/prepare_sources.py 1.2.2 --verify-only
```

이미 clone했다면 `git submodule update --init --depth 1`로 원본을 준비한다. helper는 원본 HEAD를 유지하는 linked worktree에 전체 patch·lockfile·추가 source를 적용한다. source checksum과 file mode를 검사하며 기존 수정 source는 reset/덮어쓰기하지 않는다. `source-state/files`는 검토용이며 SDK 빌드는 준비된 `source/findwig`에서 한다.

## 검증·라이선스 경계

과거 iOS 검증은 device arm64와 simulator arm64/x86_64, IMAGE/VIDEO 및 당시 제품 closure에 한정한다. LIVE_STREAM은 source 분기 확인을 실행 검증으로 확대하지 않는다. 호환 변경에는 공개되지 않은 일부 API 제외가 있어 원본의 모든 API를 제공하는 drop-in SDK라고 주장하지 않는다. 이번 게시 작업의 source 복원 검증은 새 전체 빌드·성능·카메라 품질 검증이 아니다.

[LICENSE](LICENSE)·[NOTICE](NOTICE) 및 upstream third-party notices를 보존한다. [MediaPipe Solution API 약관](https://developers.google.com/edge/mediapipe/legal/tos)과 개별 모델 조건은 source Apache-2.0과 별개다. no-op logger recipe가 다른 앱의 네트워크 동작이나 법적 의무까지 해결한다는 의미는 아니다. 새 공개 source를 추가할 때 루트 `.gitignore` allowlist를 갱신한다.
