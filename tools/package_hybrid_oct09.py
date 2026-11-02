"""Generate delivery Markdown, charts and a small GPT review code/data bundle."""
from pathlib import Path
import hashlib
import json
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
FOLDER=ROOT/'simplified_rapidchiplet/results/hybrid_gui_oct09/d09e10000001'
OUT=ROOT/'output/hybrid_oct09'


def main():
    suite=json.loads((FOLDER/'suite.json').read_text(encoding='utf-8'))
    validation=json.loads((FOLDER/'validation.json').read_text(encoding='utf-8'))
    ablation=json.loads((FOLDER/'ablation.json').read_text(encoding='utf-8'))
    assert validation['passed']
    OUT.mkdir(parents=True,exist_ok=True)
    lines=['# 多模型／GUI 實作與驗證結果','',
           '日期：2026-10-09 Asia/Taipei。正式結果採同一份固定估算器source；驗證資料不是silicon量測。',
           '', '## 已交付的功能','',
           '支援七種torchvision真實DAG；新GUI可選均衡、低功耗、小面積、低延遲，使用Gemini V-A的Energy/Area/Delay指數目標及多模型幾何平均，另以平均Power W施加硬性上限。硬體保留IO cluster mesh與片內multi-ring，新增有成本的双L1/L2 banks預取。whole-DAG frontier DP與RL共同選mapping，named SRAM與NoP競爭由完整oracle驗證；每次結果都有實際數量的package/die/PE圖與可點選layout。',
           '', '## 驗收證據','',
           '- 全回歸156 tests PASS（82 hybrid）。包含800步LRU差分、跨程序模型fingerprint一致、prefetch依賴與bank重用、paid area/leakage、Flatten精確覆蓋、四種偏好、多模型source/設定resume guard、HTTP與PPA限制。',
           '- 實際瀏覽器完成GUI submit、四偏好切換、點compute die、layer切換、重新載入保存工作，以及Area=1mm²硬限制失敗。三級SVG已XMLparse驗證。',
           f'- 完整224×224、batch1、seed7、RL4queries的15 trials：{validation["feasible_count"]}/15合法；三個硬體都評估ResNet18/50、VGG16、MobileNetV2、AlexNet。ResNet34/VGG19另經真實frontend及shape/MAC語意tests，未列入這15個PPA trials。',
           '- 保存timeline的dependency/resource calendars逐份核對，dynamic energy重加與MAC守恆、NoP hopbyte重加、UB及concurrent scratch容量均通過。每份結果包含全部hybrid模組SHA256；不同process提取的同模型fingerprint已一致。',
           '', '## 共同硬體結果','',
           f'選定模型組合與均衡偏好的共同最佳：**{suite["best_architecture"]}**。這是本次明示資源、單seed與小budget下的候選比較，不是所有模型／批次／成本profile的普遍最優，也不是RL優於baseline的公平優勝結論。',
           '', '| 架構 | 多模型共同score（越小越佳） | 全模型可行 |','|---|---|---|']
    for rank in suite['ranking']:
        lines.append(f'| {rank["architecture"]} | {rank["cost"]:.6f} | {rank["feasible_for_all_models"]} |')
    lines += ['', '共同score=(E^wE×A^wA×D^wD)對五個模型取幾何平均；E/A/D用相同固定共同單位1J/1mm²/1s，沒有使用每個architecture自己的relative improvement來排名。Area為Gemini monetary cost的明示代理，無美元／良率主張。',
              '', '| 架構 / 模型 | Latency ms | Energy mJ | Avg Power W | Silicon mm² | UB peak MiB/die |','|---|---|---|---|---|---|']
    for row in suite['runs']:
        m=row['metrics']
        if m.get('feasible'):
            lines.append(f'| {row["architecture"]} / {row["model"]} | {m["latency_s"]*1e3:.4f} | {m["energy_j"]*1e3:.4f} | {m["power_w"]:.3f} | {m["area_mm2"]:.3f} | {max(m["buffer_peak_bytes"].values())/1024**2:.3f} |')
        else:
            lines.append(f'| {row["architecture"]} / {row["model"]} | infeasible | - | - | - | - |')
    lines += ['', '這組完整模型候選總UB128MiB、雙scratch banks；16-die每die8MiB UB、8-die16MiB、4-die32MiB。256PE、64cores、DRAM總容量/頻寬守恆。額外SRAM、PHY、IO/controller、die面積/leakage均付費；不是舊32MiB budget的免費升級。',
              '', '## 同硬體 mapping 驗證','',
              '下表比較共同最佳硬體上的balanced baseline與交付的DP＋dataflow＋RL組合。兩者使用相同物理資源與完整batch oracle；百分比只對兩者均合法時列出，不將infeasible mapping的PPA當作改善基準，也不把組合收益全歸因於RL。',
              '', '| 模型 | Balanced合法 | Latency變化% | Energy變化% | NoP hopbytes變化% |','|---|---|---|---|---|']
    for row in ablation:
        d=row['change_percent']
        values=[f'{d.get(key):.2f}' if d.get(key) is not None else '不可比較' for key in ('latency_s','energy_j','nop_hop_bytes')]
        lines.append(f'| {row["model"]} | {row["baseline"]["feasible"]} | {" | ".join(values)} |')
    lines += ['', '## 使用方式與交付位置','',
              'GUI目前可用 http://127.0.0.1:8765，載入工作ID **d09e10000001**可查看完整五模型結果。重新啟動方式見hybrid_oct09_runbook.md；本次server使用results/hybrid_gui_oct09，完整資料保存於其ID資料夾。程式不會由另一個GPT自動讀取本機路徑，請實際上傳PDF，程式核對則附GPT資料包ZIP。',
              '', 'Reproduce: tools/validate_hybrid_oct09.py --worker 4/8/16（各自一次），全部完成後--merge。--resume只重用相同source、fingerprint、硬體與設定且完整的trial。Config: simplified_rapidchiplet/configs/hybrid_oct09_suite.json。',
              '', '## 來源與未兌現的部分','',
              'Gemini：HPCA2024，Section V-A（PDF第6頁）與five operators；INDM：Fig.3 IO cluster/multi-ring及cross-layer mapping方法。使用者Word及補充PDF第1/2/4/5點、Word內兩張書頁均已核對。公開分享只提供文字摘要，16原圖未能取回，沒有逐圖精讀聲稱。',
              '', '晶片的精確layout、packet VC/arbitration、foundry/yield、thermal、BFP/FP16及跨die IC reduction不在此原型模型內。Post-op時間/SRAM有計入，独立非MAC ALU能量/面積未獨立校準。輸出package圖是實際評估幾何；die/PE圖是資源示意，不是完成place-and-route。',
              '', '本次沒有外部發布或傳送他人訊息，沒有覆寫10/06舊benchmark。']
    (ROOT/'docs/hybrid_oct09_validation.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    models=list(suite['models'])
    architectures=[r['architecture'] for r in suite['ranking']]
    fig,axes=plt.subplots(1,2,figsize=(11,4.8),layout='constrained')
    palette=['#7069c7','#278580','#bf8441']
    for index,architecture in enumerate(architectures):
        rows={r['model']:r['metrics'] for r in suite['runs'] if r['architecture']==architecture}
        x=np.arange(len(models))+(index-1)*.24
        for ax,key,scale in ((axes[0],'latency_s',1e3),(axes[1],'energy_j',1e3)):
            ax.bar(x,[rows[model][key]*scale for model in models],width=.23,label=architecture.split('_')[0],color=palette[index])
    for ax,title in zip(axes,('Batch latency (ms)','Batch energy (mJ)')):
        ax.set_title(title);ax.set_xticks(range(len(models)),[name.replace('mobilenet_v2','MobileNetV2') for name in models],rotation=25,ha='right')
        ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True);ax.legend(frameon=False)
    fig.suptitle('224 input / batch 1 / native RapidChiplet + analytical PPA',fontsize=12)
    fig.savefig(OUT/'ppa_comparison.png',dpi=180)
    fig.savefig(OUT/'ppa_comparison.svg')
    plt.close(fig)
    files=list((ROOT/'simplified_rapidchiplet/simple_rapidchiplet/hybrid').glob('*.py'))
    # The parent package facade imports the legacy evaluator; preserve its local
    # dependencies for importability. Only hybrid/* is the new evaluator.
    files+=list((ROOT/'simplified_rapidchiplet/simple_rapidchiplet').glob('*.py'))
    files+=list((ROOT/'simplified_rapidchiplet/gui').glob('*'))
    files+=list((ROOT/'simplified_rapidchiplet/tests').glob('test_hybrid*.py'))
    files+=[ROOT/'simplified_rapidchiplet/simple_rapidchiplet/__init__.py',ROOT/'simplified_rapidchiplet/hybrid_dse.py',ROOT/'simplified_rapidchiplet/hybrid_gui.py',
            ROOT/'simplified_rapidchiplet/scripts/start_hybrid_gui.ps1',ROOT/'simplified_rapidchiplet/configs/hybrid_oct09_suite.json']
    files+=list((ROOT/'docs').glob('hybrid_oct09_*.md'))
    files+=[ROOT/'docs'/name for name in ('hybrid_gemini_source_notes.md','hybrid_hardware_source_notes.md')]
    files+=list((ROOT/'simplified_rapidchiplet').glob('requirements*.txt'))
    files+=[ROOT/'tools'/name for name in ('validate_hybrid_oct09.py','ablate_hybrid_oct09.py','package_hybrid_oct09.py','export_hybrid_oct09_pdf.py','export_hybrid_reports_pdf.py')]
    files+=[FOLDER/name for name in ('suite.json','validation.json','ablation.json','job.json')]
    files+=[ROOT/'simplified_rapidchiplet/results/hybrid_oct09_unittest.txt']
    files+=list(OUT.glob('*.png'))+list(OUT.glob('*.svg'))+[OUT/'gui_qa.json']
    files+=[ROOT/'output/pdf/INDM_Gemini_MultiModel_GUI_20261009.pdf']
    for row in suite['runs']:
        files += [Path(row['folder'])/name for name in ('summary.json','run.json','mapping.json','hardware.json','network.json','workload.json','buffers.json','layer_switching.json','layout.json','layout.html','architecture.svg','timeline.csv','link_traffic.csv','search.json','checkpoint.json')]
    files=list(dict.fromkeys(files))
    bundle=OUT/'GPT_review_code_and_results.zip'
    with zipfile.ZipFile(bundle,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            if path.is_file():
                archive.write(path,path.relative_to(ROOT).as_posix())
    manifest={path.relative_to(ROOT).as_posix():hashlib.sha256(path.read_bytes()).hexdigest() for path in files if path.is_file()}
    (OUT/'delivery_manifest.json').write_text(json.dumps({'files':manifest,'suite':str(FOLDER),'zip_bytes':bundle.stat().st_size},ensure_ascii=False,indent=2),encoding='utf-8')
    print('Report and bundle:',bundle)


if __name__=='__main__':
    main()
