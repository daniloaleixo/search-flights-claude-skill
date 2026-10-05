"""Turn the harvester's text dump into raw/search_rows.json.

The dump has two sections, one line per listing and one line per
(listing, date pair) price; see scripts/harvest.js for the format.
"""
import json
import os
import re
import sys


def parse_dump(text, pair_keys):
    section, listings, prices = None, {}, []
    lines = []
    for raw in text.splitlines():
        if raw.startswith("#") or re.match(r"^\d+\|", raw) or not lines:
            lines.append(raw)
        else:  # a listing name with an embedded newline
            lines[-1] += " " + raw.strip()
    for line in lines:
        if line.startswith("#LISTINGS"):
            section = "L"; continue
        if line.startswith("#PRICES"):
            section = "P"; continue
        if line.startswith("#END") or not line.strip():
            continue
        f = line.split("|")
        if section == "L":
            # id|box|title|name|info|rating|lat|lng|badges|pm  (name may contain '|')
            extra = len(f) - 10
            name = "|".join(f[3:4 + extra])
            f = f[:3] + [name] + f[4 + extra:]
            listings[f[0]] = dict(id=f[0], box=f[1], title=expand_title(f[2]), name=name.strip(),
                                  info=expand_info(f[4]), rating=f[5], lat=float(f[6]), lng=float(f[7]),
                                  badges=f[8], pm=expand_pm(f[9]))
        elif section == "P":
            lid, key, price, orig, box = f
            ci, co = pair_keys[key]
            prices.append(dict(id=lid, ci=ci, co=co, price=price, orig=orig, box=box))
    rows = []
    for p in prices:
        L = listings[p["id"]]
        rows.append({**L, "box": p["box"], "ci": p["ci"], "co": p["co"],
                     "price": p["price"], "orig": p["orig"], "qual": "total", "page": None})
    return rows


def expand_title(t):
    return t.replace("Apt@", "Apartment in ").replace("Condo@", "Condo in ")


def expand_info(info):
    """'3br,4bd,2ba' -> '3 bedrooms / 4 beds / 2 baths'."""
    parts = []
    for part in info.split(","):
        part = re.sub(r"^([\d.]+)br$", r"\1 bedrooms", part)
        part = re.sub(r"^([\d.]+) ?(\w*)bd$", lambda m: f"{m.group(1)} {m.group(2) + ' ' if m.group(2) else ''}beds", part)
        part = re.sub(r"^([\d.]+)ba$", r"\1 baths", part)
        parts.append(part)
    return " / ".join(parts)


def expand_pm(pm):
    return pm.replace("FC", "Free cancellation").replace("ESD", "Extended stay discount")


if __name__ == "__main__":
    run = sys.argv[1]
    params = json.load(open(os.path.join(run, "params.json")))
    keys = {chr(ord("A") + i): tuple(p) for i, p in enumerate(params["date_pairs"])}
    rows = parse_dump(open(os.path.join(run, "raw", "search_dump.txt"), encoding="utf-8").read(), keys)
    json.dump(rows, open(os.path.join(run, "raw", "search_rows.json"), "w"), ensure_ascii=False, indent=0)
    print(len(rows), "rows,", len({r["id"] for r in rows}), "listings")
