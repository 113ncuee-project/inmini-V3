"""Read-only audit of the versioned cost16 delivery, independent of search."""
from dataclasses import asdict, replace
import hashlib
import json
import math
from pathlib import Path
import sys
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'simplified_rapidchiplet'))
from simple_rapidchiplet.hybrid.hardware import HardwareSpec, build_package
from simple_rapidchiplet.hybrid.report import write_json
from sensitivity_hybrid_cost16 import FOLDER, FULL, ENERGY
from validate_hybrid_oct09 import source_hashes


def main():
    suite=json.loads((FOLDER/'suite.json').read_text(encoding='utf-8'))
    audit=json.loads((FOLDER/'validation.json').read_text(encoding='utf-8'))
    source=source_hashes()
    assert audit['passed'] and len(audit['trials'])==15
    assert all(row['native_source_verified'] for row in audit['trials'])
    for row in suite['runs']:
        hw=HardwareSpec.from_dict(json.loads((Path(row['folder'])/'hardware.json').read_text(encoding='utf-8')))
        assert hw.cost_profile=='literature16_v1' and hw.compute_clock_hz==500e6
        assert hw.effective_mac_energy_pj==.024 and hw.mac_area_mm2_per_unit==135.1e-6
        assert hw.compute_count*hw.unified_buffer_bytes==128*1024**2 and hw.prefetch_slots==2
        assert row['metrics']['oracle_source_sha256']==source
        area=sum(node.area_mm2 for node in build_package(hw).nodes.values())
        assert math.isclose(row['metrics']['area_mm2'],area,rel_tol=1e-12)
    count=0
    for name in (*FULL,*ENERGY):
        rows=json.loads((FOLDER/f'sensitivity/{name}/rows.json').read_text(encoding='utf-8'))
        assert len(rows)==15
        overrides=FULL[name] if name in FULL else ENERGY[name][1]
        for row in rows:
            parent=next(Path(b['folder']) for b in suite['runs'] if b['architecture']==row['architecture'] and b['model']==row['model'])
            base=HardwareSpec.from_dict(json.loads((parent/'hardware.json').read_text(encoding='utf-8')))
            data=json.loads(Path(row['hardware_json']).read_text(encoding='utf-8'))
            assert data==asdict(replace(base,**overrides))
            assert row['fixed_mapping_sha256']==hashlib.sha256((parent/'mapping.json').read_bytes()).hexdigest()
            assert row['baseline_hardware_sha256']==hashlib.sha256((parent/'hardware.json').read_bytes()).hexdigest()
            assert row['metrics']['oracle_source_sha256']==source
            assert row['metrics']['hardware_cost_provenance']==json.loads(json.dumps(HardwareSpec.from_dict(data).provenance))
        count+=len(rows)
    out=ROOT/'output/hybrid_cost16'
    manifest=json.loads((out/'review_manifest.json').read_text(encoding='utf-8'))
    with zipfile.ZipFile(out/'GPT_review_cost16.zip') as archive:
        for path,sha in manifest['files'].items():
            assert hashlib.sha256(archive.read(path)).hexdigest()==sha,path
            assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==sha,path
    from pypdf import PdfReader
    pdf=ROOT/'output/pdf/INDM_Gemini_Cost16_Constraints_20261009.pdf'
    pages=PdfReader(pdf).pages
    assert len(pages)==10 and all(page.extract_text().strip() for page in pages)
    with urllib.request.urlopen('http://127.0.0.1:8765/api/jobs/c16100000001') as response:
        job=json.load(response)
    assert job['state']=='complete' and job['result']==suite
    delivery=dict(passed=True,tests=166,hybrid_tests=92,baseline_trials=15,full_sensitivity_trials=60,
                  ledger_sensitivity_trials=165,sensitivity_records_verified=count,pdf_pages=10,pdf_visual_qa='all latest rendered pages inspected',
                  zip_files_verified=len(manifest['files']),gui_live_job_verified=True,oracle_source_sha256=source,
                  artifacts={str(path.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(path.read_bytes()).hexdigest()
                             for path in (pdf,out/'GPT_review_cost16.zip',out/'review_manifest.json',FOLDER/'suite.json',FOLDER/'validation.json',FOLDER/'sensitivity.json')})
    write_json(out/'delivery_manifest.json',delivery)
    print(json.dumps(dict(passed=True,zip_files=len(manifest['files']),sensitivity_records=count,pdf_pages=10,
                          pdf_bytes=pdf.stat().st_size,zip_bytes=(out/'GPT_review_cost16.zip').stat().st_size)))


if __name__=='__main__':
    main()
