"""Searchable Chinese cost provenance, constraints and validation handoff."""
from pathlib import Path
import sys
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Image, KeepTogether
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from PIL import Image as PILImage

sys.path.insert(0,str(Path(__file__).resolve().parent))
from export_hybrid_reports_pdf import add_markdown, styles

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/pdf/INDM_Gemini_Cost16_Constraints_20261009.pdf'
FIG=ROOT/'output/hybrid_cost16'


def figure(path,width=515,height=600):
    with PILImage.open(path) as im:
        w,h=im.size
    scale=min(width/w,height/h)
    return Image(str(path),width=w*scale,height=h*scale)


def footer(canvas,doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor('#cdd6e1'));canvas.line(40,39,A4[0]-40,39)
    canvas.setFont('JhengHei',8);canvas.setFillColor(colors.HexColor('#627186'))
    canvas.drawString(40,25,'INDM + Gemini + RL | Cost16 與 PPA 限制 | 2026-10-09')
    canvas.drawRightString(A4[0]-40,25,str(doc.page));canvas.restoreState()


def main():
    OUT.parent.mkdir(parents=True,exist_ok=True)
    story=[Spacer(1,35),Paragraph('16 nm 文獻參考成本<br/>與 PPA 限制修正',styles['h1']),
           Paragraph('INDM + Gemini + RL - 2026-10-09',styles['body']),Spacer(1,10),
           Paragraph('保留 IO cluster mesh、片內 multi-ring、layer pipeline 與 RL 五 operators。撤回 MAC 乘 8 的推導，改用明示 op convention；SRAM 按實體 bank 計費；GRS 按 whole macro 與方向付成本。',styles['body']),
           Paragraph('使用者可輸入 Power / Area / Latency，逐項選擇嚴格上限或軟性目標。找不到符合候選時，提供最接近的物理可行方案及各模型超限差距。所有 PPA 是未校準的分析估算，無實體 signoff。',styles['body']),
           Paragraph('驗證：166 tests PASS、五個full224模型 x 三種die數共15組、60組area/clock/combined敏感度full-oracle評估、11種fixed-ledger係數情境，以及GUI strict / soft / closest三種瀏覽器流程。',styles['body']),
           Spacer(1,12),figure(FIG/'architecture.png',height=280),
           Paragraph('新版本16-die參考方案：package尺寸來自本次hardware.json；die/PE資源是示意配置，不是place-and-route。',styles['caption']),
           Paragraph('GUI：http://127.0.0.1:8765 - 載入工作 c16100000001。程式與實際 JSON 請一併上傳 GPT_review_cost16.zip；另一個 GPT 無法直接開啟本機路徑。',styles['body']),PageBreak()]
    add_markdown(ROOT/'docs/hybrid_cost16_sources.md',story)
    story+=[Spacer(1,8),Paragraph('可點選的原始來源',styles['h2']),
            Paragraph('<link href="https://www.zhanhongtan.com/publication/isca21/isca21.pdf" color="#235fa4">NN-Baton ISCA 2021 - Table I / Fig.10 / Sec.V-A</link>',styles['body']),
            Paragraph('<link href="https://research.nvidia.com/sites/default/files/pubs/2019-01_A-1.17-pJ/b%2C-25-Gb/s/pin/JSSCC_2019_GRS_FINAL.pdf" color="#235fa4">NVIDIA GRS JSSC - eight data lanes, footprint and energy</link>',styles['body']),
            Paragraph('Gemini HPCA 2024 - Sec.V-A（偏好指數與多模型幾何平均）；本專案的closest minimax政策是extension，不是該論文提供的演算法。',styles['body']),PageBreak()]
    add_markdown(ROOT/'docs/hybrid_cost16_validation.md',story)
    story+=[PageBreak(),Paragraph('完整15組：GUI結果表',styles['h1']),figure(FIG/'gui_results.png',height=610),
            Paragraph('無額外數值上限的共同推薦。Power欄為平均推論功率；硬性限制要對每個所選模型逐項檢查。',styles['caption']),
            PageBreak(),Paragraph('達不到嚴格上限：仍交付布局與差距',styles['h1']),figure(FIG/'gui_closest.png',height=650),
            Paragraph('故意給1mm²作測試：顯示最接近4-die方案、未符合strict以及超出的百分比；不把fallback稱為符合。',styles['caption']),
            PageBreak(),Paragraph('取消strict：軟目標仍回報差距',styles['h1']),figure(FIG/'gui_soft.png',height=650),
            Paragraph('相同目標取消strict後不淘汰方案，但保留soft penalty及目標差距。',styles['caption'])]
    SimpleDocTemplate(str(OUT),pagesize=A4,rightMargin=40,leftMargin=40,topMargin=42,bottomMargin=51,
                      title='INDM Gemini Cost16 and PPA Constraints',author='Rapid Chiplet DSE').build(story,onFirstPage=footer,onLaterPages=footer)
    print(OUT)


if __name__=='__main__':
    main()
