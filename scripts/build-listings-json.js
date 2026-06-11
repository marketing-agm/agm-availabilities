#!/usr/bin/env node
// build-listings-json.js
// Regenerates listings.json from the canonical data embedded in index.html.
//
// index.html is the single source of truth for availabilities (updated by the
// daily AppFolio sync). The standalone book-a-tour pages read listings.json at
// runtime so they always reflect the same units. Run this after any change to
// the agmListings array in index.html:
//
//     node scripts/build-listings-json.js
//
// CI/sync note: the daily availabilities routine MUST run this step after
// updating index.html so the tour page stays in sync.

const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname, '..');
const indexPath = path.join(root, 'index.html');
const outPath = path.join(root, 'listings.json');

const html = fs.readFileSync(indexPath, 'utf8');

// Extract `const agmListings = [ ... ];`
const listingsMatch = html.match(/const agmListings = (\[[\s\S]*?\n\s*\]);/);
if (!listingsMatch) {
    console.error('ERROR: could not find the agmListings array in index.html');
    process.exit(1);
}
const listings = JSON.parse(listingsMatch[1]);

// Extract `const propertyLeasingAgents = { ... };`
function extractObject(name) {
    const m = html.match(new RegExp('const ' + name + ' = (\\{[\\s\\S]*?\\n\\s*\\});'));
    if (!m) {
        console.error('ERROR: could not find ' + name + ' in index.html');
        process.exit(1);
    }
    // The objects use unquoted-safe JS literals; evaluate in a sandboxed Function.
    return Function('return ' + m[1])();
}
const leasingAgents = extractObject('propertyLeasingAgents');

const out = {
    updatedAt: new Date().toISOString().slice(0, 10),
    listings,
    leasingAgents,
};

fs.writeFileSync(outPath, JSON.stringify(out, null, 2) + '\n');

// Sanity check: every property in listings should have a leasing agent.
const missing = [...new Set(listings.map((l) => l.property))].filter(
    (p) => !(p in leasingAgents)
);
if (missing.length) {
    console.warn('WARNING: listings reference properties with no leasing agent:', missing.join(', '));
}

console.log(
    'Wrote listings.json — ' +
        listings.length +
        ' listings, ' +
        Object.keys(leasingAgents).length +
        ' leasing agents'
);
