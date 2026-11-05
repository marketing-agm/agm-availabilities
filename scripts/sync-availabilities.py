#!/usr/bin/env python3
"""sync-availabilities.py — refresh agmListings in index.html from AppFolio.

    python3 scripts/sync-availabilities.py --dry-run    # change report only
    python3 scripts/sync-availabilities.py              # apply + rebuild listings.json

Why this is a script and not a prompt
-------------------------------------
This used to be prose in UPDATE_PROMPT.md with literal CSS selectors and a
hardcoded copy of every property's neighborhood, coordinates and website.
Both drifted:

  * AppFolio widened its class attributes, so `class="js-listing-blurb-rent"`
    stopped matching `class="sidebar__price rent-banner__text js-listing-blurb-rent"`.
    An exact-match regex then returns nothing and every rent silently becomes 0.
  * The property tables in the doc fell behind index.html, listing properties
    AGM no longer has and missing ones it does.

So: match on "class contains", and read every property mapping out of
index.html, which is the actual source of truth. Nothing to keep in sync.

Safety
------
The old failure mode was writing bad data quietly. This one refuses to write
when anything looks wrong — too few listings, too many missing rents, an
unrecognised property, a lost Quil placeholder — and says which. A non-zero
exit means nothing was changed.
"""

import argparse
import json
import html as htmllib
import os
import re
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, 'index.html')
FEED = 'https://agmrealestategroup.appfolio.com/listings'
QUIL = 'Quil Creek Crossing Apartments'
MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

# A feed this much smaller than what we already publish is a red flag, not a
# quiet week. Raise deliberately if AGM really does shrink the portfolio.
MIN_LISTINGS = 40
MAX_MISSING_RENT_RATIO = 0.10


class SyncError(Exception):
    pass


# ---------------------------------------------------------------- helpers
def clean(fragment):
    return re.sub(r'\s+', ' ', htmllib.unescape(re.sub(r'<[^>]+>', '', fragment))).strip()


def normalise_date(value):
    value = (value or '').strip()
    if not value:
        return ''
    if value.upper() == 'NOW':
        return 'Now'
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{2,4})$', value)
    if not m:
        return value
    month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return '%s %02d, %d' % (MONTHS[month - 1], day, year + 2000 if year < 100 else year)


def host_of(url):
    return re.sub(r'^https?://(www\.)?|/.*$', '', (url or '').strip().lower())


# ------------------------------------------------------- index.html reads
def read_index():
    html = open(INDEX, encoding='utf-8').read()
    m = re.search(r'const agmListings = (\[[\s\S]*?\n\s*\]);', html)
    if not m:
        raise SyncError('could not find the agmListings array in index.html')
    listings = json.loads(m.group(1))

    def obj(name):
        om = re.search(r'const ' + name + r' = (\{[\s\S]*?\n        \});', html)
        if not om:
            raise SyncError('could not find %s in index.html' % name)
        return dict(re.findall(r'"([^"]+)":\s*"([^"]*)"', om.group(1)))

    websites = obj('propertyWebsites')
    neighborhoods, short_names = {}, {}
    for l in listings:
        neighborhoods.setdefault(l['property'], l['neighborhood'])
        sm = re.match(r'^(?:Studio|\d+ Bedrooms?) \| (.+)$', l['title'])
        if sm:
            short_names.setdefault(l['property'], sm.group(1))
    return html, listings, websites, neighborhoods, short_names


# --------------------------------------------------------------- parsing
def parse_feed(doc):
    blocks = doc.split('<div class="listing-item result js-listing-item"')[1:]
    if not blocks:
        raise SyncError('no listing blocks found — AppFolio markup has changed, '
                        'or the page did not load')

    def detail(block, label):
        m = re.search(r'<dt class="detail-box__label">\s*' + re.escape(label) +
                      r'\s*</dt>\s*<dd class="detail-box__value[^"]*"[^>]*>(.*?)</dd>',
                      block, re.S | re.I)
        return clean(m.group(1)) if m else None

    def by_class(block, cls):
        # "contains", not "equals" — AppFolio adds utility classes freely.
        m = re.search(r'class="[^"]*\b' + re.escape(cls) + r'\b[^"]*"[^>]*>(.*?)</', block, re.S)
        return clean(m.group(1)) if m else None

    rows = []
    for block in blocks:
        tm = re.search(r'<h2 class="listing-item__title js-listing-title">\s*'
                       r'<a href="/listings/detail/([0-9a-f-]+)"[^>]*>(.*?)</a>', block, re.S)
        if not tm:
            raise SyncError('a listing block has no title/UUID link — markup has changed')
        uuid, title = tm.group(1), clean(tm.group(2))

        rent_txt = detail(block, 'RENT') or by_class(block, 'js-listing-blurb-rent') or ''
        rv = re.search(r'\$([\d,]+)', rent_txt)
        rent = int(rv.group(1).replace(',', '')) if rv else 0

        bb = detail(block, 'Bed / Bath') or by_class(block, 'js-listing-blurb-bed-bath') or ''
        if re.search(r'studio', bb, re.I):
            bedrooms = 'Studio'
        else:
            bm = re.search(r'([\d.]+)\s*bd', bb, re.I)
            bedrooms = int(float(bm.group(1))) if bm else None
        bam = re.search(r'([\d.]+)\s*ba', bb, re.I)

        sq_txt = detail(block, 'Square Feet')
        if sq_txt is None:
            sm = re.search(r'js-listing-square-feet[^>]*>\s*Square Feet:\s*([\d,]+)', block)
            sq_txt = sm.group(1) if sm else ''
        sm2 = re.search(r'([\d,]+)', sq_txt or '')

        am = re.search(r'<dd class="detail-box__value js-listing-available"[^>]*>(.*?)</dd>', block, re.S)
        dm = re.search(r'js-listing-description"[^>]*>(.*?)</p>', block, re.S)
        site = re.search(r'href="(https?://[^"]+)"', dm.group(1)) if dm else None

        rows.append({
            'uuid': uuid,
            'title': title,
            'address': by_class(block, 'js-listing-address') or '',
            'rent': rent,
            'bedrooms': bedrooms,
            'bathrooms': float(bam.group(1)) if bam else 1.0,
            'sqft': int(sm2.group(1).replace(',', '')) if sm2 else 0,
            'available': normalise_date(clean(am.group(1)) if am else ''),
            'is_mfte': bool(re.search(r'MFTE', title, re.I)),
            'site': site.group(1) if site else '',
            'description': clean(dm.group(1)) if dm else '',
        })
    return rows


# ---------------------------------------------------------- property map
def build_matcher(websites, neighborhoods):
    by_host = {host_of(u): n for n, u in websites.items() if 'appfolio.com' not in u}
    # Longest names first so "Magnolia Crestview" wins over "Crestview".
    names = sorted(neighborhoods, key=len, reverse=True)

    def match(row):
        # The description always links the property's own site. AppFolio
        # titles are free-text marketing copy and often omit the name
        # entirely, so the link is the dependable signal.
        host = host_of(row['site'])
        if host and host in by_host:
            return by_host[host]
        # Full names first, across every field, before falling back to
        # shortened ones. Otherwise "Crestview Townhomes" shortens to
        # "Crestview" and swallows Magnolia Crestview's units.
        for field in (row['title'], row['description'], row['address']):
            for name in names:
                if name != QUIL and re.search(r'\b' + re.escape(name), field, re.I):
                    return name
        for field in (row['title'], row['description'], row['address']):
            for name in names:
                if name == QUIL:
                    continue
                short = re.sub(r'\s+(Apartments|Townhomes|Court|Quads|Villa)$', '', name)
                if short != name and re.search(r'\b' + re.escape(short) + r'\b', field, re.I):
                    return name
        return None

    return match


def unit_from(address):
    for pattern in (r'\bApt\s+([A-Za-z0-9-]+)', r'\bUnit\s+([A-Za-z0-9-]+)', r'#\s*([A-Za-z0-9-]+)'):
        m = re.search(pattern, address, re.I)
        if m:
            return m.group(1)
    return 'Not Specified'


def bed_label(bedrooms):
    if bedrooms == 'Studio':
        return 'Studio'
    return '1 Bedroom' if bedrooms == 1 else '%d Bedrooms' % bedrooms


def to_listing(row, prop, neighborhoods, short_names):
    return {
        'property': prop,
        'neighborhood': neighborhoods[prop],
        'unit': unit_from(row['address']),
        'title': '%s | %s' % (bed_label(row['bedrooms']), short_names.get(prop, prop)),
        'bedrooms': row['bedrooms'],
        'bathrooms': float(row['bathrooms']),
        'rent': row['rent'],
        'sqft': row['sqft'],
        'available': row['available'],
        'address': row['address'],
        'features': ['On-Site Laundry'] + (['MFTE/MHA'] if row['is_mfte'] else []),
        'detailsUrl': 'https://agmrealestategroup.appfolio.com/listings/detail/' + row['uuid'],
        'applyUrl': ('https://agmrealestategroup.appfolio.com/listings/rental_applications/'
                     'new?listable_uid=%s&source=Website' % row['uuid']),
    }


# --------------------------------------------------------------- reports
def uid_of(listing):
    m = re.search(r'/detail/([0-9a-f-]+)', listing.get('detailsUrl') or '')
    return m.group(1) if m else listing.get('detailsUrl')


def change_report(current, new):
    before = {uid_of(l): l for l in current if l['property'] != QUIL}
    after = {uid_of(l): l for l in new}
    added = [after[k] for k in after if k not in before]
    removed = [before[k] for k in before if k not in after]
    changed = []
    for k in after:
        if k in before:
            diff = {f: (before[k].get(f), after[k].get(f))
                    for f in ('rent', 'available', 'sqft', 'bedrooms', 'bathrooms', 'unit', 'property')
                    if before[k].get(f) != after[k].get(f)}
            if diff:
                changed.append((after[k], diff))

    def money(v):
        return '$%s' % format(v, ',') if v else 'Call'

    lines = ['ADDED (%d)' % len(added)]
    for l in sorted(added, key=lambda x: (x['property'], x['unit'])):
        lines.append('  + %-30s %-14s %-8s %s' % (l['property'], l['unit'], money(l['rent']), l['available']))
    lines.append('REMOVED (%d)' % len(removed))
    for l in sorted(removed, key=lambda x: (x['property'], x['unit'])):
        lines.append('  - %-30s %-14s %-8s %s' % (l['property'], l['unit'], money(l['rent']), l['available']))
    lines.append('CHANGED (%d)' % len(changed))
    for l, diff in sorted(changed, key=lambda x: (x[0]['property'], x[0]['unit'])):
        detail = '; '.join('%s %s -> %s' % (f, a, b) for f, (a, b) in sorted(diff.items()))
        lines.append('  ~ %-30s %-14s %s' % (l['property'], l['unit'], detail))
    return '\n'.join(lines), len(added), len(removed), len(changed)


# ----------------------------------------------------------------- write
def unit_sort_key(unit):
    m = re.match(r'^(\d+)', str(unit))
    return (0, int(m.group(1)), str(unit)) if m else (1, 0, str(unit))


FIELD_ORDER = ['property', 'neighborhood', 'unit', 'title', 'bedrooms', 'bathrooms',
               'rent', 'sqft', 'available', 'address', 'features', 'detailsUrl', 'applyUrl']


def write_index(html, merged):
    m = re.search(r'(const agmListings = \[\n)(.*?)(\n        \];)', html, re.S)
    body = ',\n'.join(
        '            ' + json.dumps({k: l[k] for k in FIELD_ORDER if k in l}, ensure_ascii=False)
        for l in merged)
    open(INDEX, 'w', encoding='utf-8').write(html[:m.start(2)] + body + html[m.end(2):])


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='report changes, write nothing')
    ap.add_argument('--from-file', help='parse a saved copy of the feed instead of fetching')
    args = ap.parse_args()

    html, current, websites, neighborhoods, short_names = read_index()

    if args.from_file:
        doc = open(args.from_file, encoding='utf-8', errors='replace').read()
    else:
        print('fetching %s ...' % FEED)
        with urllib.request.urlopen(FEED, timeout=120) as r:
            doc = r.read().decode('utf-8', 'replace')

    rows = parse_feed(doc)
    print('feed listings: %d' % len(rows))

    if len(rows) < MIN_LISTINGS:
        raise SyncError('only %d listings in the feed (floor is %d). Refusing to publish '
                        'what is probably a partial page.' % (len(rows), MIN_LISTINGS))

    missing_rent = [r for r in rows if not r['rent']]
    if len(missing_rent) > MAX_MISSING_RENT_RATIO * len(rows):
        raise SyncError('%d of %d listings have no rent. That is the signature of a selector '
                        'that no longer matches, not of real "Call for price" units.'
                        % (len(missing_rent), len(rows)))
    for r in missing_rent:
        print('  note: no published rent (renders as "Call"): %s | %s' % (r['title'][:50], r['address'][:40]))

    bad = [r for r in rows if r['bedrooms'] is None or not r['available'] or not r['address']]
    if bad:
        raise SyncError('%d listings are missing bed/bath, availability or address, e.g. %s'
                        % (len(bad), bad[0]['title'][:60]))

    match = build_matcher(websites, neighborhoods)
    new, unknown = [], []
    for r in rows:
        prop = match(r)
        if not prop:
            unknown.append('%s  ||  %s' % (r['title'][:60], r['address'][:45]))
        else:
            new.append(to_listing(r, prop, neighborhoods, short_names))
    if unknown:
        raise SyncError('listings for a property this app does not know:\n   ' +
                        '\n   '.join(unknown) +
                        '\n   Add it to agmListings, propertyCoordinates, propertyWebsites and '
                        'propertyLeasingAgents in index.html first, then rerun.')

    quil = [l for l in current if l['property'] == QUIL]
    if len(quil) != 3:
        raise SyncError('expected 3 Quil Creek Crossing placeholders in index.html, found %d. '
                        'They are maintained by hand and are not in the feed.' % len(quil))

    report, n_add, n_rm, n_ch = change_report(current, new)
    print()
    print(report)
    print()
    print('result: %d feed listings + %d Quil placeholders = %d' % (len(new), len(quil), len(new) + len(quil)))

    gone = {l['property'] for l in current if l['property'] != QUIL} - {l['property'] for l in new}
    fresh = {l['property'] for l in new} - {l['property'] for l in current}
    if gone:
        print('properties with no listings today (kept in the supporting objects): %s' % ', '.join(sorted(gone)))
    if fresh:
        print('properties back in the feed: %s' % ', '.join(sorted(fresh)))
    if gone or fresh:
        print('NOTE: propertyCoordinates changed membership -> rerun scripts/build-transit-data.py')

    if args.dry_run:
        print('\n--dry-run: nothing written.')
        return 0
    if not (n_add or n_rm or n_ch):
        print('\nNothing changed. index.html left alone.')
        return 0

    merged = sorted(new + quil, key=lambda l: (l['property'], unit_sort_key(l['unit'])))
    write_index(html, merged)
    print('\nwrote %d listings to index.html' % len(merged))
    subprocess.run([ 'node', os.path.join(ROOT, 'scripts', 'build-listings-json.js') ], check=True)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except SyncError as exc:
        print('\nSYNC FAILED: %s' % exc, file=sys.stderr)
        print('Nothing was written.', file=sys.stderr)
        sys.exit(1)
