#!/usr/bin/env python3
"""Check a region map built by tools/build_region_map.py, and show that the engine can use it with no network.

  python3 tools/check_region_map.py derived/regions/TH-10
  python3 tools/check_region_map.py derived/regions/TH-10 --engine --find Siriraj --find สยาม --near 13.7649,100.5383

Without --engine it reads the files only:
  - map-set.json lists every file at its real size, and only map files (GEO_FILES in packaging/scan_pack.py);
  - <folder>.build.json, when it is there, has the same SHA-256 for each file;
  - the tables and columns are the ones docs/MAPS.md describes, and every help-point class is one the engine
    names (HELP in server.py);
  - features, help points and place-finder rows exist and lie in or near the region's box;
  - the place finder's index answers a search.

With --engine it copies the map into a fresh data folder with an empty library, blocks every outgoing connection in
this process, loads server.py and asks it for a map tile, the pins, the nearest help points and a place search: the
same calls the app makes. Nothing is written into the region folder or into derived/geo/.

Exit status 0 when every check passes. It needs no extra packages.
"""
import argparse
import hashlib
import json
import math
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GEO_FILES = {'national.sqlite', 'map.sqlite', 'water.sqlite', 'terrain.sqlite', 'buildings.sqlite', 'crops.sqlite',
             'places.sqlite', 'national-status.json', 'socal-cells.json'}
MAP_TABLES = {'feat': ['id', 'layer', 'cls', 'name', 'minz', 'geom'], 'poi': ['id', 'cls', 'name', 'lon', 'lat'],
              'meta': ['key', 'value']}
LAYERS = {'water', 'wet', 'beach', 'land', 'waterway', 'rail', 'road', 'bldg', 'place', 'ocean', 'island'}
fails = []


def check(ok, text):
    print(('ok    ' if ok else 'FAIL  ') + text)
    if not ok:
        fails.append(text)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def help_classes():
    """The classes server.py has a plain name for, read from its source so this tool needs no import for the file checks."""
    text = (REPO / 'server.py').read_text(encoding='utf-8')
    start = text.index('HELP = {')
    return set(eval(text[start + 7:text.index('}', start) + 1]))  # a literal dict of strings in our own file


def read_files(root):
    info = json.loads((root / 'map-set.json').read_text(encoding='utf-8'))
    files = info.get('files', {})
    check(bool(info.get('name')) and bool(files), f"map-set.json names the region ({info.get('name')}) and lists {len(files)} files")
    for rel, size in files.items():
        p = root / rel
        parts = rel.split('/')
        check(parts[:2] == ['derived', 'geo'] and len(parts) == 3 and parts[2] in GEO_FILES, f'{rel} is a map file')
        check(p.is_file() and p.stat().st_size == size, f'{rel} is there at {size:,} bytes')
    on_disk = {str(p.relative_to(root)).replace(os.sep, '/') for p in root.rglob('*') if p.is_file()} - {'map-set.json'}
    check(on_disk == set(files), 'the folder holds nothing map-set.json does not list')
    check(info.get('bytes') == sum(files.values()), 'map-set.json adds the sizes up correctly')
    report = Path(str(root) + '.build.json')
    if report.exists():
        built = json.loads(report.read_text(encoding='utf-8'))
        for rel, want in built['files'].items():
            check(sha256(root / rel) == want['sha256'], f'{rel} has the SHA-256 in {report.name}')
    else:
        print(f'note  no {report.name}: checksums not compared')
    return info


def read_map(root):
    geo = root / 'derived' / 'geo'
    db = sqlite3.connect(f'file:{geo / "national.sqlite"}?mode=ro', uri=True)
    for table, cols in MAP_TABLES.items():
        got = [r[1] for r in db.execute(f'PRAGMA table_info({table})')]
        check(got == cols, f'national.sqlite {table} has columns {", ".join(cols)}')
    meta = dict(db.execute('SELECT key,value FROM meta'))
    box = [float(v) for v in meta['bounds'].split(',')]
    w, s, e, n = box
    check(all(k in meta for k in ('source', 'data_as_of', 'bounds', 'region')), 'meta gives the source, its date, the box and the region')
    check('OpenStreetMap' in meta.get('source', '') and 'ODbL' in meta.get('source', ''), 'meta credits OpenStreetMap and names the ODbL')
    layers = dict(db.execute('SELECT layer,COUNT(*) FROM feat GROUP BY layer'))
    check(set(layers) <= LAYERS, f'feature layers are ones the tile code draws: {layers}')
    check(layers.get('road', 0) > 0, f"there are roads ({layers.get('road', 0):,})")
    check(layers.get('place', 0) > 0, f"there are place labels ({layers.get('place', 0):,})")
    nfeat = db.execute('SELECT COUNT(*) FROM feat').fetchone()[0]
    check(db.execute('SELECT COUNT(*) FROM feat_idx').fetchone()[0] == nfeat, 'every feature is in the spatial index')
    tol = 0.001  # the index stores 32-bit numbers, and outlines are simplified, so an edge feature can sit a hair outside
    out = db.execute('SELECT COUNT(*) FROM feat_idx WHERE maxx<? OR minx>? OR maxy<? OR miny>?', (w - tol, e + tol, s - tol, n + tol)).fetchone()[0]
    check(out == 0, 'every feature touches the box (to 0.001 degrees)')
    kinds = dict(db.execute('SELECT cls,COUNT(*) FROM poi GROUP BY cls'))
    check(sum(kinds.values()) > 0, f'there are help points ({sum(kinds.values()):,} in {len(kinds)} classes)')
    unknown = set(kinds) - help_classes()
    check(not unknown, 'every help-point class has a name in server.py' + (f' (unknown: {sorted(unknown)})' if unknown else ''))
    pad = 0.5
    far = db.execute('SELECT COUNT(*) FROM poi WHERE lon<? OR lon>? OR lat<? OR lat>?', (w - pad, e + pad, s - pad, n + pad)).fetchone()[0]
    check(far == 0, 'every help point is in or near the box')
    status = json.loads((geo / 'national-status.json').read_text(encoding='utf-8'))
    check(status.get('state') == 'complete' and status.get('features') == nfeat, 'national-status.json says complete, with the feature count')
    check(json.loads((geo / 'socal-cells.json').read_text(encoding='utf-8')) == [], 'socal-cells.json is an empty list')
    empty = sqlite3.connect(f'file:{geo / "map.sqlite"}?mode=ro', uri=True)
    check(empty.execute('SELECT (SELECT COUNT(*) FROM feat)+(SELECT COUNT(*) FROM poi)').fetchone()[0] == 0, 'map.sqlite has the tables and no rows')
    pl = sqlite3.connect(f'file:{geo / "places.sqlite"}?mode=ro', uri=True)
    got = [r[1] for r in pl.execute('PRAGMA table_info(place)')]
    check(got == ['id', 'name', 'kind', 'detail', 'lat', 'lon', 'rank', 'source'], 'places.sqlite place has the place finder\'s columns')
    rows = pl.execute('SELECT COUNT(*) FROM place').fetchone()[0]
    check(rows > 0, f'the place finder has rows ({rows:,})')
    name = pl.execute("SELECT name FROM place WHERE rank=1 AND name<>'' LIMIT 1").fetchone() or pl.execute("SELECT name FROM place LIMIT 1").fetchone()
    word = name[0].split()[0].replace('"', '')
    hit = pl.execute('SELECT COUNT(*) FROM place_fts WHERE place_fts MATCH ?', (f'"{word}"*',)).fetchone()[0]
    check(hit > 0, f'the place finder\'s index finds "{word}" ({hit})')
    return box


def tile_of(lon, lat, z):
    n = 2 ** z
    y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    return int((lon + 180) / 360 * n), int(y)


def with_engine(root, box, finds, near):
    work = Path(tempfile.mkdtemp(prefix='lastbook-region-check-'))
    try:
        shutil.copytree(root, work, dirs_exist_ok=True)
        (work / 'library-data').mkdir()
        (work / 'library-data' / 'catalog.json').write_text('[]', encoding='utf-8')
        os.environ['LASTBOOK_DATA'] = str(work)
        import socket

        def refuse(*a, **k):
            raise OSError('check_region_map.py blocks every connection')
        socket.socket.connect = refuse
        socket.socket.connect_ex = refuse
        socket.create_connection = refuse
        sys.path.insert(0, str(REPO))
        import server
        check(Path(server.HERE).resolve() == work.resolve(), 'the engine is reading the copy, with an empty library')
        lon, lat = (near[1], near[0]) if near else ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
        for z in (10, 13, 16):
            x, y = tile_of(lon, lat, z)
            layers = json.loads(server.map_tile(z, x, y)).get('layers', {})
            check('road' in layers, f'tile {z}/{x}/{y} draws: ' + ', '.join(f'{k} {len(v)}' for k, v in layers.items()))
        d = 0.1
        got = server.pins(lon - d, lat - d, lon + d, lat + d, 12, ['hospital', 'clinic', 'pharmacy', 'police', 'fire_station'])
        check(len(got.get('points', [])) > 0, f"pins near {lat:.4f},{lon:.4f}: {len(got.get('points', []))} groups")
        close = server.near(lat, lon, ['hospital', 'pharmacy', 'police'], 3)
        check(len(close) > 0, 'nearest help: ' + '; '.join(f"{p['label']} {p['name'] or '(no name)'} {p['km']} km" for p in close[:4]))
        for q in finds:
            res = server.places(q)
            check(len(res) > 0, f'place search "{q}": ' + '; '.join(f"{p['name']} ({p['kind']})" for p in res[:3]))
        info = server.map_contents()
        check(bool(info['layers']) and info['bounds'] is not None, f"the app is told the map holds {len(info['layers'])} kinds, within {[round(v, 2) for v in info['bounds']]}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('region', help='the folder tools/build_region_map.py wrote, for example derived/regions/TH-10')
    ap.add_argument('--engine', action='store_true', help='also load server.py on a copy, with connections blocked')
    ap.add_argument('--find', action='append', default=[], help='with --engine: a place to search for (may be given more than once)')
    ap.add_argument('--near', help='with --engine: lat,lon to ask around (default: the middle of the box)')
    args = ap.parse_args()
    root = Path(args.region).resolve()
    read_files(root)
    box = read_map(root)
    if args.engine:
        with_engine(root, box, args.find, [float(v) for v in args.near.split(',')] if args.near else None)
    print(f'\n{len(fails)} failed' if fails else '\nall checks passed')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
