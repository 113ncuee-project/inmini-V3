"""Create a source-backed Traditional Chinese project report from real runs."""
from __future__ import annotations
from collections import Counter,defaultdict
from datetime import datetime,timezone,timedelta
import hashlib
import json
import math
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT,TA_CENTER
from reportlab.lib.pagesizes import A4,landscape
from reportlab.lib.styles import ParagraphStyle,getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import BaseDocTemplate,PageTemplate,Frame,Paragraph,Spacer,PageBreak,NextPageTemplate,Table,TableStyle,KeepTogether
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.graphics.shapes import Drawing,Rect,Line,String,Polygon,PolyLine

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'output'/'detailed_project_report_20261031'
PDF=ROOT/'output'/'pdf'/'INMIN_整體流程與實驗結果報告_20261031.pdf'
FONT='MSJH';BOLD='MSJHB'
pdfmetrics.registerFont(TTFont(FONT,'C:/Windows/Fonts/msjh.ttc',subfontIndex=0))
pdfmetrics.registerFont(TTFont(BOLD,'C:/Windows/Fonts/msjhbd.ttc',subfontIndex=0))
pdfmetrics.registerFontFamily(FONT,normal=FONT,bold=BOLD,italic=FONT,boldItalic=BOLD)
INK=colors.HexColor('#202d3b');BLUE=colors.HexColor('#244962');PALE=colors.HexColor('#edf3f7')
W=A4[0]-84;LW=landscape(A4)[0]-72

styles={
 'title':ParagraphStyle('Title',fontName=BOLD,fontSize=24,leading=34,textColor=colors.black,spaceAfter=16),
 'subtitle':ParagraphStyle('Subtitle',fontName=FONT,fontSize=12,leading=19,textColor=colors.black,spaceAfter=12),
 'h1':ParagraphStyle('Heading1',fontName=BOLD,fontSize=17,leading=24,textColor=colors.black,spaceBefore=8,spaceAfter=12,keepWithNext=True),
 'h2':ParagraphStyle('Heading2',fontName=BOLD,fontSize=12.5,leading=19,textColor=colors.black,spaceBefore=10,spaceAfter=7,keepWithNext=True),
 'body':ParagraphStyle('Body',fontName=FONT,fontSize=9.5,leading=15.2,textColor=INK,spaceAfter=7,wordWrap='CJK'),
 'small':ParagraphStyle('Small',fontName=FONT,fontSize=8.5,leading=12.5,textColor=INK,spaceAfter=6,wordWrap='CJK'),
 'cell':ParagraphStyle('Cell',fontName=FONT,fontSize=8.5,leading=11.5,textColor=INK,wordWrap='CJK'),
 'tiny':ParagraphStyle('Tiny',fontName=FONT,fontSize=7.8,leading=10.5,textColor=INK,wordWrap='CJK'),
 'thead':ParagraphStyle('TableHead',fontName=BOLD,fontSize=8.5,leading=12,textColor=colors.white,wordWrap='CJK'),
 'caption':ParagraphStyle('Caption',fontName=FONT,fontSize=8.2,leading=12,textColor=colors.HexColor('#555555'),spaceBefore=4,spaceAfter=10,wordWrap='CJK'),
}
story=[];md=[];heading_number=0

def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def fmt(v,n=5):return '-' if v is None else f'{float(v):.{n}g}'
def yes(v):return '勾選' if v else '未勾選'
def limit(v):return '未啟用' if v is None else f'{v:g}'
def target(name,value,unit,strict):return name+' 未啟用' if value is None else f'{name} ≤ {value:g} {unit}（{yes(strict)}）'
def modelname(v):return {'resnet18':'ResNet 18','resnet34':'ResNet 34','mobilenet_v2':'MobileNetV2','alexnet':'AlexNet','toy':'Toy residual'}.get(v,v)
def prefname(v):return {'balanced':'均衡','low_power':'低功率','small_area':'小面積','low_latency':'低延遲'}[v]
def shortcore(v):return str(v).replace('compute:','C').replace('/core:',':c').replace('memory:','D').replace('io:','I')

def P(text,kind='body'):
    rendered=str(text).replace('≤','<=').replace('ᵀ','^T').replace('—','-').replace('–','-').replace('‑','-')
    return Paragraph(escape(rendered).replace('\n','<br/>'),styles[kind])
def para(text,kind='body'):
    story.append(P(text,kind));md.append(str(text)+'\n')
def heading(text,level=1):
    global heading_number
    heading_number+=1
    p=P(text,'h1' if level==1 else 'h2');p._bookmarkName=f'section_{heading_number}'
    p._tocLevel=level-1;story.append(p);md.append('#'*level+' '+text+'\n')
def page(text,land=False):
    if story:story.extend([NextPageTemplate('landscape' if land else 'portrait'),PageBreak()])
    heading(text)
def table(headers,rows,widths,small=False):
    data=[[P(h,'thead') for h in headers]]+[[P(c,'tiny' if small else 'cell') for c in row] for row in rows]
    t=Table(data,colWidths=widths,repeatRows=1,hAlign='LEFT')
    t.setStyle(TableStyle([
       ('BACKGROUND',(0,0),(-1,0),BLUE),('GRID',(0,0),(-1,-1),.45,colors.HexColor('#d9d9d9')),
       ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,PALE]),('VALIGN',(0,0),(-1,-1),'MIDDLE'),
       ('LEFTPADDING',(0,0),(-1,-1),5),('RIGHTPADDING',(0,0),(-1,-1),5),
       ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4),
    ]))
    story.extend([t,Spacer(1,8)])
    md.append('| '+' | '.join(str(h).replace('\n',' ') for h in headers)+' |\n'+'| '+' | '.join('---' for _ in headers)+' |\n')
    for row in rows:md.append('| '+' | '.join(str(c).replace('\n','; ') for c in row)+' |\n')
    md.append('\n')

def text(d,x,y,value,size=9,bold=False,anchor='start',color=INK):
    d.add(String(x,y,str(value),fontName=BOLD if bold else FONT,fontSize=size,fillColor=color,textAnchor=anchor))
def arrow(d,x1,y1,x2,y2,color=BLUE,width=1):
    d.add(Line(x1,y1,x2,y2,strokeColor=color,strokeWidth=width))
    a=math.atan2(y2-y1,x2-x1);r=4
    d.add(Polygon([x2,y2,x2-r*math.cos(a-.5),y2-r*math.sin(a-.5),x2-r*math.cos(a+.5),y2-r*math.sin(a+.5)],fillColor=color,strokeColor=color))

def flow_figure():
    d=Drawing(W,170)
    labels=[('使用者輸入','模型  batch  PPA  偏好'),('模型 DAG','tensor shape  residual'),('Tangram 式起點','分組  配額  分割'),('候選式 RL','原子與複合動作')]
    gap=10;cw=(W-3*gap)/4
    for i,(title,sub) in enumerate(labels):
        x=i*(cw+gap);d.add(Rect(x,100,cw,52,rx=5,fillColor=PALE,strokeColor=BLUE,strokeWidth=.8))
        text(d,x+cw/2,132,title,9.5,True,'middle');text(d,x+cw/2,113,sub,7.2,False,'middle')
        if i<3:arrow(d,x+cw+1,126,x+cw+gap-1,126)
    lower=[('交易式修改','shadow state 一次提交'),('完整 evaluator','容量  路由  排程  PPA'),('最佳可行 archive','符合硬限制才推薦'),('可視化與報告','分割  深度  布局  流量')]
    for i,(title,sub) in enumerate(lower):
        x=i*(cw+gap);d.add(Rect(x,22,cw,52,rx=5,fillColor=colors.white,strokeColor=BLUE,strokeWidth=.8))
        text(d,x+cw/2,54,title,9.5,True,'middle');text(d,x+cw/2,35,sub,7.2,False,'middle')
        if i<3:arrow(d,x+cw+1,48,x+cw+gap-1,48)
    arrow(d,W-cw/2,100,cw/2,74)
    d.add(PolyLine([cw*1.5+gap,22,cw*1.5+gap,5,W-cw/2,5,W-cw/2,100],strokeColor=colors.HexColor('#758a90'),strokeWidth=.8))
    text(d,W*.58,8,'診斷與成本差值回饋 RL',7.5)
    return d

def package_figure(detail,width=W,height=145):
    pack=detail['package'];nodes={n['id']:n for n in pack['nodes']}
    xmax=max(n['x_mm']+n['width_mm'] for n in nodes.values());ymax=max(n['y_mm']+n['height_mm'] for n in nodes.values())
    scale=min((width-20)/xmax,(height-18)/ymax);ox=(width-xmax*scale)/2;oy=(height-ymax*scale)/2
    d=Drawing(width,height)
    centers={k:(ox+(n['x_mm']+n['width_mm']/2)*scale,oy+(ymax-n['y_mm']-n['height_mm']/2)*scale) for k,n in nodes.items()}
    marked=set()
    if detail['flow_examples']:
        f=next((f for f in detail['flow_examples'] if any(len(r['path'])>3 for r in f['routes'])),detail['flow_examples'][0])
        for r in f['routes']:
            physical=[]
            for p in r['path']:
                p=p.split('/')[0]
                if not physical or physical[-1]!=p:physical.append(p)
            marked.update(frozenset((a,b)) for a,b in zip(physical,physical[1:]))
    for link in pack['links']:
        a,b=centers[link['a']],centers[link['b']]
        col=colors.HexColor('#c97020') if frozenset((link['a'],link['b'])) in marked else colors.HexColor('#80949f')
        d.add(Line(*a,*b,strokeColor=col,strokeWidth=1.7 if col==colors.HexColor('#c97020') else .8))
    fills={'compute':colors.HexColor('#d7e9e2'),'io':colors.HexColor('#f2ddbb'),'memory':colors.HexColor('#f5f6f7')}
    for ident,n in nodes.items():
        x=ox+n['x_mm']*scale;y=oy+(ymax-n['y_mm']-n['height_mm'])*scale;w=n['width_mm']*scale;h=n['height_mm']*scale
        d.add(Rect(x,y,w,h,fillColor=fills[n['role']],strokeColor=INK,strokeWidth=.6))
        label=ident.replace('compute:','C').replace('io:','I').replace('memory:','D')
        text(d,x+w/2,y+h/2-2,label,min(9,max(5,w/2.9)),True,'middle')
    return d

def core_figure():
    d=Drawing(W,162)
    cw=220;ch=65
    for core in range(4):
        r,c=divmod(core,2);x=18+c*250;y=94-r*78
        d.add(Rect(x,y,cw,ch,rx=4,fillColor=colors.HexColor('#d7e9e2'),strokeColor=BLUE,strokeWidth=.8))
        text(d,x+10,y+47,f'Core {core}   GLB 2 MiB',10,True)
        text(d,x+10,y+29,'16 PE × 8 lanes × 8 MAC',8.5)
        text(d,x+10,y+12,'Vector  Control  DMA  Router',8)
    arrow(d,239,126,265,126);arrow(d,239,48,265,48)
    arrow(d,128,92,128,84);arrow(d,378,92,378,84)
    text(d,W/2,2,'每側 2 個 D2D interfaces   每 die 共 8 個   每 interface 16 GB/s',8,False,'middle')
    return d

def residual_figure():
    d=Drawing(W,112);xs=[0,132,264,396];labels=['Input tensor','Conv 0','Conv 1','Add']
    for i,x in enumerate(xs):
        d.add(Rect(x,50,110,42,rx=4,fillColor=colors.HexColor('#fff1c9') if i==3 else PALE,strokeColor=BLUE,strokeWidth=.8))
        text(d,x+55,66,labels[i],10,True,'middle')
        if i<3:arrow(d,x+110,71,x+130,71)
    d.add(PolyLine([55,50,55,20,451,20,451,48],strokeColor=BLUE,strokeWidth=1));arrow(d,451,38,451,49)
    text(d,245,27,'shortcut 原始相依保留',8,False,'middle')
    return d

def target_heatmap(summary):
    d=Drawing(LW,32+len(summary)*22);labels=[('power_W','max_power_W','strict_power','Power'),('area_mm2','max_area_mm2','strict_area','Area'),('latency_ms','max_latency_ms','strict_latency','Latency')]
    h=d.height
    text(d,0,h-12,'案例與模型',9,True)
    for j,(_,_,_,name) in enumerate(labels):text(d,300+j*140,h-12,name+' 實際 / 目標',9,True)
    for i,row in enumerate(summary):
        y=h-35-i*22;text(d,0,y+4,row['case']+' / '+modelname(row['model']),8)
        for j,(actual,limit,strict,_) in enumerate(labels):
            ratio=row[actual]/row[limit] if row[limit] else None
            fill=colors.HexColor('#eeeeee') if ratio is None else colors.HexColor('#e1efe7') if ratio<=1 else colors.HexColor('#f8e1dd') if row[strict] else colors.HexColor('#fff0cc')
            x=290+j*140;d.add(Rect(x,y,127,18,fillColor=fill,strokeColor=colors.white))
            text(d,x+63.5,y+5,'未啟用' if ratio is None else f'{ratio:.3f} '+('硬' if row[strict] else '軟'),8,False,'middle')
    return d

class ReportDoc(BaseDocTemplate):
    def afterFlowable(self,flowable):
        if hasattr(flowable,'_tocLevel'):
            if flowable._tocLevel==0 and not flowable.getPlainText().startswith(('案例 ','未完成情境','補充診斷方案')):
                self.notify('TOCEntry',(flowable._tocLevel,flowable.getPlainText(),self.page,flowable._bookmarkName))
            self.canv.bookmarkPage(flowable._bookmarkName)
            self.canv.addOutlineEntry(flowable.getPlainText(),flowable._bookmarkName,level=flowable._tocLevel,closed=False)

def footer(canvas,doc):
    width,height=canvas._pagesize;canvas.saveState();canvas.setFont(FONT,7.5);canvas.setFillColor(colors.HexColor('#666666'))
    canvas.drawString(36,22,'INMIN Gemini 2×2 Core RL DSE  |  2026 10 31')
    canvas.drawRightString(width-36,22,str(doc.page));canvas.restoreState()

def build():
    PDF.parent.mkdir(parents=True,exist_ok=True)
    data=read(BASE/'report_data.json');cases=data['cases'];summary=data['summary'];coverage=data.get('coverage',{})
    ordered=['R_balanced','R_power','R_area','R_latency','R_tight_latency','R_impossible_area','R_soft_latency','R34_balanced','M_balanced','M_latency','A_balanced','J_resnets','J_shared','T_fusion','T_fused_demo','R32_fusion','R_power_DF_on_prior']
    cases.sort(key=lambda c:ordered.index(c['id']) if c['id'] in ordered else 99)
    main=[c for c in cases if c['id']!='R_power_DF_on_prior']
    complete=[c for c in main if c['status']['status']=='complete']
    nofeas=[c['id'] for c in complete if not c['suite']['best_architecture']]
    allmodels=sorted({m for c in complete for m in c['config']['models']})
    story.extend([Spacer(1,35),P('INMIN 整體專題流程與實驗結果報告','title'),P('Gemini 固定 2×2 core chiplet 與瓶頸導向複合動作 RL','subtitle')])
    para('本報告說明目前可執行系統的輸入、DAG、硬體模板、Tangram 式初始化、RL 搜尋與 PPA 評估，並以實際執行紀錄列出每個情境找到的部署方案。每個方案均可追溯到模型、限制、偏好、分割、pipeline group、DF 融合、core 配額、資料路徑與實體 chiplet 位置。')
    para(f'本次完成 {len(complete)} 個正式情境，涵蓋 '+ '、'.join(modelname(m) for m in allmodels)+'。另外保留全尺寸融合開啟的已完成對照與中斷紀錄。模型搜尋使用固定 seed 7；各案例的實際完整查詢預算與耗時在後文逐項列出。')
    para('主要結論', 'h2')
    para('目前系統會輸出「指定模板與查詢預算內的最佳可行解」。硬限制不滿足時，最佳推薦欄位保持空值，另提供最近的可執行診斷方案；不會將診斷方案冒稱為可行推薦。')
    para('每顆 compute chiplet 固定為四個完整 cores。系統可搜尋 1、2、4、8、16 顆與 15 個矩形形狀；IO 與 DRAM 數量、資料流與成本隨模板實際更新。')
    para('實跑代表解：ResNet18 均衡偏好為 1 顆 compute chiplet，1.74085 ms、6.92130 W、77.7720 mm²；低功率偏好則為 2.09702 ms、6.06029 W、相同面積。AlexNet 找到 1×8 compute-chiplet mesh，2.23413 ms、8.91976 W、194.3623 mm²。這些都是各案例已完成查詢中的最佳可行解。')
    para('PPA 為完整分析式排程的估計，沒有 RTL 或 silicon signoff。Tangram 使用可稽核的 bounded DP/beam adapter，沒有執行原版 Tangram/BSD/ALLO binary。RL 使用線性候選式 actor-critic，沒有以 GNN、PPO 或 SA 冒充目前演算法。')
    para('本輪全尺寸主要對照將 DF 融合開關關閉，以讓 PPA、偏好與模型比較在可控的完整評估成本下完成；Toy、32×32 ResNet18 與一個已完成的 224×224 低功率對照另行開啟融合。所有表格均註明輸入尺寸與開關，不能將縮小輸入的效能視為 224×224 的效能。')
    if nofeas:para('本次未找到嚴格可行推薦的正式案例：'+ '、'.join(nofeas)+'。原因與違反量均逐案列出。')
    page('目錄')
    toc=TableOfContents();toc.levelStyles=[ParagraphStyle('TOC1',fontName=FONT,fontSize=9,leading=14,spaceBefore=2),ParagraphStyle('TOC2',fontName=FONT,fontSize=8,leading=11,leftIndent=14)]
    story.append(toc)

    page('第一章 整體專題流程')
    story.append(flow_figure());para('圖 1 目前的端到端資料管線。診斷與成本只改變候選及學習回饋，不能直接修改物理 PPA。','caption')
    heading('使用者輸入與有效決策',2)
    para('使用者選擇模型或支援算子的明確 DAG、batch、平均功率上限、總矽面積上限、batch latency 上限，以及一個偏好選項。GUI 的偏好為單選按鈕；「嚴格遵守」則是 Power、Area、Latency 各自的核取方塊。未勾選某一項，該輸入值轉成軟目標。')
    table(['偏好選項','Power 權重','Area 權重','Latency 權重'],[['均衡','1/3','1/3','1/3'],['低功率','0.8','0.1','0.1'],['小面積','0.1','0.8','0.1'],['低延遲','0.1','0.1','0.8']],[W*.34,W*.22,W*.22,W*.22])
    para('模型權重、數值精度、算子語意與使用者要求的 batch 不由動作改變。torchvision 模型以 weights=None 的 FX/meta shapes 建立硬體工作量；本工具不執行 PTQ 精度驗證，也沒有宣稱模型準確率。')
    para('多模型選擇目前表示同一硬體可逐一執行各模型，所有模型都通過自己的限制才作共同推薦。這不是多模型同時混跑的競爭排程；不能據此宣稱 concurrent mixed-workload latency。')
    heading('模型 DAG 與兩個融合層級',2)
    story.append(residual_figure())
    para('圖 2 residual 的兩路輸入保留為獨立相依。Add 必須等到兩路所需 tensor regions 都就緒。','caption')
    para('Parser 可把 BatchNorm/ReLU 等固定 post-ops 合併到 Conv 的 LayerSpec；這是圖解析層級的既定處理。RL 的 DF fusion 則是跨多個 LayerSpec 以末層空間 tile 回推需求。報告的 DF 深度一律以 LayerSpec 節點數計算，深度 1 表示沒有跨層 DF 融合，不能把 Conv 的 post-ops 數量混入。')
    page('第一章續 Tangram 式初始化與 RL 起點')
    para('依 DAG 的拓樸順序提出有限 pipeline segmentation、microbatch divisor 與 balanced core allocation，利用 bounded graph-cut DP/beam 估計排序，再用完整 evaluator 評估 seed 候選。proxy 的延遲與能量不是最終 PPA；失敗候選、query 數與耗時都有記錄。本輪多數案例 seed budget 為每個嘗試模板 2 次，ResNet34／共同 ResNet 案例為 1 次，Toy 融合示範為 4 次；當較小模板沒有可執行 seed，才繼續較大合法模板。')
    table(['步驟','輸入、處理與輸出'],[
        ['1 完整 DAG','保留各 tensor 的 BKHW、layer operator、kernel、stride、padding 與全部輸入 edges；先決定合法拓樸順序。'],
        ['2 有限分段','對連續拓樸 prefix 探索 group 邊界。新層須與 segment prefix 有依賴或共享 input，並受 max group layers 與 beam width 限制；另保留單層 sequential baseline。'],
        ['3 配額與 partition','依 segment 估計工作量產生整數 core 配額及合法 B/K/H/W partition；同時考慮可用 cores、microbatch divisor 與本地容量。這不是窮舉所有原版 Tangram loop blocking。'],
        ['4 Proxy 排序','bounded DP／beam 只保留有限組合，用估計延遲／能量選出候選列表。proxy 可用於節省搜尋，不能直接作最終效能數字。'],
        ['5 真正完整評估','逐案在 seed query 上限內呼叫共享 evaluator，編譯 tensors、計算容量、流量、路由與排程。沒有有限正值 PPA 或容量不合法者不得當起點。'],
        ['6 使用者偏好排序','可執行 seed 依固定 PPA reference、偏好與硬限制 violation penalty 排名。超過使用者 PPA 的可執行解仍可作 RL 改善起點；硬體容量不合法的解不可以。'],
        ['7 轉為 RL state','輸出 architecture ID、mapping、模型 hash、seed provenance、每次 query、拒絕原因與耗時。RL 後續改動都能追溯回這個 state。']
    ],[W*.24,W*.76])
    seed=read(BASE/'experiments/R_balanced/run/resnet18/seed.json')
    heading('實際 ResNet18 初始化片段',2)
    para('R balanced 的起點使用 '+seed['architecture_candidate_id']+'。以下列出 seed.json 最前面的 groups；這是已評估的初始化，不是手畫的最終 mapping。')
    table(['Seed group','mode','保留的有序 LayerSpec'],[[g['id'],g['mode'],' → '.join(g['layer_ids'])] for g in seed['mapping']['groups'][:4]],[W*.17,W*.17,W*.66],True)
    para('Temporal group 允許成員重用 core 資源，由實際資料依賴與資源 calendar 決定何時執行；spatial group 的不同層必須使用互斥 core 集合，才能形成 inter-layer pipeline。兩種 group 都不自動代表 DF 融合。batch=1 時 microbatch 只能為 1，這輪不具備多個 microbatches 的重疊收益。','small')

    page('第二章 硬體與 PPA 評估')
    story.append(core_figure());para('圖 3 固定 compute chiplet 資源示意。四個 core 各有 GLB、PE array、vector、DMA、router 與 control。','caption')
    table(['資源','本版設定'],[['每 compute chiplet','2×2 cores；共 64 PEs'],['每 core','16 PEs × 8 lanes × 8 scalar MAC；1024 MAC/cycle'],['Clock 與理論吞吐','1 GHz；每 die 4.096 TMAC/s，按 2 ops/MAC 為 8.192 TOPS'],['記憶體','每 core 2 MiB GLB；每 PE WL1/AL1/OL1 為 4/8/2 KiB；單 scratch slot'],['NoC 與 D2D','NoC 每 directed link 32 GB/s；D2D 每 interface 16 GB/s；每側兩個 interfaces'],['IO 與 DRAM','每 compute-chiplet row 左右各一個 IO＋DRAM；每 DRAM 16 GB/s、2 GiB'],['精度與製程成本','INT8 activation/weight、INT24 psum；16 nm 文獻參考成本，未校準']],[W*.28,W*.72])
    para('每 core GLB 的 read/write stage 與 endpoint DMA 競爭同一個 aggregate glb_port，避免免費並行頻寬。由於目前沒有實體 bank-address allocator，整個 atomic stage 共用該資源是保守近似。core 的 MAC stage 使用本地 L1，不會全程占用 GLB port。')
    heading('布局與互連如何決定',2)
    para('合法候選為 rows×cols 的 compute-chiplet mesh，C=rows×cols、IO=2×rows、DRAM=2×rows。每個 compute die 的四個 core 排成 2×2；全域 core mesh 為 2rows×2cols。相鄰 cores 使用 NoC，跨 die 邊界使用兩條獨立 D2D lanes。IO 位於各 chiplet row 兩側，外接 DRAM。相同 row 增加 compute dies 不會自動增加 DRAM 帶寬。')
    para('路由固定先 X/column、後 Y/row。package.json 的兩 lane aggregate link 用於實體幾何與 native 檢查；workload 路由、競爭及能量使用逐 core 的 16 GB/s lanes。單一 flow 不會免費取得 32 GB/s aggregate 帶寬。系統沒有搜尋任意 floorplan、任意實體 topology 或任意 routing。')
    heading('PPA 的精確定義',2)
    para('Area 是 compute＋IO＋DRAM 的總 silicon area，封裝 footprint 另列；Latency 是指定 batch 的完整 makespan；Energy 包含同一時間窗的 dynamic 與 idle/leakage；平均 Power=Energy/Latency。本輪 batch=1，因此每 batch 與每 inference 的能量一致。Peak power、TDP、製造成本及良率不在目前模型內。')
    para('完整 evaluator 重建 spatial output ownership、tail tiles、stride/padding/halo、權重工作集、shortcut 與 cache 存活、DRAM/NoC/D2D 傳輸，並以 resource calendar 排程。busy time、memory service 與 network waits 可重疊，不能直接相加當成 E2E latency。缺少唯一歸因的 NoC/D2D/DRAM 等待會記為 null，而不捏造精確分解。')

    page('第三章 RL 如何選擇與更新方案')
    para('State 保存模型 hash、硬體模板、architecture ID、layer partitions、ordered core allocations、pipeline groups、DF stacks/tile/cache、DRAM 配置及工作量／PPA 目標。derived flows、容量與排程由 evaluator 產生，不能再由另一個決策者無聲覆寫。')
    para('Policy 使用 16 維 state 特徵及 86 維穩定 candidate 特徵。特徵含 PPA/reference 比例、違反量、資源數、group/fusion 比例、microbatch、瓶頸比例，以及候選的 action multi-hot、macro、分割／tile／cache／配額變化與目標工作量。DAG 供合法性、候選與成本使用；目前不是把 DAG 直接送入 GNN。')
    table(['原子動作','修改內容'],[['A1','merge/split/shift fused stack，保留原 DAG'],['A2','調整 B/K/H/W spatial partition，重建所有相鄰流量'],['A3','調整末層 DF sink tile H/W，往前回推需求'],['A4','同一合法共享資源池轉移 core 配額'],['A5','同層 partition 的 ordered placement／合法 relocation'],['A6','同一 spatial group 兩層等量位置交換'],['A7','重算、horizontal cache、full cache 三個可支援 overlap 模式'],['A8','合法 DRAM 配置與 interleave，更新 producer/consumer'],['A9','合法架構模板切換，顯式撤離／重配工作與資料'],['A10','pipeline group 邊界或不改總 batch 的 microbatch unit']],[55,W-55])
    para('歷史清單的 A11 與 A9 都表示調整系統 chiplet 數量。依本次規格，A11 匯入即正規化成 A9，只有十個唯一 atomic transitions，沒有重複的 policy 類別或搜尋機率。')
    table(['複合動作','協同修改意圖'],[['C1','關鍵 compute 層的資源轉移＋雙方重新分割／位置'],['C2','擴充合法架構＋工作重新配置／分割／資料位置'],['C3','縮減架構＋完整撤離與重新配置'],['C4','相鄰 producer/consumer 協同改 partition'],['C5','依 queue windows 與 flow owners 改 placement＋DRAM'],['C6','合法閉合子圖的 fusion＋sink tile＋cache'],['C7','縮 tile／拆 stack／減 cache 的容量替代方案'],['C8','tile 與 cache 協同評估重算／重用取捨'],['C9','pipeline 邊界與新 group 配額／partition 協同']],[55,W-55])
    para('先以 hard validity 排除無法執行的候選，再以診斷與有限 shortlist 產生多種方向，保留通用探索候選。Policy 對合法候選作 softmax 選擇，逐筆保存實際 behavior probability；沒有「加 chiplet」或「減 hops」的固定獎勵。複合動作名稱只表示意圖，不能保證改善。')
    page('第三章續 交易 Reward 與學習更新')
    para('一個 ActionPlan 在 shadow state 依序執行所有明確 edits；中途失敗即完整回復。合法 trial 以同一完整 oracle 評估；PPA 較差但可執行的 trial 也可提交探索。探索 current state 與 best feasible archive 分開，最後輸出 archive 而非最後一步。')
    para('J = wL×L/Lref + wA×A/Aref + wP×P/Pref + soft-goal penalty。各 reference 在每個模型 episode 內固定；hard violation V 為各硬限制相對超標量之和。Reward = (Jold+10Vold) - (Jnew+10Vnew)，gamma=1。不能跨不同 references 的案例直接比較 normalized cost；本報告跨案例以原始 PPA 為主。')
    para('每個 macro 只算一個環境 step，但所有實際 oracle calls 都列帳。Seed 預算與 RL unique full-evaluation ceiling 分開；seed 後清除底層 cache，避免把 seed hit 偽稱完整 RL query。報告重播 trace 另列實際 evaluator 次數。精確 cache key 包含硬體、完整設計、precision、routing/scheduler、工作量與 evaluator identity。')
    heading('真正的 Actor Critic 更新',2)
    para('Actor 對每個合法候選 a 形成穩定特徵 x(s,a)，以線性分數 θᵀx 作 softmax；critic 以線性 Vφ(s) 估計後續回報。實際抽樣的候選機率、log probability、reward 與 advantage 都存入 trace，不是以候選列表索引代表固定動作語意。')
    para('TD advantage 使用 r + γVφ(snext) - Vφ(s)，episode 終端的後續 value 為 0。Actor 依所選候選與整個分布的特徵差更新，critic 依 state features 更新；程式對 advantage 與 feature norm 作數值限制，並有 entropy regularization。硬體不可執行 trial 會被回復與列入 rejection，不使用假的 PPA 訓練。')
    table(['學習設定','本輪使用值'],[['Actor learning rate','0.03'],['Critic learning rate','0.03'],['Entropy coefficient','0.005'],['Discount γ','1'],['Episode horizon','16 steps'],['初始參數','每個獨立 run 的 actor/critic 從零初始化；checkpoint resume 會還原已學權重'],['跨模型訓練','目前沒有跨模型預訓練或共享 policy；每個模型／情境線上學習']],[W*.4,W*.6])
    para('因此，本輪幾次至數十次完整查詢只能證明更新機制與執行流程，不能當成已訓練出泛化到所有 DNN 的 policy。相同 query 預算下仍必須與 atomic、random、greedy 及更大 seed 數比較。')
    heading('終止與最後輸出',2)
    para('完整 query 預算耗盡、step ceiling、沒有合法非重複動作等狀態分別保存；budget truncation 不等於找到了全域最優。合法但較差的 current state 可以繼續探索，archive 只保存各架構中最好且符合硬限制的候選。整體多模型推薦必須對每個選定模型都被實際評估且通過限制；未訪問的共同架構不補造分數。')

    page('第四章 實驗設計與使用者輸入',land=True)
    para('以下均為本次實際啟動的案例。P、A、L 分別為 W、mm²、ms；H=嚴格遵守已勾選，S=未勾選而作為軟目標。除另列外 batch=1、seed=7、Tangram seed budget=2、RL shortlist=24、通用 quota=6、每 family 上限=6、horizon=16。每次完整 evaluator ceiling 含 RL initial design。')
    inputrows=[]
    for c in cases:
        cfg=c['config']
        inputrows.append([c['id'],','.join(modelname(m) for m in cfg['models']),str(cfg.get('input_size',224)) if cfg['models']!=['toy'] else f"{cfg.get('toy_spatial',8)} Toy",prefname(cfg['preference']),limit(cfg['max_power'])+(' H' if cfg['max_power'] else ''),limit(cfg['max_area'])+(' H' if cfg['max_area'] else ''),limit(cfg['max_latency_ms'])+(' H' if cfg['strict_latency'] else ' S') if cfg['max_latency_ms'] else '未啟用',str(cfg['budget']), '開' if cfg['fusion']=='dp' else '關'])
    table(['案例','模型選擇','輸入 H=W','偏好選取','Power','Area','Latency','RL預算','DF'],inputrows,[115,160,70,70,70,70,90,55,LW-700],True)
    para('R power DF on prior 為前一輪已完成的 224×224 低功率／融合開啟對照。最初的 R balanced 與 R area 融合開啟嘗試在完整評估耗時過長時中斷，沒有把 partial seed 或尚未完成的 current state 當成最終結果。這些紀錄保存在 fusion_on_initial_attempt。正式全尺寸對照統一關閉 DF；pipeline、partition、placement、DRAM 與 architecture actions 照常搜尋。','small')
    page('第五章 各情境找到的最佳可行解',land=True)
    resultrows=[]
    for r in summary:
        case=next(c for c in cases if c['id']==r['case']);rec=case.get('suite',{}).get('best_architecture')
        resultrows.append([r['case'],modelname(r['model']), '可行推薦' if rec else '僅診斷',r['architecture'].replace('gemini_',''),f"{r['compute']}/{r['IO']}/{r['DRAM']}",fmt(r['latency_ms']),fmt(r['power_W']),fmt(r['area_mm2']),fmt(r['energy_mJ']),','.join(map(str,r['DF_stack_depths'])) or '1 無DF'])
    table(['案例','模型','狀態','架構','C/I/D','L ms','P W','A mm²','E mJ','DF深度'],resultrows,[107,90,56,90,54,64,60,64,64,LW-649],True)
    para('C/I/D 分別為 compute chiplets、IO chiplets 與 DRAM dies；total chiplets=C+I，total physical dies=C+I+D。表中「僅診斷」不是合法推薦。找不到可行方案與後端無法執行為不同狀態。若某案例狀態為 failed/timeout，會在逐案章節說明，並且不補造 PPA。','small')
    page('第五章續 PPA 限制達成率',land=True)
    para('以下色塊用同一列實際值除以上限。綠色表示達標；紅色為硬限制超標；黃色為軟目標未達；灰色為未啟用上限。多模型列分開檢查，不能用平均值遮蔽某一個模型的違反。','small')
    story.append(target_heatmap(summary))

    page('第五章續 這些實驗實際告訴我們什麼')
    table(['可比較案例','觀察與可支持的結論'],[
        ['R balanced / power / area / latency','固定 224×224、batch 1、P≤20 W、A≤250 mm²、L≤3 ms。均衡／小面積／低延遲選到相同配置；低功率選到不同 pipeline／core 配置。不同偏好不保證不同最佳模板。'],
        ['低功率的取捨','相對均衡，平均功率減少約 12.44%，延遲增加約 20.46%，能量增加約 5.47%。最小平均功率不等於最小單次推論能量。兩者均使用同一顆四 core compute die 與兩組 IO＋DRAM。'],
        ['R tight / soft latency','硬 0.8 ms 案例沒有可行推薦；軟 0.8 ms 案例可推薦 1.74085 ms 的方案，但仍須顯示軟目標超出約 117.61%。estimated compliant 表示通過硬限制，不代表所有軟目標達成。'],
        ['R impossible area','15 個合法硬體模板的最小 silicon area 為 77.7720 mm²，高於 60 mm²。因此在此固定硬體與成本模型內可直接證明此硬面積條件無解；不是只有搜尋預算不夠。'],
        ['模型差異','ResNet34 的完成解為 1 顆 compute die、3.75443 ms、6.51075 W。AlexNet 為 8 顆橫排、2.23413 ms、8.91976 W；AlexNet 的 seed 可執行性與容量要求和 ResNet 不同，不能只用模型名稱推斷最佳顆數。'],
        ['共同硬體','ResNet18＋ResNet34 共同推薦同一顆 compute die；兩個模型各有自己的 mapping／資料流。此結果證明逐模型可部署，沒有模擬兩者同時執行。'],
        ['融合深度','Toy fused demo 實際選到 conv0→conv1→add 深度 3、sink tile 8×8、recompute；其他完成案例的最佳解全部為深度 1。開啟 fusion 搜尋不表示最後必然融合。兩個 Toy 案例的限制與候選參數不同，不能當成控制變因融合效益比較。'],
        ['MobileNetV2','均衡、低延遲及含 MobileNet 的共同模型三案均達 600 秒 cap。沒有完整 RL 最終推薦；本報告不以 seed 指標填入最佳解欄位。']
    ],[W*.26,W*.74])

    if coverage:
        page('第五章續 嚴格延遲條件的模板覆蓋稽核',land=True)
        para('這是獨立的補充實驗，不是 R tight latency 原本 24-query RL episode 的延伸結果。模型為 ResNet18 224×224、batch 1、P≤40 W、A≤500 mm²、L≤0.8 ms、低延遲偏好、DF 關閉。每個已完成模板最多用一次 bounded Tangram seed 的完整評估，沒有 RL 更新。','small')
        cr=[]
        for r in coverage['rows']:
            m=r.get('metrics',{})
            state='已評估，未達硬限制' if m else '面積硬剪枝' if r.get('hard_pruned_area') else '未完成評估'
            cr.append([r['architecture'].replace('gemini_',''),state,fmt(m.get('latency_s',0)*1000) if m else '—',fmt(m.get('power_w')) if m else '—',fmt(m.get('area_mm2',r.get('silicon_area_mm2'))),fmt(r.get('elapsed_s'),6) if m else '—'])
        table(['模板','實際狀態','Latency ms','Power W','Area mm²','評估耗時 s'],cr,[LW*.18,LW*.26,LW*.14,LW*.14,LW*.14,LW*.14],True)
        para('10 個模板有完成的 seed PPA，3 個其餘模板由已知實體面積直接剪枝，另 2 個 16-chiplet 模板沒有完成的 PPA。稽核在單個 16-chiplet 評估長時間未完成後停止；未完成與剪枝列沒有填造 latency／power。部分較早完成的模板雖面積超標，仍保留其實際評估數據。','small')
        if coverage.get('best'):
            best=coverage['best'];m=best['metrics']
            para(f"已完成 seed 中最近的診斷方案是 {best['architecture']}：{m['latency_s']*1000:.6f} ms、{m['power_w']:.6f} W、{m['area_mm2']:.6f} mm²，延遲仍超出 0.8 ms 約 {(m['latency_s']*1000/.8-1)*100:.2f}%。這不是可行推薦，也不是已證明所有 mapping 在 0.8 ms 下無解。",'small')
            page('補充診斷方案 2×2 compute chiplets')
            detail=coverage['deployment'];hw=detail['hardware']
            story.append(package_figure(detail))
            para('圖為補充稽核完成候選中最接近硬限制的 2×2 compute-chiplet mesh，含 4 顆 compute、4 顆 IO、4 顆 DRAM；共 16 個 cores。其餘核心路由仍先 X 後 Y，每個 chiplet 邊界有兩條 16 GB/s lane。此圖不改變前述 RL 案例「沒有推薦」的狀態。','caption')
            para('此候選沒有跨層 DF stack，所有層融合深度為 1；完整逐層分割另列於附錄 A 的 S template audit 配置，全部 tensor regions 與路徑位於 evidence/S_template_audit/resnet18。')
            representative=[detail['layers'][0],max(detail['layers'],key=lambda x:x['core_count']),detail['layers'][-1]]
            table(['Layer','輸出 BKHW','Partition BKHW','Ordered cores'],[[l['layer'],'×'.join(map(str,l['output_BKHW'])),'×'.join(map(str,l['partition_BKHW'])),l['core_text']] for l in representative],[W*.23,W*.19,W*.16,W*.42],True)
            para('增加 chiplet 數不保證此 bounded seed 更快；分組、分割、core 利用率、重分布與 DRAM 位置會一起改變。本稽核只比較特定初始化方法生成的已完成配置，不能把曲線視為硬體本身的速度上限。')

    page('第六章 最佳方案的部署與資料流')
    para('每個小節先列使用者輸入與最終狀態，再列實際 PPA、pipeline／DF 結構、實體布局、分割與代表性 flow。完整逐層表格在附錄，完整 half-open tensor regions 與 routes 在 evidence CSV。所有部署皆取 suite.json 的共同 display architecture；沒有 strict best 時，明確標為 closest 診斷。')
    para('C0:c1 表示 compute chiplet 0 內的 core 1。core 0/1 位於上排，core 2/3 位於下排。D0 是 DRAM 0，I0 是 IO 0。core 列表依序對應 shard 順序 H→W→B→K，K 變化最快；不是將 core ID 當成 chiplet ID。')
    first_detail=True
    for c in cases:
        for di,detail in enumerate(c['deployments']):
            if first_detail:
                heading('案例 '+c['id'].replace('_',' ')+' '+modelname(detail['model']),2)
                first_detail=False
            else:page('案例 '+c['id'].replace('_',' ')+' '+modelname(detail['model']))
            cfg=c['config'];m=detail['metrics'];feasible=detail['strict_compliant'];hw=detail['hardware'];layers=detail['layers']
            para(('最佳可行推薦：' if feasible else '沒有符合硬限制的推薦；以下僅為最近的診斷方案：')+detail['architecture']+'。')
            para(f"模型 {modelname(detail['model'])}，輸入 {'Toy '+str(cfg.get('toy_spatial',8))+'×'+str(cfg.get('toy_spatial',8)) if detail['model']=='toy' else str(cfg.get('input_size',224))+'×'+str(cfg.get('input_size',224))}，batch 1；偏好 {prefname(cfg['preference'])}；"+ '、'.join([target('Power',cfg['max_power'],'W',cfg['strict_power']),target('Area',cfg['max_area'],'mm²',cfg['strict_area']),target('Latency',cfg['max_latency_ms'],'ms',cfg['strict_latency'])])+f"。DF 開關：{'開啟' if cfg['fusion']=='dp' else '關閉'}。",'small')
            table(['Latency ms','平均 Power W','Area mm²','Energy mJ','C / IO / DRAM'],[[fmt(m['latency_s']*1000),fmt(m['power_w']),fmt(m['area_mm2']),fmt(m['energy_j']*1000),f"{m['compute_chiplets']} / {m['io_chiplets']} / {m['memory_dies']}"]],[W*.2]*5)
            violations=[f"{x['metric']} 超出 {x['excess_percent']:.2f}%" for x in detail['constraints']['limits'] if not x['within_target']]
            if violations:para('未達項目：'+'；'.join(violations)+'。'+('未勾嚴格的項目只影響軟 penalty。' if feasible else '這些值不能視為符合使用者限制。'),'small')
            search=c['searches'][detail['model']]
            para(f"本模型實際 {search['evaluations']} 次 RL unique full queries、{search['policy_updates']} 次 policy updates；可執行 architecture archive 涵蓋 {len(search['visited_executable_architectures'])} 個模板。完成狀態 {search['status']}；整案例 wall time {fmt(c['status']['elapsed_s'])} 秒。未訪問的 15-template 候選不能當成已比較。",'small')
            para(f"本案例 seed budget={cfg.get('seed_budget',4)}、shortlist={cfg.get('shortlist',48)}、generic quota={cfg.get('random_quota',12)}、每 family 上限={cfg.get('max_per_family',12)}。",'small')
            story.append(package_figure(detail));para(f"布局 {hw['cluster_rows']}×{hw['cluster_cols']} compute-chiplet mesh；全域 core grid 為 {2*hw['cluster_rows']}×{2*hw['cluster_cols']}。C 為 compute、I 為 IO、D 為 DRAM；圖形使用 package.json 的 mm 幾何比例。橘色為一個代表 flow 的 package 投影，逐 core hops 見下表。",'caption')
            stacks=detail['mapping']['fusion_stacks']
            if stacks:
                table(['DF stack 與成員','深度','sink H×W','overlap'],[[f"S{i+1}: "+' → '.join(s['layer_ids']),str(len(s['layer_ids'])),'×'.join(map(str,s['tile_hw'])),s['overlap']] for i,s in enumerate(stacks)],[W*.58,W*.08,W*.14,W*.2])
                para(f"共有 {len(detail['groups'])} 個 pipeline groups，{len(stacks)} 個 DF stacks；其餘未列入 stack 的層，DF 深度均為 1。執行 MAC={m['executed_macs']:,}，重算 MAC={m['recompute_macs']:,}。",'small')
            else:para(f"本次方案有 {len(detail['groups'])} 個 pipeline groups，沒有跨層 DF stack；全部層的 DF 深度為 1。pipeline group 合併不等於 DF fusion。Parser 固定 post-ops 另列於附錄。",'small')
            selected=[]
            for layer in [layers[0],max(layers,key=lambda x:x['core_count']),next((l for l in layers if l['operator']=='Add'),layers[-1])]:
                if layer['layer'] not in [x['layer'] for x in selected]:selected.append(layer)
            table(['代表層','輸出 B K H W','分割 B K H W','依序配置 cores'],[[l['layer'],'×'.join(map(str,l['output_BKHW'])),'×'.join(map(str,l['partition_BKHW'])),l['core_text']] for l in selected],[W*.24,W*.2,W*.16,W*.4],True)
            examples=detail['flow_examples'][:2]
            table(['實際 flow 與 tensor','Payload 與 region','逐 core 路徑 第一目的地'],[[f"{f['id']} {f['kind']}\n{f['tensor']}",f"{f['bytes']:,} B\n"+str(f['region']['bounds']), ' → '.join(shortcore(p) for p in f['routes'][0]['path'])] for f in examples],[W*.27,W*.32,W*.41],True)
            para(f"完整 {detail['full_flow_count']:,} 條 flows、{detail['exact_shard_count']:,} 個 spatial shards 及 {detail['exact_unit_count']:,} 個 executable units，均附在 evidence/{c['id']}/{detail['model']}。",'small')
            if c['id']=='T_fused_demo':
                page('三層融合示範的完整資料流')
                para('此為真正完成的 T fused demo：輸入 image=1×8×8×8，conv0 為 3×3、conv1 為 1×1，add 同時需要原始 image 與 conv1。三個 LayerSpec 同屬 spatial group 與一個深度 3 DF stack，末層 sink tile=8×8，overlap=recompute。')
                para('conv0 配置 C0:c1，conv1 配置 C0:c2，add 配置 C0:c3；每層 partition 均為 1×1×1×1。C0:c0 沒有執行這三層的 MAC，仍可作路由中繼。完整輸入及 shortcut 由 D1 multicast 到 c1 與 c3，不是省略 shortcut。')
                transfers=read(Path(detail['folder'])/'traffic_routes.json')['transfers']
                table(['實際搬移','tensor / payload','完整 paths'],[[f['id']+'\n'+f['kind'],f['tensor']+f"\n{f['bytes']:,} bytes",'\n'.join(' → '.join(shortcore(p) for p in r['path']) for r in f['routes'])] for f in transfers],[W*.24,W*.27,W*.49],True)
                para('conv0→conv1 的 512 bytes 經 c1→c0→c2，conv1→add 的 512 bytes 經 c2→c3。中間 tensor 留在 compute-side flows，沒有寫回 DRAM。最後 add 輸出以 interleave 分為 D0、D1 各 256 bytes；兩個 output_write 的區域不同，不是重複輸出。')
                para('本例輸入＋權重＋最終輸出的 DRAM 搬移合計 1,664 bytes；D2D hop-bytes 為 2,176，core NoC hop-bytes 為 2,400。Multicast 的 injected input payload 是 512 bytes，因為需要送到兩個 core，其 D2D hop-bytes 變成 1,024。這些數字直接加總原始 traffic statistics，不將各層資料量當成免費傳遞。')
    incomplete=[c for c in cases if not c['deployments']]
    if incomplete:
        page('未完成情境與時間上限')
        para('以下案例沒有完成的可行推薦，不補造最終 PPA 或最佳部署。已完成的初始化 PPA 只代表 seed，不能冒稱完成 RL 搜尋。每個案例的 source manifest、設定、run.log 與 seed.json 都保留。')
        table(['案例與模型','實際狀態','輸入條件與說明'],[[c['id']+'\n'+','.join(modelname(m) for m in c['config']['models']),c['status']['status'],prefname(c['config']['preference'])+f"; P {limit(c['config']['max_power'])} W; A {limit(c['config']['max_area'])} mm²; L {limit(c['config']['max_latency_ms'])} ms\n"+c['status'].get('error','沒有共同可執行 archive')] for c in incomplete],[W*.3,W*.16,W*.54])
        para('MobileNetV2 的 224×224 工作量在本次初始化已完成候選完整評估，但兩個 16-query 情境都未在 600 秒內完成整個搜尋與報告重播。這是本版可擴充性仍需改善的證據，不是已證明模型在硬體上無解。')

    page('第七章 如何精確解讀分割與資料搬移')
    heading('Spatial partition 與 Temporal tile 分開',2)
    para('Layer 的 partition=(B,K,H,W) 為同時分配到多個 cores 的 spatial ownership，乘積必須等於 core 配額。每軸長度 N 分成 p 段時，第 i 段為 [floor(Ni/p), floor(N(i+1)/p))，可處理非整除尾塊。shard 順序先枚舉 H、W、B，再枚舉 K；依序配給 mapping 的 ordered cores。')
    para('Temporal tiling 則是在一個 spatial shard 內依容量逐塊執行。tile_shape 的 0 表示由 backend 依容量自動推導，不表示零大小的 tile。附錄列出實際 executable unit 的 output tile shapes，execution_units.csv 列出每個 unit 的確切輸入、輸出及權重區域。channel_tile=128 等 C streaming 是 core 內 temporal 處理，不是跨 chiplet 的 C partition 或 partial-sum reduction。')
    para('對卷積，輸出空間範圍 [h0,h1) 需要的輸入為 [max(0,h0×stride-pad), min(Hin,(h1-1)×stride-pad+dilation×(kernel-1)+1))；W 同理。這會產生 halo 或重複輸入需求。groups/depthwise 依輸出 K 推導對應輸入 C 群組，不將所有 channels 當成免費共享。')
    heading('Group 邊界與 DF stack 的資料行為',2)
    para('不同 pipeline groups 的邊界 tensor 必須依 FD 設定 materialize 到 DRAM；不能因 producer/consumer 位於同一顆 chiplet 就假設免費傳遞。同一 group 內則按 tensor-region ownership 建立直接 core-to-core flows；若不同 partition 不相容，要付重新分布。DF 以 sink tile 沿完整依賴回推各層需求，cache、shortcut、psum、weights 同時計入各 core GLB 存活容量。')
    para('融合可能減少中間 DRAM 存取，但不同 cores 之間仍要傳資料。Multicast 在共同 directed edges 只傳一次同一 region；各目的 core 的 GLB 副本仍付容量與讀寫成本。完整 flows.csv 的 payload_bytes、DRAM_bytes、D2D_hop_bytes、core_NoC_hop_bytes 與 link_transmitted_bytes 分開，不能將 injected bytes 當成整條網路總 bytes。')
    heading('每份最佳解如何重建',2)
    para('依附錄找到 architecture ID 與每層 B/K/H/W、ordered cores、group、DF stack、sink tile、cache 與 FD selectors，再搭配 workload.json 中的 shape/kernel/stride/padding/dilation，便可重建 compiler 的所有執行工作。exact_spatial_partitions.csv 保留常規 shard ownership；DF 的實際重算／cache units 另在 execution_units.csv，兩者不應混為同一種切割。')

    page('第八章 驗證 結果限制與後續工作')
    para('前一輪完整新舊回歸為 231 tests / OK，涵蓋交易 rollback、A11 alias、resource legality、MAC/region 覆蓋、tail/halo、shortcut/cache/psum 容量、真 Gemini 1→2→1 擴縮、GLB port、精確 cache、reward 差值及 checkpoint continuation。本次另將報告重建的 executable-unit MAC 加總與每份原始 evaluation.executed_macs 比對，避免報告表格脫離實際方案。')
    prior=read(ROOT/'output/rl_dse_20261031/ablations_final/summary.json')
    table(['前一輪 Toy variable hardware 三 seeds','平均最佳 cost','標準差'],[[a['proposal']+' '+a['method'],fmt(a['best_cost_mean'],6),fmt(a['best_cost_stdev'],6)] for a in prior['aggregates'] if a['scope']=='variable'],[W*.62,W*.19,W*.19])
    para('上述 18-run 消融使用相同 RL unique full-query 預算，初始化與報告重播另計，沒有固定 wall-clock。結果未顯示 composite RL 優於 random，也沒有顯示 composite 優於 atomic。固定 4-chiplet 控制組的可行域與可變顆數不同，不能把增加硬體的收益全部歸因於 mapping 或 RL。此結論不能直接推廣到其他模型或更大預算。')
    para('本次正式情境的 source_before/source_after 逐案保存並核對；搜尋數值來自完成的 suite/run/metrics，沒有以手動重算偏好分數冒充已重新搜尋。每個偏好與限制案例都實際執行自己的 seed 與 RL。搜尋耗時是 CPU-side DSE wall time，PPA latency 則是估計的 accelerator makespan，兩者完全不同。')
    table(['目前邊界','對報告的影響'],[['全尺寸評估成本','部分 DF 候選過慢；MobileNet 即使 DF 關閉也超時。主 224×224 對照關閉 DF，開啟案例另列，不宣稱已完成所有模型的全功能搜尋'],['有限模板與預算','未遍歷的架構／mapping 不屬於已比較空間；無可行解不自動代表全域無解'],['Tangram adapter','重用 DP/beam 初始化機制，沒有原版 binary/BSD/ALLO，不能稱原論文完整重現'],['硬體成本','16 nm 文獻估算；1 GHz 未作 timing signoff，沒有 peak power 或實體量測保證'],['未支援能力','任意 routing/floorplan、跨 chiplet C reduction、vertical-only cache、自動 spill、C10 local DP 都關閉'],['模型數值','FX/meta shape 工作量與固定 INT8/INT24 假設，不是量化後準確率或真實推論輸出驗證']],[W*.25,W*.75])
    para('後續最優先工作是降低全尺寸 DF compiler／communication／schedule 的評估成本，增加完整模型的候選覆蓋與多 seed 統計，再檢查 RL 是否真正超越相同候選／oracle 的簡單策略。這些應與 RTL 或 silicon 校準分開進行。')

    page('附錄 A 每份部署的完整逐層配置',land=True)
    para('下列依 model＋architecture＋完整 mapping 去除完全相同的重複表格。每列都有 group、DF 深度與 cache/tile；若同一配置用於不可行案例，該案例仍只是診斷，不因共用表格而變成推薦。C:c 列表保留配置順序。FD 為 input/weight/output，D0=memory:0，IL=interleave，direct 表示直接資料來源。深度 1=無跨層 DF。', 'small')
    profiles={}
    for c in cases:
        for d in c['deployments']:
            key=hashlib.sha256(json.dumps({'model':d['workload']['name'],'hash':d['metrics']['workload_fingerprint'],'arch':d['architecture'],'mapping':d['mapping']},sort_keys=True).encode()).hexdigest()
            profiles.setdefault(key,{'detail':d,'cases':[]})['cases'].append(c['id']+(' 可行' if d['strict_compliant'] else ' 診斷'))
    if coverage.get('deployment'):
        d=coverage['deployment']
        profiles['supplemental_template_audit']={'detail':d,'cases':['S_template_audit 僅診斷 非RL']}
    for pi,profile in enumerate(profiles.values(),1):
        d=profile['detail']
        heading(f'配置 A{pi} '+modelname(d['model'])+' '+d['architecture'].replace('_',' '),2)
        para('對應案例：'+'；'.join(profile['cases'])+'。','small')
        rows=[]
        for l in d['layers']:
            df=f"深度 {l['DF_depth']}"
            if l['DF_stack']:df+=f" S{l['DF_stack']}\n"+'×'.join(map(str,l['DF_sink_tile_HW']))+' '+l['overlap']
            tile='; '.join('×'.join(map(str,t['BKHW']))+f" ({t['count']})" for t in l['actual_unit_tile_shapes'][:3])
            if len(l['actual_unit_tile_shapes'])>3:tile+='; 另'+str(len(l['actual_unit_tile_shapes'])-3)+'種'
            fd='/'.join(str(l[k]).replace('memory:','D').replace('interleave','IL') for k in ('input_DRAM','weight_DRAM','output_DRAM'))
            rows.append([l['layer']+'\n'+l['operator'],'×'.join(map(str,l['output_BKHW'])),'×'.join(map(str,l['partition_BKHW'])),l['core_text'],l['pipeline_group']+'\n'+l['group_mode'],df,tile,fd+'\n'+','.join(l['parser_fused_post_ops'])])
        table(['Layer 與 operator','輸出 BKHW','Partition BKHW','Ordered cores','Pipeline group','DF 深度 tile cache','實際 unit tile BKHW 次數','FD 與 parser postops'],rows,[118,69,66,126,68,87,126,LW-660],True)
        para(f"本配置完整 {d['exact_shard_count']:,} 個 spatial shards、{d['exact_unit_count']:,} 個 executable units 與 {d['full_flow_count']:,} 條 flows。重複 tile-shape 次數代表實際 units，不代表新模型 batch。",'small')

    page('附錄 B 原始資料與重現方式')
    para('本報告數值來源依序為：experiment.json 的使用者設定；status.json 的實際來源與執行狀態；suite.json 的共同硬體推薦；joint_search.json 的 best/closest archive、query 與 policy trace；選定架構下 mapping/package/traffic/diagnostics/timeline；報告 evidence 由相同 compiler 重建的 shard 與 unit 區域。')
    table(['檔案','用途'],[['scenario_results.csv','所有正式與補充案例的原始 PPA、限制、偏好、DF、顆數與搜尋預算總表'],['report_data.json','報告讀取的結構化資料，含逐層與代表性完整 routes'],['evidence/案例/模型/layers.csv','每一層的所有 partition/core/group/DF/FD/post-ops 與實際 tile shapes'],['pipeline_groups_and_fusion.csv','每一 pipeline group 成員、模式、真正 DF 深度、sink tile 與 cache'],['exact_spatial_partitions.csv','每一 shard 的 core 與 half-open B/K/H/W ownership'],['execution_units.csv','每一實際執行 unit 的輸入、輸出、權重 regions、MACs 與 core'],['flows.csv','所有實際 routes、payload、逐段搬移量、依賴與開始／結束時間'],['package_nodes.csv 與 package_links.csv','每個 compute/IO/DRAM 的 mm 位置、尺寸與實體 link/lane/bandwidth'],['search_transitions.csv','每一步 family、明確 edits、reward、違反量與最佳成本']],[W*.42,W*.58])
    para('重跑本次正式矩陣：.venv/Scripts/python.exe -X utf8 tools/run_detailed_report_cases.py --workers 2。相同完成設定與來源會重用；來源或設定異動會重新執行。每案例有 600 秒 wall-clock cap，timeout 不會被記成完成推薦。收集資料：tools/collect_detailed_report_data.py；產生 PDF：tools/build_detailed_project_report.py。')
    para('補充模板實驗的 config、各已完成 mapping/hardware 與 results.json 另存 template_coverage；template_coverage_results.csv 是可直接開啟的總表。該實驗因執行時間中止後，以 --finalize-known 保留已完成數據並重播所選診斷候選一次；這個重播不是額外搜尋。所有 15 個硬體模板的固定面積與 IO／DRAM／core 數另列 template_catalog.csv。')
    para('原始來源定位：simplified_rapidchiplet/rl_dse.py；hybrid/hardware.py、architecture.py、gemini_network.py、models.py、workload.py、tangram_seed.py、rl_schema.py、rl_actions.py、rl_search.py、mapping.py、depth_first.py、communication.py、scheduler.py、evaluator.py。每個實驗的 SHA256 在 status.json。')
    para('研究依據：使用者提供的 Gemini HPCA 2024 論文 §III/Fig.2 與 §VI/Table I，以及原始碼 src/main.cpp／spatial_mapping/segmentation.cpp；Tangram ASPLOS 2019 §4.2 的 DP/beam；DeFiNES 的 tile/overlap/cache；INDM 的相鄰層通訊與 partition 協同。工程 C1-C9 與本專題 RL 是本系統提案，不能聲稱是原論文現成演算法。成本來源與差異詳見 docs/gemini_hardware_contract.md、docs/rl_dse_action_contract.md 及 TANGRAM_SEED_ADAPTER.md。')

    doc=ReportDoc(str(PDF),pagesize=A4,leftMargin=42,rightMargin=42,topMargin=42,bottomMargin=42,
        title='INMIN 整體專題流程與實驗結果報告',author='INMIN Project',subject='Gemini 2x2 Core Tangram-style RL DSE actual experiment report')
    doc.addPageTemplates([PageTemplate(id='portrait',frames=[Frame(42,42,W,A4[1]-84,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)],pagesize=A4,onPage=footer),
        PageTemplate(id='landscape',frames=[Frame(36,36,LW,landscape(A4)[1]-72,leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)],pagesize=landscape(A4),onPage=footer)])
    doc.multiBuild(story)
    (BASE/'INMIN_整體流程與實驗結果報告.md').write_text('\n'.join(md),encoding='utf-8')
    print(json.dumps({'pdf':str(PDF),'cases':len(cases),'deployments':len(summary),'unique_mapping_profiles':len(profiles)},ensure_ascii=False))

if __name__=='__main__':build()
