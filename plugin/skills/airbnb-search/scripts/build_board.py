"""Build the comparison board: one self-contained HTML page.

Usage:
    python3 -m scripts.build_board <run_dir> > board.html

Reads <run_dir>/params.json and <run_dir>/listings.json (written by merge.py).
All ranking happens in the page, so switching the date pair re-scores price.
"""
import html
import json
import os
import sys
from datetime import date

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "board_template.html")


def zone(L, params):
    """Area from the pin when params define zone boxes, else Airbnb's card title."""
    z = params.get("search", {}).get("zones")
    if not z:
        return L["area"] or ""
    for name, (ne_lat, ne_lng, sw_lat, sw_lng) in z["boxes"]:
        if sw_lat <= L["lat"] <= ne_lat and sw_lng <= L["lng"] <= ne_lng:
            return name
    return z["default"]


def slim(L, params):
    """Only what the page draws; descriptions and amenity lists stay on disk."""
    det = L.get("detail") or {}
    return {
        "id": L["id"], "name": L.get("name_local") or L["name"], "area": zone(L, params),
        "lat": L["lat"], "lng": L["lng"], "beach_m": L["beach_m"], "blocks": L["beach_blocks"],
        "bedrooms": L.get("bedrooms"), "beds": L.get("beds"), "baths": L.get("baths"),
        "cap": det.get("cap"), "sqm": L.get("sqm"), "sqm_ctx": (L.get("sqm_ctx") or "").replace("DemandStayListingPdpPresentationDescriptions UGCText", "").strip(), "rating": L.get("rating"), "reviews": L.get("reviews"),
        "badges": L.get("badges", ""), "prices": L["prices"],
        "must": L["must"], "nice": L["nice"], "detail_read": bool(det),
        "park": (det.get("park") or "")[:160],
        "parking_amenity": next((a for a in det.get("amen", []) if "parking" in a.lower() or "garage" in a.lower()), ""),
    }


MONTHS = {
    "en": "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(),
    "pt-BR": "jan fev mar abr mai jun jul ago set out nov dez".split(),
}
NIGHTS = {"en": "nights", "pt-BR": "noites"}


def pair_label(pair, lang="en"):
    """'22–27 Dec · 5 nights' / '22–27 dez · 5 noites'."""
    ci, co = (date.fromisoformat(d) for d in pair)
    months = MONTHS.get(lang, MONTHS["en"])
    nights = f"{(co - ci).days} {NIGHTS.get(lang, 'nights')}"
    if ci.month == co.month:
        return f"{ci.day}–{co.day} {months[ci.month - 1]} · {nights}"
    return f"{ci.day} {months[ci.month - 1]}–{co.day} {months[co.month - 1]} · {nights}"


def build(run_dir):
    params = json.load(open(os.path.join(run_dir, "params.json")))
    listings = json.load(open(os.path.join(run_dir, "listings.json")))
    data = {
        "destination": params["destination"],
        "guests": params["guests"],
        "lang": params.get("lang", "en"),
        "currency": params.get("currency", "EUR"),
        "budget": params.get("budget_total"),
        "budget_night": params.get("budget_per_night"),
        "pairs": [{"key": f"{a}_{b}", "ci": a, "co": b, "label": pair_label((a, b), params.get("lang", "en"))} for a, b in params["date_pairs"]],
        "must": [{k: m[k] for k in ("key", "label")} for m in params["must_have"]],
        "nice": [{k: n[k] for k in ("key", "label", "weight")} for n in params["nice_to_have"]],
        "weights": params["rank_weights"],
        "block_m": params["beach"]["block_m"],
        "searched": len(listings),
        "zones": ([b[0] for b in params["search"]["zones"]["boxes"]] + [params["search"]["zones"]["default"]]) if params.get("search", {}).get("zones") else [],
        "listings": [slim(L, params) for L in listings],
        "captured": params.get("captured", ""),
    }
    page = open(TEMPLATE, encoding="utf-8").read()
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return (page.replace("__DATA__", payload)
                .replace("__TITLE__", html.escape(params.get("board_title", "Stay Shortlist"))))


if __name__ == "__main__":
    sys.stdout.write(build(sys.argv[1]))
