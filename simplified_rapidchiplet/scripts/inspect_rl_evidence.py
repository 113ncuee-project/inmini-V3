"""Compact, read-only analysis of the overnight runs and supplied conversation."""
import argparse
import csv
from html.parser import HTMLParser
import json
from pathlib import Path
import statistics
import re

class TextParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.ignore=0; self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.ignore+=1
        if tag in ('p','div','li','h1','h2','h3','tr'):self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.ignore=max(0,self.ignore-1)
    def handle_data(self,data):
        if not self.ignore:self.parts.append(data)

def read(path):return json.loads(path.read_text(encoding='utf-8'))
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2]);args=parser.parse_args()
    root=args.root; html=root/'tmp/inmin_v04/shared_conversation.html'
    if html.exists():
        p=TextParser();p.feed(html.read_text(encoding='utf-8'))
        if len(''.join(p.parts))<100:
            for match in re.finditer(r'enqueue\(("(?:[^"\\]|\\.)*")\)',html.read_text(encoding='utf-8')):
                try:
                    payload=json.loads(json.loads(match[1]))
                    for value in payload if isinstance(payload,list) else []:
                        if isinstance(value,str) and sum('\u4e00'<=c<='\u9fff' for c in value)>20:
                            p.parts.append(value+'\n\n')
                except ValueError:pass
        (html.parent/'shared_conversation.txt').write_text(''.join(p.parts),encoding='utf-8')
        print('conversation_chars',len(''.join(p.parts)))
    rows=[]
    for name in ('local_rl_v03_r18',*(f'local_rl_v03_p{i}' for i in range(2,7))):
        run=root/'output'/name
        for path in sorted((run/'cases').rglob('joint_search.json')):
            data=read(path); s=data.get('summary',{}); arm=path.parent.name
            if arm=='seed_only':continue
            records=read(path.parent/'worker/accounting.json') if (path.parent/'worker/accounting.json').exists() else []
            durations=[r['evaluation_elapsed_s'] for r in records if r.get('full_evaluations')]
            traces=data.get('trace',[])
            phases={key:statistics.mean(m.get('oracle_phase_wall_s',{}).get(key,0) for m in [t['current_metrics'] for t in traces])
                    for key in ('compile','communication_and_job_build','schedule','capacity_and_metrics','diagnostics')} if traces else {}
            rows.append(dict(case=str(path.parent.relative_to(run)),run=name,arm=arm,
                full=s.get('search_full_ppa'),updates=s.get('policy_updates'),gain=s.get('improvement_over_best_seed_pct'),
                mean_full_s=statistics.mean(durations) if durations else None,
                proposal_s=data.get('proposal_elapsed_s'),oracle_s=data.get('evaluation_elapsed_s'),wall=data.get('elapsed_s'),
                feasible_steps=sum(t.get('valid',False) for t in traces),steps=len(traces),
                entropy_mean=statistics.mean(t.get('policy_normalized_entropy',0) for t in traces) if traces else None,
                families={f:sum(t['action_plan']['family_id']==f for t in traces) for f in sorted({t['action_plan']['family_id'] for t in traces})},
                phases_current_state=phases))
    print(json.dumps(rows,ensure_ascii=False,indent=2))
    out=root/'tmp/inmin_v04/overnight_analysis.json';out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
