#!/usr/bin/env python3
"""build-transit-data.py

Regenerates the transit datasets the availabilities map renders:

    transit-data.js      light rail / commuter rail geometry + stations,
                         and the bus stops & routes near every AGM property
    transit-routes.json  bus + RapidRide route geometry (lazy-loaded by the
                         map only when the "Bus & RapidRide routes" layer is
                         switched on)

Sources (all public, no API key of ours required):

  * Sound Transit rail GTFS  - https://www.soundtransit.org/GTFS-rail/40_gtfs.zip
    Official Link / Sounder / T Line alignments and stations.
  * OneBusAway regional API  - https://api.pugetsound.onebusaway.org
    Region-wide stop and route data covering King County Metro, Sound Transit,
    Community Transit, Everett Transit, Seattle Streetcar and the Monorail.
    Uses the public "TEST" key, which is rate limited - the script paces itself.

Property coordinates are read straight out of index.html, which stays the
single source of truth.

Usage:

    python3 scripts/build-transit-data.py [--cache DIR]

Re-run it whenever properties are added or removed, or every few months to
pick up service changes. It takes about 5 minutes (mostly API pacing).
"""

import argparse
import csv
import io
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, 'index.html')
ST_GTFS = 'https://www.soundtransit.org/GTFS-rail/40_gtfs.zip'
OBA = 'https://api.pugetsound.onebusaway.org/api/where'
OBA_KEY = 'TEST'

# Walk radius used to decide which stops "serve" a property.
STOP_RADIUS_M = 800
MAX_STOPS_PER_PROPERTY = 10
MAX_ROUTES_PER_PROPERTY = 14

# Rail routes we draw. T Line is Tacoma-only and nowhere near an AGM
# property, so it is left out to keep the map readable.
RAIL_ROUTES = {
    '100479': {'name': '1 Line', 'mode': 'link'},
    '2LINE':  {'name': '2 Line', 'mode': 'link'},
    'SNDR_EV': {'name': 'N Line', 'mode': 'sounder'},
    'SNDR_TL': {'name': 'S Line', 'mode': 'sounder'},
}

AGENCIES = {
    '1': 'King County Metro',
    '23': 'Seattle Streetcar',
    '29': 'Community Transit',
    '40': 'Sound Transit',
    '96': 'Seattle Monorail',
    '97': 'Everett Transit',
}


# --------------------------------------------------------------- helpers
def log(*a):
    print(*a, flush=True)


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def perp_dist(p, a, b):
    (x, y), (x1, y1), (x2, y2) = p, a, b
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(x - x1, y - y1)
    t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(x - (x1 + t * dx), y - (y1 + t * dy))


def simplify(points, eps_m):
    """Iterative Ramer-Douglas-Peucker (recursion blows the stack on GTFS shapes)."""
    if len(points) < 3:
        return list(points)
    eps = eps_m / 111320.0
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        lo, hi = stack.pop()
        if hi - lo < 2:
            continue
        dmax, idx = 0.0, lo
        for i in range(lo + 1, hi):
            d = perp_dist(points[i], points[lo], points[hi])
            if d > dmax:
                dmax, idx = d, i
        if dmax > eps:
            keep[idx] = True
            stack.append((lo, idx))
            stack.append((idx, hi))
    return [p for p, k in zip(points, keep) if k]


def decode_polyline(encoded):
    """Google encoded-polyline -> [(lng, lat), ...]"""
    pts, index, lat, lng = [], 0, 0, 0
    n = len(encoded)
    while index < n:
        for axis in range(2):
            shift, result = 0, 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else (result >> 1)
            if axis == 0:
                lat += delta
            else:
                lng += delta
        pts.append((lng / 1e5, lat / 1e5))
    return pts


def fetch_json(url, tries=6):
    last = None
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.load(r)
        except Exception as exc:  # noqa: BLE001 - want to retry on anything
            last = exc
            log('  retry %d: %s' % (attempt, exc))
            time.sleep(2 * (attempt + 1))
    raise SystemExit('gave up on %s (%s)' % (url, last))


def cached_json(cache, name, produce):
    path = os.path.join(cache, name)
    if os.path.exists(path):
        log('using cached %s' % name)
        with open(path) as f:
            return json.load(f)
    data = produce()
    os.makedirs(cache, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f)
    return data


# --------------------------------------------------------------- sources
def read_properties():
    html = open(INDEX, encoding='utf-8').read()
    m = re.search(r'const propertyCoordinates = \{(.*?)\n        \};', html, re.S)
    if not m:
        raise SystemExit('could not find propertyCoordinates in index.html')
    props = {}
    for name, lat, lng in re.findall(
            r'"([^"]+)":\s*\{\s*lat:\s*([-\d.]+),\s*lng:\s*([-\d.]+)\s*\}', m.group(1)):
        props[name] = (float(lat), float(lng))
    if not props:
        raise SystemExit('propertyCoordinates parsed as empty')
    return props


def load_st_gtfs(cache):
    """Pull the Sound Transit rail GTFS and keep only what we draw."""
    def produce():
        log('downloading Sound Transit rail GTFS ...')
        with urllib.request.urlopen(ST_GTFS, timeout=300) as r:
            blob = r.read()
        zf = zipfile.ZipFile(io.BytesIO(blob))

        def rows(name):
            with zf.open(name) as fh:
                yield from csv.DictReader(io.TextIOWrapper(fh, encoding='utf-8-sig'))

        routes = {r['route_id']: r for r in rows('routes.txt')}
        trips = [t for t in rows('trips.txt') if t['route_id'] in RAIL_ROUTES]
        shapes = {}
        for s in rows('shapes.txt'):
            shapes.setdefault(s['shape_id'], []).append(
                (int(s['shape_pt_sequence']), float(s['shape_pt_lon']), float(s['shape_pt_lat'])))
        for k in shapes:
            shapes[k] = [[lon, lat] for _, lon, lat in sorted(shapes[k])]

        # longest shape per route (one direction is enough to draw the line)
        best = {}
        for t in trips:
            sid = t.get('shape_id')
            if not sid or sid not in shapes or t.get('direction_id') != '0':
                continue
            rid = t['route_id']
            if rid not in best or len(shapes[sid]) > len(shapes[best[rid]]):
                best[rid] = sid

        trip_route = {t['trip_id']: t['route_id'] for t in trips}
        route_stop_ids = {}
        for st in rows('stop_times.txt'):
            rid = trip_route.get(st['trip_id'])
            if rid:
                route_stop_ids.setdefault(rid, set()).add(st['stop_id'])
        stops = {s['stop_id']: {'name': s['stop_name'], 'lat': float(s['stop_lat']),
                                'lon': float(s['stop_lon']), 'parent': s.get('parent_station', '')}
                 for s in rows('stops.txt')}
        return {
            'routes': {k: routes[k] for k in RAIL_ROUTES if k in routes},
            'shapes': {rid: shapes[sid] for rid, sid in best.items()},
            'route_stop_ids': {k: sorted(v) for k, v in route_stop_ids.items()},
            'stops': stops,
        }

    return cached_json(cache, 'st_gtfs.json', produce)


def load_nearby(cache, props):
    """Stops within STOP_RADIUS_M of every property, with the routes serving them."""
    def produce():
        out, routes = {}, {}
        for i, (name, (lat, lng)) in enumerate(sorted(props.items()), 1):
            url = ('%s/stops-for-location.json?key=%s&radius=%d&lat=%s&lon=%s'
                   % (OBA, OBA_KEY, STOP_RADIUS_M, lat, lng))
            data = fetch_json(url)['data']
            routes.update({r['id']: r for r in data['references']['routes']})
            out[name] = [{'id': s['id'], 'name': s['name'], 'lat': s['lat'], 'lon': s['lon'],
                          'routes': s.get('routeIds', [])} for s in data['list']]
            log('  [%2d/%d] %-34s %3d stops' % (i, len(props), name, len(out[name])))
            time.sleep(1.1)
        return {'nearby': out, 'routes': routes}

    log('looking up transit stops near each property ...')
    return cached_json(cache, 'oba_nearby.json', produce)


def load_route_shapes(cache, route_ids):
    def produce():
        res = {}
        for i, rid in enumerate(route_ids, 1):
            url = ('%s/stops-for-route/%s.json?key=%s&includePolylines=true'
                   % (OBA, urllib.parse.quote(rid), OBA_KEY))
            entry = fetch_json(url)['data']['entry']
            res[rid] = [p['points'] for p in entry.get('polylines', []) if p.get('points')]
            log('  [%2d/%d] %-12s %3d polylines' % (i, len(route_ids), rid, len(res[rid])))
            time.sleep(1.1)
        return res

    log('fetching route geometry ...')
    return cached_json(cache, 'oba_shapes.json', produce)


# --------------------------------------------------------------- shaping
def classify(route):
    """Map an OBA route onto a display mode + colour."""
    agency = str(route.get('agencyId'))
    short = (route.get('shortName') or '').strip()
    rtype = route.get('type')
    if agency == '40' and rtype in (0, 1, 2):
        return None  # Link / Sounder are drawn by the rail layer
    if agency == '1' and short.endswith('Line'):
        return ('rapidride', '#9C182F', 'RapidRide')
    if agency == '29' and short.startswith('Swift'):
        colour = '#' + (route.get('color') or '006CFF')
        return ('brt', colour, 'Swift BRT')
    if agency == '23':
        return ('streetcar', '#F47836', 'Streetcar')
    if agency == '96':
        return ('monorail', '#5A5A5A', 'Monorail')
    if agency == '40':
        return ('express', '#2B376E', 'ST Express')
    if agency == '29':
        return ('bus', '#0070C0', 'Community Transit')
    if agency == '97':
        return ('bus', '#1F7A6B', 'Everett Transit')
    return ('bus', '#D99100', 'Metro bus')


def dedupe_polylines(encoded_list, keep_cap=4):
    """Several variants per route overlap heavily. Keep the longest ones that
    actually add new ground, measured on a ~40 m grid."""
    decoded = sorted((decode_polyline(e) for e in encoded_list), key=len, reverse=True)
    covered, kept = set(), []
    for pts in decoded:
        if len(pts) < 4:
            continue
        cells = {(round(x, 3), round(y, 3)) for x, y in pts}
        new = cells - covered
        if kept and len(new) < 0.25 * len(cells):
            continue
        covered |= cells
        kept.append(pts)
        if len(kept) >= keep_cap:
            break
    return kept


def build():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cache', default=os.path.join(ROOT, '.transit-cache'),
                    help='directory for downloaded source data (delete it to refetch)')
    args = ap.parse_args()
    cache = args.cache

    props = read_properties()
    log('%d properties' % len(props))

    # ---- rail lines + stations ----------------------------------------
    gtfs = load_st_gtfs(cache)
    rail_features = []
    for rid, meta in RAIL_ROUTES.items():
        shape = gtfs['shapes'].get(rid)
        route = gtfs['routes'].get(rid)
        if not shape or not route:
            log('WARNING: no shape for %s' % meta['name'])
            continue
        pts = simplify([tuple(p) for p in shape], 12)
        rail_features.append({
            'type': 'Feature',
            'properties': {
                'line': meta['name'],
                'mode': meta['mode'],
                'color': '#' + route['route_color'],
                'desc': route['route_long_name'],
            },
            'geometry': {'type': 'LineString',
                         'coordinates': [[round(x, 5), round(y, 5)] for x, y in pts]},
        })
        log('  %s: %d -> %d points' % (meta['name'], len(shape), len(pts)))

    stations = {}
    for rid, stop_ids in gtfs['route_stop_ids'].items():
        if rid not in RAIL_ROUTES:
            continue
        for sid in stop_ids:
            stop = gtfs['stops'][sid]
            parent = gtfs['stops'].get(stop['parent'], stop)
            key = parent['name'].strip().lower()
            entry = stations.setdefault(key, {
                'name': parent['name'].strip(),
                'lat': round(parent['lat'], 5),
                'lng': round(parent['lon'], 5),
                'lines': [],
                'mode': RAIL_ROUTES[rid]['mode'],
            })
            line = RAIL_ROUTES[rid]['name']
            if line not in entry['lines']:
                entry['lines'].append(line)
            if RAIL_ROUTES[rid]['mode'] == 'link':
                entry['mode'] = 'link'  # a Link stop wins over a Sounder-only stop
    stations = sorted(stations.values(), key=lambda s: s['name'])
    for st in stations:
        st['lines'].sort()
    log('  %d rail stations' % len(stations))

    # ---- stops & routes near each property ----------------------------
    near = load_nearby(cache, props)
    oba_routes = near['routes']

    route_meta, property_transit = {}, {}
    for name, (plat, plng) in sorted(props.items()):
        stops = []
        for s in near['nearby'][name]:
            usable = [r for r in s['routes'] if classify(oba_routes[r])]
            if not usable:
                continue
            stops.append({
                'n': s['name'],
                'y': round(s['lat'], 5),
                'x': round(s['lon'], 5),
                'm': int(round(haversine_m(plat, plng, s['lat'], s['lon']))),
                'r': sorted(usable),
            })
        stops.sort(key=lambda s: s['m'])

        # one stop per name (both directions of a street collapse into one dot)
        seen, trimmed = set(), []
        for s in stops:
            if s['n'] in seen:
                continue
            seen.add(s['n'])
            trimmed.append(s)
        trimmed = trimmed[:MAX_STOPS_PER_PROPERTY]

        best_route = {}
        for s in stops:
            for rid in s['r']:
                if rid not in best_route or s['m'] < best_route[rid]['m']:
                    best_route[rid] = {'id': rid, 'm': s['m'], 'stop': s['n']}
        ranked = sorted(best_route.values(), key=lambda r: (r['m'], r['id']))[:MAX_ROUTES_PER_PROPERTY]

        for r in ranked:
            route_meta.setdefault(r['id'], None)
        for s in trimmed:
            for rid in s['r']:
                route_meta.setdefault(rid, None)

        property_transit[name] = {
            'stops': trimmed,
            'routes': [{'id': r['id'], 'm': r['m'], 'stop': r['stop']} for r in ranked],
        }

    for rid in list(route_meta):
        route = oba_routes[rid]
        kind = classify(route)
        if not kind:
            del route_meta[rid]
            continue
        mode, colour, label = kind
        route_meta[rid] = {
            'n': (route.get('shortName') or route.get('longName') or '').strip(),
            'd': (route.get('description') or route.get('longName') or '').strip(),
            'm': mode,
            'c': colour,
            'a': label,
            'agency': AGENCIES.get(str(route.get('agencyId')), ''),
        }
    log('  %d distinct routes near AGM properties' % len(route_meta))

    # ---- route geometry (lazy-loaded) ---------------------------------
    shapes_raw = load_route_shapes(cache, sorted(route_meta))
    routes_geo = {'type': 'FeatureCollection', 'features': []}
    for rid, meta in sorted(route_meta.items()):
        for pts in dedupe_polylines(shapes_raw.get(rid, [])):
            simple = simplify(pts, 20)
            routes_geo['features'].append({
                'type': 'Feature',
                'properties': {'id': rid, 'n': meta['n'], 'd': meta['d'],
                               'm': meta['m'], 'c': meta['c'], 'a': meta['a']},
                'geometry': {'type': 'LineString',
                             'coordinates': [[round(x, 5), round(y, 5)] for x, y in simple]},
            })
    log('  %d route line features' % len(routes_geo['features']))

    # ---- write ---------------------------------------------------------
    payload = {
        'generated': time.strftime('%Y-%m-%d'),
        'railLines': {'type': 'FeatureCollection', 'features': rail_features},
        'stations': stations,
        'routes': route_meta,
        'properties': property_transit,
    }
    js_path = os.path.join(ROOT, 'transit-data.js')
    with open(js_path, 'w', encoding='utf-8') as f:
        f.write('// Generated by scripts/build-transit-data.py - do not edit by hand.\n')
        f.write('// Sources: Sound Transit rail GTFS + OneBusAway Puget Sound regional API.\n')
        f.write('window.AGM_TRANSIT = ')
        json.dump(payload, f, separators=(',', ':'))
        f.write(';\n')

    json_path = os.path.join(ROOT, 'transit-routes.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(routes_geo, f, separators=(',', ':'))

    log('wrote %s (%.0f KB)' % (js_path, os.path.getsize(js_path) / 1024))
    log('wrote %s (%.0f KB)' % (json_path, os.path.getsize(json_path) / 1024))


if __name__ == '__main__':
    build()
