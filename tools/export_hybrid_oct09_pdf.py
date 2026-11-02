"""Searchable Chinese PDF handoff: verified implementation, examples and figures."""
from pathlib import Path
import sys
import html
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors

sys.path.insert(0,str(Path(__file__).resolve().parent))
from export_hybrid_reports_pdf import add_markdown, styles

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'output'/'pdf'/'INDM_Gemini_MultiModel_GUI_20261009.pdf'


def footer(canvas,doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor('#cdd6e1'))
    canvas.line(40,39,A4[0]-40,39)
    canvas.setFont('JhengHei',8)
    canvas.setFillColor(colors.HexColor('#627186'))
    canvas.drawString(40,25,'INDM + Gemini + RL | 多模型與 GUI 交付 | 2026-10-09')
    canvas.drawRightString(A4[0]-40,25,str(doc.page))
    canvas.restoreState()


def main():
    OUT.parent.mkdir(parents=True,exist_ok=True)
    story = [Spacer(1,40),Paragraph('INDM + Gemini + RL<br/>多模型、硬體布局與 GUI',styles['h1']),
             Paragraph('2026-10-09 • 可直接上傳 GPT 的實作與驗證報告',styles['body']),
             Spacer(1,16),Paragraph('此版本支援七種真實模型DAG、四種Energy/Area/Delay偏好、Power硬限制、whole-DAG traffic-aware mapping、付費雙緩衝及每次結果的實際package/die/PE圖。PPA為分析估算，尚未經silicon/RTL校準。',styles['body']),
             Paragraph('共享聊天的16張原圖無法公開取回；已讀其中的文字摘要及使用者筆記內兩張書頁。本報告不冒稱逐張核對原圖，也不將BFP/FP16或FPGA數字混入INT8 profile。',styles['body']),
             Spacer(1,15),Paragraph('給GPT的審閱訊息',styles['h2']),
             Paragraph('請以此新版本與本報告為準，檢查INDM cluster/multi-ring、Gemini layer-pipeline與五operators、whole-DAG residual通信、named SRAM容量、付費prefetch、四種指數偏好與多模型排名是否一致。不要預设RL優於greedy、不要把分析PPA當量測。對原16張圖片的推論只視為可讀摘要來源，若要逐圖核對請要求原圖。程式與JSON需另外上傳資料包，不要聲稱能打開本機路徑。',styles['body'])]
    figure = ROOT/'output'/'hybrid_oct09'/'architecture.png'
    if figure.is_file():
        from PIL import Image as PILImage
        with PILImage.open(figure) as im:
            width,height = im.size
        story += [Spacer(1,16),Image(str(figure),width=515,height=515*height/width),
                  Paragraph('參數導出的實際package＋die＋PE架構圖；可縮放SVG原稿另附。Package採用實際幾何，片內為資源示意。',styles['caption'])]
    story += [PageBreak(),Paragraph('共同最佳硬體：實際 package 位置',styles['h1']),
              Paragraph('本次五模型均衡模式：16 compute dies、4 IO dies、4 DRAM endpoints。位置與尺寸由本次硬體配置產生；綠色連線是IO mesh，灰色是cluster與memory連線。SVG可放大檢視。',styles['body'])]
    from PIL import Image as PILImage
    path=ROOT/'output/hybrid_oct09/package.png'
    with PILImage.open(path) as im: width,height=im.size
    scale=min(515/width,610/height)
    story.append(Image(str(path),width=width*scale,height=height*scale))
    story += [PageBreak(),Paragraph('Compute die 與 PE 資源細節',styles['h1'])]
    for name,max_width,max_height in [('die',515,280),('pe',315,340)]:
        path=ROOT/'output/hybrid_oct09'/f'{name}.png'
        with PILImage.open(path) as im:width,height=im.size
        scale=min(max_width/width,max_height/height)
        story.append(Image(str(path),width=width*scale,height=height*scale))
        story.append(Spacer(1,8))
    story.append(Paragraph('每die有16PE／4cores／4單向rings。每PE為16 lanes×16 INT8 MAC，INT24 local accumulator；付費雙scratch slots。片內圖為資源示意，無place-and-route主張。',styles['caption']))
    for name in ('hybrid_oct09_validation.md','hybrid_oct09_architecture.md','hybrid_oct09_runbook.md'):
        story += [PageBreak(),Paragraph('來源：docs/'+name,styles['caption'])]
        add_markdown(ROOT/'docs'/name,story)
    for index,(name,title) in enumerate((('ppa_comparison.png','五模型與三種架構的PPA'),('gui.png','實際GUI：載入完整五模型結果'),('gui_layout.png','實際GUI：選die與layer查看mapping'))):
        path = ROOT/'output'/'hybrid_oct09'/name
        if path.is_file():
            from PIL import Image as PILImage
            with PILImage.open(path) as im:
                width,height=im.size
            scale = min(515/width,675/height)
            story += [PageBreak() if index else Spacer(1,12),Paragraph(title,styles['h2']),Image(str(path),width=width*scale,height=height*scale)]
    doc = SimpleDocTemplate(str(OUT),pagesize=A4,leftMargin=40,rightMargin=40,topMargin=43,bottomMargin=51,
                            title='INDM Gemini RL - Multi-model GUI and Hardware',author='RapidChiplet project')
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    print(OUT)


if __name__=='__main__':
    main()
