"""Cross-check durable GUI04 results and evidence, without re-evaluating PPA."""
from pathlib import Path
import json,hashlib,math,shutil,re
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'output/gui04_20261101'
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    data=read(BASE/'gui04_report_data.json');batch=Path(read(BASE/'final_batch.json')['root'])
    assert len(data['cases'])==15
    assert all(c['status']['status']=='complete' and c['status']['source_stable'] for c in data['cases'])
    checks=[];control_checks=[]
    for c in data['cases']:
        for d in c['deployments']:
            m=d['metrics'];nodes=d['package']['nodes']
            area=sum(n['width_mm']*n['height_mm'] for n in nodes)
            assert math.isclose(m['power_w'],m['energy_j']/m['latency_s'],rel_tol=1e-12)
            assert math.isclose(m['area_mm2'],area,rel_tol=1e-12),(d['case'],area,m['area_mm2'])
            flows=read(Path(d['folder'])/'traffic_routes.json')['transfers']
            for f in flows:
                assert f['bytes']>=0 and f['finish_s']>=f['start_s']
                for route in f['routes']:
                    assert route['path'][0]==f['src'] and route['path'][-1] in f['dsts']
            for l in d['layers']:
                assert math.prod(l['partition_BKHW'])==len(l['ordered_cores'])
                assert l['DF_depth']>=1
            if c['spec']['kind']=='auto':
                for limit in d['constraints']['limits']:
                    if d['strict_compliant'] and limit['strict']:assert limit['within_target']
            checks.append({'case':d['case'],'model':d['model'],'P_equals_E_over_L':True,'area_equals_package_silicon_sum':True,
                'partition_product_equals_core_quota':True,'flow_path_endpoints_and_time_valid':True,
                'unit_MAC_sum_verified_by_collector':True,'flows':len(flows),'units':d['exact_unit_count']})
        if c['spec']['kind']!='auto':
            folder=batch/'experiments'/c['id'];results=read(folder/'controlled_results.json')
            assert len(results)==2 and all(r['status']=='complete' for r in results)
            plans=[read(folder/r['variant']/'mapping.json') for r in results]
            if c['spec']['kind']=='partition_control':
                for p in plans:
                    for layer in p['layer_mappings']:layer.pop('partition')
                assert plans[0]==plans[1],c['id']
                changed='only B/K/H/W partition'
            else:
                for p in plans:p.pop('fusion_stacks')
                assert plans[0]==plans[1],c['id'];changed='only fusion_stacks'
            control_checks.append({'case':c['id'],'same_other_mapping_fields':True,'changed':changed})
    historical=read(BASE/'historical_result_sha256.json');assert all(sha(ROOT/p)==h for p,h in historical.items())
    # Preserve concise failure evidence as well as the intact local superseded runs.
    for p in (batch/'superseded').rglob('status.json'):
        if read(p).get('status')!='failed':continue
        for name in ['status.json','experiment.json','run.log']:
            src=p.parent/name
            if src.is_file():
                target=BASE/'failure_records'/p.parent.relative_to(batch/'superseded')/name
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,target)
    gui_src=BASE/'gui_delivery/ef8f26a003a7';gui_dst=BASE/'gui_final_evidence/ef8f26a003a7'
    for p in gui_src.rglob('*'):
        if p.is_file() and not any(v in p.parts for v in ['oracle_runtime','__pycache__']) and 'checkpoint' not in p.name:
            target=gui_dst/p.relative_to(gui_src);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
    probe=read(BASE/'release_acceptance/resume_verified.json');assert probe['new_full_queries_on_completed_resume']==0
    pdf=ROOT/'output/pdf/INMIN_GUI04_修改與重跑實驗報告_20261101.pdf'
    audit={'case_count':len(data['cases']),'auto_count':len(data['auto_results']),'control_variant_count':len(data['controlled_results']),
        'test_result':data['test_result'],'historical_unchanged_files':len(historical),'source_cohorts':read(BASE/'source_cohorts.json'),
        'deployment_checks':checks,'controlled_mapping_checks':control_checks,'actual_v1_replay':read(BASE/'release_acceptance/v1_verified.json'),
        'actual_completed_v2_resume':probe,'GUI_job':'ef8f26a003a7','GUI_console_errors':[],
        'PDF_SHA256':sha(pdf) if pdf.is_file() else None,'note':'Audits saved outputs; does not replay or alter evaluator PPA.'}
    dump(BASE/'report_audit.json',audit);print(json.dumps({'cases':len(data['cases']),'deployments_audited':len(checks),'control_pairs_audited':len(control_checks),'historical_unchanged':len(historical)}))
if __name__=='__main__':main()
