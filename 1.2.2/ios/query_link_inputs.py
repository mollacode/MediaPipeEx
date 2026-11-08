from pathlib import Path
import os,subprocess,argparse,ast,hashlib,json
sdk=Path(__file__).resolve().parent.parent; work=sdk/'ios/workspace'
p=argparse.ArgumentParser();args=p.parse_args()
python=(sdk/'ios/tools')/'cpython-3.11.14-macos-x86_64-none/bin/python3.11'
cmake=(sdk/'ios/tools')/'cmake-3.24.0-macos-universal/CMake.app/Contents/bin'
env=os.environ.copy();env.update({'PATH':str(cmake)+os.pathsep+str(python.parent)+os.pathsep+env['PATH'],'HERMETIC_PYTHON_VERSION':'3.11','PYTHON_BIN_PATH':str(python),'PYTHON_LIB_PATH':str(python.parent.parent/'lib/python3.11/site-packages'),'TMPDIR':str(work/'tmp'),'XDG_CACHE_HOME':str(work/'cache/xdg')})
query='filter("^//mediapipe/tasks/ios:MediaPipeTaskGraphs$", deps(//mediapipe/tasks/ios:MediaPipeTaskGraphs_library))'
expr='str({"label":str(target.label),"libraries":[{"path":l.static_library.path if l.static_library else l.pic_static_library.path if l.pic_static_library else "", "alwayslink":l.alwayslink} for i in providers(target)["CcInfo"].linking_context.linker_inputs.to_list() for l in i.libraries]})'
cmd=[str(sdk/'ios/tools/bazel-7.7.0-darwin-x86_64'),'--batch','--output_user_root='+str(work/'cache/bazel'),'--host_jvm_args=-Xmx2g','cquery','-c','opt','--apple_generate_dsym=false','--apple_crosstool_top=@local_config_apple_cc//:toolchain','--define=OPENCV=source','--jobs=3','--local_resources=memory=6144','--distdir='+str(sdk/'ios/inputs/distdir'),'--repository_cache='+str(work/'cache/repository'),'--config=ios_sim_device_fat','--output=starlark','--starlark:expr='+expr,query]
r=subprocess.run(cmd,cwd=sdk/'source/findwig',env=env,stdout=subprocess.PIPE,text=True,check=True)
(work/'output/source-linking-raw.txt').write_text(r.stdout)
source=sdk/'source/findwig'
def digest(path):
 with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
variants={}; cache={}
for line in r.stdout.splitlines():
 if not line.startswith('{'):continue
 row=ast.literal_eval(line);libraries=row['libraries'];assert libraries
 first=libraries[0]['path']
 if first.startswith('bazel-out/ios_sim_arm64-'):key='simulator/arm64'
 elif first.startswith('bazel-out/ios_x86_64-'):key='simulator/x86_64'
 elif first.startswith('bazel-out/ios_arm64-'):key='device/arm64'
 else:raise AssertionError('unexpected configured iOS architecture: '+first)
 assert key not in variants
 unique={}
 for library in libraries:
  path=Path(library['path']);assert not path.is_absolute() and '..' not in path.parts
  full=(source/path).resolve(strict=True);assert full.is_relative_to(work.resolve()) and full.is_file()
  name=str(path)
  if full not in cache:cache[full]=digest(full)
  if name in unique:unique[name]['alwayslink'] |= library['alwayslink']
  else:unique[name]={'path':name,'alwayslink':library['alwayslink'],'sha256':cache[full]}
 assert sum(bool(x['alwayslink']) for x in unique.values())>0
 variants[key]=list(unique.values())
assert set(variants)=={'device/arm64','simulator/arm64','simulator/x86_64'}
bin=source/'bazel-bin/mediapipe/tasks/ios'
archives={n:digest(bin/n) for n in ['MediaPipeTasksCommon_framework.xcframework.zip','MediaPipeTasksVision_framework.xcframework.zip','MediaPipeTaskGraphs_library.xcframework.zip']}
result={'version':'1.2.2','sourceCommit':subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip(),'compatibilityPatchSha256':digest(sdk/'ios/public_source_build_compatibility.patch'),'streamModePatchSha256':digest(sdk/'ios/face_landmarker_stream_mode.patch'),'archives':archives,'variants':variants,'purpose':'Preserve actual CcInfo alwayslink flags; normal archives use normal symbol extraction. No duplicate/undefined suppression.'}
(work/'output/source-link-plan.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'result':'PASS','variants':{k:{'libraries':len(v),'alwayslink':sum(bool(x['alwayslink']) for x in v)} for k,v in variants.items()}}))
