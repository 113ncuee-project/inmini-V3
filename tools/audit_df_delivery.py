"""Audit saved source, schedules, and test evidence without repeating DSE."""
from pathlib import Path
import csv
import hashlib
import json
import re
from collections import defaultdict

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/df_joint_20261011'

def calendar(folder):
    rows=list(csv.DictReader((folder/'timeline.csv').open(encoding='utf8')))
    by_id={r['id']:r for r in rows};resources=defaultdict(list)
    for r in rows:
        start,end=float(r['start_s']),float(r['finish_s'])
        for dep in filter(None,r['dependencies'].split('|')):
            assert float(by_id[dep]['finish_s'])<=start+1e-12
        for resource in filter(None,r['resources'].split('|')):
            if end>start:resources[resource].append((start,end))
    for spans in resources.values():
        spans.sort()
        assert all(a[1]<=b[0]+1e-12 for a,b in zip(spans,spans[1:]))
    return {'events':len(rows),'resources':len(resources),'dependency_and_calendar_valid':True}

def main():
    expected={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
              (ROOT/'simplified_rapidchiplet/simple_rapidchiplet/hybrid').glob('*.py')}
    data=json.loads((OUT/'validation.json').read_text(encoding='utf8'))
    assert data['source_sha256']==expected
    resnet=json.loads((OUT/'resnet18_32_dp/run.json').read_text(encoding='utf8'))
    assert resnet['metrics']['oracle_source_sha256']==expected
    assert resnet['metrics']['feasible'] and resnet['metrics']['backend']=='official_rapidchiplet'
    text=(OUT/'tests.txt').read_text(encoding='utf8')
    assert re.search(r'Ran 176 tests',text) and re.search(r'\nOK\s*$',text)
    schedule=calendar(OUT/'resnet18_32_dp')
    log=json.loads((OUT/'resnet18_32_dp/summary.json').read_text(encoding='utf8'))
    stats=resnet['metrics']['depth_first']
    report={'regression_tests':176,'source_matches':True,'official_rapidchiplet':True,
        'exact_resume':data['exact_resume_2_to_3'],'residual_numerical_modes':3,
        'resnet50_bottleneck_modes':3,'outer_methods':4,
        'full_resnet18':{'input':[1,3,32,32],'metrics':resnet['metrics'],
                        'elapsed_s':resnet['elapsed_s'],'calendar':schedule,
                        'selected_fusion_stacks':len(stats['stacks']) if stats else 0,
                        'fusion_search':{k:v for k,v in log['planning']['fusion_search'].items() if k!='candidates'}},
        'performance_limit':{'resnet18_input224':'search stopped after over20min; no finished PPA or improvement claim',
                             'scope':'analytical explorer runtime, not hardware inference latency'},
        'source_sha256':expected}
    (OUT/'validation_manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print({k:report[k] for k in ('regression_tests','source_matches','official_rapidchiplet','exact_resume')})
    print('ResNet18 selected stacks:',report['full_resnet18']['selected_fusion_stacks'],schedule)

if __name__=='__main__':main()
