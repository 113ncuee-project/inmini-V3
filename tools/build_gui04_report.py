"""Source-backed GUI04 implementation and actual experiment report."""
from pathlib import Path
from collections import Counter
from xml.sax.saxutils import escape
import json,hashlib,re
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4,landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import BaseDocTemplate,PageTemplate,Frame,Paragraph,Table,TableStyle,Spacer,PageBreak,NextPageTemplate,Image
from build_detailed_project_report import package_figure,FONT,BOLD

ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'output/gui04_20261101'
PDF=ROOT/'output/pdf/INMIN_GUI04_修改與重跑實驗報告_20261101.pdf'
W=A4[0]-80;LW=landscape(A4)[0]-72;story=[];md=[]
S={k:ParagraphStyle(k,fontName=BOLD if k in ['title','h1','h2','head'] else FONT,
    fontSize=size,leading=lead,textColor=colors.white if k=='head' else colors.HexColor('#233548'),
    spaceAfter=space,wordWrap='CJK',keepWithNext=k in ['h1','h2'])
    for k,size,lead,space in [('title',23,33,15),('h1',17,25,12),('h2',12,18,8),('body',9.5,15.5,8),('small',8.3,12.5,6),('cell',8,11.5,0),('head',8,11.5,0)]}
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def fmt(v,d=6):return '-' if v is None else f'{float(v):.{d}g}'
def p(v,kind='body'):
    value=str(v).replace('≤','<=').replace('ᵀ','^T').replace('—','-').replace('–','-').replace('‑','-')
    return Paragraph(escape(value).replace('\n','<br/>'),S[kind])
def para(v,kind='body'):story.append(p(v,kind));md.append(str(v)+'\n')
def head(v,kind='h1'):story.append(p(v,kind));md.append(('# ' if kind=='h1' else '## ')+v+'\n')
def page(v,land=False):
    if story:story.extend([NextPageTemplate('L' if land else 'P'),PageBreak()])
    head(v)
def table(headers,rows,widths):
    t=Table([[p(v,'head') for v in headers]]+[[p(v,'cell') for v in row] for row in rows],colWidths=widths,repeatRows=1,hAlign='LEFT')
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#244962')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#edf3f7')]),('GRID',(0,0),(-1,-1),.4,colors.HexColor('#d3dce2')),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]));story.extend([t,Spacer(1,8)])
    md.append('| '+' | '.join(headers)+' |\n| '+' | '.join('---' for h in headers)+' |\n')
    for row in rows:md.append('| '+' | '.join(str(v).replace('\n','; ').replace('|','/') for v in row)+' |\n')
    md.append('\n')
def bank(v,name,key):return v.get('SRAM_ledger',{}).get(name,{}).get(key)
def flow(v,name,key):return v.get('flow_ledger',{}).get(name,{}).get(key,0)
def kib(v):return '-' if v is None else fmt(v/1024)
def footer(c,doc):
    c.saveState();c.setFont(FONT,7);c.setFillColor(colors.HexColor('#697680'));c.drawString(36,21,'INMIN GUI04 / 2026-11-01 / Analytical PPA');c.drawRightString(c._pagesize[0]-36,21,str(doc.page));c.restoreState()

def build():
    data=read(BASE/'gui04_report_data.json');cases=data['cases'];auto=data['auto_results'];controls=data['controlled_results']
    source={r['source_identity'] for r in auto}
    incomplete=[c['id'] for c in cases if c['status']['status']!='complete']
    profiles={'fast':'快速','standard':'標準','deep':'深入'}
    story.append(Spacer(1,26));para('INMIN GUI04 修改與重跑實驗報告','title')
    para('2026-11-01 / Gemini 2×2-core chiplet / Auto 搜尋與 Weight-shared 假設')
    para('本報告核對新版前端、版本化請求、時間／查詢預算、多模板起點與有界 fusion DP，並呈現實際完整 evaluator 的結果。ResNet 的 Weight-shared／P-parallel 優勢被當作待驗證假設，沒有加入偏好加分、修改成本係數或指定勝出 partition。')
    para(f'本批次共有 {len(cases)} 個情境，包含 {len(auto)} 個模型／搜尋模式結果與 {len(controls)} 個固定條件控制方案。各方案的設定、來源版號、完整查詢數、停止原因、每層 partition 與 fusion 深度均可追溯。PPA 是實際跑出的分析估計，不是 silicon 量測。')
    if incomplete:para('此版尚有未完成情境：'+', '.join(incomplete)+'。未完成者不補造 PPA。')
    head('主要發現','h2')
    for cid in ['resnet18_standard','resnet18_low_power','resnet18_low_latency']:
        r=next(v for v in auto if v['case']==cid)
        para(f"{cid}：實際推薦 {r['best_architecture']}，L={fmt(r['latency_ms'])} ms、P={fmt(r['power_W'])} W、A={fmt(r['area_mm2'])} mm²；Conv 分割={r['best_conv_partition_counts']}。")
    para('本輪 ResNet 的所有均一 P-only 控制（含相同 temporal K=64 補充組）均因 GLB／UB 容量未通過，不能把其診斷延遲與能量當作合法解來判勝負；目前沒有證據支持「ResNet 全模型 P-only 一定較佳」。自由搜尋則保留實際較佳的 P/K 混合或 K-only 配置。')
    para('MobileNetV2 快速與標準模式均在上限內未完成 seed，無可報告 PPA。所有本輪自由搜尋最佳解都沒有跨層 DF stack；depth2/3/6 的能力驗收與手動控制不被冒稱為已選中的融合深度。')
    for cid in sorted({v['case'] for v in controls if v['variant']=='weight_shared_P'}):
        pair={v['variant']:v for v in controls if v['case']==cid and v.get('physical_feasible')}
        if all(k in pair for k in ['weight_shared_P','activation_shared_K']):
            a=pair['weight_shared_P'];b=pair['activation_shared_K']
            para(f"{cid} 固定條件控制：P-parallel 延遲 {fmt(a['latency_ms'])} ms、能量 {fmt(a['energy_mJ'])} mJ；K-parallel 為 {fmt(b['latency_ms'])} ms、{fmt(b['energy_mJ'])} mJ。P 相對 K 的延遲差 {(a['latency_ms']/b['latency_ms']-1)*100:+.2f}%、能量差 {(a['energy_mJ']/b['energy_mJ']-1)*100:+.2f}%。")
    para('控制試驗的均一 P／K 分割與自由搜尋的混合解是不同問題。最後推薦必須以該次搜尋的 archive 為準；控制結果不能被拿來硬改 RL 最佳解。')
    page('一 真正修改的系統與相容性')
    table(['範圍','已實作行為'],[
        ['正式前端 04','預設 standard、single Batch=1；進階 Seed=7／Auto 預算收合。沿用原 /api/jobs，保留前三區 PPA、strict 與模型欄位。'],
        ['v2 normalization','原始 requested_ui 與數值 effective config 分開。Auto 不直接塞入舊整數欄位；手動數值預算原樣使用。'],
        ['多架構起點','按 count 與 throughput/weight-bandwidth proxy 覆蓋合法矩形形狀，保留多個已完整評估起點；小模板有 P/K／容量替代提案。'],
        ['真正的時間保護','獨立 evaluator 行程可在單次評估超時時停止；使用已完成 archive，未完成回應不當成物理拒絕或可行 PPA。'],
        ['局部 fusion DP','固定 Part/CG/FD 的 compiled-region proposal DP，顯式 A10＋A1 交易；保留 depth1 baseline，tile/cache 與全域 PPA 分開。'],
        ['相容與 resume','v1 不進 Auto resolver；v2 恢復保存的 suite 與 RL phase 設定。來源／模型／設定不同即拒絕沿用 checkpoint。']
    ],[W*.25,W*.75])
    para('歷史 10/31 結果未批次覆寫；獨立 SHA256 清單檢查涵蓋 578 個檔案。新功能與實驗位於 gui04_20261101。開發校準及中斷紀錄保留，不能混入正式結果。')
    para('結果保留兩個實際來源版號：D=75c7bcc5…、E=9624c002…。D 完成且來源穩定的案例原樣保留；兩個檔案讀取失敗案例在 E 重跑，新增控制亦使用 E。E 只增加已發布回應的 Windows 讀鎖重試（受原 deadline 約束）與 scratch 清理容錯；PPA、reward、候選生成與有效設定沒有改動。兩份來源快照與逐案完整 hash 均附上，沒有把 D 結果改標成 E。')
    para('效能修正排除 derived report 後再計算 state hash 與 transaction 副本，保留同一設計識別碼；相同 per-core microkernel 可以跨系統矩形幾何重用精確 cache。PPA、精度、資源與 reward 公式未為了預期結果而調整。')
    page('系統流程與本次真正搜尋的變數')
    table(['階段','實際資料與決策'],[
        ['1 使用者輸入','模型、三項 PPA 上限／strict、PPA preference → v2 requested UI → 數值 effective config。'],
        ['2 建立 DAG','PyTorch/torchvision FX 取得 operators、tensor BKHW、shortcut、權重、MAC 與相依關係；BatchNorm/ReLU post-ops 與跨層 DF 分開。'],
        ['3 初始化','合法 Gemini 模板 → bounded throughput/weight-bandwidth proxy → Tangram 式 DP/beam 起點；每個 retained seed 都經完整 evaluator。'],
        ['4 聯合 RL','診斷特徵 → actor-critic 選 atomic／composite family → 交易式套用 → 完整合法性 → global PPA/reward → 更新 policy/archive。'],
        ['5 深度融合提案','局部 closed-DAG window DP 只提出 tile/cache/boundary；需要調整 group 時明確提交 A10+A1。更深候選仍由全域 evaluator 驗收。'],
        ['6 排程與 PPA','編譯 shard／temporal units／tensor region → 片內 PE/NoC、跨 die D2D、IO/DRAM → 排程時間與流量／SRAM 能量 → P=E/T、總矽面積。'],
        ['7 可視化','只從完成的合法 archive 選 best-so-far；輸出布局、DAG、每層 partition、DF stacks、core、XY paths、PPA 與停止原因。']
    ],[W*.24,W*.76])
    para('硬體固定每 compute chiplet 為 2×2 個完整 cores。每 core 有 GLB 2 MiB、16 PEs、1024 MAC/cycle，INT8×INT8→INT24；整顆 4096 MAC/cycle、1 GHz。NoC 每 link 32 GB/s；每側 2 個 D2D interfaces、每 interface 16 GB/s。模板決定 compute 數與矩形 mesh、兩側 IO/DRAM 個數；不把 package 任意擺放當成已支援動作。')
    page('動作與最佳解的含義')
    table(['動作','正式語意'],[
        ['A1 / A2','融合 stack split/merge/shift boundary；各層 B/K/H/W partition。'],
        ['A3 / A4','DF sink tile；layer/group core 資源轉移。'],
        ['A5 / A6','層內 core ordering／placement；同一 spatial group 內的跨層 core 交換，保留 quota。'],
        ['A7 / A8','支援的 overlap cache；input/weight/output DRAM configuration。'],
        ['A9 / A11','切換合法硬體模板；A11 是 A9 的同義入口，不重複算獨立能力。'],
        ['A10','group 邊界／排程模式／microbatch；Batch=1 時只允許 microbatch=1。'],
        ['C1–C9 / C10','已支援的交易式複合族與診斷導引提案；C10 communication-aware partition DP 尚未接入。']
    ],[W*.25,W*.75])
    para('本機使用 linear actor-critic 與有界候選 shortlist。11 個 action 標籤對應 10 個不同 atomic 語意；每次複合提交若有一項不合法即整筆回滾。硬體切換、group 調整與 partition 仍會付相同 global evaluation 成本。初始化與 RL 成果分別記帳，不能把 seed 的改善直接說成 policy 學得。')
    page('二 Auto 的上限與真實計帳')
    table(['模式','RL ceiling','Wall/model','Seed quota','架構目標','單次 eval cap'],[['快速','12','90 s','3','2','45 s'],['標準 r2','48','480 s','8','3','400 s'],['深入','128','1200 s','16','5','360 s']],[W*.17,W*.15,W*.18,W*.16,W*.16,W*.18])
    para('初輪標準模式的 270 秒單次上限曾截斷 MobileNetV2 冷啟動評估，因此 r2 在原 480 秒整體包絡內放寬單次上限至 400 秒。舊校準與失敗／中斷紀錄保留，但不混入本次 release_r2 表格。')
    para('Ceiling 是上限，不是保證使用次數或更佳品質。一般表單的「Auto」會解析成上述有界設定，手動預算不被重新改寫。啟動／模組載入與最後 suite 索引的額外時間，另反映在實際整案 wall time。多模型是逐模型的相同硬體部署要求，不是多模型同時競爭執行的模擬。')
    para('Seed、RL exact queries、cache hits、局部編譯與 archive 保存分開。已付費且完整評估的 seed 可進入 bootstrap cache/archive，不冒充新的 RL query。所有改進方案保留完整 trace 後輸出，報告 replay query=0；export 的次數與時間仍列帳。')
    para('系統依最近 evaluator 耗時的 median 估計剩餘可用查詢數，並保留輸出時間。timeout／wall cap 下的 best-so-far 只包含完整評估結果。如果只有 seed 完成、RL query=0，報告明確標示為 seed-derived best-so-far，不能稱為已學得的 RL 改善。')
    para('Fusion 深度為每個實際 stack 的長度。起始 cap=4，合法且有正局部 proxy 機會時最多擴展到 8；有候選不保證選中。六層壓測已防止短前綴耗盡 DP 預算：先保留 singleton baseline 與完整窗口 0→N edge，再分配其餘提案。所有更深交易仍需完整 evaluator。')
    para('Batch=1 唯一合法 microbatch=1。任意 floorplan／routing、C10 communication-aware partition DP、跨 chiplet C reduction、peak power、未支援 cache 方向仍未開啟。深入模式完整 128-query 品質仍屬 heuristic 上限；本輪深入 smoke 使用明確手動 12 queries，不宣稱已校準全部深搜空間。')
    page('三 使用者輸入與 preference')
    table(['情境','P / A / L 上限','勾選與偏好'],[
        ['Toy / ResNet18 / MobileNetV2 fast、standard','20 W / 250 mm² / 3 ms','三項 strict=true；balanced'],
        ['ResNet18 low_power','20 W / 250 mm² / 3 ms','三項 strict=true；low_power；manual RL=16'],
        ['ResNet18 low_latency','40 W / 500 mm² / 1.2 ms','三項 strict=true；low_latency；manual RL=16'],
        ['Toy deep smoke','三項上限均未啟用','balanced；manual RL=12']
    ],[W*.4,W*.28,W*.32])
    para('正式聯合搜尋呼叫 rl_dse.make_objective：score=(P/Pref)^wP × (A/Aref)^wA × (L/Lref)^wL，越低越好；每個 workload 的 reference 在該次搜尋固定。balanced 的 P/A/L 權重各 1/3；low_power 為 0.8/0.1/0.1；low_latency 為 0.1/0.1/0.8。能量 E 另列，energy_weight=0。')
    para('Power 是同一推論時間窗的平均 P=E/T，不是 peak power；低功率解可能比均衡解更慢、總能量也較高。small_area 選項仍可用，本輪沒有額外跑它的 Auto 情境。舊 preferences.py 的 energy objective 不是本次正式 joint search 的呼叫路徑。')
    page('四 Auto 實際找到的最佳可行解',True)
    rows=[]
    for r in auto:
        arch=r['best_architecture'] or ('無推薦；診斷 '+r['display_architecture'] if r['display_architecture'] else '無完成方案')
        rows.append([r['case'],arch,fmt(r['latency_ms']),fmt(r['power_W']),fmt(r['area_mm2']),fmt(r['energy_mJ']),fmt(r['wall_s']),r['execution_status']])
    table(['案例','最佳／診斷架構','L ms','P W','A mm²','E mJ','DSE wall s','實際狀態'],rows,[LW*.20,LW*.16,LW*.08,LW*.08,LW*.09,LW*.08,LW*.08,LW*.23])
    para('只有 best_architecture 才是可行推薦。找不到結果或未完成完整評估的欄位保留空值，表中顯示 -。這些都是有限模板／預算內完成的估算，未聲稱全域最優。','small')
    para('所有真實模型輸入為 224×224、batch=1，Toy 為 8 channels、8×8。所有正式 Auto 案例開啟 fusion 搜尋。快速／標準均衡案例 P≤20 W、A≤250 mm²、L≤3 ms；low_latency 案例 P≤40 W、A≤500 mm²、L≤1.2 ms；低功率使用均衡同一組上限；Toy 深入手動案例未啟用 PPA 上限。','small')
    page('五 查詢 融合覆蓋與停止原因',True)
    table(['案例','Seed full','RL full / cap','Policy updates','已完成起點數','局部提出 DF 深度','選中且評估 DF 深度','最後選中 stack 深度','停止原因'],[[r['case'],str(r['seed_full_evaluations']),f"{r['RL_full_evaluations']}/{r['query_ceiling']}",str(r['policy_updates']),str(len(r['bootstrap_architectures'])),str(r['proposed_fusion_depths']),str(r['selected_and_evaluated_fusion_depths']),str(r['best_DF_depths']) if r['best_DF_depths'] else '1 無跨層 DF',r['stop_reason']] for r in auto],[LW*.18,LW*.06,LW*.09,LW*.07,LW*.08,LW*.1,LW*.1,LW*.1,LW*.22])
    para('提出／局部編譯／經全域 evaluator 評估／最後 archive 選中是不同階段。DF-on 不代表一定融合；[] 表示沒有此種已完成結果，不補造深度。架構覆蓋數是已完成的 seed 數，不能把 15 個模板目錄當成全部已評估。','small')
    for r in auto:
        if r['RL_full_evaluations']==0 and r['best_architecture']:
            para(r['case']+'：目前推薦來自已完整評估的初始化 archive，RL 尚無新的完整查詢，不宣稱學習帶來改善。','small')
    page('六 Weight-shared 假設如何公平比較')
    para('外層 partition=(B,K,H,W)。此處 P=H×W 的輸出位置並行：P-parallel 通常令 K 分割為 1，讓多個 cores 使用相同權重區域；K-parallel 切輸出 channels，各 core 使用不同權重並共享輸入 activation。這與 PE 內的 weight-stationary loop order 不同。')
    para('每組控制固定同一硬體：ResNet18／34 各有單顆 compute chiplet、4 cores 的比較，另補 ResNet18 四顆 2×2 mesh、16 cores 的跨 chiplet 比較。INT8/INT24、1 GHz、模型與 Batch=1 相同；各配對保留相同 group 邊界、ordered core lists、DRAM selectors、cold weights、temporal hints 與 precision，只改合法 B/K/H/W partition。無合法 P-only 分割的層保留原分割，fallback 名單完整保存。')
    para('本組控制的 PE 內資料流固定 output_stationary，沒有把它偷偷切換成 weight_stationary。每層使用第一個合法的 P-only 或 K-only 候選，並非各家族內充分優化後的最優值；因此結果只回答這組固定配置的差異。')
    para('原始全尺寸 temporal K 控制若因 P-only 超出 GLB 而不可行，另設 tileK=64 的配對：P 與 K 都使用相同 temporal BKHW=(0,64,0,0)，其餘欄位完全保留。只在同一 case 的兩種合法方案之間算比值；絕不拿 tiled P 與 untiled K 混比。0 表示此維度由現有編譯器依 shard／容量決定。')
    para('ResNet 名稱不能直接推導每一層都 weight-intensive；實際 weight/input/output 大小逐層列出。比較指標包括全模型 L/P/A/E、DRAM 權重 bytes、送達 GLB 的權重副本、NoC/D2D hop-bytes，以及各 PE WL1 的 refill/write bytes 與 read/write 比。')
    para('同一權重經 multicast 可共享一段連線，仍需支付目的 core/PE 副本與 SRAM 存取；P 分割也可能增加 halo、權重容量或改變每 core 的工作粒度。L1 refills、pipeline／DRAM 邊界與 lane/PE 利用率可能抵銷某個方向的重用收益。以下解釋僅根據此模型的實際流量與存取帳本。')
    para('WL1 read/write 比是本模型的聚合存取重用指標；不是未經量測的真實硬體 cache hit rate。控制的固定 partition 不代表該 partition 家族已被全域優化。若某固定方案容量不合法，只能下「此配置不合法」的結論，不能宣布整個 P 或 K 家族無效。')
    para('本模型的 reuse.py 會以 exact weight region 在每個接收 core 保存到最後 reader，並檢查容量。ResNet 後段 512×512×3×3 的 INT8 權重共 2,359,296 B，已大於每 core 2,097,152 B GLB；純 P 分割保留完整 K 的副本，可能成為這個 residency 模型的限制。較小 temporal tile 不保證立刻釋放所有仍有後續 reader 的權重；本次沒有為了讓 P 通過而改變這項假設。')
    page('七 固定硬體的 P 與 K 控制結果',True)
    pc=[r for r in controls if r['variant'] in ['weight_shared_P','activation_shared_K']]
    table(['模型／硬體／variant','物理合法','L ms','P W','E mJ','權重 DRAM KiB','GLB delivered KiB','NoC hop KiB','D2D hop KiB','WL1 write KiB','WL1 read/write'],[[r['model']+f" C={r.get('compute')} tileK={'64' if r.get('matched_temporal_tile_BKHW') else 'auto'}\n"+r['variant'],'合法' if r.get('physical_feasible') else r['status']+' 不可比較',fmt(r['latency_ms']) if r.get('physical_feasible') else '-',fmt(r['power_W']) if r.get('physical_feasible') else '-',fmt(r['energy_mJ']) if r.get('physical_feasible') else '-',kib(flow(r,'dram_weight','DRAM_bytes')),kib(flow(r,'dram_weight','local_delivered_bytes')),kib(flow(r,'dram_weight','core_NoC_hop_bytes')),kib(flow(r,'dram_weight','D2D_hop_bytes')),kib(bank(r,'WL1','write_bytes')),fmt(bank(r,'WL1','reads_per_filled_byte'))] for r in pc],[LW*.18,LW*.07,LW*.07,LW*.07,LW*.07,LW*.09,LW*.10,LW*.09,LW*.09,LW*.09,LW*.08])
    para('KiB=1024 bytes。DRAM payload、目的端 delivered bytes 與每 hop 累計 bytes 是不同量。面積在固定同一硬體的控制中保持一致，不能歸因於 partition 的改變。所有 fallback 層與每層權重／輸入量在控制結果 JSON 及 evidence CSV。','small')
    page('容量違反與重用觀察')
    invalid=[r for r in pc if not r.get('physical_feasible')]
    bad_rows=[]
    for r in invalid:
        violations=r.get('violations') or []
        glb=[int(m.group(1)) for v in violations if (m:=re.search(r'GLB needs (\d+) B',v))]
        ub=[int(m.group(1)) for v in violations if (m:=re.search(r'unified buffer needs (\d+) B',v))]
        bad_rows.append([r['case'],str(len(violations)),fmt(max(glb)/1024 if glb else None),fmt(max(ub)/1024 if ub else None)])
    table(['P-only 控制案例','違反數','max GLB KiB','max die UB KiB'],bad_rows,[W*.48,W*.12,W*.2,W*.2])
    para('限制是每 core GLB 2048 KiB、每 die 合計 8192 KiB。上述 max 值只摘要已列出的容量違反，不是 peak power。失敗方案的流量／SRAM 帳本用於診斷；即使排程器算出時間，也不能當成合法 PPA 比較。完整每 core 違反與 raw metrics 仍保存在 JSON。')
    for cid in sorted({r['case'] for r in pc}):
        pair={r['variant']:r for r in pc if r['case']==cid and r.get('physical_feasible')}
        if len(pair)==2:
            a,b=pair['weight_shared_P'],pair['activation_shared_K']
            para(f"{cid}：P/K 延遲比 {a['latency_ms']/b['latency_ms']:.6f}，能量比 {a['energy_mJ']/b['energy_mJ']:.6f}；WL1 write bytes 比 {bank(a,'WL1','write_bytes')/bank(b,'WL1','write_bytes'):.6f}。這些比例由同一 case 的兩個合法完成結果直接計算。",'small')
    para('本輪所有 P-only 的完整 ResNet 控制都未通過容量，因此沒有合法的 P/K 全模型比值。這不證明所有合法 P 家族方案都較差；未做 eviction-aware weight streaming 與各家族充分搜尋，結論限於本次映射與既有 residency 模型。')
    page('八 完整模型實際採用的混合分割',True)
    table(['案例','Conv P-only','Conv K-only','Conv mixed P/K','Conv single-core','最佳架構','真正 DF stacks'],[[r['case'],str(r['best_conv_partition_counts'].get('weight_shared_P',0)),str(r['best_conv_partition_counts'].get('activation_shared_K',0)),str(r['best_conv_partition_counts'].get('mixed_PK',0)),str(r['best_conv_partition_counts'].get('serial_single_core',0)),r['best_architecture'] or '-',str(r['best_DF_depths']) or '-'] for r in auto],[LW*.26,LW*.11,LW*.11,LW*.13,LW*.13,LW*.15,LW*.11])
    para('表內僅統計 Conv2d，沒有把 Add／Flatten／FC 的 fallback 當作卷積分割優勢。Single-core 表示該層未跨 cores 做 spatial partition，不等於 PE array 沒有內部並行。完整逐層表另含 group、tile、cache、FD 與真正 DF 深度。','small')
    selected_details=[]
    for case_id in ['resnet18_standard','resnet18_low_power','resnet18_low_latency','mobilenet_v2_standard','toy_standard']:
        case=next((c for c in cases if c['id']==case_id),None)
        if not case or not case['deployments']:continue
        d=case['deployments'][0];selected_details.append((case_id,d));m=d['metrics']
        page('部署 '+case_id)
        para(f"{d['architecture']}；L={fmt(m['latency_s']*1000)} ms，P={fmt(m['power_w'])} W，A={fmt(m['area_mm2'])} mm²，E={fmt(m['energy_j']*1000)} mJ。")
        if not d['strict_compliant']:
            para('這是最接近的診斷方案，沒有符合使用者全部嚴格限制，因此不作可行推薦。未達項目：'+str([l for l in d['constraints']['limits'] if not l['within_target']]))
        story.append(package_figure(d));para(f"實際 package 幾何；compute mesh {d['hardware']['cluster_rows']}×{d['hardware']['cluster_cols']}，每 die 2×2 cores；先 X 後 Y routing，雙側 IO 與 DRAM。",'small')
        stacks=d['mapping']['fusion_stacks']
        if stacks:table(['所有 DF stack 成員','深度','sink H×W','overlap'],[[' → '.join(s['layer_ids']),str(len(s['layer_ids'])),str(s['tile_hw']),s['overlap']] for s in stacks],[W*.56,W*.09,W*.15,W*.2])
        else:para('沒有跨層 DF stack：全部 LayerSpec 的 DF 深度均為 1；parser 的 BatchNorm/ReLU post-ops 不算跨層融合。')
        sample=d['layers'][:2]+[l for l in d['layers'] if l['operator']=='Add'][:1]+d['layers'][-1:]
        table(['代表 Layer','輸出 BKHW','Partition BKHW','Ordered cores'],[[l['layer'],str(l['output_BKHW']),str(l['partition_BKHW']),l['core_text']] for l in sample],[W*.25,W*.23,W*.19,W*.33])
        table(['實際 flow','Payload bytes','第一目的地完整 path'],[[f['id']+' '+f['kind'],str(f['bytes']),' → '.join(f['routes'][0]['path'])] for f in d['flow_examples'][:2]],[W*.25,W*.15,W*.6])
        para(f"完整 {d['full_flow_count']} flows、{d['exact_shard_count']} shards、{d['exact_unit_count']} executable units 均可在 evidence/{case_id}/{d['model']} 核對。")
    page('九 同條件融合控制與深層驗收')
    fusion=[r for r in controls if r['model']=='toy']
    table(['固定 mapping 控制','L ms','P W','E mJ','DF 深度','重算 MAC'],[[r['variant'],fmt(r['latency_ms']),fmt(r['power_W']),fmt(r['energy_mJ']),str(r.get('DF_depths',[])),str(r.get('recompute_MACs','-'))] for r in fusion],[W*.30,W*.13,W*.13,W*.13,W*.12,W*.19])
    pair={r['variant']:r for r in fusion}
    if len(pair)==2:
        a=pair['DF_depth3_same_mapping'];b=pair['no_cross_layer_fusion']
        para(f"本控制 DF depth3 的延遲增加 {(a['latency_ms']/b['latency_ms']-1)*100:.2f}%，能量增加 {(a['energy_mJ']/b['energy_mJ']-1)*100:.2f}%；帳本記錄額外 recompute MAC={a['recompute_MACs']}。這組未再優化的融合配置沒有收益，不能因此說所有融合皆無效。")
    para('上述比較只開關同一份 mapping 的三層 fusion stack；硬體、partition、placement、FD、batch 與精度固定。它驗證融合機制，不能冒稱 RL 自動選到該手動控制方案。真正搜尋的 stack 深度以逐案 archive 為準。')
    para('新增六層 closed chain 壓測會要求 production proposal hook 真的回傳合法 depth6 交易，再由 HybridEvaluator 評估並核對執行 MAC。這個測試驗證較深動作能執行，不代表 ResNet 或 MobileNet 的最佳解一定應選 depth6。')
    page('十 驗證 複現與限制')
    para(data.get('test_result','完整回歸結果見 log')+'。包含舊流程回歸、v1/v2 normalization、手動預算、resume、期限中止、depth2/3/6 真實候選與完整物理驗收。沙箱 localhost 被拒的初次 log 仍保留，正式通過證據為可存取 localhost 的 final log。')
    para('原 10/31 Toy 配置的真實 v1 重播，raw latency/power/area/energy/MAC、action family sequence 與 RL query count 相同；來源版號不同，不宣稱所有 DNN 逐 bit 等價。實際 v2 resume probe 確認有效 phase limits 不變、archive PPA 不變，完成工作重開 0 個新 full queries。')
    table(['限制','如何呈現'],[['有限搜尋','只稱已完成預算內 best-so-far；不保證更深／更多 queries 必然改善。'],['Timeout','未完成評估不填 PPA，不當成硬體不合法；保存已驗證 archive。'],['Proxy DP','bounded 編譯估計與 heuristic 剪枝；全域 reward 始終來自完整 evaluator。'],['硬體估計','文獻成本與固定 1 GHz，沒有 RTL/timing/silicon signoff 或模型量化準確率驗證。'],['外部依賴','重跑需要既有 PyTorch/torchvision 與 native RapidChiplet；附件可離線閱讀但不是免安裝環境。']],[W*.24,W*.76])
    para('重跑到全新目錄：.venv/Scripts/python.exe -X utf8 tools/run_gui04_experiments.py --workers 2 --output-root output/gui04_reproduce_20261101。本輪是兩個實驗 worker 同機執行，前段亦有 GUI／回歸工作同機執行；wall time 不是隔離 CPU benchmark。Seed=7 不能取代多 seed 統計，本文不據此宣稱 RL 優於 random。')
    para('原始來源與審查：gui04_changes.patch；docs/gui04_request_contract.md；requested_ui/config/context/seed_states/joint_search/verified_archive/accounting；auto_results.csv 與 partition_and_fusion_controls.csv；逐層、每 shard、每 unit、flow 路徑與 SRAM 帳本均在附件。最終批次使用獨立 release_r2 目錄，並採 Windows 原子替換重試與完整 evaluator 子行程樹中止。')
    page('附錄 最佳方案逐層配置',True)
    seen=set()
    for case_id,d in selected_details:
        key=hashlib.sha256(json.dumps({'workload':d['metrics']['workload_fingerprint'],'arch':d['architecture'],'mapping':d['mapping']},sort_keys=True).encode()).hexdigest()
        if key in seen:para(case_id+' 與先前配置完全相同，完整證據仍各自保存。','small');continue
        seen.add(key);head(case_id+' '+d['model'],'h2')
        table(['Layer / operator','輸出 BKHW','Partition BKHW','Ordered cores','Group / mode','DF depth / tile / cache'],[[l['layer']+'\n'+l['operator'],str(l['output_BKHW']),str(l['partition_BKHW']),l['core_text'],l['pipeline_group']+'\n'+l['group_mode'],str(l['DF_depth'])+'\n'+str(l['DF_sink_tile_HW'])+'\n'+l['overlap']] for l in d['layers']],[LW*.22,LW*.14,LW*.13,LW*.22,LW*.13,LW*.16])
    PDF.parent.mkdir(parents=True,exist_ok=True)
    doc=BaseDocTemplate(str(PDF),pagesize=A4,title='INMIN GUI04 修改與重跑實驗報告',author='INMIN project')
    doc.addPageTemplates([PageTemplate(id='P',pagesize=A4,frames=[Frame(40,40,W,A4[1]-80,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)],onPage=footer),PageTemplate(id='L',pagesize=landscape(A4),frames=[Frame(36,36,LW,landscape(A4)[1]-72,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)],onPage=footer)])
    doc.build(story)
    (BASE/'GUI04_修改與實驗報告.md').write_text('\n'.join(md),encoding='utf-8')
    print(json.dumps({'pdf':str(PDF),'auto':len(auto),'controls':len(controls),'source_versions':len(source)},ensure_ascii=False))

if __name__=='__main__':build()
