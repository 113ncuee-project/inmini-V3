"""Build the local exact scheduler; no package download or physical model change."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from simple_rapidchiplet.hybrid.native_schedule import SOURCE,library_path,source_hash

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--compiler');args=parser.parse_args()
    choices=[args.compiler,shutil.which('g++'),r'C:\Vivado\2022.1\tps\mingw\6.2.0\win64.o\nt\bin\g++.exe']
    compiler=next((p for p in choices if p and Path(p).exists()),None)
    if not compiler:raise SystemExit('No local g++ found. Pass --compiler; Python coalesced fallback remains available.')
    out=library_path();out.parent.mkdir(exist_ok=True)
    command=[compiler,'-std=c++14','-O3','-ffp-contract=off','-shared','-static-libgcc','-static-libstdc++',str(SOURCE),'-o',str(out)]
    result=subprocess.run(command,capture_output=True,text=True)
    if result.returncode:print(result.stdout+result.stderr);raise SystemExit(result.returncode)
    (out.with_suffix('.build.json')).write_text(json.dumps(dict(source_sha256=source_hash(),command=command,
        compiler=subprocess.check_output([compiler,'--version'],text=True),model_change=False),indent=2),encoding='utf-8')
    print(out)

if __name__=='__main__':main()
