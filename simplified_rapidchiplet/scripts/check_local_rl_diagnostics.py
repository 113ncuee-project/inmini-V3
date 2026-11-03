"""Read-only physical/accounting/source audit; does not start any oracle."""
import argparse
import json
from pathlib import Path
from analyze_local_rl_diagnostics import analyze

if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--out',required=True,type=Path)
    result=analyze(parser.parse_args().out)
    print(json.dumps(result,indent=2,ensure_ascii=False))
    raise SystemExit(bool(result['errors']))
