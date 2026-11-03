"""Small integrated v0.4 validation: stop/resume, exact budgets and audit.

Reuses a previously measured Toy workload. No DNN, model download or images.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from run_local_rl_diagnostics import APP, read, write, sources, sha


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seed-case',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();out=args.out.resolve()
    if out.exists():raise ValueError('choose a new validation output')
    out.mkdir(parents=True);before=sources();began=time.perf_counter()
    runner=APP/'replay_mapping_dse.py';analyzer=APP/'scripts/analyze_replay_mapping.py'
    def invoke(script,*arguments):
        result=subprocess.run([sys.executable,'-u','-X','utf8',str(script),*map(str,arguments)],capture_output=True,text=True,encoding='utf-8')
        with (out/'commands.log').open('a',encoding='utf-8') as f:
            f.write(json.dumps(list(map(str,arguments)))+'\n'+result.stdout+result.stderr+'\n')
        if result.returncode:raise AssertionError(result.stderr+'\n'+result.stdout)
        return result
    def command(target):
        return ['--seed-case',str(args.seed_case.resolve()),'--out',str(target),'--queries','12','--seconds','90',
            '--methods','replay_rl,random,sa,greedy','--eval-timeout','15','--shortlist','24','--local-candidates','6','--save-candidate-sets']
    full,partial=out/'full',out/'resumed'
    invoke(runner,*command(full))
    with (out/'interrupted.log').open('wb') as log:
        process=subprocess.Popen([sys.executable,'-u','-X','utf8',str(runner),*command(partial)],stdout=log,stderr=log)
        deadline=time.monotonic()+90
        while process.poll() is None and time.monotonic()<deadline:
            checkpoint=read(partial/'replay_rl/checkpoint.json',{})
            if checkpoint.get('steps',0)>=2:
                (partial/'STOP_REQUESTED').touch();break
            time.sleep(.05)
        else:
            if process.poll() is None:(partial/'STOP_REQUESTED').touch()
            raise AssertionError('could not reach intended checkpoint')
        code=process.wait(timeout=60)
    if not code or read(partial/'status.json')['status']!='interrupted':raise AssertionError('controlled stop not recorded')
    interrupted_count=sum(r.get('full_evaluations',0) for r in read(partial/'replay_rl/worker/accounting.json'))
    invoke(runner,'--resume','--out',partial)
    for method in ('replay_rl','random','sa','greedy'):
        a,b=read(full/method/'checkpoint.json'),read(partial/method/'checkpoint.json')
        if a['elite']['mapping']!=b['elite']['mapping']:raise AssertionError(method+': resumed best mapping differs')
        def hashes(folder):return [json.loads(line)['state_hash'] for line in (folder/method/'events.jsonl').read_text(encoding='utf-8').splitlines()]
        if hashes(full)!=hashes(partial):raise AssertionError(method+': resumed action sequence differs')
        ledger=read(partial/method/'worker/accounting.json');physical=[r for r in ledger if r.get('full_evaluations')]
        if len({r['durable_key'] for r in physical})!=len(physical):raise AssertionError('completed PPA recomputed')
        if a['policy_updates']!=b['policy_updates']:raise AssertionError('policy updates differ after resume')
        if read(partial/method/'summary.json')['full_ppa']!=12:raise AssertionError('Toy full query ceiling not reached')
    warmups=[]
    for method in ('replay_rl','random','sa'):
        warmups.append([json.loads(line)['state_hash'] for line in (full/method/'events.jsonl').read_text(encoding='utf-8').splitlines()[:4]])
    if not warmups[0]==warmups[1]==warmups[2]:raise AssertionError('SA acceptance RNG changed the common uniform warmup')
    protected={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in partial.rglob('*') if p.is_file() and p.name in ('checkpoint.json','accounting.json','summary.json')}
    invoke(analyzer,'--out',partial)
    invoke(runner,'--resume','--out',partial)
    after={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in partial.rglob('*') if p.is_file() and p.name in ('checkpoint.json','accounting.json','summary.json')}
    if protected!=after:raise AssertionError('analysis or completed resume modified physical/checkpoint evidence')
    audit=read(partial/'analysis/audit.json')
    if not audit['passed']:raise AssertionError(audit['errors'])
    result=dict(passed=True,elapsed_s=time.perf_counter()-began,source_stable=before==sources(),source_identity=sha(before),
        interrupted_search_full_ppa=interrupted_count,unique_physical_ppa=audit['actual_unique_physical_ppa'],
        checks=['all four methods reach exactly 12 charged full PPA', 'cooperative stop and identical resumed action order',
                'same best exact mapping and policy update count', 'no duplicate durable PPA',
                'analysis/completed resume do not mutate PPA or checkpoints', 'full ledger/source/physical/reward audit'])
    write(out/'result.json',result);print(json.dumps(result,indent=2))
    if not result['source_stable']:raise AssertionError('sources changed during workflow validation')


if __name__=='__main__':main()
