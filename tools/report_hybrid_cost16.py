"""Build reviewable Markdown evidence and a compact upload bundle."""
import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'simplified_rapidchiplet'))
from simple_rapidchiplet.hybrid.hardware import HardwareSpec
from simple_rapidchiplet.hybrid.report import write_json

FOLDER=ROOT/'simplified_rapidchiplet/results/hybrid_gui_cost16/c16100000001'
OUT=ROOT/'output/hybrid_cost16'


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    suite=json.loads((FOLDER/'suite.json').read_text(encoding='utf-8'))
    audit=json.loads((FOLDER/'validation.json').read_text(encoding='utf-8'))
    sensitivity=json.loads((FOLDER/'sensitivity.json').read_text(encoding='utf-8'))
    gui=json.loads((OUT/'gui_qa.json').read_text(encoding='utf-8'))
    sensitivity_check=json.loads((FOLDER/'sensitivity_verification.json').read_text(encoding='utf-8'))
    assert audit['passed'] and gui['passed'] and sensitivity_check['passed']
    test_log=(ROOT/'tmp/cost16/unittest.txt').read_text(encoding='utf-8')
    assert 'Ran 166 tests' in test_log and test_log.rstrip().endswith('OK')
    text=['# Cost16 基準、限制與驗證結果','',
          '本報告以真正保存的 hardware.json / mapping.json 為準。舊混合製程 PPA 保留作歷史資料，不覆寫也不與此source混用。此版本移除unsupported MAC乘8與Gemini12nm SRAM/MAC密度；維持INDM硬體與Gemini/RL方法。','',
          '## 實際實驗設定','',
          '五個full224模型：ResNet18 / ResNet50 / VGG16 / MobileNetV2 / AlexNet。Batch1、seed7、traffic_dp+auto dataflow、RL4 unique mapping queries per trial（另有planner評估）；這是重現驗證的小搜尋預算，不是全域最優或RL優勝證據。',
          '共用資源：256 PEs、64 mapping cores、每PE16 lanes x16 vector MAC、INT8/INT24、compute500MHz，共65.536 TOPS（每scalar MAC報2ops）。總UB128MiB，L1/L2雙緩衝。DRAM總容量8GiB、總BW75GB/s。IO clusters依die數為1/2/4，保持4compute/cluster。','',
          '| Compute dies | IO / memory dies | PE / die | UB / die | 總 SRAM 面積估算 mm² | GRS whole-footprint mm² | 總矽面積 mm² |',
          '|---|---|---|---|---|---|---|']
    for arch in dict.fromkeys(r['architecture'] for r in suite['runs']):
        row=next(r for r in suite['runs'] if r['architecture']==arch)
        hw=HardwareSpec.from_dict(json.loads((Path(row['folder'])/'hardware.json').read_text(encoding='utf-8')))
        network=json.loads((Path(row['folder'])/'network.json').read_text(encoding='utf-8'))
        sram=sum(hw.compute_area_breakdown[k] for k in ('l1_sram','l2_sram','unified_sram'))*hw.compute_count
        grs=hw.compute_area_breakdown['grs_phy']*hw.compute_count
        # IO port count follows actual mesh degree, not identical IO assumption.
        from simple_rapidchiplet.hybrid.hardware import build_package
        package=build_package(hw)
        grs+=sum(n.area_components['grs_phys'] for n in package.nodes.values() if n.role=='io')
        text.append(f'| {hw.compute_count} | {hw.cluster_count} / {hw.cluster_count} | {hw.pe_count} | {hw.unified_buffer_bytes/1024**2:.0f}MiB | {sram:.3f} | {grs:.3f} | {row["metrics"]["area_mm2"]:.3f} |')
    text+=['', 'UB不隨雙緩衝再翻倍。新估算下總UB約77.916mm²（包含實體bank周邊）；舊flat density下103.51mm²只是歷史模型算式，兩者均非foundry認證數值。L1/L2額外bank周邊、MAC與PHY仍會影響不同die數的成本。','',
           '## 15組重新產生的PPA','',
           '| 架構 | 模型 | Latency ms | Energy mJ | 平均功率 W | Silicon mm² |',
           '|---|---|---|---|---|---|']
    table=[]
    for row in suite['runs']:
        m=row['metrics']
        text.append(f'| {row["architecture"]} | {row["model"]} | {m["latency_s"]*1e3:.4f} | {m["energy_j"]*1e3:.3f} | {m["power_w"]:.3f} | {m["area_mm2"]:.3f} |')
        table.append(dict(architecture=row['architecture'],model=row['model'],latency_ms=m['latency_s']*1e3,energy_mj=m['energy_j']*1e3,power_w=m['power_w'],area_mm2=m['area_mm2']))
    with (OUT/'ppa.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(table[0]));writer.writeheader();writer.writerows(table)
    text+=['','均衡 E/A/D 幾何平均分數（共同1J/1mm²/1s參考，越小越好）：'+', '.join(f'{r["architecture"]}={r["cost"]:.6f}' for r in suite['ranking'])+'.',
           f'未額外設上限時，此次候選／預算的推薦是 **{suite["best_architecture"]}**。限制會改變可選候選，不能說它永遠最佳。','',
           '## 成本敏感度與限制可行性','',
           'OAT能量或leakage情境使用fixed-schedule component ledger精確重算；不冒稱每筆都重新跑physical oracle。SRAM area、1GHz及combined high情境完整重跑native placement/latency、microkernel與buffer schedule。所有情境另存actual hardware.json與baseline mapping SHA。範圍是探索假設，不是信賴區間；沒有重新搜尋，所以不能證明robust optimality。',
           '範例限制為16W / 800mm² / 500ms；邊界probe為16W / 260mm² / 40ms，純粹用來檢查限制翻轉，不是使用者此次輸入。','',
           '| 情境 | 無上限推薦 | 範例限制 compliant trials /15 | 範例推薦 | 邊界限制 compliant trials /15 | 邊界推薦／狀態 |',
           '|---|---|---|---|---|---|']
    index={(r['scenario'],r['limits']):r for r in sensitivity['summaries']}
    labels={'nominal':'基準','mac_2ops':'MAC 2 op/MAC','sram_energy_050':'SRAM能量 x0.5','sram_energy_150':'SRAM能量 x1.5',
            'leakage_050':'漏電 x0.5','leakage_200':'漏電 x2','fabric_energy_050':'片內互連能量 x0.5',
            'fabric_energy_150':'片內互連能量 x1.5','grs_energy_080':'GRS能量 x0.8','grs_energy_120':'GRS能量 x1.2',
            'dram_energy_080':'DRAM能量 x0.8','dram_energy_120':'DRAM能量 x1.2',
            'sram_area_075':'SRAM面積 x0.75','sram_area_125':'SRAM面積 x1.25',
            'clock_1GHz_unverified':'1GHz（時序未驗證）','assumptions_high':'成本假設合併提高'}
    def arch_label(value):
        return value.replace('dies','').replace('_multi_ring',' dies') if value else '無'
    status_labels={'estimated_compliant':'估算符合','closest_exceeds_strict_limits':'最接近；未符合嚴格上限',
                   'no_physically_valid_candidate':'無物理可行候選'}
    for name in dict.fromkeys(r['scenario'] for r in sensitivity['summaries']):
        base=index[name,'unlimited'];example=index[name,'example_user_limits'];boundary=index[name,'boundary_probe']
        text.append(f'| {labels[name]} | {arch_label(base["recommended_architecture"])} | {example["compliant_trial_count"]} | {arch_label(example["recommended_architecture"])} / {status_labels[example["recommendation_status"]]} | {boundary["compliant_trial_count"]} | {arch_label(boundary["recommended_architecture"])} / {status_labels[boundary["recommendation_status"]]} |')
    nominal=index['nominal','boundary_probe']
    flips=[name for name in dict.fromkeys(r['scenario'] for r in sensitivity['summaries'])
           if (index[name,'boundary_probe']['recommendation_status'],index[name,'boundary_probe']['recommended_architecture']) != (nominal['recommendation_status'],nominal['recommended_architecture'])]
    text+=['','邊界probe相對nominal的推薦或compliance狀態改變：'+(', '.join(flips) if flips else '此次設定未觀察到')+'。實際差距請見sensitivity.json；即使無上限排名未改變，不能將成本不確定性忽略。','',
           '## 驗證證據與GUI','',
           '166 tests PASS，其中92個hybrid tests。15/15 full-model trials通過独立saved-artifact audit：source/native hashes、MAC conservation、energy component/event ledger、calendar/dependencies、UB/scratch capacity、actual die/PE count與SVG XML。',
           'GUI Edge headless實測三情境：strict不可能上限仍有closest布局；取消strict保留soft target與gap；可達上限輸出estimated_compliant。四個偏好按鈕及strict config傳遞已檢查，沒有page JS error。','',
           '另以16-die ResNet18的完整physical oracle抽查mac_2ops / sram_energy_150 / leakage_200三個係數情境，latency、energy、area、power與全部energy components均與fixed-ledger重算相符（relative tolerance 1e-12）。','',
           'GUI：http://127.0.0.1:8765，載入完整工作ID **c16100000001**。啟動：`./simplified_rapidchiplet/scripts/start_hybrid_gui.ps1`。新預設結果根目錄為results/hybrid_gui_cost16。',
           '重跑：`.venv/Scripts/python.exe tools/validate_hybrid_cost16.py --worker 4`（8/16同理），全部完成後 `--merge`；中斷用 `--resume`，source/settings/hardware不一致會拒絕reuse。敏感度工具：`tools/sensitivity_hybrid_cost16.py --scenario <name>`，四個full情境完成後 `--merge`。',
           '新建GUI工作將以使用者數值與strict設定進行搜尋。找不到compliant時明示closest與gap；物理容量失敗的候選不會被fallback推薦。平均Power不是peak/TDP，silicon area不是package area，有限搜尋也不是不存在可行解的證明。','',
           '## 尚未校準／未完成硬體signoff','',
           'MAC reported op=scalar MAC仍是明示convention；原作者沒有提供可排除2op計數的定義。SRAM width/ports/read-write/area模型、DDR與memory die、router/CPU、NoC/crossbar、leakage等仍依來源notes標為anchor或假設。GRS只建立whole-macro accounting與array-fit條件，尚未完成electrical／thermal／timing驗證。所有方案提供的是nominal analytical estimate；不能宣稱達成使用者真實silicon PPA上限。']
    (ROOT/'docs/hybrid_cost16_validation.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    # Self-contained code/results handoff without old results, installed libraries,
    # caches or huge repeated service NDJSON.
    files=list((ROOT/'simplified_rapidchiplet/simple_rapidchiplet/hybrid').glob('*.py'))
    files+=[ROOT/'simplified_rapidchiplet/hybrid_gui.py',ROOT/'simplified_rapidchiplet/hybrid_dse.py']
    files+=list((ROOT/'simplified_rapidchiplet/gui').glob('*'))
    files+=list((ROOT/'docs').glob('hybrid_cost16*.md'))
    files+=list((ROOT/'simplified_rapidchiplet/tests').glob('test_hybrid*.py'))
    files+=[ROOT/'tools'/name for name in ('validate_hybrid_cost16.py','validate_hybrid_oct09.py','sensitivity_hybrid_cost16.py','report_hybrid_cost16.py','verify_cost16_sensitivity.py','export_hybrid_cost16_pdf.py','export_hybrid_reports_pdf.py','audit_hybrid_cost16_delivery.py')]
    files+=[ROOT/'simplified_rapidchiplet/configs/hybrid_oct09_suite.json',ROOT/'simplified_rapidchiplet/scripts/start_hybrid_gui.ps1',ROOT/'tmp/cost16/unittest.txt']
    files+=[FOLDER/name for name in ('suite.json','validation.json','recommendation.json','sensitivity.json','sensitivity_verification.json','job.json')]
    for row in suite['runs']:
        files+=[Path(row['folder'])/name for name in ('run.json','summary.json','hardware.json','mapping.json','workload.json','network.json','buffers.json','layer_switching.json','layout.json','layout.html','architecture.svg','package.svg','die.svg','pe.svg','timeline.csv','link_traffic.csv','search.json','checkpoint.json')]
    files+=list((FOLDER/'sensitivity').rglob('hardware.json'))+list((FOLDER/'sensitivity').rglob('rows.json'))
    files+=[OUT/'gui_qa.json',OUT/'ppa.csv']
    files+=list(OUT.glob('*.svg'))+list(OUT.glob('*.png'))
    files=sorted({p.resolve() for p in files if p.is_file()})
    manifest={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    write_json(OUT/'review_manifest.json',dict(files=manifest,verified=True,cost_profile='literature16_v1'))
    with zipfile.ZipFile(OUT/'GPT_review_cost16.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path,str(path.relative_to(ROOT)))
        archive.write(OUT/'review_manifest.json','review_manifest.json')
    print('report and bundle',len(files),'files')


if __name__=='__main__':
    main()
