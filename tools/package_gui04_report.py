"""Build an offline evidence index and audited ZIP without touching old reports."""
from pathlib import Path
import argparse,hashlib,json,shutil,zipfile,difflib,html,os

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'output/gui04_20261101'
PDF=ROOT/'output/pdf/INMIN_GUI04_修改與重跑實驗報告_20261101.pdf'
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def dump(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def rel(p):return Path(os.path.relpath(p,BASE)).as_posix()
def link(path,label):return '<a href="'+html.escape(rel(path),quote=True)+'">'+html.escape(label)+'</a>'

def source_snapshot():
    baseline=BASE/'baseline_source';dest=BASE/'final_source';manifest={};diff=[]
    for p in sorted((ROOT/'simplified_rapidchiplet').rglob('*')):
        if not p.is_file() or any(v in p.parts for v in ['__pycache__','results','.git']):continue
        if p.suffix not in ['.py','.html','.js','.css','.json','.md','.txt']:continue
        r=p.relative_to(ROOT/'simplified_rapidchiplet');target=dest/r
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
        manifest[r.as_posix()]=sha(p)
    for name in sorted(set(read(BASE/'baseline_source_sha256.json'))|{p.relative_to(ROOT/'simplified_rapidchiplet').as_posix() for p in (ROOT/'simplified_rapidchiplet').rglob('auto_*.py')}|{'gui_request.py','tests/test_gui04.py'}):
        r=Path(name);a=baseline/r;b=ROOT/'simplified_rapidchiplet'/r
        if not b.is_file():continue
        old=a.read_text(encoding='utf-8').splitlines(keepends=True) if a.is_file() else []
        new=b.read_text(encoding='utf-8').splitlines(keepends=True)
        diff.extend(difflib.unified_diff(old,new,fromfile='a/simplified_rapidchiplet/'+r.as_posix(),tofile='b/simplified_rapidchiplet/'+r.as_posix()))
    (BASE/'gui04_changes.patch').write_text(''.join(diff),encoding='utf-8')
    dump(BASE/'final_source_sha256.json',manifest)

def index(data):
    batch=Path(read(BASE/'final_batch.json')['root']);cards=[]
    for case in data['cases']:
        folder=batch/'experiments'/case['id'];cfg=case.get('suite',{}).get('config',{});spec=case['spec']
        request=cfg or spec.get('request',{});model=','.join(request.get('models',[spec.get('model','')]))
        pref=request.get('preference','固定條件控制');state=case['status']['status']
        title=html.escape(case['id']);body=f'<article data-model="{html.escape(model)}" data-pref="{html.escape(pref)}" data-state="{html.escape(state)}"><h2>{title}</h2>'
        body+='<p>'+html.escape(f'{model} · {pref} · {state}')+'</p>'
        if cfg:
            body+='<p>'+html.escape(f"限制 P/A/L={cfg.get('max_power')} W / {cfg.get('max_area')} mm² / {cfg.get('max_latency_ms')} ms；strict={cfg.get('strict_power')}/{cfg.get('strict_area')}/{cfg.get('strict_latency')}；{cfg.get('search_mode')} · Seed={cfg.get('seed')} · B={cfg.get('batch')} · RL ceiling={cfg.get('budget')} · wall/model={cfg.get('max_wall_time_s')}s")+'</p>'
        body+='<p>'+link(folder/'experiment.json','原始情境')+' · '+link(folder/'status.json','執行／來源紀錄')
        if cfg:body+=' · '+link(folder/'run/requested_ui.json','requested UI')+' · '+link(folder/'run/config.json','effective config')+' · '+link(folder/'run/accounting.json','實際計帳')
        body+='</p>'
        for detail in case['deployments']:
            m=detail['metrics'];f=Path(detail['folder']);e=BASE/'evidence'/detail['case']/detail['model']
            feasible=detail['strict_compliant'];body+='<section><h3>'+html.escape(detail['architecture'])+'</h3>'
            body+='<p>'+html.escape(f"{'符合嚴格限制' if feasible else '未符合／僅供診斷'}；L={m['latency_s']*1000:.8g} ms · P={m['power_w']:.8g} W · A={m['area_mm2']:.8g} mm² · E={m['energy_j']*1000:.8g} mJ")+'</p>'
            body+='<p>真正 DF stack 深度：'+html.escape(str([len(s['layer_ids']) for s in detail['mapping']['fusion_stacks']]) or '[]')+'（[] 表示沒有跨層 DF）</p><p>'
            body+=' · '.join(link(p,label) for p,label in [(f/'layout.html','互動布局／core／路徑'),(f/'architecture.svg','架構圖'),(f/'mapping.json','完整 mapping'),(f/'traffic_routes.json','完整資料流'),(e/'layers.csv','每層 partition／融合深度'),(e/'exact_spatial_partitions.csv','精確 shard 邊界'),(e/'execution_units.csv','每 unit／MAC'),(e/'flows.csv','每 flow 路徑與流量'),(e/'package_nodes.csv','實際座標'),(e/'package_links.csv','實際連線'),(e/'pipeline_groups_and_fusion.csv','group 與 fusion'),(e/'partition_classification.csv','分割分類')])
            body+='</p></section>'
        if not case['deployments']:body+='<p class="warn">沒有完成並可展示的完整 PPA；不補填數字。請查看停止原因與時間紀錄。</p>'
        body+='</article>';cards.append(body)
    models=sorted({m for c in data['cases'] for m in c['spec'].get('request',{}).get('models',[c['spec'].get('model','')]) if m})
    options=''.join('<option>'+html.escape(m)+'</option>' for m in models)
    text='''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>INMIN GUI04 實驗證據</title><style>body{font:16px/1.65 system-ui,"Microsoft JhengHei",sans-serif;color:#233548;background:#eef3f7;margin:0}main{max-width:1200px;margin:auto;padding:32px}h1{font-size:30px}h2{font-size:21px}h3{font-size:18px}article{background:white;border:1px solid #ccd8e2;border-radius:12px;margin:20px 0;padding:22px}section{border-top:1px solid #dde5ed;padding-top:8px}a{color:#155d86;overflow-wrap:anywhere}select,input{font:inherit;padding:8px;margin:6px;border:1px solid #9dafbc;border-radius:6px}.warn{color:#a24216}small{overflow-wrap:anywhere}nav{position:sticky;top:0;background:#eef3f7;padding:10px;border-bottom:1px solid #ccd8e2}p{margin:10px 0}pre{white-space:pre-wrap}</style><main><h1>INMIN GUI04 修改與實際重跑</h1><p>2026-11-01 · 所有 PPA 來自實際完成的分析 evaluator。有限搜尋僅代表 best-so-far，不保證全域最優。P／K 控制保留相同硬體與 mapping 其他欄位；沒有為了預期方向修改 reward。</p>'''
    text+='<p>'+' · '.join(link(p,l) for p,l in [(BASE/PDF.name,'PDF 報告'),(BASE/'GUI04_修改與實驗報告.md','文字報告'),(BASE/'auto_results.csv','Auto 結果 CSV'),(BASE/'partition_and_fusion_controls.csv','P/K 與融合控制 CSV'),(BASE/'docs/gui04_request_contract.md','新舊介面文件'),(BASE/'gui04_changes.patch','修改 diff'),(BASE/'report_audit.json','交付稽核'),(BASE/'bundle_manifest.json','附件 SHA256')])+'</p>'
    text+='<p class="warn">MobileNetV2 的快速與標準實際狀態均以各案紀錄為準；timeout 沒有 PPA 時保留空值，不能解讀為硬體不可行。</p>'
    text+='<nav><label>模型 <select id="model"><option value="">全部</option>'+options+'</select></label><label>Preference <select id="pref"><option value="">全部</option><option>balanced</option><option>low_power</option><option>low_latency</option><option>固定條件控制</option></select></label><label>搜尋 <input id="query" placeholder="案例名稱或模型"></label></nav>'+''.join(cards)
    text+='<p>離線重跑需要 PyTorch/torchvision 與 native RapidChiplet 等既有依賴。附件含來源快照與 trace，未封裝 Python 環境。完整舊報告另存，不會被本次覆寫。</p><script>function filter(){for(const c of document.querySelectorAll("article")){const m=document.querySelector("#model").value,p=document.querySelector("#pref").value,q=document.querySelector("#query").value.toLowerCase();c.hidden=!!((m&&!c.dataset.model.split(",").includes(m))||(p&&c.dataset.pref!==p)||(q&&!c.textContent.toLowerCase().includes(q)))}}for(const e of document.querySelectorAll("select,input"))e.addEventListener("input",filter);const params=new URLSearchParams(location.search);for(const key of ["model","pref","query"]){if(params.has(key))document.querySelector("#"+key).value=params.get(key)}filter();</script></main></html>'
    (BASE/'index.html').write_text(text,encoding='utf-8')

def package():
    data=read(BASE/'gui04_report_data.json');source_snapshot()
    (BASE/'docs').mkdir(exist_ok=True)
    for name in ['gui04_request_contract.md','gui04_implementation_progress.md']:shutil.copyfile(ROOT/'docs'/name,BASE/'docs'/name)
    shutil.copyfile(PDF,BASE/PDF.name);index(data)
    historical=read(BASE/'historical_result_sha256.json');bad=[p for p,h in historical.items() if not (ROOT/p).is_file() or sha(ROOT/p)!=h]
    assert not bad,bad
    dump(BASE/'historical_integrity_verified.json',{'checked':len(historical),'unchanged':len(historical),'mismatches':bad})
    batch=Path(read(BASE/'final_batch.json')['root'])
    roots=[BASE/'evidence',batch/'experiments',BASE/'final_source',BASE/'revision_D_source',BASE/'baseline_source',BASE/'docs',BASE/'release_acceptance',BASE/'gui_final_evidence',BASE/'failure_records']
    files=set(p for root in roots if root.exists() for p in root.rglob('*') if p.is_file())
    names=['index.html',PDF.name,'GUI04_修改與實驗報告.md','gui04_report_data.json','auto_results.csv','partition_and_fusion_controls.csv','gui04_changes.patch','final_source_sha256.json','revision_D_source_sha256.json','baseline_source_sha256.json','historical_result_sha256.json','historical_integrity_verified.json','final_batch.json','source_cohorts.json','full_regression_release.log','full_regression_delivery.log','release_acceptance.log','gui04_release_contract_tests.log','report_audit.json','pdf_visual_QA.json','gui04_final_default.png','gui04_final_result.png','gui04_final_panel.png','gui04_ResNet18_result.png']
    files.update(BASE/n for n in names if (BASE/n).is_file())
    files.update(p for p in (ROOT/'tools').glob('*gui04*.py'))
    files.update([ROOT/'tools/collect_detailed_report_data.py',ROOT/'tools/build_detailed_project_report.py'])
    def retained(p):return not any(v in p.parts for v in ['oracle_runtime','__pycache__','.locks']) and p.name not in ['checkpoint.json','rl_checkpoint.json'] and p.suffix!='.pkl'
    files={p for p in files if retained(p)}
    # Scratch worker/checkpoint files are excluded; full durable archives remain.
    names_map={p:('tools/'+p.name if p.parent==ROOT/'tools' else p.relative_to(BASE).as_posix()) for p in files}
    manifest={name:sha(p) for p,name in sorted(names_map.items(),key=lambda x:x[1])}
    dump(BASE/'bundle_manifest.json',{'algorithm':'SHA256','files':manifest,'excluded':'ephemeral oracle workspaces, model pickle and large RL checkpoints; complete durable archives included'})
    names_map[BASE/'bundle_manifest.json']='bundle_manifest.json'
    target=ROOT/'output/INMIN_GUI04_報告與實驗附件_20261101.zip'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p,n in sorted(names_map.items(),key=lambda x:x[1]):z.write(p,'INMIN_GUI04/'+n)
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
        for n,h in manifest.items():assert hashlib.sha256(z.read('INMIN_GUI04/'+n)).hexdigest()==h,n
    print(json.dumps({'zip':str(target),'files':len(names_map),'bytes':target.stat().st_size,'old_files_unchanged':len(historical)},ensure_ascii=False))

if __name__=='__main__':package()
