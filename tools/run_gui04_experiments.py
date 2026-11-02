"""Actual GUI04 profile calibration and fixed-hardware partition controls.

No expected winner is encoded. Each case saves requests, full exact-oracle
artifacts, source identity and failures. Old experiment directories are untouched.
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from dataclasses import replace
from datetime import datetime,timezone,timedelta
import argparse,json,os,subprocess,sys,time,traceback,hashlib

ROOT=Path(__file__).resolve().parents[1];APP=ROOT/'simplified_rapidchiplet'
OUT=ROOT/'output/gui04_20261101'
sys.path.insert(0,str(APP))
def dump(p,x):
    from simple_rapidchiplet.hybrid.auto_runtime import atomic_json
    atomic_json(p,x)
def cases():
    rows=[]
    for model in ['toy','resnet18','mobilenet_v2']:
        for mode in ['fast','standard']:
            request={'ui_schema_version':2,'models':[model],'search_mode':mode,'preference':'balanced',
                'max_power':20.,'max_area':250.,'max_latency_ms':3.,'seed':7}
            rows.append({'id':model+'_'+mode,'kind':'auto','request':request})
    rows.append({'id':'toy_deep_manual','kind':'auto','request':{'ui_schema_version':2,'models':['toy'],
        'search_mode':'deep','budget_mode':'manual','budget':12,'seed':7}})
    for pref in ['low_power','low_latency']:
        rows.append({'id':'resnet18_'+pref,'kind':'auto','request':{'ui_schema_version':2,'models':['resnet18'],
            'search_mode':'standard','preference':pref,'budget_mode':'manual','budget':16,'seed':7,
            'max_power':40. if pref=='low_latency' else 20.,'max_area':500. if pref=='low_latency' else 250.,
            'max_latency_ms':1.2 if pref=='low_latency' else 3.}})
    for model in ['resnet18','resnet34']:
        rows.append({'id':model+'_partition_control','kind':'partition_control','model':model})
    rows.append({'id':'toy_fusion_control','kind':'fusion_control','model':'toy'})
    rows.append({'id':'resnet18_interchiplet_partition_control','kind':'partition_control','model':'resnet18','compute_count':4,'mesh_shape':[2,2]})
    for count,shape in [(1,[1,1]),(4,[2,2])]:
        rows.append({'id':f'resnet18_C{count}_tiled_partition_control','kind':'partition_control','model':'resnet18',
            'compute_count':count,'mesh_shape':shape,'matched_temporal_tile_BKHW':[0,64,0,0]})
    return rows

def controlled(spec,folder):
    from simple_rapidchiplet.hybrid.architecture import enumerate_gemini_architectures
    from simple_rapidchiplet.hybrid.models import extract_model
    from simple_rapidchiplet.hybrid.workload import make_toy_workload
    from simple_rapidchiplet.hybrid.mapping import initial_mapping,enumerate_partitions,FusionStack
    from simple_rapidchiplet.hybrid.auto_runtime import BoundedOraclePool,EvaluationTimeout
    w=make_toy_workload(channels=8,spatial=8) if spec['model']=='toy' else extract_model(spec['model'],1,input_size=224)
    count=spec.get('compute_count',1)
    candidates=enumerate_gemini_architectures(compute_counts=(count,))
    c=next(c for c in candidates if not spec.get('mesh_shape') or [c.hardware.cluster_rows,c.hardware.cluster_cols]==spec['mesh_shape'])
    base=initial_mapping(w,c.package.mapping_core_ids,c.package.memory_ids,microbatch_size=1,
        max_group_layers=3 if spec['kind']=='fusion_control' else 1)
    if spec.get('matched_temporal_tile_BKHW'):
        base=replace(base,layer_mappings=tuple(replace(m,tile_shape=tuple(spec['matched_temporal_tile_BKHW'])) for m in base.layer_mappings))
    variants=[];fallbacks={}
    if spec['kind']=='fusion_control':
        ids=tuple(l.id for l in w.layers)
        variants=[('no_cross_layer_fusion',base),('DF_depth3_same_mapping',replace(base,fusion_stacks=(FusionStack(ids,(8,8),'recompute'),)))]
    else:
        for kind in ['weight_shared_P','activation_shared_K']:
            mappings=[];fallback=[]
            for item in base.layer_mappings:
                opts=enumerate_partitions(w,item.layer_id,len(item.chiplets),1)
                matching=[p for p in opts if p.k==1 and p.h*p.w>1] if kind=='weight_shared_P' else [p for p in opts if p.h*p.w==1 and p.k>1]
                if matching:part=matching[0]
                else:part=item.partition;fallback.append(item.layer_id)
                mappings.append(replace(item,partition=part))
            variants.append((kind,replace(base,layer_mappings=tuple(mappings))));fallbacks[kind]=fallback
    result=[];started=time.monotonic()
    pool=BoundedOraclePool(w,folder/'oracle_runtime',deadline=started+900,evaluation_timeout_s=400)
    try:
        for name,plan in variants:
            tick=time.monotonic();record={'variant':name,'architecture':c.id,'input_shape':[1,3,224,224] if spec['model']!='toy' else [1,8,8,8],
                'fallback_layers_no_exact_target_partition':fallbacks.get(name,[]),'mapping':plan.to_dict()}
            try:
                measured=pool.evaluate(c,plan,phase='controlled')['metrics']
                record.update(status='complete',metrics=measured)
                pool.persist(c,plan,folder/name,{'experiment':'controlled','spec':spec,
                    'same_across_variants':'workload, hardware, precision, clock, group boundaries, core lists, FD, cold weights, microbatch 1, temporal mapper hints',
                    'only_changed':'B/K/H/W partition' if spec['kind']=='partition_control' else 'fusion stack only'})
                from collections import defaultdict
                transfer=json.loads((folder/name/'traffic_routes.json').read_text(encoding='utf-8'))['transfers']
                ledger=defaultdict(lambda:defaultdict(float))
                for f in transfer:
                    stat=f['statistics'];row=ledger[f['kind']]
                    row['flows']+=1;row['payload_bytes']+=f['bytes'];row['DRAM_bytes']+=stat.get('dram_bytes',0)
                    row['core_NoC_hop_bytes']+=stat.get('core_noc_hop_bytes',0);row['D2D_hop_bytes']+=stat.get('nop_hop_bytes',0)
                    row['local_delivered_bytes']+=stat.get('local_delivered_bytes',0);row['energy_j']+=stat['energy_j']
                record['flow_ledger']={k:dict(v) for k,v in ledger.items()}
                # Per-layer control evidence keeps operator/shape/mapping, exact
                # measured service bottleneck and weight versus activation sizes.
                record['layer_workload']=[{'layer':l.id,'kind':l.kind,'weight_bytes':l.weight_bytes,
                    'input_tensor_bytes':sum(w.tensor_map[t].bytes for t in l.inputs),
                    'output_bytes':w.tensor_map[l.output].bytes,'MACs':l.macs_per_sample,
                    'partition':plan.mapping_map[l.id].partition.as_tuple()} for l in w.layers]
            except EvaluationTimeout as error:record.update(status='timeout',error=str(error))
            except ValueError as error:record.update(status='rejected',error=str(error))
            record['elapsed_s']=time.monotonic()-tick;result.append(record);dump(folder/'controlled_results.json',result)
    finally:pool.close()
    dump(folder/'control_accounting.json',{'oracle_records':pool.records,'full_evaluations':pool.full_evaluations,'elapsed_s':time.monotonic()-started})
    return result

def worker(spec,folder):
    from rl_dse import source_identity
    before=source_identity();started=time.monotonic()
    dump(folder/'experiment.json',spec)
    state={'status':'running','source_before':before,'started_taipei':datetime.now(timezone(timedelta(hours=8))).isoformat()}
    dump(folder/'status.json',state)
    try:
        if spec['kind']=='auto':
            from hybrid_gui import run_suite
            r=run_suite(spec['request'],folder/'run',update=lambda **v:print(v.get('message',''),flush=True) if v.get('message') else None)
            state.update(status='complete',execution_status=r['execution_status'],best_architecture=r['best_architecture'])
        else:
            r=controlled(spec,folder);state.update(status='complete',variant_statuses={v['variant']:v['status'] for v in r})
    except Exception as error:
        state.update(status='failed',error=type(error).__name__+': '+str(error));traceback.print_exc()
    state.update(elapsed_s=time.monotonic()-started,source_after=source_identity())
    state['source_stable']=state['source_before']==state['source_after'];dump(folder/'status.json',state)
    return int(state['status']!='complete')

def main():
    global OUT
    p=argparse.ArgumentParser();p.add_argument('--worker');p.add_argument('--only',default='');p.add_argument('--workers',type=int,default=2);p.add_argument('--output-root',type=Path);a=p.parse_args()
    if a.output_root:
        OUT=a.output_root.resolve()
        if not OUT.is_relative_to((ROOT/'output').resolve()):raise ValueError('experiment output must stay inside workspace/output')
    if a.worker:
        folder=Path(a.worker);return worker(json.loads((folder/'experiment.json').read_text(encoding='utf-8')),folder)
    specs=cases();allowed=set(a.only.split(',')) if a.only else None
    if allowed:specs=[s for s in specs if s['id'] in allowed]
    dump(OUT/'experiment_matrix.json',cases())
    def run_unlocked(s):
        folder=OUT/'experiments'/s['id'];folder.mkdir(parents=True,exist_ok=True)
        from rl_dse import source_identity
        if (folder/'status.json').is_file():
            old=json.loads((folder/'status.json').read_text(encoding='utf-8'))
            same_effective=True
            if s['kind']=='auto':
                from hybrid_gui import normalize_gui_request
                same_effective=(folder/'run/config.json').is_file() and json.loads((folder/'run/config.json').read_text(encoding='utf-8'))==normalize_gui_request(s['request'])[0]
            if old['status']=='complete' and old.get('source_stable') and old['source_after']==source_identity() and json.loads((folder/'experiment.json').read_text(encoding='utf-8'))==s and same_effective:return s['id'],'reused'
            # Preserve an earlier source's evidence instead of overwriting it.
            archive=OUT/'superseded'/datetime.now().strftime('%H%M%S')/s['id'];archive.parent.mkdir(parents=True,exist_ok=True)
            if not folder.resolve().is_relative_to(OUT.resolve()) or not archive.resolve().is_relative_to(OUT.resolve()):
                raise ValueError('experiment archive move escaped the declared output root')
            folder.rename(archive);folder.mkdir(parents=True)
        dump(folder/'experiment.json',s)
        with (folder/'run.log').open('w',encoding='utf-8') as log:
            proc=subprocess.run([sys.executable,'-X','utf8',str(Path(__file__).resolve()),'--worker',str(folder)],stdout=log,stderr=subprocess.STDOUT,cwd=ROOT)
        return s['id'],proc.returncode
    def run(s):
        lock=OUT/'.locks'/(s['id']+'.lock');lock.parent.mkdir(parents=True,exist_ok=True)
        try:
            with lock.open('x',encoding='utf-8') as stream:json.dump({'owner_pid':os.getpid(),'case':s['id']},stream)
        except FileExistsError:raise RuntimeError('experiment already owned by another process; use a new output root: '+str(lock))
        try:return run_unlocked(s)
        finally:lock.unlink()
    results=[]
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for f in as_completed([pool.submit(run,s) for s in specs]):
            row=f.result();results.append(row);print(json.dumps(row),flush=True);dump(OUT/'batch_status.json',results)
    return int(any(isinstance(row[1],int) and row[1]!=0 for row in results))
if __name__=='__main__':raise SystemExit(main())
