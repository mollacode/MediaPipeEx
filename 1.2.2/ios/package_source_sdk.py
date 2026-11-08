#!/usr/bin/env python3
"""Link only complete, public-source SDK archives into staging XCFrameworks.

Run only after the three source archives complete. Never updates the product Vendor directory.
"""
import gzip, hashlib, json, plistlib, re, shutil, subprocess, sys, zipfile
from pathlib import Path

SDK = Path(__file__).resolve().parent.parent
ROOT = SDK / "ios/workspace"
SOURCE = SDK / "source/findwig"
assert subprocess.check_output(["git","-C",str(SOURCE),"rev-parse","HEAD"],text=True).strip() == "2c2d4a7454d6358e0d6f0b54e254d231fe4cc78f"
assert "return TasksDummyLogger::Create();" in (SOURCE/"mediapipe/tasks/cc/core/logging/factory/logging_factory.cc").read_text()
label=sys.argv[1] if len(sys.argv)>1 else "packaged-baseline"
assert re.fullmatch("[a-z0-9_-]+",label), "safe fresh staging label required"
BIN = SOURCE / "bazel-bin/mediapipe/tasks/ios"
OUT = ROOT / label
assert not OUT.exists(), "use a fresh reviewed staging destination"
OUT.mkdir()
records = []

def run(args):
    subprocess.run(list(map(str,args)),check=True)

def read_archive(data):
    """Read BSD ar long names without overwriting duplicate member filenames."""
    assert data.startswith(b"!<arch>\n")
    pos = 8
    while pos < len(data):
        header = data[pos:pos+60]
        assert len(header)==60 and header[58:]==b"`\n"
        size = int(header[48:58]); name = header[:16].decode().strip()
        payload = data[pos+60:pos+60+size]
        assert len(payload)==size
        pos += 60 + size + (size % 2)
        if name.startswith("#1/"):
            length = int(name[3:]); name = payload[:length].rstrip(b"\0").decode()
            payload = payload[length:]
        if name.startswith("__.SYMDEF") or name in ("/", "//"): continue
        assert payload[:4] in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"), name
        yield payload
    assert pos == len(data)

def extract_validated(zipped, destination):
    """Keep framework symlinks, rejecting any destination outside staging."""
    destination.mkdir(parents=True, exist_ok=True)
    for item in zipped.infolist():
        name=Path(item.filename)
        assert not name.is_absolute() and ".." not in name.parts
        target=destination/name
        assert target.resolve().is_relative_to(destination.resolve())
        if (item.external_attr >> 16) & 0o170000 == 0o120000:
            link=zipped.read(item).decode()
            assert not Path(link).is_absolute()
            assert (target.parent/link).resolve().is_relative_to(destination.resolve())
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(link)
        else: zipped.extract(item, destination)

archives = {}
for key, target, filename in [
    ("common","MediaPipeTasksCommon","MediaPipeTasksCommon_framework.xcframework.zip"),
    ("vision","MediaPipeTasksVision","MediaPipeTasksVision_framework.xcframework.zip"),
    ("graphs","MediaPipeTaskGraphs_library","MediaPipeTaskGraphs_library.xcframework.zip"),
    ("opencv","opencv2","source-built-opencv2.xcframework.zip")]:
    src = (SDK / "ios/inputs" / filename) if key=="opencv" else (BIN / filename)
    assert src.is_file(), src
    dest = OUT / (key + "-static")
    with zipfile.ZipFile(src) as zipped:
        assert zipped.testzip() is None
        for info in zipped.infolist():
            name=Path(info.filename)
            assert not name.is_absolute() and ".." not in name.parts
        extract_validated(zipped, dest)
    roots = list(dest.glob("*.xcframework")); assert len(roots)==1
    info=plistlib.loads((roots[0]/"Info.plist").read_bytes())
    archives[key]={}
    for lib in info["AvailableLibraries"]:
        platform=lib.get("SupportedPlatformVariant","device")
        entry=roots[0]/lib["LibraryIdentifier"]
        library=entry/lib["LibraryPath"]
        assert set(lib["SupportedArchitectures"]) == ({"arm64"} if platform=="device" else {"arm64","x86_64"})
        if library.is_dir():
            assert library.name == target+".framework"
            binary=library/library.stem
            headers=library/"Headers"; modules=library/"Modules"
        else:
            assert library.is_file() and library.suffix==".a", str(library)
            binary=library
            headers=entry/lib.get("HeadersPath","Headers")
            modules=entry/"Modules"
        archives[key][platform] = dict(binary=binary,headers=headers,modules=modules)
    assert set(archives[key])=={"device","simulator"}
    records.append({"input":filename,"sha256":hashlib.sha256(src.read_bytes()).hexdigest()})

# Preserve notices for the actual static archive link closure, plus inline
# numerical headers and the source-built OpenCV dependency.
def collect_notices():
    external=next((ROOT/"cache/bazel").glob("*/external"))
    repositories=set()
    for stem in ["MediaPipeTasksCommon_framework","MediaPipeTaskGraphs_library"]:
        params=list(BIN.glob(stem+"*-fl.a-2.params"))
        assert len(params)>=3, "need all three actual archive link-input records: "+stem
        for param in params:
            repositories.update(re.findall(r"/external/([^/\s]+)",param.read_text()))
    assert repositories, "source archive dependency closure must not be empty"
    repositories.update(name for name in ["ios_opencv_source","eigen_archive","eigen","FP16","FXdiv","psimd"] if (external/name).is_dir())
    notices=OUT/"Notices";notices.mkdir()
    shutil.copyfile(SOURCE/"LICENSE",notices/"MediaPipe-LICENSE.txt")
    special={
     "com_google_sentencepiece":["sentencepiece/LICENSE","sentencepiece/third_party/*/LICENSE"],
     "icu":["icu4c/LICENSE","vendor/double-conversion/upstream/LICENSE","vendor/double-conversion/upstream/COPYING"],
     "fft2d":["readme*.txt"],
     "pffft":["README.md","pffft.h","fftpack.h"],
     "ios_opencv_source":["opencv-4.5.3/LICENSE","opencv-4.5.3/doc/LICENSE*.txt","opencv-4.5.3/modules/core/3rdparty/SoftFloat/COPYING*","opencv-4.5.3/3rdparty/**/LICENSE*","opencv-4.5.3/3rdparty/**/COPYING*","opencv-4.5.3/3rdparty/**/README.ijg"],
     "org_tensorflow":["third_party/icu/data/LICENSE"]}
    notice_records=[]
    for repository in sorted(repositories):
        folder=external/repository
        candidates=[]
        for pattern in ["LICENSE*","COPYING*","NOTICE*","COPYRIGHT*","LICENSES/*"]+special.get(repository,[]):
            candidates.extend(p for p in folder.glob(pattern) if p.is_file())
        # New bzlmod names retain the same upstream notice locations.
        if not candidates:
            candidates=[p for p in folder.rglob("LICENSE*") if p.is_file()]
            candidates += [p for p in folder.rglob("COPYING*") if p.is_file()]
        assert candidates, "missing dependency notice: "+repository
        seen=set()
        for original in candidates:
            relative=original.relative_to(folder)
            if str(relative).casefold() in seen: continue
            seen.add(str(relative).casefold())
            data=original.read_bytes()
            if original.suffix==".h":
                text=data.decode();start=text.index("/*");end=text.index("*/",start)+2
                data=text[start:end].encode();relative=Path(str(relative)+".license-header.txt")
            target=notices/repository/relative
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
            notice_records.append({"repository":repository,"path":str(relative),"sha256":hashlib.sha256(data).hexdigest()})
    (notices/"NOTICE_INDEX.json").write_text(json.dumps(notice_records,indent=2)+"\n")
    (notices/"README.txt").write_text("Notices retained from the pinned MediaPipe public-source link inputs and source-built OpenCV. OpenCV bundled notices may cover optional components not linked in this build. See the source input and link manifests for the exact binary closure. Build-only tools are not shipped.\n")
    (notices/'FIND_WIG_MODIFICATIONS.txt').write_text(
        "Find Wig source SDK derived from MediaPipe1.2.2 / 2c2d4a7454d6358e0d6f0b54e254d231fe4cc78f.\n"
        "FaceLandmarkerOptions helper: explicitly serialize use_stream_mode for VIDEO/LIVE_STREAM, false for IMAGE.\n"
        "inference_runner_litert.cc/BUILD: declare the existing absl::MakeCleanup header and direct dependency; runtime cleanup unchanged.\n"
        "Apple BUILD metadata: preserve iOS15/device arm64/simulator arm64+x86_64; declare Abseil header ownership.\n"
        "Unavailable new interactive-segmenter references and unused retrieval private-prebuilt dependencies are excluded; Face and existing Vision graphs are preserved.\n"
        "OpenCV4.5.3 uses the pinned public source build. Public TasksDummyLogger is retained.\n"
        "Dynamic packaging preserves actual Bazel CcInfo alwayslink and normal archive extraction; no symbol-error suppression or private protobuf mixing.\n"
        "Source, patches, fixed inputs and rebuild tools are managed in MediaPipe/1.2.2/ios.\n")
    return notices, notice_records

notices, notice_records = collect_notices()
# The pinned TensorFlow ICU recipe declares this provider separately from
# icuuc. Reproduce its merge_conversion_data target, preserving the real data
# rather than suppressing the optional provider's undefined linker reference.
external=next((ROOT/"cache/bazel").glob("*/external"))
icu_data=external/"org_tensorflow/third_party/icu/data"
chunks=sorted(icu_data.glob("icu_conversion_data.c.gz.*")); assert chunks
conversion=gzip.decompress(b"".join(p.read_bytes() for p in chunks))
assert b"uprv_getICUData_conversion()" in conversion and b"icudt69l_dat" in conversion
conversion_source=OUT/"conversion_data.c"; conversion_source.write_bytes(conversion)
records.append({"input":"TensorFlow ICU conversion_data", "sha256":hashlib.sha256(conversion).hexdigest(),
                "chunks":[{"name":p.name,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for p in chunks]})
link_plan_path=ROOT/'output/source-link-plan.json'
link_plan=json.loads(link_plan_path.read_text())
assert link_plan['version']=='1.2.2' and link_plan['sourceCommit']=='2c2d4a7454d6358e0d6f0b54e254d231fe4cc78f'
assert link_plan['compatibilityPatchSha256']==hashlib.sha256((SDK/'ios/public_source_build_compatibility.patch').read_bytes()).hexdigest()
assert link_plan['streamModePatchSha256']==hashlib.sha256((SDK/'ios/face_landmarker_stream_mode.patch').read_bytes()).hexdigest()
for name,expected in link_plan['archives'].items():
    assert hashlib.sha256((BIN/name).read_bytes()).hexdigest()==expected, 'stale source archive link plan: '+name
assert set(link_plan['variants'])=={'device/arm64','simulator/arm64','simulator/x86_64'}
shutil.copyfile(link_plan_path,OUT/'source-link-plan.json')
records.append({'input':'actual Bazel CcInfo link plan','sha256':hashlib.sha256(link_plan_path.read_bytes()).hexdigest()})
checked_libraries={}
frameworks={}
for variant, archs, sdk in [("device",["arm64"],"iphoneos"),("simulator",["arm64","x86_64"],"iphonesimulator")]:
    sdk_path=subprocess.check_output(["xcrun","--sdk",sdk,"--show-sdk-path"],text=True).strip()
    for key, module in [("common","MediaPipeTasksCommon"),("vision","MediaPipeTasksVision")]:
        framework=OUT/variant/(module+".framework")
        framework.mkdir(parents=True)
        if key=="common": shutil.copytree(notices,framework/"ThirdPartyNotices")
        # Public Vision headers/module map come from the same full source build.
        original=archives[key][variant]
        for name,location in [("Headers",original["headers"]),("Modules",original["modules"])]:
            if location.is_dir(): shutil.copytree(location,framework/name)
        if not (framework / "Headers" / (module + ".h")).exists():
            (framework/"Headers").mkdir(exist_ok=True)
            headers=framework/"Headers"
            public=sorted(p.relative_to(headers).as_posix() for p in headers.rglob("*.h") if p.name!=module+".h")
            if key=="vision":
                assert public, "Vision must expose the headers from its source-built archive"
            umbrella="// Generated from this source archive's public headers.\n"
            umbrella += "".join('#import "'+name+'"\n' for name in public)
            (headers/(module+".h")).write_text(umbrella)
        if not (framework/"Modules/module.modulemap").exists():
            (framework/"Modules").mkdir(exist_ok=True)
            (framework/"Modules/module.modulemap").write_text('framework module '+module+' {\n umbrella header "'+module+'.h"\n export *\n module * { export * }\n}\n')
        metadata={"CFBundleIdentifier":"com.google.mediapipe.tasks."+key,"CFBundleName":module,"CFBundleExecutable":module,"CFBundlePackageType":"FMWK","CFBundleShortVersionString":"1.2.2","CFBundleVersion":"1.2.2","MinimumOSVersion":"15.0","CFBundleSupportedPlatforms":["iPhoneOS" if variant=="device" else "iPhoneSimulator"]}
        # Installation services require SDK/platform metadata even for manually
        # linked dynamic frameworks. Values come from the selected Xcode SDK.
        sdk_version=subprocess.check_output(["xcrun","--sdk",sdk,"--show-sdk-version"],text=True).strip()
        metadata.update({"CFBundleInfoDictionaryVersion":"6.0", "DTPlatformName":sdk,
                         "DTPlatformVersion":sdk_version,"DTSDKName":sdk+sdk_version,
                         "DTSDKBuild":subprocess.check_output(["xcrun","--sdk",sdk,"--show-sdk-build-version"],text=True).strip(),
                         "UIDeviceFamily":[1,2]})
        (framework/"Info.plist").write_bytes(plistlib.dumps(metadata))
        thin=[]
        for arch in archs:
            objects=OUT/"objects"/variant/arch/key; objects.mkdir(parents=True)
            triple=arch+"-apple-ios15.0"+("-simulator" if variant=="simulator" else "")
            # Preserve archive semantics: only CcInfo alwayslink libraries are
            # forced. Flattening every transitive member incorrectly forces two
            # independent zlib archives (legacy WORKSPACE and bzlmod) together.
            normal=[str(original['binary'])]; force=[]; libraries=[]
            if key=="common":
                provider=objects/"conversion_data.o"
                run(["xcrun","--sdk",sdk,"clang","-target",triple,"-isysroot",sdk_path,"-O2","-I",external/"icu/icu4c/source/common","-c",conversion_source,"-o",provider])
                normal.append(str(provider))
                libraries=link_plan['variants'][variant+'/'+arch]
                for library in libraries:
                    relative=Path(library['path'])
                    assert not relative.is_absolute() and '..' not in relative.parts
                    path=(SOURCE/relative).resolve(strict=True)
                    assert path.is_relative_to(ROOT.resolve()) and path.is_file()
                    if path not in checked_libraries:
                        with path.open('rb') as stream:checked_libraries[path]=hashlib.file_digest(stream,'sha256').hexdigest()
                    assert checked_libraries[path]==library['sha256'], 'stale archive: '+str(relative)
                    if library['alwayslink']:force.append('-Wl,-force_load,'+str(path))
                    else:normal.append(str(path))
            listing=objects/"normal-archives.txt";listing.write_text("\n".join(normal)+"\n")
            binary=objects/module
            command=["xcrun","--sdk",sdk,"clang++","-target",triple,"-isysroot",sdk_path,"-dynamiclib","-ObjC","-Wl,-filelist,"+str(listing),*force,"-install_name","@rpath/"+module+".framework/"+module,"-lobjc","-lz"]
            if key=="common":command += ["-Wl,-map,"+str(objects/"link.map")]
            names=["Foundation","UIKit","Accelerate","AVFoundation","CoreMedia","CoreGraphics","CoreImage","CoreVideo","QuartzCore","Metal","MetalKit","MetalPerformanceShaders","OpenGLES","AVFAudio","AudioToolbox","CoreFoundation"]
            for name in names: command += ["-framework",name]
            if key=="vision": command += ["-F",str(frameworks[(variant,"common")].parent),"-Wl,-reexport_framework,MediaPipeTasksCommon"]
            run(command+["-o",binary]); thin.append(binary)
            records.append({"module":module,"variant":variant,"architecture":arch,"linkMode":"actual-CcInfo" if key=="common" else "normal-source-archive-reexport","normalArchives":len(normal),"alwayslinkArchives":len(force),"sha256":hashlib.sha256(binary.read_bytes()).hexdigest()})
        destination=framework/module
        if len(thin)==1: shutil.copyfile(thin[0],destination)
        else: run(["xcrun","lipo","-create",*thin,"-output",destination])
        frameworks[(variant,key)]=framework
for key,module in [("common","MediaPipeTasksCommon"),("vision","MediaPipeTasksVision")]:
    run(["xcodebuild","-create-xcframework","-framework",frameworks[("device",key)],"-framework",frameworks[("simulator",key)],"-output",OUT/(module+"DynamicUniversal.xcframework")])
(ROOT/"output/source-sdk-link-manifest.json").write_text(json.dumps(records,indent=2)+"\n")
(OUT/"source-sdk-link-manifest.json").write_text(json.dumps(records,indent=2)+"\n")
print("STAGING_ONLY_SOURCE_SDK_LINK_COMPLETE_NOT_INSTALLED")
