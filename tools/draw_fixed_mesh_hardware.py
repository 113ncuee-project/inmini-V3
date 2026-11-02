"""Draw the current fixed chiplet profile as a paper-style, editable figure."""
from pathlib import Path
import html
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'simplified_rapidchiplet'))
from simple_rapidchiplet.hybrid.hardware import fixed_mesh_hardware, FIXED_CHIPLET_PROFILE

OUT = ROOT / 'output/hardware_fixed_mesh_20261025'
raise SystemExit('此舊圖已撤回：請執行 tools/draw_verified_mesh_hardware.py，依實際端口與連線資料產生修正版。')
OUT.mkdir(parents=True, exist_ok=True)
H = fixed_mesh_hardware(4)
K = 1024
assert H.total_buffer_bytes_per_die == 11452416

INK = '#222222'
MINT = '#b0cfc4'
SRAM = '#dedede'
DARK = '#6d6d6d'
TAN = '#c6a27e'
MEM = '#f2e0bc'
CHIP = '#f1f1f1'
BASE = '#ebeff1'
FONT = "'Microsoft JhengHei','Arial',sans-serif"
parts = [f'''<svg xmlns="http://www.w3.org/2000/svg" width="2000" height="1940" viewBox="0 0 2000 1940">
<defs>
<marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" markerUnits="userSpaceOnUse" orient="auto-start-reverse"><path d="M0 0L8 4L0 8Z" fill="{INK}"/></marker>
</defs><rect width="2000" height="1940" fill="white"/>
''']

def rect(x, y, w, h, fill='white', stroke=INK, sw=2):
    parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')

def line(x1,y1,x2,y2,sw=2,color=INK,dash=None,arrows=False):
    extra = (' stroke-dasharray="8 6"' if dash else '') + (' marker-start="url(#arrow)" marker-end="url(#arrow)"' if arrows else '')
    parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{sw}"{extra}/>')

def path(d,sw=2,color=INK,dash=False):
    parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}"'+(' stroke-dasharray="8 6"' if dash else '')+'/>')

def txt(x,y,s,size=22,weight='normal',anchor='start',color=INK,rotate=None):
    transform = f' transform="rotate({rotate} {x} {y})"' if rotate is not None else ''
    parts.append(f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}" fill="{color}"{transform}>{html.escape(str(s))}</text>')

def label(x,y,lines,size=22,gap=30,weight='normal',anchor='middle',color=INK):
    for i,s in enumerate(lines):
        txt(x,y+i*gap,s,size,weight,anchor,color)

def box_label(x,y,w,h,fill,lines,size=22,gap=30,color=INK):
    rect(x,y,w,h,fill)
    first = y+h/2-(len(lines)-1)*gap/2+size*.32
    label(x+w/2,first,lines,size,gap,anchor='middle',color=color)

txt(1000,65,'INMIN V2 固定硬體架構',38,'bold','middle')
txt(1000,108,'相同 compute chiplet × 純 mesh interposer × 本地 DRAM',25,anchor='middle')
line(60,133,1940,133,1.5)

# (b) Detailed compute chiplet. Components carry modeled nominal capacities.
txt(60,177,'(b) 單顆運算 chiplet：固定 4×4 PE',29,'bold')
rect(90,220,1160,650,CHIP,sw=3)

# Inter-die wires run in the perimeter gutters, behind the component blocks.
path('M 963 220 V 236 H 1208 V 770 H 710',3,DARK)
path('M 1250 515 H 1208',3,DARK)
path('M 965 870 V 825 H 720 V 770',3,DARK)
path('M 90 510 H 111 V 699 H 365 V 738',3,DARK)

box_label(130,255,165,78,'#454545',['Control unit','控制單元'],21,28,'white')
box_label(130,354,165,78,'#bcbcbc',['DMA','資料搬移'],22,29)
line(212,333,212,354,2,arrows=True)
box_label(130,464,165,88,TAN,['DRAM controller','整合於每顆 chiplet'],17,27)
box_label(130,582,165,60,'#dec9ad',['DRAM PHY'],20)
line(212,552,212,582,2.2,arrows=True)

box_label(350,255,170,374,'#c5c5c5',['Unified','Buffer (UB)','8 MiB','每顆共用','64 GB/s'],26,48)
line(295,393,350,393,2.5,arrows=True)

txt(655,246,'共享 L2／每個槽',20,anchor='middle')
box_label(560,268,190,95,SRAM,['WL2 · 權重','64 KiB / slot'],22,30)
box_label(560,383,190,95,SRAM,['AL2 · 輸入','16 KiB / slot'],22,30)
box_label(560,498,190,95,SRAM,['OL2 · 輸出','8 KiB / slot'],22,30)
label(655,622,['A / B 雙緩衝','合計 176 KiB','L2 service：64 GB/s'],19,29)
line(520,432,540,432,2.5,arrows=True)
line(540,315,540,545,1.6)
for by in (315,432,545):
    line(540,by,560,by,1.6)
line(765,302,765,545,1.6)
for by in (302,432,545):
    line(750,by,765,by,1.6)

# Exactly sixteen PEs; row-wise groups correspond to actual mapping core IDs.
for row in range(4):
    txt(786,330+row*94,f'C{row}',17,'bold','middle')
    for col in range(4):
        px,py = 815+col*94,263+row*94
        if col<3:
            line(px+82,py+39,px+94,py+39,2.2)
        if row<3:
            line(px+41,py+78,px+41,py+94,2.2)
        box_label(px,py,82,78,MINT,[f'PE {row*4+col}','256 MAC'],17,25)

line(750,302,815,302,2.6,arrows=True)
txt(781,278,'W/A',14,anchor='middle')
txt(1000,682,'4×4 PE mesh NoC',24,'bold','middle')
txt(1000,716,'8.5 GB/s／方向／link · 1 GHz',20,anchor='middle')

box_label(350,751,360,76,'#b7b7b7',['Inter-die router / crossbar','共用交換服務 50 GB/s'],20,28)
line(435,629,435,751,2.5,arrows=True)
txt(455,715,'UB 存取',18)
path('M 295 508 H 322 V 789 H 350',2.5)

for x,y,w,h,content,angle in (
    (887,201,156,38,'D2D N',None),
    (887,851,156,38,'D2D S',None),
    (71,448,38,130,'D2D W',-90),
    (1231,448,38,130,'D2D E',90),
):
    rect(x,y,w,h,DARK)
    txt(x+w/2,y+h/2+6,content,19,'normal','middle','white',angle)

box_label(130,902,165,64,MEM,['本地 DRAM','512 MiB'],20,27)
line(212,642,212,902,2.3,arrows=True)
txt(230,888,'4.6875 GB/s',18)
txt(365,908,'D2D：4 個方向 · 12.5 GB/s／方向 · 全雙工 · NoP 1 GHz',22,'bold')
txt(365,943,'Compute：500 MHz · 4096 MAC/cycle · 4.096 TOPS / chiplet',21)
txt(60,999,'C0–C3：4 個 mapping cores，每組 4 PE；L2 由 PE 0 接入 NoC。',20)

# (c) A single PE, with the two real scratch slots explicitly separated.
txt(1340,177,'(c) 單個 PE：L1 與運算陣列',29,'bold')
rect(1340,220,600,750,'#fafafa',sw=3)
txt(1640,252,'INT8 activation × INT8 weight → INT24 psum',20,anchor='middle')
for slot,y in (('A',283),('B',405)):
    txt(1360,y+19,f'Slot {slot}',18,'bold')
    box_label(1360,y+32,210,69,SRAM,['WL1 · 權重','64 KiB'],20,27)
    box_label(1580,y+32,165,69,SRAM,['AL1 · 輸入','16 KiB'],20,27)
    box_label(1755,y+32,165,69,SRAM,['OL1 · 輸出','8 KiB'],20,27)
txt(1640,548,'每 PE：88 KiB × 2 = 176 KiB',23,'bold','middle')
txt(1640,580,'L1 service：64 GB/s／PE',21,anchor='middle')
rect(1360,605,560,285,'#e4e4e4')
txt(1640,637,'16 lanes × 16 vector MACs',25,'bold','middle')
for lane in range(16):
    for mac in range(16):
        rect(1464+mac*22,658+lane*12,18,9,MINT,sw=.65)
txt(1435,669,'Lane 0',14,anchor='end')
txt(1435,845,'Lane 15',14,anchor='end')
txt(1640,874,'256 scalar MAC / cycle / PE',21,anchor='middle')
txt(1640,926,'L1 權重／輸入／輸出皆有 A、B 兩個實體槽',19,anchor='middle')

# (a) Shallow 2.5D package style, with four identical computing chiplets.
txt(60,1076,'(a) 可擴展封裝：4 顆 chiplet 的 2×2 mesh 示意',29,'bold')
parts.append(f'<path d="M75 1155 L1202 1155 L1270 1124 L143 1124 Z" fill="#f7f7f7"/>')
rect(75,1155,1127,500,BASE,stroke='#d1d7d9',sw=1)
parts.append('<path d="M75 1655H1202L1270 1624V1638L1202 1669H75Z" fill="#2c5268"/>')

positions=[(250,1185),(820,1185),(250,1435),(820,1435)]
for a,b in ((0,1),(0,2),(1,3),(2,3)):
    xa,ya=positions[a]; xb,yb=positions[b]
    line(xa+117,ya+80,xb+117,yb+80,9,DARK)
    line(xa+117,ya+80,xb+117,yb+80,2,'#333333')

for i,(x,y) in enumerate(positions):
    mx = 91 if i%2==0 else 1095
    my = y+32
    line(x+117,y+80,mx+55,my+45,3)
    parts.append(f'<path d="M{x} {y+160}H{x+235}L{x+246} {y+150}V{y+164}L{x+235} {y+175}H{x}Z" fill="#a3a3a3"/>')
    rect(x,y,235,160,'#dadada',sw=2.3)
    txt(x+117,y+25,f'Compute chiplet {i}',20,'bold','middle')
    rect(x+10,y+42,23,82,TAN,sw=1)
    rect(x+202,y+42,23,82,'#bbbbbb',sw=1)
    for r in range(4):
        for c in range(4):
            rect(x+45+c*39,y+42+r*20,33,15,MINT,sw=.8)
    txt(x+117,y+145,'16 PE · UB 8 MiB',19,anchor='middle')
    for px,py,pw,ph in ((x+85,y-8,65,13),(x+85,y+155,65,13),(x-8,y+52,13,59),(x+230,y+52,13,59)):
        rect(px,py,pw,ph,DARK,sw=.9)
    box_label(mx,my,110,91,MEM,['DRAM','512 MiB'],20,28)

txt(650,1245,'12.5 GB/s／方向',21,anchor='middle')
txt(650,1299,'雙向 D2D link',19,anchor='middle')
txt(650,1495,'12.5 GB/s／方向',21,anchor='middle')
txt(120,1641,'Passive interposer',19)
txt(650,1704,'圖示 4 顆為部署示例；可選 1／2／4／8／16 顆相同 chiplet。',21,anchor='middle')

# Legend and capacity summary of exactly the shown example.
txt(1340,1076,'圖例與容量彙總',29,'bold')
for i,(color,s) in enumerate(((MINT,'PE／MAC 運算單元'),(SRAM,'UB／L1／L2 SRAM'),(DARK,'D2D PHY 介面'),(TAN,'DRAM controller／PHY'),(MEM,'外部 DRAM'),(BASE,'Passive interposer'))):
    rect(1350,1111+i*36,26,24,color,sw=1)
    txt(1393,1131+i*36,s,21)

rect(1340,1352,600,348,'white',stroke='#999999',sw=1.5)
txt(1360,1387,'名義儲存容量',24,'bold')
txt(1918,1387,'每 chiplet',20,'bold','end')
line(1356,1401,1924,1401,1,'#aaaaaa')
rows=[('L1：16 PE × 176 KiB','2.75 MiB'),('L2：2 × (64 + 16 + 8) KiB','176 KiB'),('Unified Buffer','8 MiB'),('片內 SRAM 合計','10.921875 MiB'),('對應本地 DRAM','512 MiB')]
for i,(s,v) in enumerate(rows):
    txt(1360,1436+i*40,s,19)
    txt(1918,1436+i*40,v,20,'bold','end')
txt(1360,1664,'4 顆示例：64 PE · UB 32 MiB · DRAM 2 GiB',20,'bold')

line(60,1744,1940,1744,1.2,'#aaaaaa')
txt(60,1781,'容量：KiB = 2¹⁰ B；MiB = 2²⁰ B；頻寬 GB/s = 10⁹ B/s。L1／L2 採雙緩衝；UB 容量不翻倍。',22)
txt(60,1822,'Control、DMA、router 與 PHY 未另設定私有 buffer 容量；圖中以功能、數量或頻寬標示。',22)
txt(60,1863,'本圖為目前分析模型的硬體示意，區塊不按實際面積比例；不包含獨立 I/O chiplet 或 multi-ring。',22)
txt(1000,1910,'Fig. 1. INMIN V2 homogeneous mesh hardware — package, compute chiplet, and PE.',23,anchor='middle')
parts.append('</svg>')
(OUT/'inmin_v2_hardware_zh.svg').write_text('\n'.join(parts),encoding='utf-8')
data={'profile':FIXED_CHIPLET_PROFILE,'illustrated_compute_chiplets':4,'hardware':H.to_dict(),
      'capacity_summary':{'l1_all_pes_bytes':H.prefetch_slots*H.pe_count*H.l1_bytes_per_pe,
                          'l2_bytes':H.prefetch_slots*H.l2_bytes_per_die,
                          'unified_buffer_bytes':H.unified_buffer_bytes,
                          'on_die_sram_total_bytes':H.total_buffer_bytes_per_die},
      'scope':'Schematic of current modeled hardware; 4-chiplet package is an illustration, not a sizing recommendation.'}
(OUT/'hardware_spec.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(OUT/'inmin_v2_hardware_zh.svg')
