"""Night-layover economics, coverage checks, and expansion selection.

A night layover does not disqualify a trip; it obliges the trip to be
considerably cheaper. "Considerably" is a saving of at least 150 EUR or at
least 20% against the cheapest trip in the run that has no night layover.
The absolute floor binds on expensive fares, the percentage on cheap ones.

The comparison is made on what the trip costs from the front door, not on
its fare. An airport six hours away by train sells a fare that is not the
price of going there, and ranking on fares alone recommended Amsterdam at
933 EUR over Berlin at 939 on the first Sao Paulo run, when the Amsterdam
trip carried 120 to 240 EUR of rail on top and Berlin carried none. Fares
stay untouched; `door_lo_eur` and `door_hi_eur` sit beside them, and every
comparison here reads those.
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


def ground_band(params):
    """One-way ground cost per airport, as a (low, high) pair.

    Read from `ground_cost` in the params file, which mirrors the prose
    table in references/ground.md. A code absent here has no band, and a
    trip touching it gets no door-to-door figure at all, rather than one
    with a missing end quietly set to zero.
    """
    out = {}
    for code, band in (params.get("ground_cost") or {}).items():
        low, high = band
        if low > high:
            raise ValueError(f"ground_cost[{code!r}] is inverted: {band!r}")
        out[code] = (low, high)
    return out


def door_to_door(trip, bands):
    """Fare plus the ground journey at both ends, as a (low, high) band.

    The fare itself is never touched. This is a second number shown beside
    it, not a correction to it: an estimate added to a price stops being a
    price, so the two travel separately and the reader sees both.

    A round trip pays the same journey twice, out and back. An open jaw
    pays the outbound origin's journey and the return airport's. Either end
    missing a band returns (None, None), because a door-to-door figure
    missing one of its two journeys is not a door-to-door figure.
    """
    fare = trip.get("price_eur")
    if fare is None:
        return (None, None)
    out_code = trip.get("origin")
    back_code = trip.get("ret_airport") or out_code
    try:
        out_band = bands[out_code]
        back_band = bands[back_code]
    except KeyError:
        return (None, None)
    return (fare + out_band[0] + back_band[0],
            fare + out_band[1] + back_band[1])


def apply_ground_cost(trips, params):
    """Attach the door-to-door band to every trip."""
    bands = ground_band(params)
    for trip in trips:
        low, high = door_to_door(trip, bands)
        trip["door_lo_eur"] = low
        trip["door_hi_eur"] = high
    return trips


def cost_band(trip):
    """What the trip costs from the front door, low and high.

    Falls back to the bare fare when no ground band was attached, which
    collapses the band to a point and makes every comparison below behave
    exactly as it did before ground cost existed.
    """
    low = trip.get("door_lo_eur")
    high = trip.get("door_hi_eur")
    if low is None or high is None:
        return (trip["price_eur"], trip["price_eur"])
    return (low, high)


def night_baseline(trips):
    """Cheapest trip with no night layover whose legs were actually examined.

    Ranked on the low end of its door-to-door band rather than on its fare.
    The baseline is the bar every night layover has to clear, and a fare
    that arrives with a 240 EUR train attached sets a different bar than
    the same fare on the doorstep.

    Unexpanded trips are excluded: their night status is unknown, and an
    unknown is not a clean.
    """
    clean = [t for t in trips
             if t.get("legs_expanded") and t.get("night_layover") is False]
    return min(clean, key=lambda t: cost_band(t)[0], default=None)


def night_saving_band(trip, baseline):
    """What the night layover saves against the baseline, low and high.

    Both sides carry a range once ground cost is in them, so the saving
    carries one too: the low end pairs the baseline's cheapest ground with
    the trip's dearest, the high end does the reverse. With no ground data
    both ends collapse onto the fare difference.
    """
    base_lo, base_hi = cost_band(baseline)
    trip_lo, trip_hi = cost_band(trip)
    return (base_lo - trip_hi, base_hi - trip_lo)


def night_verdict(trip, baseline, abs_eur=DEFAULT_ABS_EUR, pct=DEFAULT_PCT):
    """clean, justified, borderline, not_justified, or unknown.

    `borderline` exists because the saving is a range, not a number, once
    ground cost is inside it. A trip that clears the bar at one end of its
    ground estimate and misses at the other has not earned a verdict, and
    saying so is more honest than picking whichever end settles it. With no
    ground data the range is a point and borderline never occurs.
    """
    if not trip.get("legs_expanded") or trip.get("night_layover") is None:
        return "unknown"
    if trip["night_layover"] is False:
        return "clean"
    if baseline is None:
        return "unknown"
    threshold = min(abs_eur, cost_band(baseline)[0] * pct / 100)
    low, high = night_saving_band(trip, baseline)
    if low >= threshold:
        return "justified"
    if high < threshold:
        return "not_justified"
    return "borderline"


def apply_night_economics(trips, params):
    discount = params.get("night_discount") or {}
    abs_eur = discount.get("abs_eur", DEFAULT_ABS_EUR)
    pct = discount.get("pct", DEFAULT_PCT)
    apply_ground_cost(trips, params)
    baseline = night_baseline(trips)

    for trip in trips:
        verdict = night_verdict(trip, baseline, abs_eur, pct)
        trip["night_verdict"] = verdict
        trip["is_baseline"] = bool(baseline and trip is baseline)
        if verdict in ("justified", "borderline", "not_justified"):
            low, high = night_saving_band(trip, baseline)
            trip["night_saving_eur"] = low
            trip["night_saving_hi_eur"] = high
            trip["night_saving_pct"] = round(
                low * 100 / cost_band(baseline)[0], 1)
        else:
            trip["night_saving_eur"] = None
            trip["night_saving_hi_eur"] = None
            trip["night_saving_pct"] = None
    return trips


class BaselineError(RuntimeError):
    """A trip nobody expanded undercuts the night baseline."""


def assert_baseline_sound(trips):
    """Refuse a board whose baseline an unexamined trip undercuts.

    Every night verdict on the board is measured against one row: the
    cheapest expanded trip with no night layover. If a trip nobody expanded
    is cheaper still and would have turned out clean, that row was the real
    baseline, the bar was set too high, and every not_justified verdict is
    wrong in the same direction. Expansion runs cheapest-first, so this
    usually holds by itself. Holding by itself is not the same as checked.

    A row flagged `expansion_missing` is exempt. Fares and result sets move
    between the capture pass and the expansion pass, so an itinerary that
    was on the page an hour ago is sometimes not on it now. That row has
    been looked for and it is gone; blocking the whole board on a row
    nobody can reach again would only mean never publishing.
    """
    baseline = night_baseline(trips)
    if baseline is None:
        return
    limit = cost_band(baseline)[0]
    under = [t for t in trips
             if not t.get("legs_expanded")
             and not t.get("expansion_missing")
             and t.get("price_eur") is not None
             and cost_band(t)[0] < limit]
    if under:
        cheapest = min(under, key=lambda t: cost_band(t)[0])
        raise BaselineError(
            f"{len(under)} unexpanded trips come in under the {limit:g} "
            f"baseline, cheapest {cheapest.get('origin')} at "
            f"{cost_band(cheapest)[0]:g}: expand them first, because a clean "
            f"trip among them would move the bar every verdict is measured "
            f"against")


def missing_origins(rows, expected):
    """Origins the sweep never returned.

    Absence from a capped result list is not evidence of expense, so these
    need their own searches before the run may say anything about them.
    """
    seen = {r["origin"] for r in rows}
    return [code for code in expected if code not in seen]


def itinerary_key(trip):
    """What identifies one itinerary across the rows that share it.

    One expansion opens one detail panel and its per-leg times apply to
    every row with the same shape. Price is not part of the key: fares move
    between page loads, so an expansion is matched to rows by what does not
    move.
    """
    return (trip.get("origin"), trip.get("dep_time"), trip.get("arr_time"),
            tuple(l.get("code") for l in (trip.get("layovers") or ())))


def _origin_shortfall(trips, pending, per_origin, clean_per_origin,
                      max_per_origin):
    """One pending row per origin that has not had its share of expansions.

    Counted in itineraries, not rows: one expansion propagates to every row
    sharing its shape, so counting rows would report an origin as
    thoroughly examined after a single detail panel.
    """
    seen_shapes, clean_shapes = {}, {}
    for trip in trips:
        if not trip.get("legs_expanded"):
            continue
        origin = trip.get("origin")
        seen_shapes.setdefault(origin, set()).add(itinerary_key(trip))
        if trip.get("night_layover") is False:
            clean_shapes.setdefault(origin, set()).add(itinerary_key(trip))

    picks, taken = [], set()
    for trip in pending:
        origin = trip.get("origin")
        if origin in taken:
            continue
        done = len(seen_shapes.get(origin, ()))
        if done >= max_per_origin:
            continue
        if done < per_origin or len(clean_shapes.get(origin, ())) < clean_per_origin:
            taken.add(origin)
            picks.append(trip)
    return picks


def expansion_targets(trips, want=12, want_clean=3, per_origin=1,
                      clean_per_origin=1, max_per_origin=6):
    """The next batch of trips to expand, cheapest first.

    Origins come first. Every origin gets `per_origin` expansions, and then
    keeps getting one per batch until it has `clean_per_origin` trips with
    no night layover or has spent `max_per_origin` expansions trying.
    Without that floor the batch is drawn from one end of the price range
    and a mid-priced origin can finish the run with nothing said about it:
    on the first Sao Paulo run Hamburg was never expanded once, and Berlin,
    the only airport with no ground journey attached, got two expansions
    and no clean result. The board could say least about the airports the
    reader was most able to use.

    Expansion otherwise stops on a condition rather than a count: keep going
    until `want` trips are expanded and at least `want_clean` of them turned
    out to have no night layover. Night status is only known after
    expanding, so the caller loops, calling this again after each batch
    until it returns [].
    """
    expanded = [t for t in trips if t.get("legs_expanded")]
    clean = [t for t in expanded if t.get("night_layover") is False]
    pending = sorted(
        (t for t in trips if not t.get("legs_expanded")),
        key=lambda t: t["price_eur"])

    starved = _origin_shortfall(trips, pending, per_origin, clean_per_origin,
                                max_per_origin)
    if len(expanded) < want:
        budget = want - len(expanded)
    elif len(clean) < want_clean:
        budget = want_clean - len(clean)
    else:
        budget = 0
    if not starved and budget <= 0:
        return []

    picks = list(starved)
    already = {id(t) for t in picks}
    room = max(budget, len(picks))
    for trip in pending:
        if len(picks) >= room:
            break
        if id(trip) not in already:
            picks.append(trip)
            already.add(id(trip))
    return picks
