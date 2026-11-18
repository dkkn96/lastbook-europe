#!/usr/bin/env python3
"""Builds the manifest the app carries: setup/manifest-v1.json (docs/SETUP-API.md, "The manifest").

  python3 -I -B packaging/release_manifest.py [--packs derived/release/manifest-v1.json] [--out derived/release/setup/manifest-v1.json]
                                              [--measure /path/to/the.gguf] [--small-from derived/release/1.0.0-20261104-1507]

Packs come from derived/release/manifest-v1.json, which session publish-packs writes for each verified pack. The model entry comes
from the supported model registry. memory_bytes is llama.cpp's measure of
the model and its context (device + host bytes from lastbook-llm --measure).
--small-from builds the Small pack's entry from a release folder's SHA256SUMS.txt when the packs file has none (before
publish-packs has written it). Every URL must be on an allowed host (engine/setup/download.py) or the build stops.
The packaging spec bundles the output as setup/manifest-v1.json.
"""
import argparse
import json
import re
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT)]
import llm_local                                   # noqa: E402  (constants only: importing it starts nothing)
from engine.local_models import MODELS, manifest_entry  # noqa: E402
from engine.setup import download, manifest        # noqa: E402

BASE = 'https://downloads.lastbook.org'     # live since 12 Nov 2026; packs and maps are accepted from this host only
SMALL_SUMMARY = 'The essentials: first aid, water, food, shelter and repair, with the maps of this area.'


def measure(gguf):
    runner = llm_local.runner_path()
    if not runner:
        sys.exit('no lastbook-llm runner to measure with')
    out = subprocess.run([str(runner), '--model', str(gguf), '--ctx', str(llm_local.CTX), '--threads', '8', '--measure'],
                         stdin=subprocess.DEVNULL, capture_output=True, timeout=300)
    fit = next(json.loads(l) for l in out.stdout.decode().splitlines() if l.startswith('{"ev":"fit"'))
    return fit['device_bytes'] + fit['host_bytes']


def small_from(folder):
    folder = Path(folder)
    sums = dict(reversed(l.split()) for l in (folder / 'SHA256SUMS.txt').read_text().splitlines() if l.strip())
    z = folder / 'Lastbook-Small.zip'
    with zipfile.ZipFile(z) as zf:
        installed = sum(i.file_size for i in zf.infolist())
        try:
            records = sum(json.loads(zf.read('LastbookData/pack.json')).get('counts', {}).values())
        except (KeyError, ValueError):
            records = None
    return {'id': 'small', 'title': 'Small', 'summary': SMALL_SUMMARY, 'records': records, 'installed_bytes': installed, 'available': True,
            'files': [{'name': z.name, 'url': f'{BASE}/{z.name}', 'size': z.stat().st_size, 'sha256': sums[z.name], 'kind': 'zip'}]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--packs', default=str(ROOT / 'derived' / 'release' / 'manifest-v1.json'))
    ap.add_argument('--out', default=str(ROOT / 'derived' / 'release' / 'setup' / 'manifest-v1.json'))
    ap.add_argument('--measure', help='a copy of the model file to measure memory_bytes from')
    ap.add_argument('--small-from', help='a release folder holding Lastbook-Small.zip and SHA256SUMS.txt')
    a = ap.parse_args()
    try:
        src = json.loads(Path(a.packs).read_text(encoding='utf-8'))
    except FileNotFoundError:
        src = {'version': 1, 'packs': []}
    packs = list(src.get('packs') or [])
    if a.small_from and not any(p.get('id') == 'small' for p in packs):
        packs.insert(0, small_from(a.small_from))
    for p in packs:      # the detailed map a pack already holds ("CA", "us"), from the pack as built, when its entry does not say
        if 'map' not in p:
            try:
                p['map'] = json.loads((ROOT / 'derived' / 'packs' / p['id'] / 'pack.json').read_text(encoding='utf-8')).get('map')
            except (OSError, ValueError):
                pass
    if not packs:
        sys.exit(f'no packs: {a.packs} is missing or empty (publish-packs writes it); --small-from builds Small alone')
    out = {'version': 1, 'published': src.get('published') or time.strftime('%Y-%m-%d'), 'packs': packs, 'maps': list(src.get('maps') or []),
           'address_indexes': list(src.get('address_indexes') or []),
           'models': [manifest_entry(m) for m in MODELS]}
    if a.measure:
        model = next((m for m in out['models'] if m['file'] == Path(a.measure).name), None)
        if not model:
            ap.error('--measure must name a supported model file')
        model['memory_bytes'] = measure(a.measure)
    if manifest.validate(out) is None:
        bad = [f.get('url') for p in packs for f in p.get('files', []) if not download.url_allowed(f.get('url'))]
        sys.exit('the manifest does not pass engine/setup/manifest.validate' + (f'; addresses not allowed: {bad}' if bad else ''))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=1) + '\n', encoding='utf-8')
    print(f'{a.out}: {len(out["maps"])} maps, {len(packs)} packs, {len(out["models"])} models')


if __name__ == '__main__':
    main()
