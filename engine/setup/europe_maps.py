"""The fork's published map packs, pinned independently of the upstream manifest."""

from .published_countries import PACKS as COUNTRY_PACKS

BASE = 'https://github.com/dkkn96/lastbook-europe/releases/download'
ITALIAN_PACKS = (
    ('IT-ALL', 'Italia', 'v0.1.0-alpha.2', 1_172_313_088, 3_025_703_416,
     '26cb807dfcf8ed6846f74c930ae27f502ced6f0e01188570665e723a8b587698'),
    ('IT-23', 'Valle d’Aosta / Vallée d’Aoste', 'v0.1.0-alpha.1', 13_633_590, 38_269_429,
     'a8a0d43b6f03cf149859b449c12e30010d3168270121b0f4d8033380bcd209be'),
)


def entries():
    italian = ((code, title, tag, installed, ((f'Lastbook-Map-{code}.zip', size, digest),))
               for code, title, tag, size, installed, digest in ITALIAN_PACKS)
    for code, title, tag, installed, parts in (*italian, *COUNTRY_PACKS):
        files = [{'name': name, 'url': f'{BASE}/{tag}/{name}', 'size': size, 'sha256': digest, 'kind': 'zip'}
                 for name, size, digest in parts]
        yield {'id': code, 'title': title, 'kind': 'region', 'available': True,
               'includes': '', 'installed_bytes': installed, 'download_bytes': sum(f['size'] for f in files),
               'multipart': len(files) > 1, 'files': files}


IDS = frozenset(entry['id'] for entry in entries())
URLS = frozenset(file['url'] for entry in entries() for file in entry['files'])
