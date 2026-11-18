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


RELEASE_PART_SIZE = 1900 * 1024 * 1024


def split_archive(archive, part_size=RELEASE_PART_SIZE):
    """Split a ZIP for hosting. Return each part's size and checksum in file order."""
    total = archive.stat().st_size
    parts = []
    with archive.open('rb') as source:
        for offset in range(0, total, part_size):
            part = archive.with_name(f'{archive.name}.{len(parts) + 1:02d}')
            size = min(part_size, total - offset)
            digest = hashlib.sha256()
            remaining = size
            with part.open('wb') as target:
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise OSError('The archive ended while splitting it.')
                    target.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
            parts.append({'name': part.name, 'size': size, 'sha256': digest.hexdigest()})
    return parts


def pack(root, output, release_parts=False):
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
        if release_parts and archive.stat().st_size >= 2**31:
            entry['parts'] = split_archive(archive)
            for part in entry['parts']:
                (Path(work) / part['name']).replace(output / part['name'])
            archive.unlink()
        else:
            archive.replace(output / archive.name)
        catalog = Path(work) / f'{name}.json'
        catalog.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        catalog.replace(output / catalog.name)
    return output / (f'{name}.json' if 'parts' in entry else f'{name}.zip')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('region', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--release-parts', action='store_true', help='split ZIPs of 2 GiB or more for GitHub Releases')
    args = parser.parse_args()
    print(pack(args.region, args.out, args.release_parts))


if __name__ == '__main__':
    main()
