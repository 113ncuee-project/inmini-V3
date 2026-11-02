"""Package the real report evidence with an offline, filterable review index."""
from pathlib import Path
from datetime import datetime,timezone,timedelta
from html import escape
from collections import Counter
import hashlib,json,zipfile,shutil,csv,math
from urllib.parse import quote

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'output/detailed_project_report_20261031'
PDF=ROOT/'output/pdf/INMIN_整體流程與實驗結果報告_20261031.pdf'
ZIP=ROOT/'output/INMIN_報告與完整實驗附件_20261031.zip'
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def rel(p):return Path(p).relative_to(BASE).as_posix()
def link(p,label):return '<a href="'+quote(str(p).replace('\\','/'),safe='/')+'">'+escape(label)+'</a>'
def num(x):return f'{x:.6g}'
def goal(cfg,key):
    v=cfg.get('max_'+key)
    return '未啟用' if v is None else str(v)+('（硬）' if cfg.get('strict_'+('latency' if key=='latency_ms' else key),True) else '（軟）')

def main():
    d=read(BASE/'report_data.json');cases=d['cases'];now=datetime.now(timezone(timedelta(hours=8))).isoformat()
    shutil.copy2(PDF,BASE/PDF.name)
    deployments=[v for c in cases for v in c['deployments']]+[d['coverage']['deployment']]
    for v in deployments:
        m=v['metrics']
        assert math.isclose(m['power_w'],m['energy_j']/m['latency_s'],rel_tol=1e-12)
        assert math.isclose(m['area_mm2'],sum(n['width_mm']*n['height_mm'] for n in v['package']['nodes']),rel_tol=1e-12)
        p=BASE/'evidence'/v['case']/v['model']
        with (p/'execution_units.csv').open(encoding='utf-8-sig',newline='') as f:
            units=list(csv.DictReader(f))
        assert len(units)==v['exact_unit_count']
        assert sum(int(r['MACs']) for r in units)==m['executed_macs']
        with (p/'flows.csv').open(encoding='utf-8-sig',newline='') as f:
            assert sum(1 for _ in csv.DictReader(f))==v['full_flow_count']
        for layer in v['layers']:
            assert math.prod(layer['partition_BKHW'])==layer['core_count']
    for c in cases:
        if c['status']['status']=='complete':
            assert c['status']['source_before']==c['status']['source_after']
            for name,value in c['status']['source_after'].items():assert sha(ROOT/name)==value
        else:assert not c['deployments']
    for folder in (BASE/'fusion_on_initial_attempt').iterdir():
        p=folder/'status.json'
        if p.is_file():
            s=read(p)
            if s['status']=='running':
                s.update(status='interrupted',previous_status='running',report_audit_time=now,
                    error='Initial full-size DF-on attempt interrupted before completion due to evaluation cost; no final solution claimed')
                dump(p,s)
    formal=[c for c in cases if c['id']!='R_power_DF_on_prior']
    counts=Counter(c['status']['status'] for c in formal)
    audit={'generated_taipei':now,'formal_scenarios':len(formal),'formal_status_counts':dict(counts),
        'completed_prior_DF_on_controls':1,'selected_formal_and_prior_model_deployments':len(d['summary']),
        'supplementary_diagnostic_deployments':1,'unique_mapping_profiles_in_PDF':8,
        'source_stable_all_completed':all(c['status']['source_stable'] for c in cases if c['status']['status']=='complete'),
        'coverage':{k:d['coverage']['best'][k] for k in ['evaluated_templates','hard_pruned_templates','not_completed_templates']},
        'checks':['exact executable-unit MAC sums equal stored executed_macs for all 16 selected deployments',
                  'all 16 deployments satisfy P=E/T and area=sum of physical silicon geometry',
                  'CSV unit/flow counts and partition cardinality match selected deployments',
                  'all completed cases have matching before/after production source hashes',
                  'completed source manifests still match files at report packaging time',
                  'no final PPA is attributed to a timeout or interrupted run'],
        'pdf_sha256':sha(PDF),'physical_metrics_are':'analytical estimates; no silicon measurement or timing signoff',
        'reproduction_note':'External native RapidChiplet backend and Python dependencies are required; evidence can be reviewed offline without rerunning.'}
    dump(BASE/'report_audit.json',audit)
    rows=[]
    prefs={'balanced':'均衡','low_power':'低功率','small_area':'小面積','low_latency':'低延遲'}
    for c in cases:
        cfg=c['config'];status=c['status']['status'];pname=prefs[cfg['preference']]
        if not c['deployments']:
            rows.append(f'<tr data-model="{escape(" ".join(cfg["models"]))}" data-pref="{cfg["preference"]}" data-state="timeout"><td>{escape(c["id"])}</td><td>{escape(" + ".join(cfg["models"]))}</td><td>{pname}</td><td>{goal(cfg,"power")} W<br>{goal(cfg,"area")} mm²<br>{goal(cfg,"latency_ms")} ms</td><td colspan="4">600 秒超時，沒有完成的 RL 最終推薦。{link("experiments/"+c["id"]+"/status.json","狀態與來源")}</td></tr>')
        for v in c['deployments']:
            m=v['metrics'];state='feasible' if v['strict_compliant'] else 'diagnostic';folder=rel(v['folder'])
            ev='evidence/'+c['id']+'/'+v['model']
            rows.append(f'<tr data-model="{v["model"]}" data-pref="{cfg["preference"]}" data-state="{state}"><td>{escape(c["id"])}</td><td>{escape(v["model"])}<br>{cfg.get("toy_spatial",8) if v["model"]=="toy" else cfg.get("input_size",224)} 平方輸入</td><td>{pname}</td><td>{goal(cfg,"power")} W<br>{goal(cfg,"area")} mm²<br>{goal(cfg,"latency_ms")} ms</td><td>{"可行推薦" if state=="feasible" else "僅診斷，非推薦"}<br>{escape(v["architecture"])}<br>DF '+(','.join(str(len(s['layer_ids'])) for s in v['mapping']['fusion_stacks']) or '1 無跨層融合')+f'</td><td>{num(m["latency_s"]*1000)} ms<br>{num(m["power_w"])} W<br>{num(m["area_mm2"])} mm²<br>{num(m["energy_j"]*1000)} mJ</td><td>'+link(folder+'/layout.html','開啟互動布局')+'<br>'+link(folder+'/architecture.svg','硬體架構')+'</td><td>'+link(ev+'/layers.csv','逐層切分與深度')+'<br>'+link(ev+'/flows.csv','全部資料路徑')+'<br>'+link(ev+'/exact_spatial_partitions.csv','確切空間分割')+'<br>'+link(ev+'/execution_units.csv','實際執行區域')+'<br>'+link(ev+'/pipeline_groups_and_fusion.csv','Groups 與 fusion')+'</td></tr>')
    supplemental=d['coverage']['deployment'];sp=rel(supplemental['folder'])
    html='''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>INMIN 實驗報告與部署證據</title>
<style>body{font:16px/1.6 system-ui,"Microsoft JhengHei";margin:32px;color:#22313f;background:#f8fafb}main{max-width:1500px;margin:auto}h1{font-size:29px}h2{font-size:22px;margin-top:30px}a{color:#175b85}nav{display:flex;gap:20px;flex-wrap:wrap}table{border-collapse:collapse;width:100%;background:white;font-size:14px}th,td{padding:12px;text-align:left;border:1px solid #d8e0e5;vertical-align:top}th{background:#244962;color:white;position:sticky;top:0}tr[data-state=diagnostic]{background:#fff5ed}tr[data-state=timeout]{background:#f1f1f1}label{margin-right:22px}select{padding:7px}button{padding:7px 12px}small{color:#4c5b66}.scroll{overflow:auto}.note{max-width:1050px}</style><main><h1>INMIN 整體流程與實驗結果</h1>
<p class="note">固定每顆 compute chiplet 為 2×2 完整 cores。以下連結來自實際執行結果；PPA 是分析式估計。PDF 包含完整流程、演算法與逐層配置，本頁可篩選模型、偏好和狀態，並開啟每份部署的互動布局。</p>'''
    html+='<nav>'+link(PDF.name,'49 頁完整 PDF 報告')+link('INMIN_整體流程與實驗結果報告.md','可編輯 Markdown')+link('scenario_results.csv','PPA 總表 CSV')+link('template_coverage_results.csv','模板覆蓋稽核 CSV')+link('report_audit.json','來源與結果稽核')+'</nav>'
    html+=f'<p>本輪 {len(formal)} 個情境：{counts["complete"]} 個完成、{counts["timeout"]} 個超時；另附 1 個已完成 DF-on 對照。共同模型各自列一行。空間／資料流附件包含另外 1 個補充模板診斷解。</p>'
    html+='''<h2>實際部署與最佳可行解</h2><p><label>模型 <select id="model"><option value="">全部</option><option>resnet18</option><option>resnet34</option><option>alexnet</option><option>mobilenet_v2</option><option>toy</option></select></label><label>偏好 <select id="pref"><option value="">全部</option><option value="balanced">均衡</option><option value="low_power">低功率</option><option value="small_area">小面積</option><option value="low_latency">低延遲</option></select></label><label>狀態 <select id="state"><option value="">全部</option><option value="feasible">可行推薦</option><option value="diagnostic">僅診斷</option><option value="timeout">超時</option></select></label><button id="reset">重設篩選</button></p><p><small>硬＝嚴格遵守有勾選；軟＝未勾選，只作軟目標。未啟用上限與未勾選嚴格不同。篩選只改變顯示，不會重新計算 PPA。所有結果 batch=1。</small></p><div class="scroll"><table><thead><tr><th>案例</th><th>模型</th><th>Preference</th><th>PPA 輸入上限</th><th>狀態／最佳架構</th><th>實際估計 PPA</th><th>可視化</th><th>確切分割與資料流</th></tr></thead><tbody>'''
    html+=''.join(rows)+'</tbody></table></div>'
    html+='<h2>嚴格 0.8 ms 條件的補充模板稽核</h2><p>10 個模板完成 seed 評估，3 個由固定面積剪枝，2 個沒有完成的 PPA。已完成候選中最近解為 2×2 compute-chiplet mesh，0.954409 ms、14.150699 W、188.855537 mm²，仍超過延遲硬限制；這不是 RL 最終推薦，也不是全域無解證明。</p><nav>'+link(sp+'/layout.html','補充診斷互動布局')+link('evidence/S_template_audit/resnet18/layers.csv','補充逐層配置')+link('evidence/S_template_audit/resnet18/flows.csv','補充完整資料流')+'</nav>'
    html+='''<h2>閱讀與重現</h2><p>直接開啟各 layout.html 即可切換 Layer 與資料流並點選 die。若瀏覽器阻擋本地連結，可在解壓後的資料夾以 Python 啟動 http.server，再由 localhost 開啟本頁。CSV 使用 UTF-8 BOM；JSON 保留完整 precision。source/ 含本次使用的程式與契約；重跑另需 PyTorch、torchvision 及既有 native RapidChiplet backend，詳見 README。</p><script>const selects=['model','pref','state'].map(id=>document.getElementById(id));function filter(){document.querySelectorAll('tbody tr').forEach(r=>{r.hidden=!selects.every(s=>!s.value||(r.dataset[s.id]||'').split(' ').includes(s.value))})}selects.forEach(s=>s.addEventListener('change',filter));document.getElementById('reset').onclick=()=>{selects.forEach(s=>s.value='');filter()};</script></main></html>'''
    (BASE/'index.html').write_text(html,encoding='utf-8')
    readme='''# INMIN 報告與實驗附件

解壓後開啟 index.html；完整 PDF 與 Markdown 位於同一層。

- 16 個本輪情境中 13 個完成、3 個 timeout，另附 1 個已完成 DF-on 對照。
- 共 15 份正式／對照模型部署；另有 1 份補充模板診斷部署。完全相同配置在 PDF 去重為 8 份逐層表。
- 所有 PPA 均為分析式估計。沒有宣稱 RTL、實體 timing、silicon power 或量化準確率驗證。
- 所謂最佳僅是各案例的已完成搜尋預算內最佳可行解。不可行案例只列 closest 診斷。
- 主 224×224 對照關閉跨層 DF；開啟融合的控制、32×32 測試、Toy 均明確另列。最初中斷的 full-size DF-on 嘗試不作推薦。
- 所有完成案例 source_before/source_after 一致。來源 hash 位於各 status.json。
- template_coverage 為獨立補充 seed 實驗，非原 RL episode。10 個完成、3 個面積剪枝、2 個沒有完成 PPA。C16_1x16 在完整評估中被中斷，C16_2x8 沒有再啟動；不可補造數值。

## 檔案

evidence/：逐層、每個 shard／unit、所有 flows、實體位置／連線與 search transitions CSV。
experiments/：設定、狀態、來源 hash、搜尋紀錄、selected mapping／hardware／package／traffic、可離線開啟的互動布局。
fusion_on_initial_attempt/：最初 DF-on 的已完成低功率控制與未完成紀錄。
template_coverage/：每個已完成 seed mapping、hardware、PPA 紀錄及最近診斷方案。
prior_validation/：上一輪 231 測試、消融與稽核證據。這些測試沒有在本輪修改報告時重跑。
source/：對應產生報告的程式快照，包含 runner、collector、report builder 與產品程式。
bundle_manifest.json：每份附件的 bytes 與 SHA256；report_audit.json 為本次資料核對摘要。

## 重跑

在專案根目錄執行 .venv/Scripts/python.exe -X utf8 tools/run_detailed_report_cases.py --workers 2。
使用 --only R_power 等可只重跑指定情境。預設每案 cap 600 秒，完整評估預算與 seed 預算分開。
tools/collect_detailed_report_data.py 由結果重建確切 shard／unit，並核對 MAC 守恆。
tools/build_detailed_project_report.py 使用 ReportLab 與 Microsoft JhengHei 字型建立 PDF。
tools/build_report_bundle.py 建立本附件。

本附件可獨立閱讀，但不是免安裝重跑環境。原 native backend 的預設路徑為
C:\\Users\\user\\Downloads\\rapidchiplet-main (2)\\rapidchiplet-main，實際安裝位置須配合環境。
相依套件與原論文 PDF／ZIP 沒有打包進本附件；既有 workspace/.venv 未複製。
'''
    (BASE/'REPORT_README.md').write_text(readme,encoding='utf-8')
    files={}
    def add(path,arc=None):
        p=Path(path)
        if p.is_file():files[arc or rel(p)]=p
    for p in [PDF,BASE/'INMIN_整體流程與實驗結果報告.md',BASE/'index.html',BASE/'REPORT_README.md',BASE/'scenario_results.csv',BASE/'template_catalog.csv',BASE/'template_coverage_results.csv',BASE/'report_data.json',BASE/'report_audit.json']:
        add(p,PDF.name if p==PDF else None)
    for p in (BASE/'evidence').rglob('*'):add(p)
    selected=[]
    for c in cases:
        folder=BASE/('fusion_on_initial_attempt/R_power' if c['id']=='R_power_DF_on_prior' else 'experiments/'+c['id'])
        for name in ['experiment.json','status.json','run.log','run/suite.json','run/recommendation.json','run/accounting.json']:
            add(folder/name)
        for model in c['config']['models']:
            for name in ['seed.json','context.json','accounting.json','joint_search.json','workload.json']:
                add(folder/'run'/model/name)
        selected.extend(Path(v['folder']) for v in c['deployments'])
    for folder in (BASE/'fusion_on_initial_attempt').iterdir():
        for p in folder.rglob('*'):
            if p.is_file() and (p.name in ['status.json','experiment.json','run.log','seed.json','context.json']):add(p)
    for p in (BASE/'template_coverage').glob('*.json'):add(p)
    for folder in (BASE/'template_coverage').glob('gemini_*'):
        for name in ['mapping.json','hardware.json']:add(folder/name)
    selected.append(BASE/'template_coverage/selected')
    for folder in selected:
        for p in folder.iterdir():
            if p.is_file() and p.suffix in ['.json','.csv','.html','.svg']:add(p)
    for p in [ROOT/'output/rl_dse_20261031/full_unittest_release.log',ROOT/'output/rl_dse_20261031/ablations_final/summary.json',ROOT/'output/rl_dse_20261031/ablations_final/independent_audit.json',ROOT/'output/rl_dse_20261031/acceptance_final/result.json']:
        add(p,'prior_validation/'+p.name)
    for p in (ROOT/'tools').glob('*report*.py'):add(p,'source/tools/'+p.name)
    for p in (ROOT/'simplified_rapidchiplet').rglob('*.py'):
        if not any(x in p.parts for x in ['__pycache__','.venv']):add(p,'source/'+p.relative_to(ROOT).as_posix())
    for p in (ROOT/'docs').glob('*.md'):add(p,'source/docs/'+p.name)
    for name in ['requirements.txt','TANGRAM_SEED_ADAPTER.md','RL_DSE_ACCEPTANCE_20261031.md']:
        add(ROOT/'simplified_rapidchiplet'/name,'source/simplified_rapidchiplet/'+name)
    manifest=[{'file':arc,'bytes':p.stat().st_size,'sha256':sha(p)} for arc,p in sorted(files.items())]
    dump(BASE/'bundle_manifest.json',manifest)
    with zipfile.ZipFile(ZIP,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for arc,p in sorted(files.items()):z.write(p,arc)
        z.write(BASE/'bundle_manifest.json','bundle_manifest.json')
    with zipfile.ZipFile(ZIP) as z:
        assert z.testzip() is None
    print(json.dumps({'zip':str(ZIP),'bytes':ZIP.stat().st_size,'files':len(files)+1,'audit':audit},ensure_ascii=False))

if __name__=='__main__':main()
