# Master Prompt: AGM Availabilities App Update

Copy and paste the prompt below into a new Claude Code session to update the
availabilities app from the AppFolio listings page.

The scraping, mapping and validation now live in
`scripts/sync-availabilities.py`. This prompt no longer restates CSS selectors
or property tables — those drifted out of date and silently broke the sync.
See **Why this is a script** at the bottom.

---

## The Prompt

```
Update the AGM availabilities app at /home/user/agm-availabilities from the
latest AppFolio listings.

### 1. See what would change

    python3 scripts/sync-availabilities.py --dry-run

This downloads https://agmrealestategroup.appfolio.com/listings, parses it,
maps every listing to a known property, and prints an added / removed /
changed report. It writes nothing.

If it exits non-zero, STOP and read the message. It refuses to publish when
something looks wrong rather than writing bad data:

| Failure | What it means |
|---|---|
| `no listing blocks found` | AppFolio changed its markup, or the page did not load. The parser needs updating. |
| `only N listings in the feed (floor is 40)` | Probably a partial or error page. Do not publish it. |
| `N of M listings have no rent` | A selector stopped matching. This is the exact failure that broke the sync in Oct 2026. |
| `listings for a property this app does not know` | A genuinely new property. See step 4. |
| `expected 3 Quil Creek Crossing placeholders` | Someone removed the hand-maintained Quil units from index.html. Restore them first. |

Read the report before continuing. A normal day is a handful of adds, removes
and price changes. A day where most listings change is a signal, not a win.

### 2. Apply it

    python3 scripts/sync-availabilities.py

Same work, but it rewrites the `agmListings` array in `index.html` and then
runs `scripts/build-listings-json.js` to regenerate `listings.json`. If
nothing changed, it says so and leaves both files alone.

### 3. Commit

    git add index.html listings.json
    git commit -m "Update property availabilities from AppFolio"
    git push

Always stage `listings.json` alongside `index.html` — the Book-a-Tour page
reads it at runtime, so shipping one without the other leaves the tour page
offering units that are gone.

Then give the user the change report from step 1 in markdown, and open a PR.

### 4. If a new property appears

The script stops rather than guessing. Ask the user for:

1. Canonical property name
2. Neighborhood
3. Website URL (or "none" — then use `https://agmrealestategroup.appfolio.com/listings`)
4. GPS coordinates (lat/lng)

Add it to `agmListings` (one placeholder row is enough to register it),
`propertyLeasingAgents`, `propertyCoordinates` and `propertyWebsites` in
`index.html`, then rerun. The script reads all four from `index.html`, so once
the property is there it maps on its own.

Because `propertyCoordinates` changed, also rebuild the transit data:

    python3 scripts/build-transit-data.py

That is the ONLY time a routine sync touches `transit-data.js` /
`transit-routes.json`. They are keyed off properties, not units — rebuilding
them on an ordinary sync is wasted time and churns the diff.

### 5. Quil Creek Crossing is maintained by hand

Quil Creek Crossing Apartments is NOT in the AppFolio feed. Its three
placeholder units power the `?property=Quil Creek Crossing Apartments` embed.
The script preserves them and fails if they are missing, so you do not need to
do anything — just never report them as removed.
```

---

## Verifying a sync

The script checks these itself and fails if any is wrong, but if you have
edited `index.html` by hand, confirm:

1. Every property in `agmListings` has an entry in `propertyLeasingAgents`,
   `propertyCoordinates` and `propertyWebsites`, and none of those three has
   an entry for a property that no longer exists — except Quil Creek Crossing,
   which is intentionally an orphan relative to the feed.
2. `listings.json` was regenerated and its count matches `agmListings`.
3. The three Quil placeholders are present, and the `isQuilCrossing` branches
   plus the Quil branding block near the end of the script are intact.

---

## Why this is a script

This document used to spell out the CSS selectors and carry its own copy of
every property's neighborhood, coordinates and website. Both rotted:

**The selectors.** AppFolio widened its class attributes, so the documented
`class="js-listing-blurb-rent"` no longer matched
`class="sidebar__price rent-banner__text js-listing-blurb-rent"`. An exact
match returns nothing, so every rent parsed as `0` — with no error. The sync
stopped producing usable PRs after 28 Oct 2026 and nobody was told. The script
matches on "class contains" and reads the desktop detail box first, and it
aborts outright if rents go missing en masse.

**The property tables.** The lists in this document had fallen behind
`index.html` — naming properties AGM no longer lists, and missing several it
does. The script reads every mapping out of `index.html`, which is the real
source of truth, so there is nothing left to keep in sync.

**Matching.** AppFolio titles are free-text marketing copy and often omit the
property name entirely ("2br w/ Balcony Available Now! | 1 Month Free!"). The
listing description always links the property's own website, so the script
matches on that first and falls back to the name appearing in the title,
description or address.

To check the parser against a saved page without hitting the network:

    python3 scripts/sync-availabilities.py --dry-run --from-file saved.html
