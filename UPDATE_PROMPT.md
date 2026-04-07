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

- **Listing blocks**: Each listing is a `<div>` with `data-listing-id="UUID"` attribute
- **Title**: `<a class="js-listing-title">` — contains property name + marketing text
- **Address**: `<div class="js-listing-address">` — full street address
- **Rent**: `<span class="js-listing-blurb-rent">` — e.g., "$1,695 / Month"
- **Bed/Bath**: `<span class="js-listing-blurb-bed-bath">` — e.g., "1 Bed / 1 Bath", "Studio / 1 Bath"
- **Square feet**: `<span class="js-listing-square-feet">` — e.g., "690 Sq Ft" (may be empty)
- **Availability**: `<dd class="detail-box__value js-listing-available">` — e.g., "NOW", "4/15/26"
  CRITICAL: Each listing has TWO availability elements (mobile + desktop). Use the `<dd>` version (detail-box__value), NOT the mobile one.
- **Detail URL**: `<a class="js-listing-title" href="/listings/detail/UUID">` — extract UUID from href
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
| "Ramesh" | Ramesh House |
| "Reverie" | Reverie Apartments |
| "Rialto" | Rialto Court |
| "Skandi" | Skandi Villa |
| "The Palms" or "Palms" | The Palms |
| "Viewmont" | Viewmont Apartments |
| "White Heather" | White Heather Apartments |

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
Ramesh House → Green Lake
Reverie Apartments → Beacon Hill
Rialto Court → Capitol Hill
Skandi Villa → Edmonds
The Palms → Eastlake
Viewmont Apartments → Capitol Hill
White Heather Apartments → Lake City
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
"Hill Town Apartments": { lat: 47.5921, lng: -122.3039 }
"Highway Place": { lat: 47.9335, lng: -122.2276 }
"Lorelei Apartments": { lat: 47.6270, lng: -122.3219 }
"Mercer Tower": { lat: 47.5686, lng: -122.2224 }
"Niwa Apartments": { lat: 47.6240, lng: -122.3565 }
"Ondine Eastlake": { lat: 47.6413, lng: -122.3252 }
"Ramesh House": { lat: 47.6689, lng: -122.3384 }
"Reverie Apartments": { lat: 47.5713, lng: -122.3117 }
"Rialto Court": { lat: 47.6186, lng: -122.3098 }
"Skandi Villa": { lat: 47.8127, lng: -122.3654 }
"The Palms": { lat: 47.6472, lng: -122.3249 }
"Viewmont Apartments": { lat: 47.6239, lng: -122.3242 }
"White Heather Apartments": { lat: 47.7155, lng: -122.2987 }
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
"Hill Town Apartments": "https://www.hilltownapartments.com/"
"Highway Place": "https://agmrealestategroup.appfolio.com/listings"
"Lorelei Apartments": "https://www.theloreleiapartments.com/"
"Mercer Tower": "https://www.mercertowerapartments.com/"
"Niwa Apartments": "https://www.niwaseattle.com/"
"Ondine Eastlake": "https://www.ondineeastlake.com/"
"Ramesh House": "https://agmrealestategroup.appfolio.com/listings"
"Reverie Apartments": "https://www.reveriebeaconhill.com/"
"Rialto Court": "https://www.rialtocourtapartments.com/"
"Skandi Villa": "https://www.skandivillaapartments.com/"
"The Palms": "https://www.thepalmseastlake.com/"
"Viewmont Apartments": "https://www.viewmontapts.com/"
"White Heather Apartments": "https://www.whiteheatherapts.com/"
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

After all changes are applied, print a structured text report to the user summarizing exactly what changed:

```
=== AGM Availabilities Update Report ===
Date: [today's date]
Total listings: [new count] (was [old count])

--- NEW LISTINGS ADDED ([count]) ---
- [Property] Unit [X]: $[rent], [beds]bd/[baths]ba, [sqft]sqft, Available: [date]
  (repeat for each new listing)

--- LISTINGS REMOVED ([count]) ---
- [Property] Unit [X]: was $[rent], [beds]bd/[baths]ba
  (repeat for each removed listing)

--- LISTINGS CHANGED ([count]) ---
- [Property] Unit [X]: rent $[old] → $[new]
- [Property] Unit [X]: available "[old]" → "[new]"
  (repeat for each changed listing, showing only changed fields)

--- NEW PROPERTIES ADDED ([count]) ---
- [Property Name] (Neighborhood: [X], Website: [URL])
  (repeat for each new property)

--- PROPERTIES REMOVED ([count]) ---
- [Property Name]
  (repeat for each removed property)

--- UNCHANGED LISTINGS ---
[count] listings carried over with no changes
```

This report lets the user verify correctness at a glance without diffing files.

---

### STEP 11: Commit and push

git add index.html
git commit -m "Update property availabilities from AppFolio"
git push

---

### Key gotchas to watch for:
1. **WebFetch truncates** — always use curl to download the full HTML
2. **Dual availability elements** — use `<dd class="detail-box__value js-listing-available">`, not the mobile span
3. **"Studio" is a string** — `"bedrooms": "Studio"` (with quotes), not an integer
4. **Bathrooms are floats** — always `1.0`, `1.5`, `2.0` (not integers)
5. **Missing sqft → 0** — never omit, never use null
6. **Sort alphabetically** — by property name first, then unit number
7. **New properties need user input** — don't guess neighborhoods, coordinates, or websites
8. **MFTE units** — detected by "MFTE" in AppFolio title text, get `["On-Site Laundry", "MFTE/MHA"]` features
9. **Address casing** — preserve exactly as AppFolio provides it
10. **Unit "Not Specified"** — when no unit pattern found in address (not empty string, not null)
11. **Tour booking** — powered by `propertyLeasingAgents`, not per-listing URLs. Ensure every property has an entry.
```
