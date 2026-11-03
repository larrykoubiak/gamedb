"""Refresh pinned RetroArch system icons: python scripts/sync_system_icons.py."""
import csv
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import quote
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
REVISION = 'd9f969054dc7fbb6fa89519036d2b971e0855b51'
BASE = f'https://raw.githubusercontent.com/libretro/retroarch-assets/{REVISION}'
ASSETS = ROOT / 'gamedb/explorer/assets'


def icon_filename(theme, name):
    slug = re.sub(r'[^a-z0-9]+', '-', name.casefold()).strip('-')
    digest = hashlib.sha256(name.encode()).hexdigest()[:8]
    return f'{theme}-{slug}-{digest}.png'


def download_icon(source):
    theme, name = source
    if theme not in {'pixel', 'monochrome'} or '/' in name or '\\' in name:
        raise ValueError(f'Invalid icon source: {source}')
    with urlopen(f'{BASE}/xmb/{theme}/png/{quote(name)}.png', timeout=30) as response:
        body = response.read()
    if not body.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError(f'Not a PNG: {source}')
    return icon_filename(theme, name), body


def main():
    with open(ROOT / 'reference/system_icons.csv', newline='', encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream))
    with open(ROOT / 'reference/canonical_systems.csv', newline='', encoding='utf-8-sig') as stream:
        known = {(r['canonical_manufacturer_name'], r['canonical_system_name']) for r in csv.DictReader(stream)}
    mapping, sources = {}, set()
    for row in rows:
        identity = (row['canonical_manufacturer_name'], row['canonical_system_name'])
        key = '\x1f'.join(identity)
        if identity not in known or key in mapping:
            raise ValueError(f'Unknown or duplicate system: {identity}')
        source = (row['icon_theme'], row['icon_name'])
        sources.add(source)
        mapping[key] = icon_filename(*source)
    with ThreadPoolExecutor(max_workers=6) as pool:
        icons = list(pool.map(download_icon, sorted(sources)))
    with urlopen(f'{BASE}/COPYING', timeout=30) as response:
        notice = response.read().decode('utf-8')
    notice = '\n'.join(line.rstrip() for line in notice.splitlines()).rstrip() + '\n'
    destination = ASSETS / 'system-icons'
    destination.mkdir(exist_ok=True)
    for name, body in icons:
        (destination / name).write_bytes(body)
    (ASSETS / 'system-icons.json').write_text(json.dumps(mapping, indent=2, ensure_ascii=False) + '\n')
    (ASSETS / 'system-icon-credits.txt').write_text(
        'Platform icons from RetroArch assets (Libretro contributors), pixel and monochrome themes.\n'
        f'Source: https://github.com/libretro/retroarch-assets/tree/{REVISION}\n'
        'License: Creative Commons Attribution 4.0 International.\n'
        'Artwork files are unchanged. Display size and pixel scaling are set by GameDB CSS.\n\n'
        'The complete upstream license follows:\n\n' + notice)
    print(f'Bundled {len(icons)} icons for {len(mapping)} systems.')


if __name__ == '__main__':
    main()
