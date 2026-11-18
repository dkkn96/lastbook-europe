#!/usr/bin/env python3
"""Verify country sidecars against GitHub's asset digests and write the app catalog."""

import argparse
import hashlib
import json
import re
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def record_country(code, config, tag, assets, folder):
    region = code + '-ALL'
    stem = 'Lastbook-Map-' + region

    def metadata(name):
        payload = (folder / name).read_bytes()
        asset = assets[name]
        require(len(payload) == asset['size'] and 'sha256:' + hashlib.sha256(payload).hexdigest() == asset['digest'],
                f'{name}: asset checksum does not match')
        return json.loads(payload)

    entry = metadata(stem + '.json')
    report = metadata(region + '.build.json')
    require(entry['version'] == 1 and entry['id'] == report['id'] == region, f'{code}: invalid region')
    require(entry['title'] == report['name'] == config['name'] and report['bbox'] == config['bbox'],
            f'{code}: name or bounds changed')
    require(report['features']['road'] > 0 and report['place_finder_rows'] > 0 and report['help_points_total'] > 0,
            f'{code}: incomplete map')
    require(report['source']['data_as_of'] and report['source']['licence'] == 'ODbL 1.0', f'{code}: missing provenance')
    whole = entry['file']
    parts = entry.get('parts') or [whole]
    require(whole['name'] == stem + '.zip' and whole['size'] == sum(part['size'] for part in parts), f'{code}: invalid archive')
    require(isinstance(entry['installed_bytes'], int) and entry['installed_bytes'] > 0, f'{code}: invalid installed size')
    for index, part in enumerate(parts, 1):
        name = whole['name'] if len(parts) == 1 else f"{whole['name']}.{index:02d}"
        asset = assets[name]
        require(part['name'] == name and 0 < part['size'] == asset['size'] < 2**31
                and 'sha256:' + part['sha256'] == asset['digest'], f'{code}: archive checksum or size does not match')
    return (region, entry['title'], tag, entry['installed_bytes'],
            tuple((x['name'], x['size'], x['sha256']) for x in parts))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('release', type=Path, help='release metadata from the GitHub REST API')
    parser.add_argument('metadata', type=Path, help='downloaded sidecars and reports')
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    configs = json.loads(Path(__file__).with_name('european_countries.json').read_text())
    release = json.loads(args.release.read_text())
    tag = release['tag_name']
    require(re.fullmatch(r'maps-europe-[0-9]{8}', tag), 'Expected a country map pack release')
    assets = {a['name']: a for a in release['assets'] if a['state'] == 'uploaded'}
    rows = [record_country(code, configs[code], tag, assets, args.metadata) for code in sorted(configs)
            if f'Lastbook-Map-{code}-ALL.json' in assets]
    require(rows, 'The release has no verified country packs')
    missing = sorted(configs.keys() - {row[0][:2] for row in rows})
    content = ['"""Country packs recorded from the verified GitHub release assets."""', '', 'PACKS = (']
    for region, title, release_tag, size, parts in rows:
        content.append(f'    ({region!r}, {title!r}, {release_tag!r}, {size:_}, (')
        content.extend(f'        ({name!r}, {size:_}, {digest!r}),' for name, size, digest in parts)
        content.append('    )),')
    args.out.write_text('\n'.join([*content, ')', '']), encoding='utf-8')
    print(f'{len(rows)} verified country packs. Missing: {", ".join(missing) or "none"}')


if __name__ == '__main__':
    main()
