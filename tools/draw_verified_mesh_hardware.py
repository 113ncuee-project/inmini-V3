"""Audit-backed diagram: render recorded endpoints/edges, never invent a netlist."""
from dataclasses import asdict
from pathlib import Path
import csv
import hashlib
import html
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'simplified_rapidchiplet'))
from simple_rapidchiplet.hybrid.hardware import fixed_mesh_hardware, build_package
from simple_rapidchiplet.hybrid.rapid_backend import build_native_inputs, _route_for_pair
from simple_rapidchiplet.hybrid.ondie import build_on_die_fabric
from simple_rapidchiplet.hybrid.costs import grs_port

OUT = ROOT/'output/hardware_fixed_mesh_20261025'
OUT.mkdir(parents=True,exist_ok=True)
spec = fixed_mesh_hardware(4)
package = build_package(spec)
native,_ = build_native_inputs(spec,package)
fabric = build_on_die_fabric(spec)
source = ROOT/'simplified_rapidchiplet/simple_rapidchiplet/hybrid'
mesh_edges = [e for e in package.links if e.kind=='compute_mesh']
dram_edges = [e for e in package.links if e.kind=='dram_compute']
active = {n:set() for n in package.compute_ids}
for edge in mesh_edges:
    active[edge.a].add(edge.a_port)
    active[edge.b].add(edge.b_port)
assert len(mesh_edges)==4 and len(dram_edges)==4
assert all(len(ports)==2 for ports in active.values())
assert len(fabric.edges)==50
assert _route_for_pair(package,spec,'compute:0','compute:3')==('compute:0','compute:1','compute:3')
ports = native['chiplets']['compute:0']['phys']
w = package.nodes['compute:0'].width_mm
normalized = [(round(p['x']/w,8),round(p['y']/w,8)) for p in ports]
assert normalized==[(.5,0),(1,.5),(.5,1),(0,.5),(.75,1)]
for i in range(4):
    c,m = package.nodes[f'compute:{i}'],package.nodes[f'memory:{i}']
    assert m.y_mm>c.y_mm+c.height_mm

audit = {
    'status':'corrected; previous inmin_v2_hardware_zh figure withdrawn',
    'scope':'analytical model connectivity and assumed endpoint coordinates; no macro floorplan or routed wires',
    'compute_chiplet_ports':[{'port':i,'kind':'D2D' if i<4 else 'generic DRAM endpoint',
                             'normalized_coordinate':xy,'coordinate_mm':[ports[i]['x'],ports[i]['y']]} for i,xy in enumerate(normalized)],
    'reserved_d2d_ports_per_chiplet':4,
    'used_d2d_ports_in_2x2_example':{n:sorted(ps) for n,ps in active.items()},
    'd2d_grs_cost_macros_per_port':grs_port(spec)['endpoint_macros'],
    'd2d_grs_cost_macros_per_chiplet':4*grs_port(spec)['endpoint_macros'],
    'dram_controller_phy':'bundled area/leakage on compute die; no independent macro x/y/width/height',
    'memory_endpoint_0':native['chiplets']['memory:0']['phys'][0],
    'memory_endpoint_note':'generic _phy_coordinates currently places this point at memory die bottom-right; not a real DRAM pinout',
    'package':package.to_dict(),'on_die_fabric':asdict(fabric),
    'unresolved':['DRAM standard/package pinout and calibrated PHY','separate DDR controller/PHY macro placement',
                  'D2D TX/RX macro placement and bump-level routing','Control/DMA/UB/L2/router hardware netlist',
                  'physical package wire paths'],
    'source_sha256':{n:hashlib.sha256((source/n).read_bytes()).hexdigest() for n in ('hardware.py','rapid_backend.py','ondie.py','evaluator.py','costs.py')},
}
(OUT/'hardware_connection_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
with (OUT/'connection_ledger.csv').open('w',newline='',encoding='utf-8-sig') as f:
    writer=csv.writer(f)
    writer.writerow(['scope','id','source','source_port','destination','destination_port','bandwidth_Bps','source_definition'])
    for e in package.links:
        writer.writerow(['package',f'{e.a}-{e.b}',e.a,e.a_port,e.b,e.b_port,e.bandwidth_Bps,'hardware.py:_build_compute_mesh'])
    for a,b in fabric.edges:
        writer.writerow(['on_die',f'{a}>{b}',a,'',b,'',spec.noc_bandwidth_Bps,'ondie.py:build_on_die_fabric'])

INK='#222'; MINT='#b0cfc4'; GREY='#e5e5e5'; GOLD='#c29a64'; BLUE='#22658c'; FONT="'Microsoft JhengHei','Arial',sans-serif"
svg=['<svg xmlns="http://www.w3.org/2000/svg" width="2000" height="2100" viewBox="0 0 2000 2100">',
     '<rect width="2000" height="2100" fill="white"/>']
def rect(x,y,w,h,fill='white',stroke=INK,sw=2):
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')
def text(x,y,s,size=22,bold=False,anchor='start',color=INK):
    svg.append(f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" font-weight="{"bold" if bold else "normal"}" text-anchor="{anchor}" fill="{color}">{html.escape(str(s))}</text>')
def line(points,color=INK,sw=2,dash=False,ident=None):
    tag=f' data-edge="{html.escape(ident)}"' if ident else ''
    svg.append(f'<polyline{tag} points="'+ ' '.join(f'{x},{y}' for x,y in points)+f'" fill="none" stroke="{color}" stroke-width="{sw}"'+(' stroke-dasharray="7 5"' if dash else '')+'/>')
def dot(x,y,used=True,color=INK,size=8):
    svg.append(f'<circle cx="{x}" cy="{y}" r="{size}" fill="{color if used else "white"}" stroke="{color}" stroke-width="2"/>')
def panel(x,y,w,h,title):
    text(x,y,title,27,True)
    line([(x,y+18),(x+w,y+18)],'#aaa',1)

text(1000,61,'INMIN V2：程式定義的端口、連線與容量',35,True,'middle')
text(1000,107,'模型連接圖；端口方位為既有模型假設，內部 macro 位置與實體走線尚未定義',23,False,'middle')
line([(60,137),(1940,137)],INK,1.5)

panel(60,192,900,780,'(a) 每顆 chiplet 的 5 個端口：4 D2D ＋ 1 DRAM')
x0,y0,side=225,260,460
rect(x0,y0,side,side,'#f3f3f3',sw=3)
text(x0+side/2,y0+57,'Compute chiplet',27,True,'middle')
text(x0+side/2,y0+140,'此框只表示 die 邊界與端點',23,False,'middle')
text(x0+side/2,y0+192,'Controller＋PHY：成本在此 die 內',22,True,'middle')
text(x0+side/2,y0+237,'沒有獨立 macro 座標／尺寸',23,True,'middle',BLUE)
text(x0+side/2,y0+286,'Control、DMA、router、UB、L2',21,False,'middle')
text(x0+side/2,y0+324,'未建立內部實體 netlist／floorplan',21,False,'middle')
for i,(nx,ny) in enumerate(normalized):
    dot(x0+side*nx,y0+side*ny,color=INK if i<4 else BLUE,size=9)
text(455,238,'P0 · N · (0.5W, 0)',23,True,'middle')
text(711,482,'P1 · E',23,True)
text(711,515,'(W, 0.5H)',21)
text(198,482,'P3 · W',23,True,'end')
text(198,515,'(0, 0.5H)',21,False,'end')
text(420,760,'P2 · S',23,True,'middle')
text(420,793,'(0.5W, H)',21,False,'middle')
line([(570,720),(655,788),(880,788)],BLUE,2)
text(795,755,'P4 · DRAM 接點',23,True,'middle',BLUE)
text(735,822,'(0.75W, H)',23,True,'middle',BLUE)
text(60,870,'端點方位：P0/P1/P2/P3 分別為北／東／南／西。',22)
text(60,908,'P4 座標只代表模型接點，不等於已完成 DRAM PHY 擺放。',22,True,color=BLUE)
text(60,946,'每個 D2D port 的 TX/RX macro 尚未分別擺放。',21)

panel(1040,192,900,800,'(b) 2×2 部署的真實連接關係：每個 port 有明確對端')
text(1040,237,'黑線：D2D 12.5 GB/s／方向；藍虛線：DRAM 4.6875 GB/s',21)
pos={'compute:0':(1095,285),'compute:1':(1715,285),'compute:2':(1095,665),'compute:3':(1715,665)}
cw,ch=200,140
def port_xy(node,p):
    x,y=pos[node]; nx,ny=normalized[p]
    return x+nx*cw,y+ny*ch

# Paths below are diagram connectors only. Edge membership comes from package.links.
for e in mesh_edges:
    a,b=port_xy(e.a,e.a_port),port_xy(e.b,e.b_port)
    ident=f'{e.a}:P{e.a_port}<->{e.b}:P{e.b_port}'
    if e.a_port==1:
        points=[a,b]
        lx,ly=(a[0]+b[0])/2,a[1]-19
        label=f'{e.a[-1]}.P1 ↔ {e.b[-1]}.P3'
    else:
        gx=pos[e.a][0]-25
        points=[a,(a[0],a[1]+22),(gx,a[1]+22),(gx,b[1]-22),(b[0],b[1]-22),b]
        lx,ly=gx+18,(a[1]+b[1])/2
        label=f'{e.a[-1]}.P2 ↔ {e.b[-1]}.P0'
    line(points,INK,2.7,ident=ident)
    text(lx,ly,label,19,True,'middle' if e.a_port==1 else 'start')
for e in dram_edges:
    x,y=pos[e.a]; a=port_xy(e.a,4)
    mx,my,mw,mh=x+54,y+175,92,66
    # Memory's generic port P0 appears at its bottom-right in native inputs.
    m=(mx+mw,my+mh)
    line([a,(a[0]+18,a[1]+16),(a[0]+18,m[1]),m],BLUE,2,True,f'{e.a}:P4<->{e.b}:P0')
    rect(mx,my,mw,mh,'#f4e5c9',BLUE,1.5)
    text(mx+mw/2,my+25,'DRAM '+e.b[-1],16,True,'middle')
    text(mx+mw/2,my+49,'512 MiB',17,False,'middle')
    dot(*m,color=BLUE,size=4)
    text(mx+mw+12,my+mh+20,'M.P0*',15,False,'middle',BLUE)
for node,(x,y) in pos.items():
    rect(x,y,cw,ch,GREY,sw=2.3)
    text(x+cw/2,y+37,'Chiplet '+node[-1],24,True,'middle')
    text(x+cw/2,y+76,'16 PE · UB 8 MiB',18,False,'middle')
    for p in range(5):
        used=p in active[node] if p<4 else True
        dot(*port_xy(node,p),used,INK if p<4 else BLUE,6)
        nx,ny=normalized[p]
        tx=x+nx*cw+(-19 if p==3 else 19 if p==1 else 20 if p==0 else 0)
        ty=y+ny*ch+(-15 if p==0 or p in (2,4) else -13)
        text(tx,ty,'P'+str(p),15,True,'middle',BLUE if p==4 else INK)
text(1040,971,'實心端點＝已接線；空心 D2D＝此部署未接線，仍保留並計費。',20)
text(1040,1002,'4 顆共預留 16 個 D2D port；4 條 D2D link 用掉其中 8 個端點。',20)

panel(60,1101,900,685,'(c) 已建模的片內 NoC：連線直接取自 fabric.edges')
no_pos={f'pe:{i}':(305+(i%4)*153,1187+(i//4)*125) for i in range(16)}
no_pos['l2']=(75,1187)
nw,nh=120,76
undirected=sorted({tuple(sorted((a,b))) for a,b in fabric.edges})
for a,b in undirected:
    xa,ya=no_pos[a]; xb,yb=no_pos[b]
    aw=175 if a=='l2' else nw; bw=175 if b=='l2' else nw
    line([(xa+aw/2,ya+nh/2),(xb+bw/2,yb+nh/2)],INK,2,ident=f'NoC:{a}<->{b}')
for node,(x,y) in no_pos.items():
    if node=='l2':
        rect(x,y,175,nh,GREY)
        text(x+87,y+30,'L2 node',22,True,'middle')
        text(x+87,y+57,'W / A / O',19,False,'middle')
    else:
        i=int(node.split(':')[1]); rect(x,y,nw,nh,MINT)
        text(x+nw/2,y+30,'PE '+str(i),21,True,'middle')
        text(x+nw/2,y+58,'L1 176 KiB',17,False,'middle')
for r in range(4):
    text(929,1233+r*125,'C'+str(r),19,True,'middle')
text(60,1705,'24 組 PE 鄰接＋1 組 L2↔PE0；每組皆雙向，共 50 條 directed edges。',20)
text(60,1745,'NoC：8.5 GB/s／方向／link；每個 mapping core C0–C3 分到 4 PE。',20)
text(60,1785,'未畫 UB↔L2、DMA↔Control 等線：目前沒有對應的硬體 netlist。',20,True,color=BLUE)

panel(1040,1101,900,685,'(d) 已定義資源與容量：此表不表示 macro 位置')
rows=[
    ('運算單元','16 PE；每 PE 16×16 = 256 MAC'),
    ('每 PE L1／每個槽','W 64 KiB · A 16 KiB · O 8 KiB'),
    ('每 PE L1／A+B 兩槽','176 KiB；全 die L1 合計 2.75 MiB'),
    ('共享 L2／每個槽','W 64 KiB · A 16 KiB · O 8 KiB'),
    ('共享 L2／A+B 兩槽','176 KiB／die'),
    ('共享 UB','8 MiB／die（不因雙緩衝翻倍）'),
    ('片內 SRAM 合計','10.921875 MiB／die'),
    ('對應本地 DRAM','512 MiB／memory die；每 compute die 一顆'),
    ('D2D ports','4／die；每方向配置 12.5 GB/s'),
    ('GRS 成本單位','每 port 1 TX＋1 RX；4 ports 共 8 macros*'),
    ('DRAM controller＋PHY','在 compute die 內合併計費；未分別放置'),
    ('交換／DMA 服務','crossbar 50 GB/s；UB/L2 64 GB/s'),
    ('時脈與精度','compute 500 MHz；NoC/NoP 1 GHz；INT8/24'),
]
for i,(a,b) in enumerate(rows):
    yy=1153+i*43
    if i%2==0: rect(1040,yy-27,900,41,'#f4f4f4',stroke='none',sw=0)
    text(1052,yy,a,20,True)
    text(1380,yy,b,19)
text(1040,1745,'* 8 macros 是 TX/RX 的面積計費數，不是 8 個 D2D port。',20)
text(1040,1785,'Control、DMA 與 router 的私有 buffer 容量未定義。',20,True,color=BLUE)

line([(60,1834),(1940,1834)],'#999',1.5)
text(60,1877,'尚未完成的實體定義',24,True,color=BLUE)
text(60,1917,'DRAM PHY macro 的實際 x/y 與尺寸、D2D TX/RX macro 擺放、bump pinout、內部 netlist 與 interposer 布線均未建立。',22)
text(60,1958,'* DRAM 的 M.P0 是通用幾何函式給的右下角端點，尚未對應實際 DRAM pinout；512 MiB 本身不能決定 PHY。',22)
text(60,1999,'圖 (b) 的線只代表程式確定的 endpoint 連接關係，彎折不是已完成的走線；圖 (a) 座標使用 x 向右、y 向下的表示。',21)
text(60,2040,'依據：hardware.py／rapid_backend.py／ondie.py／evaluator.py／costs.py；每條線可查 connection_ledger.csv。',21)
svg.append('</svg>')
(OUT/'inmin_v2_hardware_verified_v2.svg').write_text('\n'.join(svg),encoding='utf-8')
print(json.dumps({'svg':str(OUT/'inmin_v2_hardware_verified_v2.svg'),'package_edges':len(package.links),
                  'on_die_directed_edges':len(fabric.edges),'on_die_drawn_bidirectional_pairs':len(undirected),
                  'normalized_ports':normalized},ensure_ascii=False))
