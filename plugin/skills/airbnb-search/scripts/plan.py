"""Print what the page scripts in harvest.js need, from params.json.

    python3 -m scripts.plan <run_dir> search        # BASE, BOXES, PAIRS
    python3 -m scripts.plan <run_dir> detail-ids    # listings worth opening, cheapest first
"""
import json
import os
import sys
from urllib.parse import quote


def search_inputs(params):
    s = params["search"]
    q = [f"adults={params['guests']}", f"currency={params.get('currency', 'EUR')}",
         "search_by_map=true", "zoom_level=16", "search_type=user_map_move"]
    if s.get("min_bedrooms"):
        q.append(f"min_bedrooms={s['min_bedrooms']}")
    if s.get("room_type"):
        q.append("room_types%5B%5D=" + quote(s["room_type"], safe=""))
    q += [f"amenities%5B%5D={a}" for a in s.get("amenity_ids", [])]
    cap = price_max(params)
    if cap:
        q.append(f"price_max={cap}&price_filter_input_type=0")
    base = "https://www.airbnb.com" + s["path"] + "?" + "&".join(q)
    boxes = {k: [b["ne"][0], b["ne"][1], b["sw"][0], b["sw"][1]] for k, b in s["boxes"].items()}
    return base, boxes, params["date_pairs"]


def price_max(params):
    """Airbnb's price slider is nightly, so turn the budget into the loosest
    nightly figure any date pair could need, plus 10 % headroom for fees the
    slider may not count. merge/build_board apply the exact cap afterwards."""
    from datetime import date
    nightly = []
    if params.get("budget_per_night"):
        nightly.append(params["budget_per_night"])
    if params.get("budget_total"):
        shortest = min((date.fromisoformat(b) - date.fromisoformat(a)).days for a, b in params["date_pairs"])
        nightly.append(params["budget_total"] / shortest)
    return int(max(nightly) * 1.1) if nightly else None


def detail_ids(run_dir):
    """Listings that pass every must-have the search alone can judge."""
    listings = json.load(open(os.path.join(run_dir, "listings.json")))
    keep = [L for L in listings if all(v is not False for v in L["must"].values())]
    keep.sort(key=lambda L: L["best_per_night"] or 1e9)
    return [L["id"] for L in keep]


if __name__ == "__main__":
    run, what = sys.argv[1], sys.argv[2]
    params = json.load(open(os.path.join(run, "params.json")))
    if what == "search":
        base, boxes, pairs = search_inputs(params)
        print("BASE =", json.dumps(base)); print("BOXES =", json.dumps(boxes)); print("PAIRS =", json.dumps(pairs))
    elif what == "detail-ids":
        ids = detail_ids(run)
        print(len(ids), file=sys.stderr); print(",".join(ids))
