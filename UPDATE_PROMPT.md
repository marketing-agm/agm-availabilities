# Master Prompt: AGM Availabilities App Update

Copy and paste the prompt below into a new Claude Code session to 1-shot update the availabilities app from the AppFolio listings page.

---

## The Prompt

```
Update the AGM availabilities app at /home/user/agm-availabilities/index.html with the latest listings from https://agmrealestategroup.appfolio.com/listings

Follow this exact workflow:

---

### STEP 1: Download the full AppFolio HTML

IMPORTANT: Do NOT use WebFetch — it truncates large pages. Use curl instead:

curl -o /tmp/appfolio_listings.html "https://agmrealestategroup.appfolio.com/listings"

Verify the listing count:
grep -c 'data-listing-id' /tmp/appfolio_listings.html

This count is the authoritative number of listings. All must be captured.

---

### STEP 2: Extract listing data with Python

Run a Python script that parses the downloaded HTML using regex. The AppFolio HTML structure uses these CSS classes/patterns:

- **Listing blocks**: Split HTML by `<div class="listing-item result js-listing-item"` — each block is one listing
- **Title + UUID**: Inside each block, find the title inside `<h2 class="listing-item__title js-listing-title">` → `<a href="/listings/detail/UUID">Title Text</a>`. IMPORTANT: Each block also has an image `<a>` linking to the same UUID — match the one inside `js-listing-title` specifically to get clean title text.
- **Address**: `<span class="js-listing-address">` — full street address
- **Rent**: `<span/div class="js-listing-blurb-rent">` — contains e.g., "$1,695" (extract with regex `\$[\d,]+`)
- **Bed/Bath**: `<span class="js-listing-blurb-bed-bath">` — e.g., "1 bd / 1 ba", "Studio / 1 ba"
- **Square feet**: Prefer `<dt class="detail-box__label">Square Feet</dt><dd class="detail-box__value">NNN</dd>` (desktop). Fallback: `<span class="js-listing-square-feet">Square Feet: NNN</span>` (mobile).
- **Availability**: `<dd class="detail-box__value js-listing-available">` — e.g., "NOW", "4/15/26"
  CRITICAL: Each listing has TWO availability elements (mobile + desktop). Use the `<dd>` version (detail-box__value), NOT the mobile one.
- **MFTE detection**: Check if title text contains "MFTE" (case-insensitive)

The Python script should output JSON with these fields per listing:
- uid (string) — from data-listing-id
- title_text (string) — raw title text
- address (string) — raw address text
- rent (integer) — parsed from "$X,XXX / Month"
- bedrooms — "Studio" (string) or integer (1, 2, 3)
- bathrooms (float) — e.g., 1.0, 1.5, 2.0
- sqft (integer) — 0 if not provided
- available (string) — "Now" or "Mon DD, YYYY" (e.g., "Apr 15, 2026")
- is_mfte (boolean)

**Availability normalization**: AppFolio uses "NOW" or "M/D/YY" (e.g., "4/15/26"). Convert to:
- "NOW" → "Now"
- "M/D/YY" → "Mon DD, YYYY" (e.g., "Apr 15, 2026")

---

### STEP 3: Map AppFolio titles to canonical property names

Each AppFolio listing title contains the property name embedded in marketing text. Extract using these keyword patterns:

| Keyword in title | Canonical property name |
|---|---|
| "301" (as standalone or in address context) | 301 Apartments |
| "Arbor Heights" | Arbor Heights |
| "Avia" | Avia Apartments |
| "BalCro" | BalCro |
| "Bayview" | Bayview Apartments |
| "Blanche Clare" | Blanche Clare Apartments |
| "Cedar Lane" | Cedar Lane Apartments |
| "Clift House" | Clift House Apartments |
| "Crestview" | Crestview Townhomes |
| "De Selm" | De Selm Apartments |
| "East Union" | East Union Apartments |
| "Fairlake" | Fairlake Quads |
| "Fremont Village" | Fremont Village |
| "Golden Inca" | Golden Inca |
| "Hill Town" | Hill Town Apartments |
| "Highway Place" | Highway Place |
| "Lorelei" | Lorelei Apartments |
| "Mercer Tower" | Mercer Tower |
| "Niwa" | Niwa Apartments |
| "Ondine" | Ondine Eastlake |
| "Reverie" | Reverie Apartments |
| "Rialto" | Rialto Court |
| "Skandi" | Skandi Villa |
| "Viewmont" | Viewmont Apartments |
| "White Heather" | White Heather Apartments |
| "Willow Creek" | Willow Creek Apartments |

If a listing title doesn't match ANY known property, it's a **new property**. STOP and ask the user for:
1. Canonical property name
2. Neighborhood
3. Website URL (or "none")
4. GPS coordinates (lat/lng)

**Short name** (used in the `title` field) — strip trailing descriptors:
- "301 Apartments" → "301"
- "Avia Apartments" → "Avia"
- "Bayview Apartments" → "Bayview"
- "Blanche Clare Apartments" → "Blanche Clare"
- "Cedar Lane Apartments" → "Cedar Lane"
- "Clift House Apartments" → "Clift House"
- "Crestview Townhomes" → "Crestview"
- "De Selm Apartments" → "De Selm"
- "East Union Apartments" → "East Union"
- "Hill Town Apartments" → "Hill Town"
- "Lorelei Apartments" → "Lorelei"
- "Niwa Apartments" → "Niwa"
- "Ondine Eastlake" → "Ondine"
- "Reverie Apartments" → "Reverie"
- "Viewmont Apartments" → "Viewmont"
- "White Heather Apartments" → "White Heather"
- "Willow Creek Apartments" → "Willow Creek"
- All others keep their full canonical name as the short name (e.g., "BalCro", "Fremont Village", "Highway Place", "Mercer Tower", etc.)

---

### STEP 4: Extract unit numbers from addresses

Parse unit from the address string using these patterns (in order):
1. `Apt XXX` or `APT XXX`
2. `Unit XXX` or `UNIT XXX`
3. `#XXX`
4. `-XXX` (hyphen before unit at end)

If no unit pattern found → use `"Not Specified"`

Examples:
- "625 N 130th St, Apt 103, Seattle, WA" → "103"
- "1406 Bellevue Ave #A, Seattle, WA" → "A"
- "8509 14th Ave NW, Apt 305, Seattle, WA" → "305"
- "12556 15TH AVE NE, SEATTLE, WA" → "Not Specified"

---

### STEP 5: Build the listing objects

Each listing in the `agmListings` array has this exact format:

```json
{
  "property": "Avia Apartments",
  "neighborhood": "Greenwood",
  "unit": "101",
  "title": "2 Bedrooms | Avia",
  "bedrooms": 2,
  "bathrooms": 1.0,
  "rent": 2195,
  "sqft": 875,
  "available": "Now",
  "address": "11534 Greenwood Ave N, Apt 101, Seattle, WA 98133",
  "features": ["On-Site Laundry"],
  "detailsUrl": "https://agmrealestategroup.appfolio.com/listings/detail/UUID",
  "applyUrl": "https://agmrealestategroup.appfolio.com/listings/rental_applications/new?listable_uid=UUID&source=Website"
}
```

Field rules:
- **property**: Canonical property name (from mapping above)
- **neighborhood**: From the property-to-neighborhood mapping (see below)
- **unit**: Extracted from address; use `"Not Specified"` if none found
- **title**: `"{BedType} | {ShortName}"` where BedType is "Studio", "1 Bedroom", "2 Bedrooms", or "3 Bedrooms"
- **bedrooms**: `"Studio"` (string with quotes) for studios, integer (1, 2, 3) for bedrooms (no quotes)
- **bathrooms**: Float (1.0, 1.5, 2.0)
- **rent**: Integer, no decimals
- **sqft**: Integer, use 0 if not available (app renders as "N/A")
- **available**: `"Now"` or `"Mon DD, YYYY"` format
- **address**: Exact address from AppFolio (preserve original casing)
- **features**: `["On-Site Laundry"]` for all standard units. Use `["On-Site Laundry", "MFTE/MHA"]` if MFTE detected in title.
- **detailsUrl**: `https://agmrealestategroup.appfolio.com/listings/detail/{UUID}`
- **applyUrl**: `https://agmrealestategroup.appfolio.com/listings/rental_applications/new?listable_uid={UUID}&source=Website`

**Sort order**: Alphabetically by property name, then by unit (numeric sort where possible).

---

### STEP 6: Property-to-neighborhood mapping

```
301 Apartments → Central District
Arbor Heights → North Seattle
Avia Apartments → Greenwood
BalCro → Ballard
Bayview Apartments → Beacon Hill
Blanche Clare Apartments → Capitol Hill
Cedar Lane Apartments → Greenwood
Clift House Apartments → Capitol Hill
Crestview Townhomes → Lynnwood
De Selm Apartments → Capitol Hill
East Union Apartments → Capitol Hill
Fairlake Quads → Bellevue
Fremont Village → Fremont
Golden Inca → Capitol Hill
Hill Town Apartments → Central District
Highway Place → Everett
Lorelei Apartments → Capitol Hill
Mercer Tower → Mercer Island
Niwa Apartments → Lower Queen Anne
Ondine Eastlake → Eastlake
Reverie Apartments → Beacon Hill
Rialto Court → Capitol Hill
Skandi Villa → Edmonds
Viewmont Apartments → Capitol Hill
White Heather Apartments → Lake City
Willow Creek Apartments → Bothell
```

If a new property appears, ask the user for the neighborhood.

---

### STEP 7: Replace the data in index.html

The file `/home/user/agm-availabilities/index.html` has four data structures to update:

1. **`agmListings` array** (~line 1386): Replace the entire array contents with all listings, sorted alphabetically by property then unit.

2. **`propertyLeasingAgents` object** (~line 1481): Ensure all properties from the new listings are present. All map to `"leasing@agmrealestategroup.com"`. Remove any property no longer in listings. Keep alphabetical order.

3. **`propertyCoordinates` object** (~line 1511): Ensure all properties are present. Remove properties no longer in listings. For new properties, ask the user for coordinates. Current coordinates:
```
"301 Apartments": { lat: 47.5991, lng: -122.2981 }
"Arbor Heights": { lat: 47.7157, lng: -122.3365 }
"Avia Apartments": { lat: 47.7103, lng: -122.3358 }
"BalCro": { lat: 47.6877, lng: -122.3788 }
"Bayview Apartments": { lat: 47.5763, lng: -122.3127 }
"Blanche Clare Apartments": { lat: 47.6148, lng: -122.3260 }
"Cedar Lane Apartments": { lat: 47.7198, lng: -122.3358 }
"Clift House Apartments": { lat: 47.6199, lng: -122.3240 }
"Crestview Townhomes": { lat: 47.8298, lng: -122.2852 }
"De Selm Apartments": { lat: 47.6223, lng: -122.3110 }
"East Union Apartments": { lat: 47.6144, lng: -122.3175 }
"Fairlake Quads": { lat: 47.5973, lng: -122.1465 }
"Fremont Village": { lat: 47.6565, lng: -122.3501 }
"Golden Inca": { lat: 47.6203, lng: -122.3112 }
"Highway Place": { lat: 47.9335, lng: -122.2276 }
"Hill Town Apartments": { lat: 47.5921, lng: -122.3039 }
"Lorelei Apartments": { lat: 47.6270, lng: -122.3219 }
"Mercer Tower": { lat: 47.5686, lng: -122.2224 }
"Niwa Apartments": { lat: 47.6240, lng: -122.3565 }
"Ondine Eastlake": { lat: 47.6413, lng: -122.3252 }
"Reverie Apartments": { lat: 47.5713, lng: -122.3117 }
"Rialto Court": { lat: 47.6186, lng: -122.3098 }
"Skandi Villa": { lat: 47.8127, lng: -122.3654 }
"Viewmont Apartments": { lat: 47.6239, lng: -122.3242 }
"White Heather Apartments": { lat: 47.7155, lng: -122.2987 }
"Willow Creek Apartments": { lat: 47.7594, lng: -122.2013 }
```

4. **`propertyWebsites` object** (~line 1541): Ensure all properties are present. Remove properties no longer in listings. For new properties without a dedicated website, use `"https://agmrealestategroup.appfolio.com/listings"`. Current websites:
```
"301 Apartments": "https://www.301apartments.com/"
"Arbor Heights": "https://www.arborheightsapartments.com/"
"Avia Apartments": "https://www.aviaapartmentsseattle.com/"
"BalCro": "https://www.balcroapartmentsseattle.com/"
"Bayview Apartments": "https://www.bayviewaptsbeaconhill.com/"
"Blanche Clare Apartments": "https://www.blancheclareapartments.com/"
"Cedar Lane Apartments": "https://www.cedarlaneseattle.com/"
"Clift House Apartments": "https://www.clifthouseapartments.com/"
"Crestview Townhomes": "https://agmrealestategroup.appfolio.com/listings"
"De Selm Apartments": "https://www.deselmapartments.com/"
"East Union Apartments": "https://www.eastunionapts.com/"
"Fairlake Quads": "https://www.fairlakequadsapartments.com/"
"Fremont Village": "https://www.fremontvillageapts.com/"
"Golden Inca": "https://www.goldenincaapartments.com/"
"Highway Place": "https://agmrealestategroup.appfolio.com/listings"
"Hill Town Apartments": "https://www.hilltownapartments.com/"
"Lorelei Apartments": "https://www.theloreleiapartments.com/"
"Mercer Tower": "https://www.mercertowerapartments.com/"
"Niwa Apartments": "https://www.niwaseattle.com/"
"Ondine Eastlake": "https://www.ondineeastlake.com/"
"Reverie Apartments": "https://www.reveriebeaconhill.com/"
"Rialto Court": "https://www.rialtocourtapartments.com/"
"Skandi Villa": "https://www.skandivillaapartments.com/"
"Viewmont Apartments": "https://www.viewmontapts.com/"
"White Heather Apartments": "https://www.whiteheatherapts.com/"
"Willow Creek Apartments": "https://www.willowcreekaptsbothell.com/"
```

---

### STEP 8: Tour booking links

The app has a "Book a Tour" form that sends emails via EmailJS to the leasing agent for the selected property. This is powered by the `propertyLeasingAgents` object (Step 7, item 2). There are NO separate per-property tour URLs in the listing data — the tour form is property-agnostic and routes via `propertyLeasingAgents[property]`.

**What to ensure**: Every property in `agmListings` has a corresponding entry in `propertyLeasingAgents`. If a property is missing from `propertyLeasingAgents`, the tour form will fall back to `leasing@agmrealestategroup.com`, but this should be explicit. All properties currently use `"leasing@agmrealestategroup.com"`.

---

### STEP 9: Verify

After updating, verify:
1. Count listings in the agmListings array matches the AppFolio count
2. Every property in agmListings exists in propertyLeasingAgents, propertyCoordinates, and propertyWebsites
3. No orphan properties in the three supporting objects (removed from listings but still in objects)
4. All UIDs are present in both detailsUrl and applyUrl for every listing

---

### STEP 10: Generate change report

After all changes are applied, print a **detailed, shareable** report to the user summarizing exactly what changed. Compare listings by UUID (extracted from detailsUrl) between the previous git commit (`HEAD~1:index.html`) and the newly updated file. The report should use markdown table format so the user can easily copy-paste and share it.

The report MUST include ALL of the following sections with the exact formatting shown:

```
============================================================
AGM AVAILABILITIES UPDATE — [Month Day, Year]
============================================================
Total active listings: [new count] (previously [old count])

------------------------------------------------------------
NEW LISTINGS ([count])
------------------------------------------------------------
```

For each new listing, show full details:
```
  [Property] — Unit [X]
    $[rent]/mo | [beds] / [baths] | [sqft] sqft
    Available: [date]
    Address: [full address]
```

Then:
```
------------------------------------------------------------
REMOVED LISTINGS ([count])
------------------------------------------------------------
```

For each removed listing:
```
  [Property] — Unit [X]
    Was: $[rent]/mo | [beds] / [baths] | [sqft] sqft
```

Then:
```
------------------------------------------------------------
UPDATED LISTINGS ([count])
------------------------------------------------------------
```

For each changed listing, show only the fields that changed:
```
  [Property] — Unit [X]
    Rent: $[old] → $[new]
    Available: [old] → [new]
    Added tags: MFTE/MHA
```

Then:
```
------------------------------------------------------------
NEW PROPERTIES ([count])
------------------------------------------------------------
  [Property Name] — Neighborhood: [X]

------------------------------------------------------------
REMOVED PROPERTIES ([count])
------------------------------------------------------------
  [Property Name]

------------------------------------------------------------
UNCHANGED LISTINGS ([count])
------------------------------------------------------------
  [Property] — Unit [X]: $[rent]/mo | [beds] / [baths] | [sqft] sqft | Avail: [date]
```

**Bed/Bath display format**: Use "Studio", "1 Bed", "2 Bed", "3 Bed" for bedrooms, and "1 Bath", "1.5 Bath", "2 Bath" for bathrooms.

**Important**: List ALL unchanged listings with their full details (one line each) so the user has a complete inventory snapshot.

This report lets the user verify correctness at a glance without diffing files, and is formatted to be easily shared with colleagues.

---

### STEP 11: Commit and push

git add index.html
git commit -m "Update property availabilities from AppFolio"
git push

---

### Key gotchas to watch for:
1. **WebFetch truncates** — always use curl to download the full HTML
2. **Split listings by the correct element** — use `<div class="listing-item result js-listing-item"` to split listing blocks (NOT by `<h2>` title tags). Each listing block wraps an image `<a>` and a title `<a>` that both link to `/listings/detail/UUID`; you must match the title inside `js-listing-title` specifically, not the first `<a>` in the block.
3. **Dual availability elements** — use `<dd class="detail-box__value js-listing-available">`, not the mobile span
4. **Square feet from detail-box** — prefer `<dt class="detail-box__label">Square Feet</dt><dd class="detail-box__value">NNN</dd>` (desktop detail box); fall back to `Square Feet: NNN` in the mobile span
5. **"Studio" is a string** — `"bedrooms": "Studio"` (with quotes), not an integer
6. **Bathrooms are floats** — always `1.0`, `1.5`, `2.0` (not integers)
7. **Missing sqft → 0** — never omit, never use null
8. **Sort alphabetically** — by property name first, then unit number
9. **New properties need user input** — don't guess neighborhoods, coordinates, or websites
10. **MFTE units** — detected by "MFTE" in AppFolio title text, get `["On-Site Laundry", "MFTE/MHA"]` features
11. **Address casing** — preserve exactly as AppFolio provides it
12. **Unit "Not Specified"** — when no unit pattern found in address (not empty string, not null)
13. **Tour booking** — powered by `propertyLeasingAgents`, not per-listing URLs. Ensure every property has an entry.
14. **Change report comparison** — compare by UUID from `detailsUrl` between `git show HEAD~1:index.html` (old) and the updated file (new). This correctly identifies added, removed, changed, and unchanged listings.
```
