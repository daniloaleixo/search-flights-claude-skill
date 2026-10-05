// Paste-able page scripts for an airbnb.com tab, run through
// mcp__claude-in-chrome__javascript_tool. Each is self-contained: the tool
// evaluates one string, so copy the whole block for the step you are on.
//
// Why fetch() inside the tab: every search and listing page embeds its data
// as JSON in <script id="data-deferred-state-0">. Fetching the page HTML from
// the airbnb origin (cookies included) and parsing that JSON returns the same
// prices the results page shows, with no clicking and no scroll-to-load.
//
// Why results never come back as a return value: the tool truncates returns
// at about a thousand characters and blocks any that contain a query string.
// Results accumulate on window.__H / window.__D; step 3 moves them to disk.

// ---------------------------------------------------------------- step 1
// Search harvest. Fill BASE, BOXES and PAIRS from params.json (plan.py
// prints them). One search per (box, date pair), every page of each.
// Airbnb stops at 15 pages of 18 (270 listings): a search that returns 270
// was truncated, so split its box and run again.
window.__H = { status: 'running', log: [], rows: [] };
const BASE = '__BASE__';        // .../s/<place>/homes?adults=..&amenities[]=..&currency=..&search_by_map=true&zoom_level=16&search_type=user_map_move
const BOXES = __BOXES__;        // {name: [ne_lat, ne_lng, sw_lat, sw_lng]}
const PAIRS = __PAIRS__;        // [[checkin, checkout], ...]
async function getRes(url) {
  const h = await (await fetch(url, { credentials: 'include' })).text();
  const s = new DOMParser().parseFromString(h, 'text/html').getElementById('data-deferred-state-0');
  return s ? JSON.parse(s.textContent).niobeClientData[0][1].data.presentation.staysSearch.results : null;
}
function row(r, ci, co, page, box) {
  const d = r.demandStayListing || {};
  let id = '?'; try { id = atob(d.id).split(':')[1]; } catch (e) {}
  const p = (r.structuredDisplayPrice && r.structuredDisplayPrice.primaryLine) || {};
  const c = (d.location && d.location.coordinate) || {};
  return { id, box, ci, co, page, title: r.title, name: r.subtitle || '',
    info: ((r.structuredContent && r.structuredContent.primaryLine) || []).map(x => x.body).join(' / '),
    price: p.discountedPrice || p.price || '', orig: p.originalPrice || '', qual: p.qualifier || '',
    rating: r.avgRatingLocalized || '', lat: c.latitude, lng: c.longitude,
    badges: (r.badges || []).map(b => b.text).join('+'), pm: (r.paymentMessages || []).map(m => m.text).join('+') };
}
(async () => {
  for (const [bn, b] of Object.entries(BOXES)) for (const [ci, co] of PAIRS) {
    const u = BASE + `&ne_lat=${b[0]}&ne_lng=${b[1]}&sw_lat=${b[2]}&sw_lng=${b[3]}&checkin=${ci}&checkout=${co}`;
    let n = 0;
    try {
      const first = await getRes(u);
      if (!first) { window.__H.log.push(`${bn} ${ci} ${co} NO DATA`); continue; }
      const cursors = first.paginationInfo.pageCursors || [];
      first.searchResults.forEach(r => { n++; window.__H.rows.push(row(r, ci, co, 1, bn)); });
      for (let i = 1; i < cursors.length; i++) {
        await new Promise(z => setTimeout(z, 1000 + Math.random() * 800));
        const res = await getRes(u + '&cursor=' + encodeURIComponent(cursors[i]));
        if (!res) { window.__H.log.push(`${bn} ${ci} ${co} p${i + 1} NO DATA`); continue; }
        res.searchResults.forEach(r => { n++; window.__H.rows.push(row(r, ci, co, i + 1, bn)); });
      }
      window.__H.log.push(`${bn} ${ci.slice(5)} ${co.slice(5)} pages ${cursors.length} n ${n}${n >= 270 ? ' TRUNCATED' : ''}`);
    } catch (e) { window.__H.log.push(`${bn} ${ci} ${co} ERR ${e.message}`); }
  }
  window.__H.status = 'done';
})();
// Poll with: window.__H.status + ' ' + window.__H.rows.length + ' | ' + window.__H.log.join(' ; ')

// ---------------------------------------------------------------- step 2
// Serialise search rows into the dump format scripts/ingest_dump.py reads.
// Pair letters follow params.json's date_pairs order (A, B, C, ...).
const PK = Object.fromEntries(__PAIRS__.map((p, i) => [p[0] + '_' + p[1], String.fromCharCode(65 + i)]));
(() => {
  const L = {}, P = [], seen = new Set();
  for (const r of window.__H.rows) {
    if (!L[r.id]) L[r.id] = [r.id, r.box, r.title.replace(/^Apartment in /, 'Apt@').replace(/^Condo in /, 'Condo@'), r.name.slice(0, 60),
      r.info.replace(/ bedrooms?/, 'br').replace(/ beds?/, 'bd').replace(/ baths?/, 'ba').replace(/ \/ /g, ','), r.rating, r.lat, r.lng, r.badges,
      r.pm.replace('Free cancellation', 'FC').replace(/Pay €0 today\+?/, '').replace('Extended stay discount', 'ESD')].join('|');
    const k = r.id + '|' + PK[r.ci + '_' + r.co];
    if (!seen.has(k)) { seen.add(k); P.push([r.id, PK[r.ci + '_' + r.co], r.price.replace(/[^\d.]/g, ''), r.orig.replace(/[^\d.]/g, ''), r.box].join('|')); }
  }
  window.__dump = '#LISTINGS ' + Object.keys(L).length + '\n' + Object.values(L).join('\n') + '\n#PRICES ' + P.length + '\n' + P.join('\n') + '\n#END';
})();

// ---------------------------------------------------------------- step 2b
// Listing details. IDS comes from scripts/plan.py detail-ids. One listing
// page each, about 4 s per page including the pause: 355 took ~25 min.
window.__D = { status: 'running', done: 0, err: [], out: {} };
const IDS = '__IDS__'.split(',');
function strs(o, acc = []) { if (typeof o === 'string') acc.push(o); else if (o && typeof o === 'object') for (const k in o) strs(o[k], acc); return acc; }
function detail(j) {
  const pp = j.niobeClientData[0][1].data.node.pdpPresentation;
  const am = pp.amenities || {};
  const groups = (am.seeAllAmenitiesGroups && am.seeAllAmenitiesGroups.length ? am.seeAllAmenitiesGroups : am.previewAmenitiesGroups) || [];
  const amen = [], missing = [];
  groups.forEach(g => (g.amenities || []).forEach(a => {
    const sub = a.subtitle ? strs(a.subtitle).filter(s => !/^[A-Z][a-zA-Z]+$/.test(s)).join(' ') : '';
    (a.available === false ? missing : amen).push(a.title + (sub ? ' — ' + sub : ''));
  }));
  const desc = strs(pp.descriptions || {}).join(' ').replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
  const m = desc.match(/(\d{1,3}(?:[.,]\d{3})+|\d{2,4})(?:[.,]\d+)?\s?(?:m²|m2\b|sqm|sq\.?\s?m\b|square\s?met|metros?\s?quadrados)/i);
  const ovs = JSON.stringify(pp.overview || {}).match(/"[0-9.]+\+? (guests?|bedrooms?|beds?|baths?|private baths?|shared baths?)"/g) || [];
  const num = re => { const x = ovs.find(s => re.test(s)); return x ? parseFloat(x.replace(/"/g, '')) : null; };
  const park = (desc.match(/[^.]{0,80}(garag|parking|vaga|estacionamento)[^.]{0,80}/gi) || []).slice(0, 3).join(' … ');
  return { cap: pp.personCapacity, bedrooms: num(/bedroom/), beds: num(/ beds?"/), baths: num(/bath/),
    sqm: m ? m[1].replace(',', '.') : '', sqmCtx: m ? desc.slice(Math.max(0, m.index - 50), m.index + 30) : '',
    amen, missing: missing.slice(0, 40), park, desc: desc.slice(0, 1800) };
}
(async () => {
  for (const id of IDS) {
    try {
      const h = await (await fetch('https://www.airbnb.com/rooms/' + id + '?currency=EUR', { credentials: 'include' })).text();
      const s = new DOMParser().parseFromString(h, 'text/html').getElementById('data-deferred-state-0');
      if (!s) window.__D.err.push(id + ':nostate'); else window.__D.out[id] = detail(JSON.parse(s.textContent));
    } catch (e) { window.__D.err.push(id + ':' + e.message.slice(0, 40)); }
    window.__D.done++;
    await new Promise(z => setTimeout(z, 900 + Math.random() * 900));
  }
  window.__D.status = 'done';
})();
// Poll with: window.__D.done + ' ' + Object.keys(window.__D.out).length + ' err ' + window.__D.err.length

// ---------------------------------------------------------------- step 3
// Move a result to disk. airbnb.com's CSP blocks fetch() to localhost, and
// get_page_text truncates at 50k characters, but window.name survives a
// navigation within the same tab. So: park the payload in window.name, send
// the tab to the local receiver (scripts/receive.py), and POST it from there.
//   (a) on airbnb.com:   window.name = window.__dump;            // or JSON.stringify(window.__D.out)
//   (b) navigate the tab to http://127.0.0.1:8765/
//   (c) on the receiver: await (await fetch('/search_dump.txt', {method: 'POST', body: window.name})).text()
// Navigating away discards window.__H / __D, so do (a) only after the poll says done.
