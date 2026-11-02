"""Build auditable report data and exact mapping/flow companion tables."""
from __future__ import annotations
from collections import Counter,defaultdict
from dataclasses import asdict
import csv
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'simplified_rapidchiplet'
BASE=ROOT/'output'/'detailed_project_report_20261031'
sys.path.insert(0,str(APP))
from simple_rapidchiplet.hybrid.hardware import HardwareSpec
from simple_rapidchiplet.hybrid.architecture import enumerate_gemini_architectures
from simple_rapidchiplet.hybrid.mapping import compile_mapping,_shards
from simple_rapidchiplet.hybrid.search import plan_from_dict
from simple_rapidchiplet.hybrid.workload import Workload,LayerSpec,TensorSpec

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def dump(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def csvfile(path,rows,fields=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not fields:
        fields=list(rows[0]) if rows else []
    with path.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list,tuple)) else v for k,v in row.items()})

def workload_from(data):
    tensors=tuple(TensorSpec(**{**t,'shape':tuple(t['shape'])}) for t in data['tensors'])
    layers=[]
    for item in data['layers']:
        item=dict(item)
        for key in ('inputs','kernel','stride','padding','dilation','weight_shape','post_ops'):
            if key in item:item[key]=tuple(item[key])
        layers.append(LayerSpec(**item))
    return Workload(data['name'],tensors,tuple(layers),tuple(data['input_ids']),tuple(data['output_ids']),data['batch_size'],data.get('source','explicit'))

def compact_cores(cores):
    runs=[]
    for core in cores:
        die,c=core.split('/');die=int(die.split(':')[1]);c=int(c.split(':')[1])
        if runs and runs[-1][0]==die:runs[-1][1].append(c)
        else:runs.append((die,[c]))
    return '; '.join(f'C{die}:c'+','.join(map(str,values)) for die,values in runs)

def deployment(case_id,model,row,destination):
    folder=Path(row['folder'])
    workload=workload_from(read(folder/'workload.json'))
    mapping=read(folder/'mapping.json')
    plan=plan_from_dict(mapping)
    hardware=HardwareSpec.from_dict(read(folder/'hardware.json'))
    package=read(folder/'package.json')
    flows=read(folder/'traffic_routes.json')['transfers']
    diagnostics=read(folder/'diagnostics.json')
    metrics=row['metrics']
    stacks={lid:(i+1,stack) for i,stack in enumerate(plan.fusion_stacks) for lid in stack.layer_ids}
    layers=[]
    partition_rows=[]
    for item in plan.layer_mappings:
        layer=workload.layer_map[item.layer_id]
        shape=workload.tensor_map[layer.output].shape
        group=plan.group_map[layer.id]
        si,stack=stacks.get(layer.id,(None,None))
        value={'layer':layer.id,'operator':layer.kind,'inputs':list(layer.inputs),'output_tensor':layer.output,
            'output_BKHW':list(shape),'partition_BKHW':list(item.partition.as_tuple()),
            'core_count':len(item.chiplets),'ordered_cores':list(item.chiplets),'core_text':compact_cores(item.chiplets),
            'pipeline_group':group.id,'group_mode':group.mode,'group_layers':list(group.layer_ids),
            'DF_stack':si,'DF_depth':len(stack.layer_ids) if stack else 1,
            'DF_sink_tile_HW':list(stack.tile_hw) if stack else None,'overlap':stack.overlap if stack else 'no DF',
            'input_DRAM':item.input_dram,'weight_DRAM':item.weight_dram,'output_DRAM':item.output_dram,
            'temporal_tile_BKHW':list(item.tile_shape),'microtile_BKHW':list(item.microtile_shape),
            'dataflow':item.dataflow,'channel_tile':item.channel_tile,'parser_fused_post_ops':list(layer.post_ops)}
        layers.append(value)
        for mb in range(0,workload.batch_size,plan.microbatch_size):
            for shard,(core,region) in enumerate(zip(item.chiplets,_shards(shape,item.partition,mb,mb+plan.microbatch_size))):
                partition_rows.append({'layer':layer.id,'microbatch_start':mb,'shard_order':shard,
                    'core':core,'output_tensor':layer.output,'region_BKHW':region.bounds,'elements':region.elements})
    group_rows=[]
    for group in plan.groups:
        stack=next((s for s in plan.fusion_stacks if s.layer_ids==group.layer_ids),None)
        group_rows.append({'group':group.id,'mode':group.mode,'layers':list(group.layer_ids),
            'layer_count':len(group.layer_ids),'DF_depth':len(stack.layer_ids) if stack else 1,
            'DF_stack_present':stack is not None,'sink_tile_HW':list(stack.tile_hw) if stack else None,
            'cache_mode':stack.overlap if stack else 'no DF'})
    compiled=compile_mapping(workload,plan,hardware)
    tiles=defaultdict(Counter)
    for u in compiled.units:tiles[u.layer_id][tuple(u.output_region.shape)]+=1
    for layer in layers:
        layer['actual_unit_tile_shapes']=[{'BKHW':list(shape),'count':count} for shape,count in tiles[layer['layer']].most_common()]
        layer['actual_execution_units']=sum(tiles[layer['layer']].values())
    unit_rows=[{'unit':u.id,'layer':u.layer_id,'core':u.chiplet,'group':u.group_id,
        'microbatch':u.microbatch,'shard':u.shard_index,'temporal_tile':u.tile_index,
        'output_tensor':u.output_tensor,'output_region_BKHW':u.output_region.bounds,
        'inputs':[{'tensor':r.tensor_id,'region_BKHW':r.region.bounds} for r in u.inputs],
        'weights_KCRS':u.weight_region.bounds if u.weight_region else None,'MACs':u.macs} for u in compiled.units]
    assert sum(u.macs for u in compiled.units)==metrics['executed_macs']
    totals=defaultdict(lambda:defaultdict(float))
    flow_rows=[]
    for f in flows:
        stat=f['statistics'];kind=f['kind'];r=totals[kind]
        r['flows']+=1;r['payload_bytes']+=f['bytes'];r['DRAM_bytes']+=stat.get('dram_bytes',0)
        r['D2D_hop_bytes']+=stat.get('nop_hop_bytes',0);r['core_NoC_hop_bytes']+=stat.get('core_noc_hop_bytes',0)
        r['energy_j']+=stat.get('energy_j',0)
        flow_rows.append({'flow':f['id'],'kind':kind,'tensor':f['tensor'],'source':f['src'],
            'destinations':f['dsts'],'payload_bytes':f['bytes'],'region':f['region']['bounds'],
            'producer_units':f['producer_units'],'consumer_units':f['consumer_units'],'routes':f['routes'],
            'start_s':f['start_s'],'finish_s':f['finish_s'],'DRAM_bytes':stat.get('dram_bytes',0),
            'D2D_hop_bytes':stat.get('nop_hop_bytes',0),'core_NoC_hop_bytes':stat.get('core_noc_hop_bytes',0),
            'link_transmitted_bytes':sum(e['bytes'] for e in stat['link_load_bytes']),
            'energy_j':stat['energy_j']})
    top=sorted(flows,key=lambda f:f['statistics']['energy_j'],reverse=True)[:3]
    examples=[]
    first_input=next((f for f in flows if f['kind']=='dram_input'),None)
    if first_input:examples.append(first_input)
    cross=next((f for f in sorted(flows,key=lambda f:f['bytes'],reverse=True)
                if f['src'].startswith('compute:') and any(d.startswith('compute:') and d.split('/')[0]!=f['src'].split('/')[0] for d in f['dsts'])),None)
    if cross:examples.append(cross)
    add=next((l for l in workload.layers if l.kind=='Add'),None)
    if add:
        for tensor in add.inputs:
            found=next((f for f in flows if f['tensor']==tensor and any(u.startswith(add.id+':') or u.startswith('df:'+add.id+':') for u in f['consumer_units'])),None)
            if found:examples.append(found)
    examples.extend(top)
    examples=list({f['id']:f for f in examples}.values())
    per=destination/case_id/model
    csvfile(per/'layers.csv',layers)
    csvfile(per/'pipeline_groups_and_fusion.csv',group_rows)
    csvfile(per/'exact_spatial_partitions.csv',partition_rows)
    csvfile(per/'execution_units.csv',unit_rows)
    csvfile(per/'flows.csv',flow_rows)
    csvfile(per/'package_nodes.csv',[{k:v for k,v in n.items() if k!='area_components'} for n in package['nodes']])
    csvfile(per/'package_links.csv',package['links'])
    value={'case':case_id,'model':model,'architecture':row['architecture'],'folder':str(folder),
        'strict_compliant':row['within_limits'],'all_targets_met':row['all_targets_met'],
        'constraints':row['constraints'],'metrics':metrics,'hardware':read(folder/'hardware.json'),
        'workload':workload.to_dict(),'mapping':mapping,'layers':layers,'groups':group_rows,
        'package':package,'flow_totals':{k:dict(v) for k,v in totals.items()},'flow_examples':examples,
        'diagnostic_layers':diagnostics['layers'],'diagnostic_memory':diagnostics['memory'],
        'full_flow_count':len(flows),'exact_unit_count':len(unit_rows),'exact_shard_count':len(partition_rows)}
    dump(per/'deployment_detail.json',value)
    return value

def main():
    cases=[];summary=[]
    dest=BASE/'evidence'
    folders=sorted((BASE/'experiments').iterdir())
    prior=BASE/'fusion_on_initial_attempt'/'R_power'
    if (prior/'run/suite.json').is_file():folders.append(prior)
    for folder in folders:
        status_path=folder/'status.json'
        if not status_path.is_file():continue
        status=read(status_path);spec=read(folder/'experiment.json')
        if folder==prior:
            spec={**spec,'id':'R_power_DF_on_prior','description':'ResNet18 224x224 DF開啟的已完成對照 原始案例R_power'}
        item={'id':spec['id'],'description':spec['description'],'config':spec['config'],'status':status,'deployments':[]}
        if status['status']=='complete':
            suite=read(folder/'run/suite.json');item['suite']=suite
            for model in spec['config']['models']:
                search=read(folder/'run'/model/'joint_search.json')
                item.setdefault('searches',{})[model]={k:v for k,v in search.items() if k not in ('trace','architecture_archive','current_state','closest_state','best_state','current_metrics','closest_metrics','initial_metrics','best_metrics')}
                item['searches'][model]['initial_metrics']={k:search['initial_metrics'][k] for k in ('latency_s','power_w','area_mm2','energy_j')}
                item['searches'][model]['visited_executable_architectures']=list(search['architecture_archive'])
                item['searches'][model]['trace']=[{k:t[k] for k in ('step','evaluations','reward','valid','rejection_reason','architecture_candidate_id','current_cost','best_cost','violation') if k in t}|
                    {'family':t['action_plan']['family_id'],'ordered_edits':t['action_plan']['ordered_edits']} for t in search['trace']]
                csvfile(dest/spec['id']/model/'search_transitions.csv',item['searches'][model]['trace'])
            selected=suite['display_architecture']
            for row in suite['runs']:
                if row['architecture']==selected:
                    detail=deployment(spec['id'],row['model'],row,dest)
                    item['deployments'].append(detail)
                    m=row['metrics'];cfg=spec['config'];search=item['searches'][row['model']]
                    summary.append({'case':spec['id'],'model':row['model'],'preference':cfg['preference'],
                        'max_power_W':cfg['max_power'],'max_area_mm2':cfg['max_area'],'max_latency_ms':cfg['max_latency_ms'],
                        'strict_power':cfg['strict_power'],'strict_area':cfg['strict_area'],'strict_latency':cfg['strict_latency'],
                        'result':suite['recommendation_status'],'architecture':selected,'compute':m['compute_chiplets'],
                        'IO':m['io_chiplets'],'DRAM':m['memory_dies'],'latency_ms':m['latency_s']*1000,
                        'power_W':m['power_w'],'area_mm2':m['area_mm2'],'energy_mJ':m['energy_j']*1000,
                        'DF_stack_depths':[len(s['layer_ids']) for s in detail['mapping']['fusion_stacks']],
                        'groups':len(detail['groups']),'RL_full_queries':search['evaluations'],
                        'policy_updates':search['policy_updates'],'visited_architectures':search['visited_executable_architectures'],
                        'search_elapsed_s':status['elapsed_s'],'source_stable':status['source_stable']})
        cases.append(item)
    templates=[]
    for candidate in enumerate_gemini_architectures():
        package=candidate.package;h=candidate.hardware
        templates.append({'id':candidate.id,'rows':h.cluster_rows,'cols':h.cluster_cols,'compute':len(package.compute_ids),
            'IO':len(package.io_ids),'DRAM':len(package.memory_ids),'total_core':h.core_count,
            'DRAM_BW_GBps':len(package.memory_ids)*h.dram_bandwidth_Bps/1e9,
            'silicon_area_mm2':sum(n.width_mm*n.height_mm for n in package.nodes.values())})
    csvfile(BASE/'template_catalog.csv',templates)
    coverage={}
    coverage_path=BASE/'template_coverage/results.json'
    if coverage_path.is_file():
        coverage=read(coverage_path)
        csvfile(BASE/'template_coverage_results.csv',[{k:v for k,v in r.items() if k!='metrics'} |
            ({'latency_ms':r['metrics']['latency_s']*1000,'power_W':r['metrics']['power_w'],
              'area_mm2':r['metrics']['area_mm2'],'energy_mJ':r['metrics']['energy_j']*1000} if 'metrics' in r else {})
            for r in coverage['rows']],fields=['architecture','compute','rows','cols','seed_queries','seed_status',
                'strict_feasible','violation','fixed_reference_cost','elapsed_s','hard_pruned_area','not_completed',
                'silicon_area_mm2','reason','latency_ms','power_W','area_mm2','energy_mJ'])
        if (BASE/'template_coverage/best.json').is_file():
            coverage['best']=read(BASE/'template_coverage/best.json')
            metrics=coverage['best']['metrics']
            folder=BASE/'template_coverage/selected'
            # Supplemental diagnostic only: this is not a completed production RL episode.
            limits=[]
            for key,limit,unit in [('latency_s',.0008,'s'),('power_w',40.,'W'),('area_mm2',500.,'mm2')]:
                value=metrics[key]
                limits.append({'metric':key,'within_target':value<=limit,'excess_percent':max(0,value/limit-1)*100,'unit':unit})
            coverage['deployment']=deployment('S_template_audit','resnet18',{'folder':str(folder),
                'architecture':coverage['best']['architecture'],'metrics':metrics,'within_limits':False,
                'all_targets_met':False,'constraints':{'limits':limits}},dest)
    dump(BASE/'report_data.json',{'cases':cases,'summary':summary,'templates':templates,'coverage':coverage,
        'minimum_template_area_mm2':min(t['silicon_area_mm2'] for t in templates)})
    csvfile(BASE/'scenario_results.csv',summary)
    print(json.dumps({'cases':len(cases),'complete':sum(c['status']['status']=='complete' for c in cases),'deployments':len(summary)},ensure_ascii=False))

if __name__=='__main__':main()
