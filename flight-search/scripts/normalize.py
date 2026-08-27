"""Night-layover economics, coverage checks, and expansion selection.

A night layover does not disqualify a trip; it obliges the trip to be
considerably cheaper. "Considerably" is a saving of at least 150 EUR or at
least 20% against the cheapest trip in the run that has no night layover.
The absolute floor binds on expensive fares, the percentage on cheap ones.
"""

from datetime import datetime, time, timedelta

NIGHT_START = time(23, 0)
NIGHT_END = time(6, 0)
DEFAULT_ABS_EUR = 150
DEFAULT_PCT = 20


def layover_windows(legs, window=(NIGHT_START, NIGHT_END)):
    """Clock windows between consecutive legs, in local time at the stop.

    `window` is the night band checked against each layover; it defaults to
    23:00-06:00 but a caller holding `params["night_layover_window"]` should
    pass it through here rather than relying on the default, so a run that
    configured a different band actually gets it applied.
    """
    out = []
    for first, second in zip(legs, legs[1:]):
        start = datetime.fromisoformat(first["arr_local"])
        end = datetime.fromisoformat(second["dep_local"])
        out.append({
            "code": first["to"],
            "start": first["arr_local"],
            "end": second["dep_local"],
            "minutes": int((end - start).total_seconds() // 60),
            "night_flag": is_night_layover(
                first["arr_local"], second["dep_local"], window),
        })
    return out


def is_night_layover(start_iso, end_iso, window=(NIGHT_START, NIGHT_END)):
    """True if the layover overlaps 23:00-06:00 on any night it spans.

    Touching an endpoint does not count: a layover ending exactly at 23:00
    has spent no time in the band.
    """
    night_start, night_end = window
    if isinstance(night_start, str):
        night_start = time.fromisoformat(night_start)
    if isinstance(night_end, str):
        night_end = time.fromisoformat(night_end)

    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso)

    day = start.date() - timedelta(days=1)
    while day <= end.date():
        band_start = datetime.combine(day, night_start)
        band_end = datetime.combine(day + timedelta(days=1), night_end)
        if start < band_end and end > band_start:
            return True
        day += timedelta(days=1)
    return False


def night_baseline(trips):
    """Cheapest trip with no night layover whose legs were actually examined.

    Unexpanded trips are excluded: their night status is unknown, and an
    unknown is not a clean.
    """
    clean = [t for t in trips
             if t.get("legs_expanded") and t.get("night_layover") is False]
    return min(clean, key=lambda t: t["price_eur"], default=None)


def night_verdict(trip, baseline, abs_eur=DEFAULT_ABS_EUR, pct=DEFAULT_PCT):
    if not trip.get("legs_expanded") or trip.get("night_layover") is None:
        return "unknown"
    if trip["night_layover"] is False:
        return "clean"
    if baseline is None:
        return "unknown"
    threshold = min(abs_eur, baseline["price_eur"] * pct / 100)
    saving = baseline["price_eur"] - trip["price_eur"]
    return "justified" if saving >= threshold else "not_justified"


def apply_night_economics(trips, params):
    discount = params.get("night_discount") or {}
    abs_eur = discount.get("abs_eur", DEFAULT_ABS_EUR)
    pct = discount.get("pct", DEFAULT_PCT)
    baseline = night_baseline(trips)

    for trip in trips:
        verdict = night_verdict(trip, baseline, abs_eur, pct)
        trip["night_verdict"] = verdict
        trip["is_baseline"] = bool(baseline and trip is baseline)
        if verdict in ("justified", "not_justified"):
            saving = baseline["price_eur"] - trip["price_eur"]
            trip["night_saving_eur"] = saving
            trip["night_saving_pct"] = round(
                saving * 100 / baseline["price_eur"], 1)
        else:
            trip["night_saving_eur"] = None
            trip["night_saving_pct"] = None
    return trips


def missing_origins(rows, expected):
    """Origins the sweep never returned.

    Absence from a capped result list is not evidence of expense, so these
    need their own searches before the run may say anything about them.
    """
    seen = {r["origin"] for r in rows}
    return [code for code in expected if code not in seen]


def expansion_targets(trips, want=12, want_clean=3):
    """The next batch of trips to expand, cheapest first.

    Expansion stops on a condition rather than a count: keep going until
    `want` trips are expanded and at least `want_clean` of them turned out to
    have no night layover. Night status is only known after expanding, so the
    caller loops, calling this again after each batch until it returns [].
    """
    expanded = [t for t in trips if t.get("legs_expanded")]
    clean = [t for t in expanded if t.get("night_layover") is False]
    if len(expanded) >= want and len(clean) >= want_clean:
        return []
    pending = sorted(
        (t for t in trips if not t.get("legs_expanded")),
        key=lambda t: t["price_eur"])
    if len(expanded) < want:
        return pending[:want - len(expanded)]
    return pending[:want_clean - len(clean)]
