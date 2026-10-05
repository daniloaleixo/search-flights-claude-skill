---
name: airbnb-search
description: Search Airbnb for every stay that fits a must-have / nice-to-have matrix across flexible dates and publish a ranked comparison board. Use when the user wants Airbnb listings found, filtered by hard requirements (amenities, guests, distance to a beach or landmark), and compared on price, features and reviews, or wants to know which date combination is cheapest.
---

Drive Airbnb from inside a logged-in Chrome tab, harvest every result page for
every date combination, open each surviving listing to confirm what the
search card can't show, and publish one sortable board.

## The rules that govern everything

**Never record a price the search did not return.** Every price on the board
is the total Airbnb's own results page offered for that exact check-in and
check-out, read from the page's embedded data. The "± 1 day" flexible-date
toggle is not used: it returns a blended set where you cannot tell which
dates a price belongs to. Instead, every date combination is its own search
(22–27, 22–28, 23–27, 23–28 for "22 or 23 until 27 or 28").

**A search that returns 270 listings was truncated.** Airbnb serves at most
15 pages of 18. On the Rio run, one map box covering Ipanema + Copacabana
returned exactly 270 for every date pair while the page said 354 existed.
Split the area into boxes that each return fewer than 270, and dedupe by
listing id. `harvest.js` marks a capped search `TRUNCATED`.

**A must-have is either confirmed on the listing page or it is unknown.**
The search's amenity filter is the host's self-report and is good enough to
narrow the search, not to pass the listing. Every listing that survives the
cheap checks gets its page opened: guest capacity, the amenity list (with
what's explicitly missing), and the description. Square metres come only
from the description; when the host doesn't state it, the board says so
rather than guessing.

**Distance is from a blurred pin.** Airbnb moves map pins by up to ~150 m.
Measure from the pin to the real beachfront road (OpenStreetMap geometry in
`references/`), convert to blocks with a measured block length, and give the
cutoff some slack (`slack_m`) rather than cutting at the exact metre.

## Where things live

`$SKILL` is this folder (`$CLAUDE_PLUGIN_ROOT/skills/airbnb-search` when
installed as a plugin). Runs go under the working directory as
`airbnb-runs/<date>-<place>/`, never beside the scripts. Every Python
command runs from `$SKILL` (`cd "$SKILL"` then `python3 -m scripts.<x>`).

## Running a search

1. **Turn the request into params.** Copy `params.example.json` into the run
   directory as `params.json`. Ask only for what the request leaves open.
   - `date_pairs`: every check-in × check-out combination the user can live with.
   - `must_have` / `nice_to_have`: the user's matrix. Each criterion has a
     `kind` (`amenity`, `min_guests`, `min_bedrooms`, `max_blocks`,
     `min_sqm`, `min_rating`, `badge`, `payment_message`, `text`) and
     regex `patterns` matched against amenity titles / description. Nice-to-haves
     carry a `weight`. Something the user says "ideally" about is a
     nice-to-have, not a must-have (the Rio run kept 2-bedroom places and
     weighted 3 bedrooms at 3).
   - `search.amenity_ids`: Airbnb's filter ids for the must-have amenities
     (verified on the Rio run by the filter chips the page displayed: Wifi 4,
     Air conditioning 5, Free parking on premises 9). Any other id, check the
     same way before trusting it: load the search and confirm the chip row
     names the amenity. Only filter on must-haves.
   - `budget_total` / `budget_per_night`: either cap is enough to qualify (the
     Rio user said "not more than 1200 euros, or no more than 250 per day").
     `plan.py` turns them into Airbnb's `price_max` so the harvest skips
     listings far over budget; the exact cap is applied afterwards on the
     all-in total, since the slider is nightly and may exclude fees.
   - `lang` (`en` or `pt-BR`): the board's language, plus criterion `label`s
     written in it. Listing names come back auto-translated from airbnb.com;
     for a non-English board, rerun the search loop on the country domain
     (airbnb.com.br, `&locale=pt`) collecting only names, and save them as
     `raw/names_<lang>.json`, which `merge` uses in place of the English names.
   - `search.boxes`: map boxes covering the target area. If the user gave a
     distance limit, draw the boxes only that far out plus ~200 m.
   - `beach`: polyline file and block length. For a new city, fetch the
     beachfront roads from Nominatim (`polygon_geojson=1`, set a User-Agent;
     Overpass often times out) and save under `references/`. Calibrate
     `block_m` on two known points (Rio: ~130 m).

2. **Open a tab** on `https://www.airbnb.com/` (`tabs_context_mcp`, then a
   new tab), decline non-essential cookies, and run step 1 of
   `scripts/harvest.js` with the values from
   `python3 -m scripts.plan <run> search`. Poll until `done`. Any log line
   with `TRUNCATED` means split that box and rerun.

3. **Move the rows to disk** with step 2 then step 3 of `harvest.js`
   (start `scripts/receive.py <run>/raw` in the background first). Then:

       python3 -m scripts.ingest_dump <run>
       python3 -m scripts.merge <run>

4. **Open every survivor.** `python3 -m scripts.plan <run> detail-ids` lists
   the listings passing the cheap checks, cheapest first. Navigate the tab
   back to any airbnb.com page, run step 2b with those ids, poll, then move
   `JSON.stringify(window.__D.out)` to `<run>/raw/details.json` with step 3.
   Budget about 4 s per listing (355 took ~25 min). Re-run `merge`.

5. **Build and publish the board**:

       python3 -m scripts.build_board <run> > <run>/board.html

   Publish it as an Artifact. The board ranks in the page: the user can
   switch the date pair (or "cheapest of N"), rank by overall / price /
   features / reviews / beach / size, filter by area and 3+ bedrooms, and
   see the excluded listings with the must-have each one failed.

6. **Recheck before recommending.** A captured price is a fact about the
   moment it was captured. Before naming a winner, open its listing for the
   chosen dates and read the booking panel total.

## Ranking

Score = `rank_weights.price` × price rank on the selected dates (percentile,
so one €10k penthouse doesn't flatten everything else) +
`rank_weights.features` × weighted share of nice-to-haves met +
`rank_weights.reviews` × rating shrunk toward 4.6 by 3 phantom reviews
(a 5.0 from 3 reviews ranks below a 4.9 from 200).

## Getting data out of the tab

The `javascript_tool` bridge truncates returns at about a thousand
characters and refuses any that contain a query string; `get_page_text`
stops at 50k characters; airbnb.com's CSP blocks `fetch` to localhost; a
script-driven `execCommand('copy')` is refused. What works is `window.name`,
which survives navigation in the same tab: park the payload there, navigate
to the local receiver, POST it from that page. Navigating away discards the
harvest's in-page state, so only do it after the poll says `done`.
