"""Actual final-version legacy replay and completed-v2-resume probes."""
from pathlib import Path
import json,sys,time
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'output/gui04_20261101'
sys.path.insert(0,str(ROOT/'simplified_rapidchiplet'))
from hybrid_gui import run_suite
from rl_dse import source_identity,run_suite as run_legacy_cli_suite
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def row(s):return next(r for r in s['runs'] if r['architecture']==s['display_architecture'])
def physical(s):
    m=row(s)['metrics'];return {k:m[k] for k in ['latency_s','power_w','area_mm2','energy_j','executed_macs','recompute_macs']}
def families(folder):return [t['action_plan']['family_id'] for t in read(folder/'toy/joint_search.json')['trace']]
def main():
    out=BASE/'release_acceptance';out.mkdir(exist_ok=True);sid=source_identity();start=time.monotonic()
    old=BASE/'v1_replay_toy';new=out/'v1_replay';a=read(old/'suite.json');b=run_legacy_cli_suite(read(old/'config.json'),new)
    assert physical(a)==physical(b)
    assert a['display_architecture']==b['display_architecture']
    assert families(old)==families(new)
    assert read(old/'toy/joint_search.json')['evaluations']==read(new/'toy/joint_search.json')['evaluations']
    v1={'source_identity':sid,'reference':'v1_replay_toy saved numeric replay of October31 Toy',
        'same_raw_physical_metrics':physical(b),'same_architecture':True,'same_action_family_sequence':True,'same_RL_full_query_count':True}
    dump(out/'v1_verified.json',v1)
    folder=out/'v2_resume';request={'ui_schema_version':2,'models':['toy'],'search_mode':'fast','budget_mode':'manual','budget':2,'seed':7}
    first=run_suite(request,folder);cfg=(folder/'config.json').read_bytes();phase=(folder/'toy/rl_effective_config.json').read_bytes()
    second=run_suite(request,folder,resume=True)
    assert physical(first)==physical(second)
    assert cfg==(folder/'config.json').read_bytes()
    assert phase==(folder/'toy/rl_effective_config.json').read_bytes()
    account=read(folder/'accounting.json')['toy'];assert account['total_full_evaluations_this_process']==0
    assert sid==source_identity()
    dump(out/'resume_verified.json',{'source_identity':sid,'same_effective_limits':True,'same_saved_RL_phase_config':True,
        'same_archived_raw_PPA':physical(second),'new_full_queries_on_completed_resume':0,'elapsed_s':time.monotonic()-start})
    print(json.dumps({'v1_numerical_replay':'pass','actual_v2_resume':'pass','source':sid}))
if __name__=='__main__':main()
