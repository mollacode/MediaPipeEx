#!/usr/bin/env python3
"""Record a locally source-built OpenCV input for build_ios_source.py.

Does not build, download, copy, or publish a framework. Refuses to overwrite a
previous record. Use the source/version/toolchain described in guides/BUILD.md.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    sdk = Path(__file__).resolve().parent.parent
    if args.output.exists():
        parser.error("output already exists; preserve the previous record")
    with zipfile.ZipFile(args.zip) as archive:
        if archive.testzip() is not None:
            parser.error("invalid framework ZIP")
        names = archive.namelist()
        if not any("ios-arm64/" in p for p in names) or not any(
                "ios-arm64_x86_64-simulator/" in p for p in names):
            parser.error("expected device arm64 and simulator arm64/x86_64 framework slices")
    toolchain = subprocess.check_output(["xcodebuild", "-version"])
    for platform in ("iphoneos", "iphonesimulator"):
        toolchain += subprocess.check_output(["xcrun", "--sdk", platform, "--show-sdk-version"])
    fingerprint = hashlib.sha256(
        toolchain + (sdk / "ios/inputs/opencv_ios_source.BUILD.source-build").read_bytes()
        + (sdk / "ios/inputs/opencv_zlib_modern_apple.patch").read_bytes()
        + b"opencv4.5.3;cmake3.24.0;iOS15;Xcode26.2"
    ).hexdigest()
    with args.zip.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    record = {"sha256": checksum, "inputFingerprint": fingerprint,
              "slices": {"device": ["arm64"], "simulator": ["arm64", "x86_64"]},
              "origin": "locally source-built OpenCV 4.5.3; inspect slices before SDK packaging"}
    with args.output.open("x") as stream:
        stream.write(json.dumps(record, indent=2) + "\n")


if __name__ == "__main__":
    main()
