"""Create a new, reproducible source snapshot without modifying existing runs."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = Path(args.out).resolve()
    if output.exists():
        raise ValueError('snapshot destination already exists; choose a new directory')
    files = list(root.glob('*.py')) + list(root.glob('requirements*.txt'))
    for directory, patterns in (('simple_rapidchiplet', ('*.py',)), ('tests', ('*.py',)),
                                ('scripts', ('*.py',)), ('configs', ('*.json',)),
                                ('gui', ('*.js', '*.html', '*.css'))):
        for pattern in patterns:
            files.extend((root / directory).rglob(pattern))
    manifest = {}
    for path in sorted(set(files)):
        relative = path.relative_to(root)
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        manifest[relative.as_posix()] = hashlib.sha256(target.read_bytes()).hexdigest()
    identity = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    (output / 'snapshot_manifest.json').write_text(json.dumps({
        'identity': identity, 'files': manifest, 'python': sys.version,
        'scope': 'immutable experiment source copy; excludes venv, git, credentials and result files'
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'snapshot': str(output), 'identity': identity, 'files': len(manifest)}))


if __name__ == '__main__':
    main()
