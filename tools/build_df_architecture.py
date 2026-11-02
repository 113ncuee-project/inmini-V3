"""Vector architecture figure matching the executable hierarchical DF pipeline."""
from pathlib import Path
import base64
import html
import json

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/df_joint_20261011'
OUT.mkdir(parents=True,exist_ok=True)
W,H=4300,1680
INK='#21344e'; MUT='#52677d'; BLUE='#23679d'; TEAL='#147b73'; PUR='#6d58a6'; ORANGE='#b37528'
p=[]
def rect(x,y,w,h,fill='white',stroke='#d5e0eb',r=12):
    p.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>')
def text(x,y,s,size=27,color=INK,bold=False):
    p.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{700 if bold else 400}">{html.escape(s)}</text>')
def lines(x,y,ss,size=26,color=MUT,gap=43):
    for i,s in enumerate(ss):text(x,y+i*gap,s,size,color)
def arrow(x1,y1,x2,y2,color=BLUE,dash=False):
    p.append(f'<path d="M{x1},{y1} L{x2},{y2}" stroke="{color}" stroke-width="3" fill="none"'+(' stroke-dasharray="9 6"' if dash else '')+f' marker-end="url(#{"reward" if color==ORANGE else "arrow"})"/>')
def node(x,y,w,h,s,color=BLUE,fill='#edf4fa'):
    rect(x,y,w,h,fill,color,6);text(x+12,y+h/2+9,s,25,color,True)
def card(x,y,w,h,title,color=BLUE):
    rect(x,y,w,h);text(x+20,y+42,title,30,color,True)
def tilegrid(x,y,rows,cols,size=35,color=TEAL):
    for j in range(rows):
        for i in range(cols):rect(x+i*(size+5),y+j*(size+5),size,size,'#dcefe9',color,3)
def data(path,mime):return f'data:{mime};base64,'+base64.b64encode(path.read_bytes()).decode()

p.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}"><title>Communication-aware Tile Fusion Reuse DP and RL Chiplet DSE</title><defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto"><path d="M0 0 L10 5 L0 10" fill="{BLUE}"/></marker><marker id="reward" markerWidth="10" markerHeight="10" refX="8" refY="5" orient="auto"><path d="M0 0 L10 5 L0 10" fill="{ORANGE}"/></marker></defs><g font-family="Microsoft JhengHei, sans-serif">')
rect(0,0,W,H,'white','white',0)
text(35,63,'通訊感知 Tile／Fusion／Reuse DP × RL Chiplet 聯合設計探索',48,INK,True)
text(35,111,'外層搜尋 Part／CG／FD；內層完成跨層排程；同一套分析評估器產出 PPA 與學習回饋',29,MUT)
columns=[(30,410,'01　真實 GUI',PUR),(490,590,'02　模型與硬體',BLUE),(1130,630,'03　外層 Mapping',PUR),
         (1810,1030,'04　內層 Tile／Fusion／Reuse DP',TEAL),(2890,700,'05　統一成本與排程',TEAL),(3640,625,'06　設計決策與輸出',BLUE)]
for x,w,title,color in columns:
    rect(x,190,w,1300,'#f7f9fc');text(x+12,167,title,31,color,True)
for x1,x2 in [(442,485),(1082,1125),(1763,1805),(2843,2885),(3592,3635)]:arrow(x1,450,x2,450)

gui=OUT/'gui_actual.png'
if gui.exists():p.append(f'<image x="51" y="215" width="368" height="1218" preserveAspectRatio="xMidYMin meet" href="{data(gui,"image/png")}"/>')
text(51,1460,'本機實際介面 · DP 可開／關',23,MUT)

card(510,214,550,600,'固定成本的硬體候選',BLUE)
for i,n in enumerate([4,8,16]):node(532+i*173,286,155,54,f'{n} dies')
text(532,383,'IO cluster mesh ＋ 每 die multi-ring',26,TEAL,True)
for j in range(2):
    for i in range(2):
        x=628+i*230;y=435+j*135
        if i==0:arrow(x+20,y+25,x+207,y+25,TEAL)
        if j==0:arrow(x+22,y+50,x+22,y+129,TEAL)
        node(x,y,60,48,'IO',TEAL,'#def0e9')
        for dx,dy in [(-50,-38),(65,-38),(-50,56),(65,56)]:
            arrow(x+28,y+22,x+dx+20,y+dy+15,TEAL);node(x+dx,y+dy,43,30,'C',BLUE)
text(532,716,'示意：16C＋4IO；DRAM 另接 IO',22,MUT)
lines(532,759,['同總算力／使用者選定總 UB','重算 die、SRAM、IO／PHY 與封裝成本'],25,gap=38)
card(510,840,550,580,'DNN → Operator／Tensor DAG',BLUE)
lines(532,922,['ResNet／VGG／MobileNet／AlexNet','FX shape propagation · INT8／INT24'],25,gap=43)
for x,s in [(545,'Conv'),(702,'Conv'),(859,'Add')]:node(x,1030,125,58,s)
arrow(670,1060,697,1060);arrow(827,1060,854,1060)
p.append(f'<path d="M565,1027 L565,995 L920,995 L920,1026" stroke="{BLUE}" stroke-width="3" fill="none" marker-end="url(#arrow)"/>')
lines(532,1165,['真實 tensor shapes 與 producer／consumer','保留 shortcut；限制融合為封閉單出口子圖','Part 表示分配；DF tile 表示執行粒度'],25,gap=48)

card(1150,214,590,310,'起點：通訊感知 mapping 規劃',PUR)
lines(1172,294,['Balanced allocator → frontier traffic DP','前後層資料區域交集 → link 負載','保留尚有未來 consumer 的 mapping 狀態','有限候選 → 完整 oracle 選初始方案'],25,gap=49)
card(1150,552,590,575,'Masked linear actor–critic',PUR)
text(1172,636,'State → action policy → mapping M',27,PUR,True)
labels=['OP1　改 B／K／H／W partition','OP2　交換單層 core 對應','OP3　交換兩層 core 配置','OP4　重新分配 core 數量','OP5　改 DRAM／interleaving']
for i,s in enumerate(labels):node(1172,676+i*77,546,58,s,PUR,'#f0ebf8')
card(1150,1155,590,265,'每個 mapping query 呼叫內層 DP',PUR)
lines(1172,1234,['RL／Greedy／SA／Random 可共用此介面','接收排程後的完整 PPA，更新 reward','外層 query 與內層評估次數分開記錄'],25,gap=48)

card(1830,214,990,342,'候選節點：封閉子圖 × Tile × Overlap',TEAL)
for x,s in [(1854,'L0'),(1995,'L1'),(2136,'L2')]:node(x,295,106,50,s,TEAL,'#e0efeb')
arrow(1962,320,1990,320);arrow(2103,320,2131,320)
rect(1847,282,416,83,'none',TEAL,7);text(1854,404,'Fusion：切分／合併合法連續子圖',25)
tilegrid(2324,285,3,3,33);tilegrid(2520,285,2,2,52)
text(2324,439,'Tile H×W：可設定候選',25)
lines(1854,488,['Part／CG／FD 沿用外層；融合深度有上限；row-major tile traversal'],25)
card(1830,582,990,375,'Sink tile → 反向需求 → 可執行 Tile DAG',TEAL)
for i,s in enumerate(['L0 區域','L1 區域','L2 tile']):node(1870+i*285,663,230,62,s,TEAL,'#e0efeb')
arrow(2146,745,1892,745,TEAL);arrow(2436,745,2177,745,TEAL)
text(1870,791,'反推 receptive-field／halo；依 owner 分割實際輸入',25)
lines(1870,842,['Recompute：每 tile 重算 overlap','Horizontal cache：同一 tile row 重用','Full cache：跨 tile rows 重用'],26,gap=43)
card(1830,986,990,434,'通訊／容量感知 interval DP',TEAL)
node(1854,1065,270,59,'子圖 oracle：E／T',TEAL)
node(2164,1065,265,59,'UB／scratch 門檻',TEAL)
node(2470,1065,325,59,'E／T 候選＋beam',TEAL)
arrow(2127,1095,2159,1095);arrow(2432,1095,2465,1095)
lines(1854,1190,['狀態：已覆蓋前綴、融合切點、固定 boundary ownership','邊界 tensor 經 DRAM；shortcut 不會被當成已釋放','保留 Energy 與 Latency，不把各組 EDP 直接相加','完整候選＋原方案 → 全模型 oracle 最終選擇'],26,gap=50)
text(1854,1390,'有界近似搜尋；proxy Pareto／beam 不保證全域最佳',24,ORANGE,True)

card(2910,214,660,397,'同一個可追溯成本帳本',TEAL)
lines(2932,297,['Logical／unique／recompute／executed MAC','UB cache lifetime · local copy events','權重讀取、SRAM access、NoC／NoP flows','multicast 共用路徑只計一次','容量不足 → 不可行；重算 → 真正增加成本'],25,gap=52)
card(2910,639,660,365,'官方 RapidChiplet ＋ 自寫模型',TEAL)
lines(2932,724,['Rapid：封裝幾何、bump ceiling、path latency','自寫：MAC／bank SRAM／multi-ring／DRAM','routing load → transfer service → energy','resource calendars：link／DMA／IO／core','依賴＋讀／算／寫 → batch makespan'],25,gap=49)
card(2910,1032,660,388,'完整全模型評估與接受',TEAL)
node(2940,1117,588,63,'PPA ＋ 容量 ＋ 重算／通訊證據',TEAL)
lines(2932,1238,['候選排名採使用者偏好與 strict／soft 限制','內層保留原方案作 fallback','全模型最佳觀察值回傳外層搜尋'],25,gap=48)

card(3660,214,585,380,'所有選定模型共同選架構',BLUE)
lines(3682,295,['先檢查逐模型嚴格 PPA 限制','再以共同尺度比較偏好成本','找不到符合方案：回報最接近與差距','Energy／Area／Delay 四種偏好','分析估算；未完成實體製程校準'],25,gap=53)
card(3660,622,585,798,'實際配置與可重現輸出',BLUE)
run=OUT/'resnet18_32_dp'
if not (run/'package.svg').exists():run=OUT/'methods/rl'
pkg=run/'package.svg'
if pkg.exists():p.append(f'<image x="3682" y="700" width="541" height="410" preserveAspectRatio="xMidYMid meet" href="{data(pkg,"image/svg+xml")}"/>')
text(3682,1145,'圖中布局由已執行 hardware／placement 產生',23,MUT)
lines(3682,1203,['mapping.json：融合群、tile 與 overlap policy','layout.html：逐 die／layer 檢查','PPA、重算 MAC、cache-copy、容量 peak','queries／時間／source identity'],25,gap=48)

p.append(f'<path d="M3240,1425 L3240,1530 L1438,1530 L1438,1427" stroke="{ORANGE}" stroke-width="4" fill="none" marker-end="url(#reward)"/>')
text(1820,1577,'完整候選 PPA → 偏好／限制評分 → reward → actor–critic 更新',29,ORANGE,True)
text(35,1640,'實作：hybrid_dse → traffic_planner／fusion_planner → depth_first → communication／ondie／scheduler／evaluator。快取位於已付成本的 UB；不宣稱任意 memory-level 搜尋。',25,MUT)
p.append('</g></svg>')
(OUT/'system_architecture.svg').write_text('\n'.join(p),encoding='utf8')
(OUT/'system_architecture.html').write_text(f'<!doctype html><meta charset="utf-8"><style>@page{{size:{W}px {H}px;margin:0}}body{{margin:0}}svg{{display:block}}</style>'+''.join(p),encoding='utf8')
print(OUT/'system_architecture.svg')
