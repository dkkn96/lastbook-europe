#!/usr/bin/env python3
"""Build a detailed offline map of one region outside the United States from an OpenStreetMap extract.

It writes a map set in the shape of a US state map (packaging/build_packs.py), with the files, tables and classes
the app already reads (docs/MAPS.md):

  <out>/<id>/derived/geo/national.sqlite       feat, feat_idx, poi, meta   streets, water, land, buildings, place
                                                                           labels, sea, and the help points
  <out>/<id>/derived/geo/map.sqlite            the same tables, empty      as in a state map
  <out>/<id>/derived/geo/places.sqlite         place, place_fts            the place finder
  <out>/<id>/derived/geo/national-status.json, socal-cells.json            as in a state map
  <out>/<id>/map-set.json                      name, files, bytes
  <out>/<id>.build.json                        source, dates, counts, sizes and SHA-256 of each file

The rows go in national.sqlite, not map.sqlite, because the engine draws pins from map.sqlite only inside a box
around Southern California (_poi_sources in server.py).

  derived/buildenv/bin/python tools/build_region_map.py thailand-latest.osm.pbf \
      --id TH-10 --name Bangkok --bbox 100.17,13.34,101.09,14.11 --out derived/regions

The only source is the .osm.pbf (OpenStreetMap contributors, ODbL 1.0), which is read and never written.
Nothing is downloaded. It needs pyosmium, as tools/build_coast.py does. The output folder is new each time:
the tool refuses to write into a folder that already holds a map, and it never touches derived/geo/.

What it keeps follows tools/build_map.py (same layers, classes and zoom rules), with three differences:
  - it reads raw OpenStreetMap tags, so it can keep a second name: the local name is the label, and the
    English name (name:en), when there is one, goes into the place finder so either script finds the place;
  - the sea is cut to the region's box, whichever side the sea is on (tools/build_coast.py assumes west);
  - amenity=shelter is kept only when it is not a bus shelter.
A feature that crosses the box is kept whole. Addresses, terrain, crops and the US-only layers are not built.
"""
import argparse
import hashlib
import json
import math
import re
import sqlite3
import sys
import tempfile
import time
from array import array
from pathlib import Path

import osmium

Q = 1e6
ROAD_Z = {'motorway': 5, 'trunk': 6, 'motorway_link': 10, 'trunk_link': 10, 'primary': 8, 'primary_link': 12,
          'secondary': 10, 'secondary_link': 13, 'tertiary': 11, 'tertiary_link': 13, 'residential': 13,
          'unclassified': 13, 'living_street': 14, 'pedestrian': 14, 'busway': 14, 'service': 15,
          'track': 13, 'track_grade1': 13, 'track_grade2': 13, 'track_grade3': 13, 'track_grade4': 13, 'track_grade5': 13,
          'footway': 15, 'path': 14, 'cycleway': 14, 'steps': 16, 'bridleway': 14}
LANDUSE_KEEP = {'park': 'park', 'forest': 'green', 'grass': 'green', 'meadow': 'green', 'scrub': 'green', 'heath': 'green',
                'recreation_ground': 'park', 'cemetery': 'park', 'allotments': 'farm', 'farmland': 'farm',
                'orchard': 'farm', 'vineyard': 'farm', 'farmyard': 'farm', 'residential': 'res', 'commercial': 'com',
                'retail': 'com', 'industrial': 'ind', 'military': 'ind', 'quarry': 'ind', 'landfill': 'ind'}
NATURAL_LAND = {'wood': 'green', 'scrub': 'green', 'heath': 'green', 'grassland': 'green'}
LEISURE_LAND = {'park': 'park', 'garden': 'park', 'recreation_ground': 'park', 'nature_reserve': 'park'}
PLACE_Z = {'city': 6, 'town': 9, 'suburb': 12, 'quarter': 12, 'neighbourhood': 13, 'village': 11, 'hamlet': 14,
           'locality': 14, 'island': 11}
PLACE_RANK = {'city': 1, 'town': 1, 'suburb': 2, 'quarter': 2, 'village': 2, 'neighbourhood': 3, 'hamlet': 3,
              'locality': 3, 'island': 3}
RAIL = {'rail', 'light_rail', 'subway', 'tram', 'monorail', 'narrow_gauge'}
WATERWAY = {'river', 'stream', 'canal', 'drain', 'ditch'}
# Help points: the classes tools/build_map.py keeps (POI_KEEP), found from raw tags.
AMENITY = {'hospital': 'hospital', 'clinic': 'clinic', 'doctors': 'doctors', 'pharmacy': 'pharmacy', 'dentist': 'dentist',
           'veterinary': 'veterinary', 'fire_station': 'fire_station', 'police': 'police',
           'drinking_water': 'drinking_water', 'fountain': 'fountain', 'toilets': 'toilet', 'shelter': 'shelter',
           'community_centre': 'community_centre', 'townhall': 'town_hall', 'school': 'school', 'library': 'library',
           'post_office': 'post_office', 'courthouse': 'courthouse', 'embassy': 'embassy',
           'nursing_home': 'nursing_home', 'kindergarten': 'kindergarten', 'college': 'college',
           'university': 'university', 'fuel': 'fuel'}
SHOP = {'supermarket': 'supermarket', 'convenience': 'convenience', 'doityourself': 'doityourself',
        'hardware': 'hardware', 'garden_centre': 'garden_centre', 'chemist': 'chemist', 'bicycle': 'bicycle_shop',
        'car_repair': 'car_repair'}
MAN_MADE = {'water_tower': 'water_tower', 'water_works': 'water_works', 'wastewater_plant': 'wastewater_plant'}
BUS_SHELTER = {'public_transport', 'bus', 'taxi'}


def poi_class(t):
    a = t.get('amenity')
    if a in AMENITY:
        if a == 'shelter' and t.get('shelter_type') in BUS_SHELTER:
            return None
        return AMENITY[a]
    s = t.get('shop')
    if s in SHOP:
        return SHOP[s]
    m = t.get('man_made')
    if m in MAN_MADE:
        return MAN_MADE[m]
    if m in ('tower', 'mast') and t.get('tower:type') == 'communication':
        return 'comms_tower'
    if t.get('tourism') == 'camp_site':
        return 'camp_site'
    if t.get('natural') == 'spring':
        return 'spring'
    if t.get('office') == 'diplomatic' or t.get('diplomatic') == 'embassy':
        return 'embassy'
    return None


def simplify(flat, tol):
    """Drop points closer than tol (degrees) to the previous kept point; keeps endpoints. As tools/build_map.py."""
    if len(flat) <= 4 or tol <= 0:
        return flat
    out = [flat[0], flat[1]]
    px, py = flat[0], flat[1]
    for i in range(2, len(flat) - 2, 2):
        x, y = flat[i], flat[i + 1]
        if abs(x - px) > tol or abs(y - py) > tol:
            out += [x, y]
            px, py = x, y
    out += [flat[-2], flat[-1]]
    return out


def pack(parts):
    """int32 array: nparts, then for each part npts followed by quantized x,y deltas. As tools/build_map.py."""
    a = array('i', [len(parts)])
    for p in parts:
        n = len(p) // 2
        a.append(n)
        lx = ly = 0
        for i in range(n):
            x, y = int(round(p[2 * i] * Q)), int(round(p[2 * i + 1] * Q))
            a.append(x - lx); a.append(y - ly)
            lx, ly = x, y
    return a.tobytes()


def bounds(parts):
    xs = [v for p in parts for v in p[0::2]]
    ys = [v for p in parts for v in p[1::2]]
    return min(xs), max(xs), min(ys), max(ys)


def area_z(minx, maxx, miny, maxy, base):
    """Small polygons only appear when zoomed in. As tools/build_map.py."""
    size = max(maxx - minx, maxy - miny)
    if size <= 0:
        return 17
    return max(base, min(16, int(math.log2(360 / size)) - 4))


# ------------------------------------------------------------------ the sea
def clip_line(pts, box):
    """The pieces of an open line that lie inside the box, each starting and ending on the box edge where it was cut."""
    w, s, e, n = box

    def inside(p):
        return w <= p[0] <= e and s <= p[1] <= n

    def cross(a, b):
        """Where a->b crosses the box edge, ordered from a."""
        out = []
        dx, dy = b[0] - a[0], b[1] - a[1]
        for edge, d, lo, hi, other in ((w, dx, s, n, 0), (e, dx, s, n, 0), (s, dy, w, e, 1), (n, dy, w, e, 1)):
            if d == 0:
                continue
            t = (edge - a[other]) / d
            if 0 <= t <= 1:
                x, y = a[0] + t * dx, a[1] + t * dy
                v = y if other == 0 else x
                if lo <= v <= hi:
                    out.append((t, (edge, y) if other == 0 else (x, edge)))
        return [p for _, p in sorted(out)]

    pieces, cur = [], None
    for a, b in zip(pts, pts[1:]):
        ia, ib = inside(a), inside(b)
        if ia and cur is None:
            cur = [a]
        if ia and ib:
            cur.append(b)
            continue
        hits = cross(a, b)
        if ia and not ib and hits:
            cur.append(hits[-1])
            pieces.append(cur)
            cur = None
        elif not ia and ib and hits:
            cur = [hits[0], b]
        elif not ia and not ib and len(hits) >= 2:
            pieces.append([hits[0], hits[-1]])
        elif ia and not ib:
            pieces.append(cur)
            cur = None
    if cur and len(cur) > 1:
        pieces.append(cur)
    return [p for p in pieces if len(p) > 1]


def edge_pos(p, box):
    """Distance clockwise round the box edge from its north-west corner, or None if the point is not on the edge."""
    w, s, e, n = box
    x, y = p
    eps = 1e-9
    if abs(y - n) < eps:
        return x - w
    if abs(x - e) < eps:
        return (e - w) + (n - y)
    if abs(y - s) < eps:
        return (e - w) + (n - s) + (e - x)
    if abs(x - w) < eps:
        return 2 * (e - w) + (n - s) + (y - s)
    return None


def sea_rings(pieces, box):
    """Close coastline pieces into sea polygons. OpenStreetMap coastlines keep land on the left and water on the right,
    so from the end of a piece the sea continues clockwise round the box edge to the start of the next piece."""
    w, s, e, n = box
    total = 2 * (e - w) + 2 * (n - s)
    corners = [(0.0, (w, n)), (e - w, (e, n)), (e - w + n - s, (e, s)), (2 * (e - w) + n - s, (w, s))]
    ends = []
    for i, p in enumerate(pieces):
        a, b = edge_pos(p[0], box), edge_pos(p[-1], box)
        if a is not None and b is not None:
            ends.append((i, a, b))
    starts = sorted((a, i) for i, a, _ in ends)
    done, rings = set(), []
    for i, _, _ in ends:
        if i in done:
            continue
        ring, j = [], i
        while j not in done:
            done.add(j)
            ring += pieces[j]
            pos = next(b for k, _, b in ends if k == j)
            nxt = next(((a, k) for a, k in starts if a > pos), None)
            wrap = nxt is None
            if wrap:
                nxt = starts[0]
            stop = nxt[0] + (total if wrap else 0)
            for c, pt in corners + [(c + total, pt) for c, pt in corners]:
                if pos < c < stop:
                    ring.append(pt)
            j = nxt[1]
        ring.append(ring[0])
        rings.append(ring)
    return rings


def chains(ways):
    """Join coastline ways end to start. Returns (closed, points) for each chain."""
    by_start = {}
    for refs, pts in ways:
        by_start.setdefault(refs[0], []).append((refs, pts))
    used, out = set(), []
    ends = {refs[-1] for refs, _ in ways}
    order = sorted(ways, key=lambda w: w[0][0] in ends)  # begin with ways nothing leads into
    for refs, pts in order:
        if id(pts) in used:
            continue
        used.add(id(pts))
        r, p = list(refs), list(pts)
        while r[-1] != r[0]:
            nxt = [w for w in by_start.get(r[-1], []) if id(w[1]) not in used]
            if not nxt:
                break
            used.add(id(nxt[0][1]))
            r += nxt[0][0][1:]
            p += nxt[0][1][1:]
        out.append((r[0] == r[-1], p))
    return out


# ------------------------------------------------------------------ reading the extract
class Region(osmium.SimpleHandler):
    def __init__(self, box, prefer, features, languages=(), buildings=True):
        super().__init__()
        self.box, self.prefer = box, prefer
        self.languages = languages
        self.features, self.buildings = features, buildings
        self.pois, self.places, self.coast = [], [], []

    def touches(self, minx, maxx, miny, maxy):
        w, s, e, n = self.box
        return maxx >= w and minx <= e and maxy >= s and miny <= n

    def names(self, t):
        """Use the local label and include translated names in the place index."""
        local, en = t.get('name'), t.get('name:en')
        translated = [t.get('name:' + language) for language in self.languages]
        label = (en if self.prefer == 'en' else local) or local or en or next((v for v in translated if v), None)
        aliases = dict.fromkeys(v for v in (local, en, *translated) if v and v != label)
        return label, ' · '.join(aliases)

    def add(self, layer, cls, name, minz, parts):
        if parts:
            self.features.add(layer, cls, name, minz, parts)

    def point(self, t, lon, lat):
        cls = poi_class(t)
        if cls:
            label, other = self.names(t)
            self.pois.append((cls, label, other, lon, lat))

    def node(self, n):
        t = n.tags
        if not n.location.valid():
            return
        lon, lat = n.location.lon, n.location.lat
        if not self.touches(lon, lon, lat, lat):
            return
        place = t.get('place')
        if place in PLACE_Z and (names := self.names(t))[0]:
            label, other = names
            z = PLACE_Z[place]
            pop = t.get('population', '')
            if place in ('city', 'town') and pop.isdigit() and int(pop) > 300000:
                z = 5
            self.add('place', place, label, z, [[lon, lat]])
            self.places.append((place, label, other, lon, lat))
        self.point(t, lon, lat)

    def way(self, w):
        t = w.tags
        hw, ww, rw = t.get('highway'), t.get('waterway'), t.get('railway')
        coast = t.get('natural') == 'coastline'
        if not (coast or hw or ww in WATERWAY or rw in RAIL):
            return
        try:
            flat = [v for n in w.nodes for v in (n.lon, n.lat)]
        except osmium.InvalidLocationError:
            return
        if len(flat) < 4 or not self.touches(min(flat[0::2]), max(flat[0::2]), min(flat[1::2]), max(flat[1::2])):
            return
        if coast:
            self.coast.append(([n.ref for n in w.nodes], list(zip(flat[0::2], flat[1::2]))))
            return
        label = self.names(t)[0]
        if hw:
            if hw == 'track' and t.get('tracktype') in ('grade1', 'grade2', 'grade3', 'grade4', 'grade5'):
                hw = 'track_' + t.get('tracktype')
            if hw in ROAD_Z and t.get('area') != 'yes':
                self.add('road', hw, label or t.get('ref'), ROAD_Z[hw], [flat])
        elif ww in WATERWAY:
            self.add('waterway', ww, label, 10 if ww == 'river' else 13, [flat])
        elif rw in RAIL and t.get('service') not in ('yard', 'siding', 'spur'):
            self.add('rail', rw, label, 10 if rw == 'rail' else 13, [flat])

    def area(self, a):
        t = a.tags
        nat, lu, lei = t.get('natural'), t.get('landuse'), t.get('leisure')
        bld = self.buildings and t.get('building')
        cls = poi_class(t)
        water = nat == 'water' or lu in ('reservoir', 'basin') or t.get('waterway') == 'riverbank'
        wet = nat == 'wetland'
        land = LANDUSE_KEEP.get(lu) or NATURAL_LAND.get(nat) or LEISURE_LAND.get(lei)
        park = t.get('boundary') in ('national_park', 'protected_area')
        if not (bld or cls or water or wet or land or park or nat == 'beach'):
            return
        try:
            rings = [[v for n in ring for v in (n.lon, n.lat)] for outer in a.outer_rings() for ring in
                     [outer] + list(a.inner_rings(outer))]
        except osmium.InvalidLocationError:
            return
        rings = [r for r in rings if len(r) >= 8]
        if not rings:
            return
        b = bounds(rings)
        if not self.touches(*b):
            return
        label = self.names(t)[0]
        if cls or nat == 'beach' or lei == 'park':
            kind = cls or ('beach' if nat == 'beach' else 'park')
            lab, other = self.names(t)
            self.pois.append((kind, lab, other, (b[0] + b[1]) / 2, (b[2] + b[3]) / 2))
        if water or wet:
            kind = 'wetland' if wet else ('reservoir' if lu in ('reservoir', 'basin') or t.get('water') == 'reservoir'
                                         else 'river' if t.get('water') in ('river', 'canal') or t.get('waterway') else 'water')
            self.add('wet' if wet else 'water', kind, label, area_z(*b, 7), [simplify(r, 0.00001) for r in rings])
        elif nat == 'beach':
            self.add('beach', 'beach', label, area_z(*b, 10), rings)
        elif bld:
            self.add('bldg', '' if bld == 'yes' else bld, None, 15, [simplify(rings[0], 0.000002)])
        elif park:
            self.add('land', 'park', None, area_z(*b, 8), [simplify(r, 0.00002) for r in rings])
        elif land:
            self.add('land', land, label, area_z(*b, 9), [simplify(r, 0.00001) for r in rings])


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


class Features:
    """Write geometries as osmium emits them so a national extract fits in memory."""

    def __init__(self, db):
        self.db = db
        self.total = 0
        self.layers = {}

    def add(self, layer, cls, name, minz, parts):
        self.total += 1
        self.db.execute('INSERT INTO feat VALUES (?,?,?,?,?,?)', (self.total, layer, cls, name, minz, pack(parts)))
        self.db.execute('INSERT INTO feat_idx VALUES (?,?,?,?,?,?,?)', (self.total, *bounds(parts), minz, 30))
        self.layers[layer] = self.layers.get(layer, 0) + 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('pbf', help='an OpenStreetMap extract (.osm.pbf), for example from download.geofabrik.de')
    ap.add_argument('--id', required=True, help='region id, for example TH-10')
    ap.add_argument('--name', required=True, help='region name in plain words, for example Bangkok')
    ap.add_argument('--bbox', required=True, help='west,south,east,north in degrees')
    ap.add_argument('--out', required=True, help='folder for the output; <out>/<id> must not exist yet')
    ap.add_argument('--prefer', choices=('local', 'en'), default='local',
                    help='which name is the map label when a feature has both (default: the local name)')
    ap.add_argument('--search-language', action='append', default=[], metavar='LANGUAGE',
                    help='index additional name tags, for example --search-language it --search-language fr')
    ap.add_argument('--source', help='source URL for the build report')
    ap.add_argument('--no-buildings', action='store_true', help='leave building outlines out (a smaller file)')
    ap.add_argument('--disk-index', action='store_true', help='put the OSM node location index on disk for large extracts')
    args = ap.parse_args()
    if not re.fullmatch(r'[A-Z]{2}-[A-Z0-9]{1,8}', args.id):
        ap.error('--id must be a country-prefixed regional ID, for example IT-23')
    try:
        west, south, east, north = box = [float(v) for v in args.bbox.split(',')]
    except ValueError:
        ap.error('--bbox must be west,south,east,north')
    if not (-180 <= west < east <= 180 and -85 <= south < north <= 85):
        ap.error('--bbox must be west,south,east,north inside the map extent')
    pbf = Path(args.pbf)
    root = Path(args.out) / args.id
    if root.exists():
        ap.error(f'{root} already exists. Choose another --out.')
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.building-', dir=root.parent) as staging:
        temporary = Path(staging) / root.name
        try:
            report = build(args, box, pbf, temporary)
        except ValueError as exc:
            ap.error(str(exc))
        temporary.rename(root)
    Path(str(root) + '.build.json').write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(report, indent=1, ensure_ascii=False))


def build(args, box, pbf, root):
    t0 = time.time()
    with osmium.io.Reader(str(pbf)) as reader:
        header = reader.header()
        as_of = header.get('osmosis_replication_timestamp') or header.get('timestamp') or ''
    geo = root / 'derived' / 'geo'
    geo.mkdir(parents=True)

    # ---- national.sqlite holds the rows; map.sqlite is the same tables with none, as in a state map
    schema = '''PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
      CREATE TABLE feat(id INTEGER PRIMARY KEY, layer TEXT, cls TEXT, name TEXT, minz INTEGER, geom BLOB);
      CREATE VIRTUAL TABLE feat_idx USING rtree(id, minx, maxx, miny, maxy, minz, maxz);
      CREATE TABLE poi(id INTEGER PRIMARY KEY, cls TEXT, name TEXT, lon REAL, lat REAL);
      CREATE INDEX poi_cls ON poi(cls, lon, lat);
      CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);'''
    dst = sqlite3.connect(geo / 'national.sqlite')
    dst.executescript(schema)
    features = Features(dst)
    h = Region(box, args.prefer, features, args.search_language, buildings=not args.no_buildings)
    index = 'sparse_file_array,' + str(root / 'osm-nodes.idx') if args.disk_index else 'flex_mem'
    try:
        h.apply_file(str(pbf), locations=True, idx=index)
    except BaseException:
        dst.close()
        raise
    if args.disk_index:
        (root / 'osm-nodes.idx').unlink(missing_ok=True)
    if not features.total:
        dst.close()
        raise ValueError('No map features found inside the selected bounds.')
    print('read', features.total, 'features', len(h.pois), 'help points', len(h.places), 'places',
          len(h.coast), 'coast ways', round(time.time() - t0), 's', flush=True)
    # the sea, cut to the box; closed coastline rings inside the box are islands, drawn as land on top
    cs = chains(h.coast)
    pieces = [piece for closed, pts in cs if not closed for piece in clip_line(pts, box)]
    rings = sea_rings(pieces, box)
    islands = [pts for closed, pts in cs if closed]
    for layer, group in (('ocean', rings), ('island', islands)):
        for ring in group:
            flat = [v for p in ring for v in p]
            features.add(layer, layer, None, 0, [flat])
    seen = set()
    pid = 0
    kinds = {}
    for cls, label, other, lon, lat in h.pois:
        key = (cls, label, round(lon, 5), round(lat, 5))
        if key in seen:
            continue
        seen.add(key)
        pid += 1
        dst.execute('INSERT INTO poi VALUES (?,?,?,?,?)', (pid, cls, label, lon, lat))
        kinds[cls] = kinds.get(cls, 0) + 1
    status = {'state': 'complete', 'stage': 'ready', 'features': features.total}
    meta = [('source', f'OpenStreetMap contributors, via {pbf.name} (ODbL 1.0)'), ('data_as_of', as_of),
            ('bounds', ','.join(f'{v:.6f}' for v in box)), ('region', args.id), ('region_name', args.name)]
    # no build time in the files: the same extract and options give the same bytes, so a checksum can be compared
    dst.executemany('INSERT INTO meta VALUES (?,?)', meta + [('status', json.dumps(status))])
    dst.commit()
    dst.execute('VACUUM')
    dst.close()
    empty = sqlite3.connect(geo / 'map.sqlite')
    empty.executescript(schema)
    empty.executemany('INSERT INTO meta VALUES (?,?)', meta)
    empty.commit()
    empty.close()
    (geo / 'national-status.json').write_text(json.dumps(status), encoding='utf-8')
    (geo / 'socal-cells.json').write_text('[]', encoding='utf-8')

    # ---- places.sqlite: the place finder, in the shape tools/build_places.py writes
    db = sqlite3.connect(geo / 'places.sqlite')
    db.executescript('''CREATE TABLE place(id INTEGER PRIMARY KEY, name TEXT, kind TEXT, detail TEXT, lat REAL, lon REAL, rank INTEGER, source TEXT);
      CREATE VIRTUAL TABLE place_fts USING fts5(name, detail, content='place', content_rowid='id', tokenize='unicode61');''')
    ins = 'INSERT INTO place(name,kind,detail,lat,lon,rank,source) VALUES (?,?,?,?,?,?,?)'
    where = f'{args.name} (OpenStreetMap)'
    nplaces = 0
    for place, label, other, lon, lat in h.places:
        db.execute(ins, (label, place, f'{other} · {where}' if other else where, lat, lon, PLACE_RANK[place], 'OpenStreetMap'))
        nplaces += 1
    seen = set()
    for cls, label, other, lon, lat in h.pois:
        key = (cls, label, round(lon, 5), round(lat, 5))
        if not label or key in seen:
            continue
        seen.add(key)
        db.execute(ins, (label, cls.replace('_', ' '), f'{other} · {where}' if other else where, lat, lon, 4, 'OpenStreetMap'))
        nplaces += 1
    db.execute("INSERT INTO place_fts(place_fts) VALUES ('rebuild')")
    db.commit()
    db.execute('VACUUM')
    db.close()

    files = {f'derived/geo/{n}': (geo / n).stat().st_size
             for n in ('national.sqlite', 'map.sqlite', 'places.sqlite', 'national-status.json', 'socal-cells.json')}
    file_digests = {rel: sha256(root / rel) for rel in files}
    (root / 'map-set.json').write_text(json.dumps(
        {'name': args.id, 'title': args.name, 'kind': 'region', 'bounds': box,
         'data_as_of': as_of, 'revision': file_digests['derived/geo/national.sqlite'][:16], 'buildings': 'bldg' in features.layers,
         'files': files, 'bytes': sum(files.values())}, indent=1, ensure_ascii=False),
        encoding='utf-8')
    report = {
        'id': args.id, 'name': args.name, 'bbox': box, 'label_names': args.prefer,
        'source': {'file': pbf.name, 'url': args.source, 'bytes': pbf.stat().st_size, 'sha256': sha256(pbf), 'data_as_of': as_of,
                   'licence': 'ODbL 1.0', 'attribution': '© OpenStreetMap contributors'},
        'features': features.layers, 'help_points': dict(sorted(kinds.items())), 'help_points_total': pid, 'place_finder_rows': nplaces,
        'files': {rel: {'bytes': size, 'sha256': file_digests[rel]} for rel, size in files.items()},
        'not_built': ['addresses', 'terrain', 'crops', 'water.sqlite', 'atlas.sqlite',
                      'building footprints' if args.no_buildings else 'buildings.sqlite (outlines are in national.sqlite)'],
        'built': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'seconds': round(time.time() - t0)}
    return report


if __name__ == '__main__':
    main()
