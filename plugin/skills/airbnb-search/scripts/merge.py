"""Turn raw search rows (one per listing per date pair) into one record per
listing, with its price for every date pair it was offered on, its distance to
the beach, and its must-have / nice-to-have verdicts.

Usage:
    python3 -m scripts.merge <run_dir>

Reads  <run_dir>/params.json, <run_dir>/raw/search_rows.json and, when present,
<run_dir>/raw/details.json. Writes <run_dir>/listings.json.
"""
import json
import os
import re
import sys

from scripts.geo import blocks, distance_to_lines, load_lines

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def money(s):
    """'€1,234' -> 1234.0; '' -> None."""
    if not s:
        return None
    digits = re.sub(r"[^\d.]", "", s.replace(",", ""))
    return float(digits) if digits else None


def rating(s):
    """'4.84 (56)' -> (4.84, 56); 'New' -> (None, 0)."""
    m = re.match(r"([\d.]+)\s*\((\d+)\)", s or "")
    return (float(m.group(1)), int(m.group(2))) if m else (None, 0)


def info_numbers(info):
    """'3 bedrooms / 4 beds / 2 baths' -> dict of ints/floats."""
    out = {}
    for key, pat in (("bedrooms", r"([\d.]+)\s+bedroom"), ("beds", r"([\d.]+)\s+(?:[a-z-]+\s+)?beds?\b"),
                     ("baths", r"([\d.]+)\s+(?:shared\s+|private\s+)?bath")):
        m = re.search(pat, info or "", re.I)
        out[key] = float(m.group(1)) if m else None
    if re.search(r"\bstudio\b", info or "", re.I):
        out["bedrooms"] = 0
    return out


SQM = re.compile(r"(\d{1,3}(?:[.,]\d{3})+|\d{2,4})(?:[.,]\d+)?\s?(?:m²|m2\b|sqm|sq\.?\s?m\b|square\s?met|metros?\s?quadrados)", re.I)


def parse_sqm(text):
    """'It is 1,500 m2 on 3 floors' -> 1500.0; the host's own number, unchecked."""
    m = SQM.search(text or "")
    return float(re.sub(r"[.,]", "", m.group(1))) if m else None


def neighbourhood(title):
    m = re.search(r" in (.+)$", title or "")
    return m.group(1) if m else ""


def amenity_has(amen, patterns):
    return any(re.search(p, a, re.I) for a in amen for p in patterns)


def evaluate(listing, params):
    """Fill listing['must'] and listing['nice'] as {key: True/False/None}.

    None means unknown: the detail page was not read, so the listing is kept
    and marked rather than passed or failed on a guess.
    """
    det = listing.get("detail") or {}
    amen = det.get("amen")
    must, nice = {}, {}
    for item in params["must_have"]:
        must[item["key"]] = check(item, listing, amen, det)
    for item in params["nice_to_have"]:
        nice[item["key"]] = check(item, listing, amen, det)
    listing["must"], listing["nice"] = must, nice
    listing["must_ok"] = all(v is not False for v in must.values())
    listing["must_confirmed"] = all(v is True for v in must.values())


def check(item, listing, amen, det):
    kind = item["kind"]
    if kind == "amenity":
        if amen is None:
            # The search was run with the matching amenity filter, so the
            # listing self-reports it; still unconfirmed until read.
            return True if item.get("search_filtered") else None
        return amenity_has(amen, item["patterns"])
    if kind == "min_guests":
        cap = det.get("cap")
        return None if cap is None else cap >= item["value"]
    if kind == "min_bedrooms":
        b = listing.get("bedrooms")
        return None if b is None else b >= item["value"]
    if kind == "max_blocks":
        # A pin is blurred by up to ~150 m, so allow part of a block of slack.
        return listing["beach_m"] <= item["value"] * listing["_block_m"] + item.get("slack_m", 0)
    if kind == "min_sqm":
        s = listing.get("sqm")
        return None if s is None else s >= item["value"]
    if kind == "min_rating":
        r = listing.get("rating")
        return None if r is None else (r >= item["value"] and listing["reviews"] >= item.get("min_reviews", 0))
    if kind == "badge":
        return amenity_has([listing.get("badges", "")], item["patterns"])
    if kind == "payment_message":
        return amenity_has([listing.get("pm", "")], item["patterns"])
    if kind == "text":
        hay = [listing.get("name", "")] + ([det.get("desc", "")] if det else [])
        return amenity_has(hay + (amen or []), item["patterns"])
    raise ValueError(f"unknown criterion kind {kind!r}")


def merge(run_dir):
    params = json.load(open(os.path.join(run_dir, "params.json")))
    rows = json.load(open(os.path.join(run_dir, "raw", "search_rows.json")))
    det_path = os.path.join(run_dir, "raw", "details.json")
    details = json.load(open(det_path)) if os.path.exists(det_path) else {}
    lang = params.get("lang", "en")
    names_path = os.path.join(run_dir, "raw", f"names_{lang}.json")
    local_names = json.load(open(names_path)) if lang != "en" and os.path.exists(names_path) else {}
    lines = load_lines(os.path.join(SKILL_DIR, params["beach"]["lines"]))
    block_m = params["beach"]["block_m"]

    listings = {}
    for r in rows:
        if r["id"] in ("?", None):
            continue
        L = listings.setdefault(r["id"], {
            "id": r["id"], "title": r["title"], "name": r["name"],
            "area": neighbourhood(r["title"]), "lat": r["lat"], "lng": r["lng"],
            "badges": r["badges"], "pm": r["pm"], "prices": {}, "boxes": set(),
            **info_numbers(r["info"]),
        })
        L["rating"], L["reviews"] = rating(r["rating"])
        L["boxes"].add(r["box"])
        pair = f'{r["ci"]}_{r["co"]}'
        total = money(r["price"])
        if total is not None:
            nights = nights_between(r["ci"], r["co"])
            L["prices"][pair] = {"total": total, "orig": money(r["orig"]),
                                 "nights": nights, "per_night": round(total / nights, 2)}

    out = []
    for L in listings.values():
        L["boxes"] = sorted(L["boxes"])
        if L["id"] in local_names:
            L["name_local"] = local_names[L["id"]]["name"].strip()
        L["beach_m"] = round(distance_to_lines(L["lat"], L["lng"], lines))
        L["beach_blocks"] = blocks(L["beach_m"], block_m)
        L["_block_m"] = block_m
        d = details.get(L["id"])
        if d:
            L["detail"] = d
            L["sqm"] = parse_sqm(d.get("sqmCtx", "")) or (float(d["sqm"]) if d.get("sqm") else None)
            L["sqm_ctx"] = d.get("sqmCtx", "")
            for k in ("bedrooms", "beds", "baths"):
                if d.get(k) is not None:
                    L[k] = d[k]
        else:
            L["sqm"] = None
        if L["prices"]:
            best = min(L["prices"].items(), key=lambda kv: kv[1]["per_night"])
            L["best_pair"], L["best_per_night"] = best[0], best[1]["per_night"]
            L["min_total"] = min(p["total"] for p in L["prices"].values())
        else:
            L["best_pair"] = L["best_per_night"] = L["min_total"] = None
        evaluate(L, params)
        out.append(L)

    out.sort(key=lambda L: (L["best_per_night"] is None, L["best_per_night"] or 0))
    json.dump(out, open(os.path.join(run_dir, "listings.json"), "w"), indent=1, ensure_ascii=False)
    return out


def nights_between(ci, co):
    from datetime import date
    return (date.fromisoformat(co) - date.fromisoformat(ci)).days


if __name__ == "__main__":
    res = merge(sys.argv[1])
    ok = [L for L in res if L["must_ok"]]
    print(f"{len(res)} listings, {len(ok)} pass must-haves (incl. unknown)")
