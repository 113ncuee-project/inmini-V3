"""Create portable local-code and text/numeric evidence ZIPs with SHA256.

Includes source-hash native binaries and original seed archives, excludes
virtual environments, Git metadata, credentials, images and unrelated output.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile

from run_local_rl_diagnostics import APP, ROOT, sources, write


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def export_inputs():
    mapping={
        'resnet18':ROOT/'output/local_rl_v03_r18/cases/resnet18/7/methods',
        'resnet50':ROOT/'output/local_rl_v03_p4/cases/resnet50/7/methods',
        'mobilenet_v2':ROOT/'output/local_rl_v03_p4/cases/mobilenet_v2/7/methods',
    }
    for model,original in mapping.items():
        folder=ROOT/'inputs/replay_v04'/model;folder.mkdir(parents=True,exist_ok=True)
        copied={}
        for name in ('workload.json','seed_attempts.json','source_identity.json'):
            source=original/name;target=folder/name
            if target.exists() and digest(target)!=digest(source):raise ValueError('existing portable input differs: '+str(target))
            if not target.exists():shutil.copyfile(source,target)
            copied[name]=digest(target)
        write(folder/'provenance.json',dict(model=model,original_case=str(original),files=copied,
            scope='unaltered previously completed workload/seed evidence; not a new Tangram execution; seed generation time is historical and separate from replay search'))


def archive(target,files):
    manifest={}
    with zipfile.ZipFile(target,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for path,name in sorted(files,key=lambda r:r[1]):
            manifest[name]=digest(path);z.write(path,name)
        z.writestr('ZIP_MANIFEST.json',json.dumps(dict(files=manifest,images=0),indent=2))
    with zipfile.ZipFile(target) as z:
        if z.testzip():raise ValueError('ZIP CRC failed')
        if set(z.namelist())!=set(manifest)|{'ZIP_MANIFEST.json'}:raise ValueError('ZIP inventory differs')
        for name,expected in manifest.items():
            if hashlib.sha256(z.read(name)).hexdigest()!=expected:raise ValueError('ZIP source hash failed: '+name)
    return dict(path=str(target),bytes=target.stat().st_size,files=len(manifest),sha256=digest(target),crc_and_sha_verified=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,default=ROOT/'output/uploads')
    p.add_argument('--tag',default='20261103')
    p.add_argument('--evidence',type=Path,action='append',default=[])
    p.add_argument('--inputs-only',action='store_true')
    args=p.parse_args();export_inputs()
    if args.inputs_only:
        print(ROOT/'inputs/replay_v04');return
    args.out.mkdir(parents=True,exist_ok=True)
    files=[(APP/rel,'simplified_rapidchiplet/'+rel) for rel in sources()]
    for rel in ('README.md','run_inmin_v04_overnight.ps1','run_inmin_v04_overnight.cmd','docs/INMIN_V04_LOCAL_GUIDE.md',
                'docs/INMIN_V04_RESULTS.md','docs/inmin_v04_progress.md','docs/INMIN_V02_IMPLEMENTATION.md',
                'docs/hybrid_gemini_source_notes.md','docs/specs/Chiplet_Hardware_Spec_v0.2_reviewed.md',
                'docs/specs/INMIN_v03_RL_Local_Diagnostic_Test_Spec.md'):
        path=ROOT/rel
        if path.exists():files.append((path,rel))
    for path in (ROOT/'inputs/replay_v04').rglob('*.json'):files.append((path,path.relative_to(ROOT).as_posix()))
    result={'code':archive(args.out/f'INMIN_v04_Code_{args.tag}.zip',files)}
    allowed={'.json','.jsonl','.csv','.md','.log','.txt','.gz','.pt','.py','.cpp','.h','.dll','.so','.js','.html','.css','.yml','.yaml','.toml','.ps1'}
    evidence=[]
    for folder in args.evidence:
        folder=folder.resolve()
        for path in folder.rglob('*'):
            if path.is_file() and path.suffix in allowed and '__pycache__' not in path.parts:
                evidence.append((path,folder.name+'/'+path.relative_to(folder).as_posix()))
    if evidence:result['evidence']=archive(args.out/f'INMIN_v04_Evidence_{args.tag}.zip',evidence)
    write(args.out/f'INMIN_v04_{args.tag}_package.json',result);print(json.dumps(result,indent=2))


if __name__=='__main__':main()
