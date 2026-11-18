#!/usr/bin/env python3
"""Package a built region for Lastbook Setup. The ZIP and its catalog entry travel together."""

import argparse
import hashlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.setup import install, manifest


def pack(root, output):
    info = install.check_map(root)
    code, title = info.get('name'), info.get('title')
    if (info.get('kind') != 'region' or not isinstance(code, str) or not manifest.REGION_ID.fullmatch(code)
            or not isinstance(title, str) or not title.strip()):
        raise ValueError('Expected a map set from tools/build_region_map.py.')
    output.mkdir(parents=True, exist_ok=True)
    name = f'Lastbook-Map-{code}'
    paths = sorted([*info['files'], 'map-set.json'])
    size = sum((root / path).stat().st_size for path in paths)
    with tempfile.TemporaryDirectory(dir=output) as work:
        archive = Path(work) / f'{name}.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
            for path in paths:
                entry = zipfile.ZipInfo(path)
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = 0o644 << 16
                with (root / path).open('rb') as source, zipped.open(entry, 'w', force_zip64=True) as dest:
                    while chunk := source.read(1024 * 1024):
                        dest.write(chunk)
        install.check_zip(archive, size, install.map_member)
        with archive.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        entry = {'version': 1, 'id': code, 'title': title, 'installed_bytes': size,
                 'file': {'name': archive.name, 'size': archive.stat().st_size, 'sha256': digest}}
        catalog = Path(work) / f'{name}.json'
        catalog.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        archive.replace(output / archive.name)
        catalog.replace(output / catalog.name)
    return output / f'{name}.zip'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('region', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(pack(args.region, args.out))


if __name__ == '__main__':
    main()
