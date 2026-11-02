"""Run actual user-input scenarios for the detailed project report.

This is an experiment driver only. Production hardware, search and PPA code are
never changed. Every case retains full inputs, source manifest and run outputs.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'simplified_rapidchiplet'
OUT=ROOT/'output'/'detailed_project_report_20261031'
TZ=timezone(timedelta(hours=8))

def dump(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def manifest():
    paths=[APP/'rl_dse.py',*sorted((APP/'simple_rapidchiplet'/'hybrid').glob('*.py'))]
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}

BASE={'batch':1,'budget':16,'seed':7,'groups':3,'method':'rl','proposal':'composite',
      'seed_budget':2,'shortlist':24,'random_quota':6,'max_per_family':6,'horizon':16,
      'fusion':'off','fusion_depth':4,'dies':[1,2,4,8,16],'input_size':224,
      'max_power':20.,'max_area':250.,'max_latency_ms':3.,
      'strict_power':True,'strict_area':True,'strict_latency':True}

def cases():
    rows=[]
    def add(name,description,**updates):
        rows.append({'id':name,'description':description,'config':{**BASE,**updates}})
    for suffix,pref in [('balanced','balanced'),('power','low_power'),('area','small_area'),('latency','low_latency')]:
        add('R_'+suffix,'ResNet18 同限制的四種 preference 比較',models=['resnet18'],preference=pref)
    add('R_tight_latency','ResNet18 嚴格延遲限制',models=['resnet18'],preference='low_latency',
        max_latency_ms=.8,max_area=500.,max_power=40.,budget=24)
    add('R_impossible_area','ResNet18 不可能的硬面積上限',models=['resnet18'],preference='balanced',
        max_area=60.,budget=8)
    add('R_soft_latency','ResNet18 將0.8ms改為軟延遲目標',models=['resnet18'],preference='low_power',
        max_latency_ms=.8,strict_latency=False)
    add('M_balanced','MobileNetV2 均衡偏好',models=['mobilenet_v2'],preference='balanced')
    add('M_latency','MobileNetV2 低延遲偏好與嚴格1ms',models=['mobilenet_v2'],preference='low_latency',
        max_latency_ms=1.,max_area=500.,max_power=40.)
    add('A_balanced','AlexNet 均衡偏好',models=['alexnet'],preference='balanced',
        max_latency_ms=10.,max_power=40.,max_area=500.,budget=12)
    add('J_shared','ResNet18與MobileNetV2選擇共同架構',models=['resnet18','mobilenet_v2'],
        preference='balanced',max_latency_ms=5.,budget=12)
    add('T_fusion','Toy residual 觀察DF融合與分割',models=['toy'],preference='balanced',
        max_power=3.,max_area=150.,max_latency_ms=.02,budget=32,toy_channels=8,toy_spatial=8,fusion='dp')
    add('R32_fusion','ResNet18 32x32 開啟DF融合的機制測試 非224效能',models=['resnet18'],preference='balanced',
        input_size=32,budget=12,fusion='dp',max_latency_ms=3.)
    add('R34_balanced','ResNet34 224x224 完整模型的均衡偏好',models=['resnet34'],preference='balanced',
        max_latency_ms=6.,budget=4,seed_budget=1)
    add('J_resnets','ResNet18與ResNet34共同架構 完整224x224',models=['resnet18','resnet34'],
        preference='balanced',max_latency_ms=6.,budget=4,seed_budget=1)
    add('T_fused_demo','Toy residual 與GUI預設候選參數相同的融合示範',models=['toy'],preference='balanced',
        max_power=None,max_area=None,max_latency_ms=None,budget=12,toy_channels=8,toy_spatial=8,
        fusion='dp',seed_budget=4,shortlist=48,random_quota=12,max_per_family=12)
    return rows

def worker(folder):
    sys.path.insert(0,str(APP))
    from rl_dse import run_suite
    folder=Path(folder)
    spec=json.loads((folder/'experiment.json').read_text(encoding='utf-8'))
    before=manifest()
    stamp={'started_taipei':datetime.now(TZ).isoformat(),'python':sys.executable,
           'source_before':before,'experiment':spec}
    dump(folder/'status.json',{**stamp,'status':'running'})
    start=time.perf_counter()
    try:
        result=run_suite(spec['config'],folder/'run',update=lambda **kw:print(kw.get('message',''),flush=True) if 'message' in kw else None)
        stamp.update(status='complete',recommendation_status=result['recommendation_status'],
            best_architecture=result['best_architecture'],closest_architecture=result.get('closest_architecture'))
    except Exception as exc:
        stamp.update(status='failed',error=f'{type(exc).__name__}: {exc}',traceback=traceback.format_exc())
        traceback.print_exc()
    stamp.update(elapsed_s=time.perf_counter()-start,finished_taipei=datetime.now(TZ).isoformat(),source_after=manifest())
    stamp['source_stable']=stamp['source_before']==stamp['source_after']
    dump(folder/'status.json',stamp)
    return int(stamp['status']!='complete')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--worker',type=Path)
    parser.add_argument('--workers',type=int,default=2)
    parser.add_argument('--only',default='')
    args=parser.parse_args()
    if args.worker:
        return worker(args.worker)
    OUT.mkdir(parents=True,exist_ok=True)
    specs=cases()
    if args.only:
        allowed=set(args.only.split(','));specs=[s for s in specs if s['id'] in allowed]
    dump(OUT/'case_matrix.json',specs)
    def run(spec):
        folder=OUT/'experiments'/spec['id']
        saved=folder/'status.json'
        if saved.is_file():
            old=json.loads(saved.read_text(encoding='utf-8'))
            if old.get('status')=='complete' and old['experiment']==spec and old.get('source_stable') and old['source_after']==manifest():
                return spec['id'],0,'reused'
        dump(folder/'experiment.json',spec)
        with (folder/'run.log').open('w',encoding='utf-8') as log:
            try:
                result=subprocess.run([sys.executable,'-X','utf8',str(Path(__file__).resolve()),'--worker',str(folder)],
                                      cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=600)
            except subprocess.TimeoutExpired:
                saved=read_status=folder/'status.json'
                state=json.loads(saved.read_text(encoding='utf-8')) if saved.is_file() else {'experiment':spec}
                state.update(status='timeout',error='600 second per-case wall-clock cap reached; no completed solution claimed')
                dump(saved,state)
                return spec['id'],124,'timeout'
        return spec['id'],result.returncode,'executed'
    results=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for future in as_completed([pool.submit(run,spec) for spec in specs]):
            row=future.result();results.append(row);print(json.dumps(row),flush=True)
            dump(OUT/'batch_status.json',results)
    return int(any(row[1] for row in results))

if __name__=='__main__':
    raise SystemExit(main())
