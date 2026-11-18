"""The fork's published map packs, pinned independently of the upstream manifest."""

BASE = 'https://github.com/dkkn96/lastbook-europe/releases/download'
PACKS = (
    ('IT-ALL', 'Italia', 'v0.1.0-alpha.2', 1_172_313_088, 3_025_703_416,
     '26cb807dfcf8ed6846f74c930ae27f502ced6f0e01188570665e723a8b587698'),
    ('IT-23', 'Valle d’Aosta / Vallée d’Aoste', 'v0.1.0-alpha.1', 13_633_590, 38_269_429,
     'a8a0d43b6f03cf149859b449c12e30010d3168270121b0f4d8033380bcd209be'),
)
IDS = frozenset(entry[0] for entry in PACKS)


def entries():
    for code, title, tag, size, installed, digest in PACKS:
        name = f'Lastbook-Map-{code}.zip'
        yield {'id': code, 'title': title, 'kind': 'region', 'available': True,
               'includes': '', 'installed_bytes': installed, 'download_bytes': size,
               'files': [{'name': name, 'url': f'{BASE}/{tag}/{name}', 'size': size,
                          'sha256': digest, 'kind': 'zip'}]}


URLS = frozenset(entry['files'][0]['url'] for entry in entries())
