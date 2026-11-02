"""Export the four GPT review reports as one searchable, font-embedded PDF."""
from pathlib import Path
import html
import re

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle, Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output' / 'pdf' / 'INDM_Gemini_RL_GPT_Review.pdf'
SOURCES = [('hybrid_validation.md','實作與驗證結果'),('hybrid_architecture.md','完整專案架構'),
           ('hybrid_gemini_source_notes.md','Gemini 論文與原始碼核對'),
           ('hybrid_hardware_source_notes.md','INDM 硬體與模型假設核對')]
pdfmetrics.registerFont(TTFont('JhengHei','C:/Windows/Fonts/msjh.ttc',subfontIndex=0))
pdfmetrics.registerFont(TTFont('JhengHeiBold','C:/Windows/Fonts/msjhbd.ttc',subfontIndex=0))
pdfmetrics.registerFontFamily('JhengHei',normal='JhengHei',bold='JhengHeiBold',italic='JhengHei',boldItalic='JhengHeiBold')
NAVY=colors.HexColor('#16334D')
styles={
 'body':ParagraphStyle('body',fontName='JhengHei',fontSize=9.5,leading=15,spaceAfter=7,wordWrap='CJK'),
 'h1':ParagraphStyle('h1',fontName='JhengHeiBold',fontSize=18,leading=26,textColor=NAVY,spaceAfter=15,keepWithNext=True,wordWrap='CJK'),
 'h2':ParagraphStyle('h2',fontName='JhengHeiBold',fontSize=12,leading=19,textColor=NAVY,spaceBefore=12,spaceAfter=7,keepWithNext=True,wordWrap='CJK'),
 'h3':ParagraphStyle('h3',fontName='JhengHeiBold',fontSize=10.5,leading=17,textColor=NAVY,spaceBefore=9,spaceAfter=6,keepWithNext=True,wordWrap='CJK'),
 'cell':ParagraphStyle('cell',fontName='JhengHei',fontSize=8,leading=12,wordWrap='CJK'),
 'code':ParagraphStyle('code',fontName='JhengHei',fontSize=8,leading=12,backColor=colors.HexColor('#F1F4F7'),borderPadding=7,spaceAfter=8,wordWrap='CJK'),
 'caption':ParagraphStyle('caption',fontName='JhengHei',fontSize=8,leading=12,textColor=colors.HexColor('#596A76'),spaceAfter=8,wordWrap='CJK'),
}

def inline(text):
 text=html.escape(text)
 # Local links are source references; preserve their labels, not unusable hyperlinks.
 text=re.sub(r'\[([^\]]+)\]\(([^)]+)\)',r'\1',text)
 text=re.sub(r'\*\*([^*]+)\*\*',r'<b>\1</b>',text)
 text=re.sub(r'`([^`]+)`',r'<font color="#355A74">\1</font>',text)
 return text

def add_markdown(path,story):
 lines=path.read_text(encoding='utf-8').splitlines();i=0
 while i<len(lines):
  line=lines[i].strip()
  if not line:i+=1;continue
  if line.startswith('```'):
   language=line[3:];i+=1;block=[]
   while i<len(lines) and not lines[i].strip().startswith('```'):
    block.append(lines[i]);i+=1
   if language=='mermaid':
    story.append(Paragraph('評估流程：Workload DAG → Mapping → Exact communication demands → Native NoP／On-die／DRAM → Resource scheduler → PPA → RL → Mapping',styles['code']))
   else:
    story.append(Paragraph('<br/>'.join(html.escape(x) or '&#160;' for x in block),styles['code']))
   i+=1;continue
  if line.startswith('|'):
   rows=[]
   while i<len(lines) and lines[i].strip().startswith('|'):
    cells=lines[i].strip().strip('|').split('|')
    if not all(re.fullmatch(r'\s*:?-+:?\s*',cell) for cell in cells):
     rows.append([Paragraph(inline(cell.strip()),styles['cell']) for cell in cells])
    i+=1
   n=max(map(len,rows)); widths=[(A4[0]-80)/n]*n
   if n==4 and path.name=='hybrid_gemini_source_notes.md':widths=[47,123,179,166]
   t=Table(rows,colWidths=widths,repeatRows=1,hAlign='LEFT')
   t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#E4EDF3')),
    ('VALIGN',(0,0),(-1,-1),'TOP'),('GRID',(0,0),(-1,-1),.3,colors.HexColor('#C4CFD7')),
    ('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),
    ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]))
   story.extend([t,Spacer(1,10)]);continue
  image_match=re.match(r'!\[([^\]]*)\]\(([^)]+)\)',line)
  if image_match:
   image_path=(path.parent/image_match.group(2)).resolve()
   if image_path.exists():
    from PIL import Image as PILImage
    with PILImage.open(image_path) as img:w,h=img.size
    story.append(Image(str(image_path),width=A4[0]-80,height=(A4[0]-80)*h/w))
    story.append(Paragraph(inline(image_match.group(1)),styles['caption']))
   i+=1;continue
  heading=re.match(r'^(#{1,3})\s+(.*)',line)
  if heading:
   story.append(Paragraph(inline(heading.group(2)),styles['h'+str(len(heading.group(1)))]));i+=1;continue
  paragraph=[line];i+=1
  if re.match(r'^(- |\d+\. )',line):
   line=re.sub(r'^- ', '• ',line)
   story.append(Paragraph(inline(line),styles['body']));continue
  while i<len(lines) and lines[i].strip() and not re.match(r'^(#|\||```|!\[|- |\d+\. )',lines[i].strip()):
   paragraph.append(lines[i].strip());i+=1
  story.append(Paragraph(inline(' '.join(paragraph)),styles['body']))

def footer(canvas,doc):
 canvas.saveState();canvas.setStrokeColor(colors.HexColor('#CBD5DF'));canvas.line(40,39,A4[0]-40,39)
 canvas.setFont('JhengHei',8);canvas.setFillColor(colors.HexColor('#617181'))
 canvas.drawString(40,25,'INDM + Gemini + RL | GPT review package | 2026-10-06')
 canvas.drawRightString(A4[0]-40,25,str(doc.page));canvas.restoreState()

def main():
 OUT.parent.mkdir(parents=True,exist_ok=True)
 story=[Spacer(1,65),Paragraph('INDM + Gemini + RL<br/>GPT 審閱資料包',styles['h1']),
  Paragraph('2026-10-06 • 原始報告完整轉換 • 可搜尋文字與嵌入中文字型',styles['body']),Spacer(1,20),
  Paragraph('此PDF包含四份主要報告，供直接上傳至GPT對話。報告引用的本機Python、JSON、CSV及兩篇原始論文不包含在此PDF；若要核對實際程式，請另外上傳相應檔案。',styles['body']),
  Paragraph('分析模型尚未經RTL或silicon校準。同預算測試中greedy平均表現優於RL，本文保留這項結果及其他限制。',styles['body']),Spacer(1,15)]
 for i,(name,title) in enumerate(SOURCES,1):story.append(Paragraph(f'{i}. {title} ({name})',styles['body']))
 story.extend([Spacer(1,20),Paragraph('給GPT的建議訊息',styles['h2']),Paragraph('請讀完這份報告，以目前實作為準，不沿用舊phase 1-10。區分已實作、已驗證、分析假設與後續研究，檢查硬體資源、communication/reuse、layer pipeline、Gemini五operators/RL，以及latency/energy/area的一致性。不要預設RL優於greedy，也不要把分析PPA當成晶片量測。指出問題時請提供報告依據與具體修正建議；未收到程式時不要聲稱已檢查程式碼。',styles['body'])])
 for name,title in SOURCES:
  story.append(PageBreak());story.append(Paragraph('來源：docs/'+name,styles['caption']))
  add_markdown(ROOT/'docs'/name,story)
 doc=SimpleDocTemplate(str(OUT),pagesize=A4,rightMargin=40,leftMargin=40,topMargin=43,bottomMargin=51,
   title='INDM Gemini RL - GPT Review Reports',author='RapidChiplet project',pageCompression=1)
 doc.build(story,onFirstPage=footer,onLaterPages=footer)
 print(OUT)

if __name__=='__main__':main()
