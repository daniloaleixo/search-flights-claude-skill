"""Render the fare board a person actually reads to pick a flight.

Three matrix builders and one renderer. The matrices all answer the same
shape of question ("cheapest trip in this cell") over different axes, so
they share one reducer and one price scale.

Why there are two airport views
-------------------------------
`origin_matrix` is the headline because it is the only airport view the
sweep genuinely supports. A multi-city result row describes the outbound
leg; Google does not commit to a return airport until an itinerary is
expanded, so `ret_airport` is None on nearly every ingested trip. Pinning
the return airport per search would cost 36 searches per date pair instead
of one.

`airport_matrix` is kept exactly as specified and rendered as a secondary
view, populated only from trips that were expanded far enough to name a
return airport. Its empty cells are honest: they say "not determined",
never a blank and never a zero, because a blank cell reads as cheap and a
zero reads as free. Both are lies about a number nobody measured.
"""

from html import escape as esc

MONTH_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

#: Steps in the sequential price ramp. Step 6 is the cheapest, and the
#: darkest, so the answer to the page's question is the thing that pops.
SEQ_STEPS = 6

#: Categorical slots for carriers, in fixed order. Slot 1 of the reference
#: palette (blue) is spent on the sequential price ramp, so carriers start
#: at slot 2 and never cycle. Validated in both modes against this page's
#: own surfaces; worst adjacent CVD delta-E 9.1 light / 8.4 dark.
CARRIER_SLOTS = 7

NIGHT_LABELS = {
    "clean": "no night layover",
    "justified": "night layover, pays for itself",
    "not_justified": "night layover, does not pay",
    "unknown": "not checked",
}


# --------------------------------------------------------------------------
# matrices
# --------------------------------------------------------------------------

def _cheaper(current, candidate):
    if current is None:
        return candidate
    if candidate["price_eur"] < current["price_eur"]:
        return candidate
    return current


def origin_matrix(trips, origins, date_pairs):
    """Cheapest trip per (origin, date pair).

    Keyed `(origin, (dep_date, ret_date))`. Every combination gets a key;
    combinations the sweep never returned hold None.
    """
    pairs = [tuple(pair) for pair in date_pairs]
    cells = {(origin, pair): None for origin in origins for pair in pairs}
    for trip in trips:
        key = (trip.get("origin"), (trip.get("dep_date"), trip.get("ret_date")))
        if key in cells:
            cells[key] = _cheaper(cells[key], trip)
    return cells


def airport_matrix(trips, origins, ret_airports):
    """Cheapest trip per (departure airport, return airport).

    The diagonal is the conventional round trip. Trips whose return airport
    was never determined take part in no cell, because guessing which
    column they belong in would invent data.
    """
    cells = {(origin, ret): None for origin in origins for ret in ret_airports}
    for trip in trips:
        if trip.get("ret_airport") is None:
            continue
        key = (trip.get("origin"), trip["ret_airport"])
        if key in cells:
            cells[key] = _cheaper(cells[key], trip)
    return cells


def date_matrix(trips, dep_dates, ret_dates):
    """Cheapest trip per (departure date, return date)."""
    cells = {(dep, ret): None for dep in dep_dates for ret in ret_dates}
    for trip in trips:
        key = (trip.get("dep_date"), trip.get("ret_date"))
        if key in cells:
            cells[key] = _cheaper(cells[key], trip)
    return cells


# --------------------------------------------------------------------------
# small formatters
# --------------------------------------------------------------------------

def _day(iso):
    """2026-12-19 -> 19 Dec. Unparseable input comes back untouched."""
    try:
        year, month, day = (int(part) for part in str(iso).split("-"))
        return f"{day} {MONTH_ABBR[month]}"
    except (ValueError, IndexError, TypeError):
        return str(iso)


def _hm(minutes):
    if not minutes:
        return "not determined"
    return f"{int(minutes) // 60}h {int(minutes) % 60:02d}m"


def _stops(count):
    if count is None:
        return "not determined"
    if count == 0:
        return "nonstop"
    return f"{count} stop" if count == 1 else f"{count} stops"


def _price_domain(trips):
    prices = [t["price_eur"] for t in trips if t.get("price_eur") is not None]
    if not prices:
        return (0, 0)
    return (min(prices), max(prices))


def _step(price, domain):
    """Sequential bin, 1 (dearest, palest) to SEQ_STEPS (cheapest, darkest).

    The magnitude encoded is how much cheaper this fare is than the worst
    fare on the page, so darker always means better. Cheap fares would
    otherwise recede toward the surface, which puts the answer in the
    faintest ink on the page.
    """
    low, high = domain
    if high <= low:
        return SEQ_STEPS
    frac = (high - price) / (high - low)
    return min(SEQ_STEPS, 1 + int(frac * SEQ_STEPS))


def _sorted_trips(trips):
    return sorted(trips, key=lambda t: (t.get("price_eur") or 0,
                                        t.get("origin") or "",
                                        t.get("dep_date") or ""))


# --------------------------------------------------------------------------
# run shape: what the page knows about the run it is describing
# --------------------------------------------------------------------------

def _origins(trips, params, coverage):
    listed = [o["code"] if isinstance(o, dict) else o
              for o in (params.get("origins") or [])]
    if listed:
        return listed
    seen = set(coverage) | {t.get("origin") for t in trips if t.get("origin")}
    return sorted(code for code in seen if code)


def _ret_airports(trips, params, origins):
    configured = params.get("return_airports", "same_as_origins")
    if configured and configured != "same_as_origins":
        if isinstance(configured, str):
            return [configured]
        return list(configured)
    named = {t["ret_airport"] for t in trips if t.get("ret_airport")}
    return sorted(set(origins) | named) if named else list(origins)


def _dep_dates(trips, params):
    window = params.get("dep_window")
    observed = sorted({t["dep_date"] for t in trips if t.get("dep_date")})
    return sorted(set(observed) | set(_span(window))) if window else observed


def _ret_dates(trips, params):
    window = params.get("ret_window")
    observed = sorted({t["ret_date"] for t in trips if t.get("ret_date")})
    return sorted(set(observed) | set(_span(window))) if window else observed


def _span(window):
    """Every ISO date from window[0] to window[1] inclusive."""
    from datetime import date, timedelta
    try:
        start = date.fromisoformat(window[0])
        end = date.fromisoformat(window[1])
    except (TypeError, ValueError, IndexError):
        return []
    out = []
    while start <= end:
        out.append(start.isoformat())
        start += timedelta(days=1)
    return out


def _date_pairs(trips, params):
    deps = _dep_dates(trips, params)
    rets = _ret_dates(trips, params)
    return [(dep, ret) for dep in deps for ret in rets]


def _ground_notes(params):
    notes = dict(params.get("ground_notes") or {})
    for origin in params.get("origins") or []:
        if isinstance(origin, dict) and origin.get("ground"):
            notes.setdefault(origin["code"], origin["ground"])
    if params.get("dest_ground"):
        notes.setdefault(params.get("dest"), params["dest_ground"])
    return notes


def _ground(notes, code):
    return notes.get(code) or "not determined"


def _sweep_stop_limit(trips):
    """The single stop limit the sweep ran at, if any sweep row exists."""
    for trip in trips:
        if trip.get("price_basis") == "sweep" and trip.get("max_stops") is not None:
            return trip["max_stops"]
    return None


def _stop_budgets(params, trips):
    budgets = {}
    for origin in params.get("origins") or []:
        if isinstance(origin, dict) and origin.get("max_stops") is not None:
            budgets[origin["code"]] = origin["max_stops"]
    for trip in trips:
        if trip.get("max_stops") is not None:
            budgets.setdefault(trip.get("origin"), trip["max_stops"])
    return budgets


def _carrier_colors(trips):
    """Fixed slot per carrier, assigned alphabetically.

    Alphabetical rather than by rank or frequency so that filtering the
    board never repaints the carriers that survive. Past seven carriers the
    tail folds into one muted "other" slot rather than inventing an eighth
    hue nobody can tell from the seventh.
    """
    names = sorted({name for trip in trips for name in (trip.get("carriers") or ())})
    return {name: index + 1 for index, name in enumerate(names[:CARRIER_SLOTS])}


# --------------------------------------------------------------------------
# fragments
# --------------------------------------------------------------------------

def _nd_cell(extra=""):
    return (f'<td class="cell cell--nd{extra}">'
            f'<span class="nd">not determined</span></td>')


def _price_cell(trip, domain, best_id, extra=""):
    if trip is None:
        return _nd_cell(extra)
    step = _step(trip["price_eur"], domain)
    is_best = best_id is not None and id(trip) == best_id
    classes = f"cell cell--seq s{step}{' is-best' if is_best else ''}{extra}"
    verdict = trip.get("night_verdict", "unknown")
    mark = '<span class="cell-mark" aria-hidden="true"></span>' if is_best else ""
    return (
        f'<td class="{classes}" title="{esc(str(trip.get("origin") or ""))} '
        f'{esc(_day(trip.get("dep_date")))} to {esc(_day(trip.get("ret_date")))}, '
        f'{esc(NIGHT_LABELS.get(verdict, verdict))}">'
        f'{mark}<span class="cell-price">{trip["price_eur"]}</span></td>'
    )


def _ramp_legend(domain, note=""):
    """Ramp legend with both ends named.

    Named ends rather than a direction word: the ramp runs light to dark on
    the light theme and dark to light on the dark one, so "darker is
    cheaper" would be a lie in one of them.
    """
    low, high = domain
    swatches = "".join(
        f'<span class="ramp-step s{step}"></span>'
        for step in range(1, SEQ_STEPS + 1))
    return (
        '<div class="legend">'
        f'<span class="legend-note">dearest</span>'
        f'<span class="legend-label">{high}</span>'
        f'<span class="ramp">{swatches}</span>'
        f'<span class="legend-label">{low}</span>'
        f'<span class="legend-note">cheapest, in EUR</span>'
        '<span class="legend-sep"></span>'
        '<span class="ramp-nd" aria-hidden="true"></span>'
        '<span class="legend-label">not determined</span>'
        f'{note}</div>'
    )


def _night_pill(trip):
    """Verdict as a pill. Every verdict gets its own shape and its own words.

    "not checked" deliberately shares nothing with "clean": no fill, a
    dashed hairline, muted ink. A trip nobody examined must never read like
    a trip that passed.
    """
    verdict = trip.get("night_verdict", "unknown")
    label = NIGHT_LABELS.get(verdict, "not checked")
    saving = trip.get("night_saving_eur")
    if verdict == "justified" and saving is not None:
        label = f"night layover, saves {saving} EUR"
    if verdict == "not_justified" and saving is not None:
        label = (f"night layover, saves only {saving} EUR" if saving > 0
                 else f"night layover, and {abs(saving)} EUR dearer")
    glyph = {"clean": "&#9679;", "justified": "&#9670;",
             "not_justified": "&#9650;"}.get(verdict, "?")
    return (f'<span class="pill pill--{esc(verdict)}">'
            f'<span class="pill-glyph" aria-hidden="true">{glyph}</span>'
            f'{esc(label)}</span>')


def _carrier_chips(trip, colors):
    names = trip.get("carriers") or ()
    if not names:
        return '<span class="muted">not determined</span>'
    chips = []
    for name in names:
        slot = colors.get(name)
        cls = f"dot c{slot}" if slot else "dot c-other"
        chips.append(f'<span class="carrier"><span class="{cls}" '
                     f'aria-hidden="true"></span>{esc(str(name))}</span>')
    return '<span class="carriers">' + "".join(chips) + "</span>"


def _layover_chips(trip):
    stops = trip.get("layovers") or ()
    if not stops:
        if trip.get("stops") in (0, None):
            return '<span class="muted">none</span>'
        return '<span class="muted">not determined</span>'
    out = []
    for stop in stops:
        code = stop.get("code") or stop.get("airport_name") or "?"
        out.append(f'<span class="lay">{esc(str(code))}'
                   f'<span class="lay-min">{_hm(stop.get("minutes"))}</span>'
                   f'</span>')
    return '<span class="lays">' + "".join(out) + "</span>"


def _link(trip):
    url = trip.get("tfs_url")
    if not url:
        return '<span class="muted">no link</span>'
    return (f'<a class="go" href="{esc(str(url))}" target="_blank" '
            f'rel="noopener noreferrer">open</a>')


def _section(eyebrow, heading, standfirst, body):
    return (
        '<section class="block">'
        f'<p class="eyebrow">{esc(eyebrow)}</p>'
        f'<h2>{esc(heading)}</h2>'
        f'<p class="standfirst">{standfirst}</p>'
        f'{body}</section>'
    )


def _scroller(inner, extra=""):
    return f'<div class="scroller{extra}" tabindex="0">{inner}</div>'


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------

def _masthead(trips, params, cheapest, domain):
    dest = params.get("dest_name") or params.get("dest") or "the destination"
    expanded = sum(1 for t in trips if t.get("legs_expanded"))
    checked = sum(1 for t in trips
                  if t.get("night_verdict") not in (None, "unknown"))
    if cheapest:
        hero = (f'<span class="hero-num">{cheapest["price_eur"]}</span>'
                f'<span class="hero-unit">{esc(params.get("currency", "EUR"))}'
                f'</span>')
        hero_note = (f'{esc(str(cheapest.get("origin") or "?"))} to '
                     f'{esc(str(cheapest.get("dest") or dest))}, '
                     f'{esc(_day(cheapest.get("dep_date")))} back '
                     f'{esc(_day(cheapest.get("ret_date")))}')
    else:
        hero = '<span class="hero-num nd-hero">not determined</span>'
        hero_note = "no fares were captured"
    low, high = domain
    return (
        '<header class="masthead">'
        f'<p class="eyebrow">Fare sweep to {esc(str(dest))}</p>'
        '<h1>Where to leave from, and when</h1>'
        '<p class="standfirst">One sweep across every departure airport and '
        'every date pair in the window, priced for one traveller in economy. '
        'Every number below is a fare somebody actually returned; everything '
        'nobody measured says so.</p>'
        '<div class="stats">'
        f'<div class="stat stat--hero"><p class="stat-label">Cheapest fare '
        f'found</p><p class="stat-value">{hero}</p>'
        f'<p class="stat-note">{hero_note}</p></div>'
        f'<div class="stat"><p class="stat-label">Fares on the board</p>'
        f'<p class="stat-value"><span class="hero-num">{len(trips)}</span></p>'
        f'<p class="stat-note">spread {low} to {high} '
        f'{esc(params.get("currency", "EUR"))}</p></div>'
        f'<div class="stat"><p class="stat-label">Itineraries expanded</p>'
        f'<p class="stat-value"><span class="hero-num">{expanded}</span>'
        f'<span class="hero-unit">of {len(trips)}</span></p>'
        f'<p class="stat-note">{checked} have a night-layover verdict</p>'
        '</div></div></header>'
    )


def _origin_section(trips, origins, pairs, domain, cheapest):
    """One small heatmap per departure airport, all on a shared scale.

    A single grid of every airport against every date pair is 6 by 20 on the
    real parameter block, which is unreadable and hides the thing worth
    seeing: each airport has its own date shape. Small multiples put those
    shapes side by side. The colour scale is shared across every grid, so a
    cell means the same fare whichever airport it sits under; scaling each
    grid to its own range would make a dear airport's best date look like a
    bargain.
    """
    cells = origin_matrix(trips, origins, pairs)
    best_id = id(cheapest) if cheapest is not None else None

    deps, rets = [], []
    for dep, ret in pairs:
        if dep not in deps:
            deps.append(dep)
        if ret not in rets:
            rets.append(ret)

    minis = []
    for origin in origins:
        found = [cells[(origin, (dep, ret))]
                 for dep in deps for ret in rets
                 if cells.get((origin, (dep, ret))) is not None]
        best = min(found, key=lambda t: t["price_eur"], default=None)
        caption = (f'<span class="mini-best">from {best["price_eur"]} EUR'
                   f'</span>' if best else
                   '<span class="mini-nd">not determined</span>')

        head = ['<tr><th class="corner" scope="col">Out</th>']
        for ret in rets:
            head.append('<th class="col" scope="col">'
                        f'<span class="col-out">{esc(_day(ret))}</span>'
                        '<span class="col-back">back</span></th>')
        head.append("</tr>")

        rows = []
        for dep in deps:
            row = [f'<tr><th class="rowhead" scope="row">'
                   f'{esc(_day(dep))}</th>']
            for ret in rets:
                row.append(_price_cell(cells[(origin, (dep, ret))], domain,
                                       best_id))
            row.append("</tr>")
            rows.append("".join(row))

        table = ('<table class="matrix matrix--tight">'
                 f'<caption class="sr-only">{esc(str(origin))}, cheapest fare '
                 'by departure date and return date</caption><thead>'
                 + "".join(head) + "</thead><tbody>"
                 + "".join(rows) + "</tbody></table>")
        minis.append(
            '<figure class="mini"><figcaption class="mini-cap">'
            f'<span class="code">{esc(str(origin))}</span>{caption}'
            '</figcaption>' + _scroller(table) + "</figure>")

    return _section(
        "The headline view",
        "Every airport, every date pair",
        "One grid per departure airport: outbound date down the side, return "
        "date across the top, cheapest fare in the cell. The grids share one "
        "colour scale, so a cell means the same fare whichever airport it "
        "sits under. This is the view the sweep genuinely supports, so it "
        "leads.",
        _ramp_legend(domain) + '<div class="minis">' + "".join(minis) + "</div>",
    )


def _coverage_section(trips, origins, coverage, domain):
    rows = []
    for origin in origins:
        found = [t for t in trips if t.get("origin") == origin]
        state = coverage.get(origin, "not_determined")
        cheapest = min(found, key=lambda t: t["price_eur"], default=None)
        backfilled = any(t.get("price_basis") == "backfill" for t in found)
        if state == "ok":
            status = ('<span class="pill pill--ok"><span class="pill-glyph" '
                      'aria-hidden="true">&#9679;</span>searched</span>')
        else:
            status = ('<span class="pill pill--nd"><span class="pill-glyph" '
                      'aria-hidden="true">?</span>no usable result page</span>')
        if state == "ok" and cheapest is not None:
            price = (f'<span class="cover-price s{_step(cheapest["price_eur"], domain)}">'
                     f'{cheapest["price_eur"]}</span>')
        else:
            price = ('<span class="nd nd--inline cover-nd">not '
                     'determined</span>')
        basis = "backfill search" if backfilled else (
            "sweep" if found else "no rows returned")
        rows.append(
            '<li class="cover">'
            f'<span class="cover-code">{esc(str(origin))}</span>'
            f'{status}{price}'
            f'<span class="cover-basis">{esc(basis)}, {len(found)} '
            f'{"fare" if len(found) == 1 else "fares"}</span></li>')
    return _section(
        "Coverage",
        "What each airport was actually asked",
        "An airport missing from a capped result list is not evidence that it "
        "is expensive. Anything that did not come back clean says "
        '"not determined" instead of showing a price.',
        '<ul class="covers">' + "".join(rows) + "</ul>",
    )


def _airport_section(trips, origins, rets, domain):
    cells = airport_matrix(trips, origins, rets)
    filled = sum(1 for cell in cells.values() if cell is not None)
    head = ['<tr><th class="corner" scope="col">Out / back</th>']
    for ret in rets:
        head.append(f'<th class="col" scope="col">'
                    f'<span class="col-out">{esc(str(ret))}</span>'
                    f'<span class="col-back">return</span></th>')
    head.append("</tr>")
    rows = []
    for origin in origins:
        row = [f'<tr><th class="rowhead" scope="row">{esc(str(origin))}</th>']
        for ret in rets:
            diag = " is-diagonal" if origin == ret else ""
            row.append(_price_cell(cells[(origin, ret)], domain, None, diag))
        row.append("</tr>")
        rows.append("".join(row))
    table = ('<table class="matrix"><caption class="sr-only">Cheapest fare by '
             'departure airport and return airport</caption><thead>'
             + "".join(head) + "</thead><tbody>" + "".join(rows)
             + "</tbody></table>")
    return _section(
        "Secondary view",
        "Departure airport by return airport",
        "The open-jaw grid, with the conventional round trip on the diagonal. "
        "Google does not name the return airport until an itinerary is "
        f"expanded, so only {filled} of {len(cells)} cells can be filled. The "
        "rest are unmeasured, not empty.",
        _ramp_legend(domain) + _scroller(table),
    )


def _candidates(trips):
    """Pick candidates by the role each one plays, not by rank alone.

    A list of the four cheapest fares mostly repeats itself. These four
    questions do not: what is cheapest, what is cheapest with a night nobody
    has to spend in a terminal, what a night in a terminal is actually
    worth, and what gets there soonest.
    """
    picks = []

    def add(trip, why):
        if trip is None:
            return
        for existing in picks:
            if existing["trip"] is trip:
                existing["why"].append(why)
                return
        picks.append({"trip": trip, "why": [why]})

    priced = [t for t in trips if t.get("price_eur") is not None]
    add(min(priced, key=lambda t: t["price_eur"], default=None),
        "cheapest on the board")
    clean = [t for t in priced if t.get("night_verdict") == "clean"]
    add(min(clean, key=lambda t: t["price_eur"], default=None),
        "cheapest with no night layover")
    justified = [t for t in priced if t.get("night_verdict") == "justified"]
    add(min(justified, key=lambda t: t["price_eur"], default=None),
        "night layover that pays for itself")
    timed = [t for t in priced if t.get("total_duration_min")]
    add(min(timed, key=lambda t: t["total_duration_min"], default=None),
        "shortest door to door")
    return picks


def _candidate_section(trips, params, colors, notes, dest):
    picks = _candidates(trips)
    if not picks:
        return _section("Shortlist", "The candidates",
                        "No fare qualified for the shortlist.",
                        '<p class="nd-block">not determined</p>')
    cards = []
    for pick in picks:
        trip = pick["trip"]
        origin = str(trip.get("origin") or "?")
        back_to = trip.get("ret_airport") or None
        ret_label = (esc(str(back_to)) if back_to
                     else '<span class="nd nd--inline">not determined</span>')
        why = "".join(f'<span class="why">{esc(reason)}</span>'
                      for reason in pick["why"])
        cards.append(
            '<article class="card">'
            f'<div class="card-why">{why}</div>'
            '<div class="card-head">'
            f'<p class="card-route"><span class="code">{esc(origin)}</span>'
            f'<span class="arrow" aria-hidden="true">&#8594;</span>'
            f'<span class="code">{esc(str(trip.get("dest") or dest))}</span>'
            '</p>'
            f'<p class="card-price">{trip.get("price_eur")}'
            f'<span class="card-unit">'
            f'{esc(params.get("currency", "EUR"))}</span></p></div>'
            '<dl class="facts">'
            f'<div><dt>Out</dt><dd>{esc(_day(trip.get("dep_date")))}</dd></div>'
            f'<div><dt>Back</dt><dd>{esc(_day(trip.get("ret_date")))}</dd></div>'
            f'<div><dt>Stops</dt><dd>{esc(_stops(trip.get("stops")))}</dd></div>'
            f'<div><dt>Duration</dt>'
            f'<dd>{esc(_hm(trip.get("total_duration_min")))}</dd></div>'
            f'<div><dt>Lands back at</dt><dd>{ret_label}</dd></div>'
            '</dl>'
            f'<p class="card-line">{_carrier_chips(trip, colors)}</p>'
            f'<p class="card-line">{_night_pill(trip)}</p>'
            '<dl class="ground">'
            f'<div><dt>Ground at {esc(origin)}</dt>'
            f'<dd>{esc(_ground(notes, origin))}</dd></div>'
            f'<div><dt>Ground at {esc(str(trip.get("dest") or dest))}</dt>'
            f'<dd>{esc(_ground(notes, trip.get("dest") or dest))}</dd></div>'
            '</dl>'
            f'<p class="card-go">{_link(trip)}</p>'
            '</article>')
    return _section(
        "Shortlist",
        "The candidates",
        "Four fares, each here for a different reason. Ground notes cover both "
        "ends, because a cheap fare into an airport two hours from where you "
        "sleep is not a cheap fare.",
        '<div class="cards">' + "".join(cards) + "</div>",
    )


def _board_section(trips, colors, domain, dest):
    rows = []
    for trip in _sorted_trips(trips):
        price = trip.get("price_eur")
        step = _step(price, domain) if price is not None else None
        price_cell = (f'<td class="b-price"><span class="chip s{step}">'
                      f'{price}</span></td>' if step
                      else '<td class="b-price"><span class="nd">not '
                           'determined</span></td>')
        back_to = trip.get("ret_airport")
        rows.append(
            "<tr>"
            + price_cell
            + f'<td class="b-route"><span class="code">'
              f'{esc(str(trip.get("origin") or "?"))}</span>'
              f'<span class="arrow" aria-hidden="true">&#8594;</span>'
              f'<span class="code">{esc(str(trip.get("dest") or dest))}</span>'
              "</td>"
            + "<td>"
            + (f'<span class="code code--soft">{esc(str(back_to))}</span>'
               if back_to else '<span class="nd nd--inline">not '
                               'determined</span>')
            + "</td>"
            + f'<td>{esc(_day(trip.get("dep_date")))}</td>'
            + f'<td>{esc(_day(trip.get("ret_date")))}</td>'
            + f'<td>{esc(_stops(trip.get("stops")))}</td>'
            + f'<td class="num">{esc(_hm(trip.get("total_duration_min")))}</td>'
            + f'<td>{_carrier_chips(trip, colors)}</td>'
            + f'<td>{_night_pill(trip)}</td>'
            + f'<td>{_layover_chips(trip)}</td>'
            + f'<td>{_link(trip)}</td>'
            + "</tr>")

    legend = "".join(
        f'<span class="carrier"><span class="dot c{slot}" aria-hidden="true">'
        f'</span>{esc(name)}</span>'
        for slot, name in sorted((slot, name) for name, slot in colors.items()))
    folded = sorted({name for trip in trips
                     for name in (trip.get("carriers") or ())
                     if name not in colors})
    if folded:
        legend += ('<span class="carrier"><span class="dot c-other" '
                   f'aria-hidden="true"></span>other ({len(folded)} more)'
                   '</span>')
    legend_block = (f'<div class="legend legend--carriers">'
                    f'<span class="legend-label">Carriers</span>{legend}</div>'
                    if legend else "")

    table = (
        '<table class="board"><caption class="sr-only">Every fare captured, '
        'cheapest first</caption><thead><tr>'
        '<th scope="col">Fare</th><th scope="col">Route</th>'
        '<th scope="col">Lands back at</th>'
        '<th scope="col">Out</th><th scope="col">Back</th>'
        '<th scope="col">Stops</th><th scope="col">Duration</th>'
        '<th scope="col">Carriers</th><th scope="col">Night</th>'
        '<th scope="col">Layovers</th><th scope="col">Link</th>'
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>")
    return _section(
        "The board",
        "Every fare captured",
        "Cheapest first. A night layover does not disqualify a fare, it "
        "obliges it to be considerably cheaper; the night column says whether "
        "it is, or says that nobody checked.",
        legend_block + _scroller(table, " scroller--board"),
    )


def _caveats_section(trips, params, origins, coverage):
    backfilled = sorted({t.get("origin") for t in trips
                         if t.get("price_basis") == "backfill"
                         and t.get("origin")})
    undetermined = [o for o in origins if coverage.get(o, "not_determined") != "ok"]
    unexpanded = [t for t in trips if not t.get("legs_expanded")]
    budgets = _stop_budgets(params, trips)
    sweep_limit = _sweep_stop_limit(trips)
    sweep_counts = {}
    for t in trips:
        if t.get("price_basis") == "sweep" and t.get("origin"):
            sweep_counts[t["origin"]] = sweep_counts.get(t["origin"], 0) + 1

    items = []
    was = "was" if len(backfilled) == 1 else "were"
    if backfilled:
        parts = []
        for origin in backfilled:
            n_sweep = sweep_counts.get(origin, 0)
            budget = budgets.get(origin)
            over_budget = (budget is not None and sweep_limit is not None
                          and budget > sweep_limit)
            detail = f"{origin} ({n_sweep} sweep fare{'s' if n_sweep != 1 else ''}"
            if over_budget:
                detail += f", allows {budget} stops against the sweep's {sweep_limit}"
            detail += ")"
            parts.append(detail)
        backfill_body = (
            ", ".join(parts) + f" {was} searched alone at their own stop "
            "budget. A search is backfilled either because the sweep "
            "returned nothing for the origin, or because the origin's stop "
            "budget is wider than the single limit a sweep search can "
            "carry, so its extra stops were never tried until backfill. "
            "Those fares came from a different search than the rest of the "
            "board.")
    else:
        backfill_body = ("No origin needed a backfill search. Every fare on "
                         "the board came out of the sweep.")
    items.append(
        f"<li><h3>Origins backfilled</h3><p>{esc(backfill_body)}</p></li>")
    them = "it" if len(undetermined) == 1 else "them"
    if undetermined:
        heading = "Coverage not determined"
        body = (esc(", ".join(undetermined)) + " did not come back with a usable "
               f"result page, so the board says nothing about {them}. Those cells "
               "are unmeasured, not expensive.")
    else:
        heading = "Coverage"
        body = "Every origin returned a usable result page."
    items.append(
        f"<li><h3>{heading}</h3><p>{body}</p></li>")
    if unexpanded:
        listed = ", ".join(
            f'{t.get("origin") or "?"} {t.get("price_eur")}'
            for t in _sorted_trips(unexpanded)[:12])
        more = (f" and {len(unexpanded) - 12} more"
                if len(unexpanded) > 12 else "")
        items.append(
            "<li><h3>Rows never expanded</h3><p>"
            f"{len(unexpanded)} of {len(trips)} rows were never opened, so "
            "their layovers and their night status are unknown. They show as "
            f'"not checked", which is not the same as clean: {esc(listed)}'
            f"{esc(more)}.</p></li>")
    else:
        items.append("<li><h3>Rows never expanded</h3><p>Every row on the "
                     "board was expanded and its layovers read.</p></li>")
    if budgets:
        listed = ", ".join(f"{code} at most {stops} "
                           f'{"stop" if stops == 1 else "stops"}'
                           for code, stops in sorted(budgets.items()))
        items.append(
            "<li><h3>Stop limit each search ran under</h3><p>"
            f"{esc(listed)}. A sweep carries one stop limit, so it runs at the "
            "tightest budget across all origins; an origin allowed more stops "
            "only sees them in its own backfill search.</p></li>")
    else:
        items.append("<li><h3>Stop limit each search ran under</h3>"
                     "<p>not determined</p></li>")
    items.append(
        "<li><h3>Where the return airport went</h3><p>A multi-city result row "
        "describes the outbound leg. Google does not commit to a return "
        "airport until the itinerary is expanded, so the return column is "
        '"not determined" for every row nobody opened, and the airport by '
        "airport grid stays mostly unfilled.</p></li>")
    items.append(
        "<li><h3>What a row's link actually opens</h3><p>Each row's link is "
        "the search it came from, not a bookmark to that one fare: a sweep "
        "search carries every origin and one date pair, so opening it "
        "reopens the whole result list, and the fare has to be found again "
        "inside it, sorted by price. It is not a permalink to a specific "
        "itinerary.</p></li>")

    return _section(
        "Read this before booking",
        "What the board does not know",
        "Every limit that could change a decision, stated rather than "
        "smoothed over.",
        '<ul class="caveats">' + "".join(items) + "</ul>",
    )


# --------------------------------------------------------------------------
# style
# --------------------------------------------------------------------------

FONTS = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
         'family=IBM+Plex+Mono:wght@400;500;600&'
         'family=IBM+Plex+Sans+Condensed:wght@500;600;700&'
         'family=IBM+Plex+Sans:wght@400;500&display=swap">')

CSS = """
<style>
:root {
  color-scheme: light;
  --plane: #eef1f2;
  --surface: #fbfcfc;
  --surface-2: #f4f7f8;
  --ink: #12171a;
  --ink-2: #4e565b;
  --muted: #7d868b;
  --hairline: #dbe1e3;
  --rule: #c2cacd;
  --focus: #2a78d6;

  --seq-1: #cde2fb; --seq-ink-1: #12171a;
  --seq-2: #9ec5f4; --seq-ink-2: #12171a;
  --seq-3: #5598e7; --seq-ink-3: #12171a;
  --seq-4: #2a78d6; --seq-ink-4: #ffffff;
  --seq-5: #1c5cab; --seq-ink-5: #ffffff;
  --seq-6: #104281; --seq-ink-6: #ffffff;

  --good: #0ca30c;
  --warn: #fab219;
  --serious: #ec835a;
  --critical: #d03b3b;

  --c1: #eb6834; --c2: #1baf7a; --c3: #eda100; --c4: #e87ba4;
  --c5: #008300; --c6: #4a3aa7; --c7: #e34948;

  --hatch: repeating-linear-gradient(45deg,
    rgba(0,0,0,0) 0 7px, var(--hairline) 7px 8px);
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --plane: #0d0f10;
    --surface: #15181a;
    --surface-2: #1c2023;
    --ink: #f2f5f6;
    --ink-2: #b3bbbf;
    --muted: #838c91;
    --hairline: #2a3033;
    --rule: #3b4347;
    --focus: #5598e7;

    --seq-1: #104281; --seq-ink-1: #ffffff;
    --seq-2: #184f95; --seq-ink-2: #ffffff;
    --seq-3: #1c5cab; --seq-ink-3: #ffffff;
    --seq-4: #2a78d6; --seq-ink-4: #ffffff;
    --seq-5: #5598e7; --seq-ink-5: #0b0b0b;
    --seq-6: #9ec5f4; --seq-ink-6: #0b0b0b;

    --c1: #d95926; --c2: #199e70; --c3: #c98500; --c4: #d55181;
    --c5: #008300; --c6: #9085e9; --c7: #e66767;

    --hatch: repeating-linear-gradient(45deg,
      rgba(0,0,0,0) 0 7px, var(--hairline) 7px 8px);
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --plane: #0d0f10;
  --surface: #15181a;
  --surface-2: #1c2023;
  --ink: #f2f5f6;
  --ink-2: #b3bbbf;
  --muted: #838c91;
  --hairline: #2a3033;
  --rule: #3b4347;
  --focus: #5598e7;

  --seq-1: #104281; --seq-ink-1: #ffffff;
  --seq-2: #184f95; --seq-ink-2: #ffffff;
  --seq-3: #1c5cab; --seq-ink-3: #ffffff;
  --seq-4: #2a78d6; --seq-ink-4: #ffffff;
  --seq-5: #5598e7; --seq-ink-5: #0b0b0b;
  --seq-6: #9ec5f4; --seq-ink-6: #0b0b0b;

  --c1: #d95926; --c2: #199e70; --c3: #c98500; --c4: #d55181;
  --c5: #008300; --c6: #9085e9; --c7: #e66767;

  --hatch: repeating-linear-gradient(45deg,
    rgba(0,0,0,0) 0 7px, var(--hairline) 7px 8px);
}

body {
  margin: 0;
  background: var(--plane);
  color: var(--ink);
  font-family: "IBM Plex Sans", ui-sans-serif, system-ui, -apple-system,
    "Segoe UI", sans-serif;
  font-size: 16px;
  line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}
.page {
  max-width: 1140px;
  margin: 0 auto;
  padding: 40px 24px 96px;
  display: flex;
  flex-direction: column;
  gap: 0;
}
.sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0;
}

h1, h2, h3, .eyebrow, .col, .rowhead, .corner, th {
  font-family: "IBM Plex Sans Condensed", "IBM Plex Sans", ui-sans-serif,
    system-ui, sans-serif;
}
h1 {
  font-size: clamp(2.1rem, 5.2vw, 3.3rem);
  font-weight: 700;
  letter-spacing: -0.018em;
  line-height: 1.04;
  margin: 6px 0 14px;
  text-wrap: balance;
}
h2 {
  font-size: clamp(1.35rem, 2.6vw, 1.75rem);
  font-weight: 700;
  letter-spacing: -0.012em;
  line-height: 1.12;
  margin: 4px 0 8px;
  text-wrap: balance;
}
h3 {
  font-size: 0.95rem;
  font-weight: 600;
  letter-spacing: 0.01em;
  margin: 0 0 4px;
}
.eyebrow {
  margin: 0;
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--muted);
}
.standfirst {
  margin: 0 0 20px;
  max-width: 66ch;
  color: var(--ink-2);
  font-size: 0.98rem;
}

.masthead { padding: 8px 0 40px; }
.masthead .standfirst { margin-bottom: 28px; }
.block {
  padding: 34px 0;
  border-top: 1px solid var(--rule);
}
.block:first-of-type { border-top-width: 2px; }

/* stats ------------------------------------------------------------- */
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
  gap: 1px;
  background: var(--hairline);
  border: 1px solid var(--hairline);
}
.stat { background: var(--surface); padding: 18px 20px 20px; }
.stat--hero { background: var(--surface-2); }
.stat-label {
  margin: 0 0 8px;
  font-size: 0.68rem;
  font-weight: 600;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--muted);
}
.stat-value { margin: 0; display: flex; align-items: baseline; gap: 8px; }
.hero-num {
  font-family: "IBM Plex Mono", ui-monospace, "SFMono-Regular", monospace;
  font-size: 2.5rem;
  font-weight: 500;
  line-height: 1;
  letter-spacing: -0.03em;
  color: var(--ink);
}
.nd-hero { font-size: 1.2rem; color: var(--muted); letter-spacing: 0.02em; }
.hero-unit {
  font-size: 0.78rem;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--muted);
}
.stat-note { margin: 8px 0 0; font-size: 0.82rem; color: var(--ink-2); }

/* legends ----------------------------------------------------------- */
.legend {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 10px;
  margin: 0 0 14px;
  font-size: 0.74rem;
  color: var(--ink-2);
}
.legend-label {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.01em;
}
.legend-note { color: var(--muted); font-style: italic; }
.legend-sep {
  width: 1px; height: 14px; background: var(--rule); margin: 0 2px;
}
.ramp { display: inline-flex; gap: 2px; }
.ramp-step { width: 22px; height: 12px; display: block; }
.ramp-nd {
  width: 22px; height: 12px; display: block;
  background-color: var(--surface-2);
  background-image: var(--hatch);
  border: 1px solid var(--hairline);
}
.legend--carriers { gap: 8px 16px; }

/* matrices ---------------------------------------------------------- */
.scroller {
  overflow-x: auto;
  overscroll-behavior-x: contain;
  border: 1px solid var(--hairline);
  background: var(--surface);
}
.scroller:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
table { border-collapse: separate; border-spacing: 0; width: 100%; }
.matrix { min-width: max-content; }
.matrix th, .matrix td {
  border-bottom: 1px solid var(--hairline);
  border-right: 1px solid var(--hairline);
}
.matrix tr:last-child th, .matrix tr:last-child td { border-bottom: 0; }
.corner, .col, .rowhead {
  background: var(--surface-2);
  color: var(--ink-2);
  font-weight: 600;
  font-size: 0.72rem;
  letter-spacing: 0.06em;
  text-align: left;
  padding: 8px 10px;
  white-space: nowrap;
}
.corner, .rowhead {
  position: sticky;
  left: 0;
  z-index: 2;
  border-right: 1px solid var(--rule);
}
.corner { z-index: 3; text-transform: uppercase; }
.rowhead {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 0.86rem;
  letter-spacing: 0.08em;
  color: var(--ink);
}
.col { text-transform: uppercase; }
.col-out, .col-back { display: block; }
.col-back {
  font-weight: 500;
  color: var(--muted);
  letter-spacing: 0.04em;
  text-transform: none;
}
.group-edge { border-left: 2px solid var(--rule); }
.cell {
  padding: 0;
  height: 46px;
  min-width: 92px;
  text-align: center;
  position: relative;
}
.cell--seq .cell-price {
  display: block;
  padding: 13px 8px;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-variant-numeric: tabular-nums;
  font-size: 0.92rem;
  font-weight: 500;
}
.cell--nd {
  background-color: var(--surface-2);
  background-image: var(--hatch);
}
.nd {
  display: block;
  padding: 8px 6px;
  font-size: 0.63rem;
  line-height: 1.25;
  letter-spacing: 0.05em;
  color: var(--muted);
}
.nd--inline { display: inline; padding: 0; font-size: 0.7rem; }
.nd-block {
  margin: 0; padding: 20px; background: var(--surface-2);
  color: var(--muted); font-size: 0.85rem; letter-spacing: 0.05em;
}
.is-diagonal { box-shadow: inset 0 0 0 1px var(--rule); }
.is-best { box-shadow: inset 0 0 0 2px var(--ink); }
.cell-mark {
  position: absolute; top: 3px; right: 4px;
  width: 5px; height: 5px; border-radius: 50%;
  background: currentColor;
}
.s1 { background-color: var(--seq-1); color: var(--seq-ink-1); }
.s2 { background-color: var(--seq-2); color: var(--seq-ink-2); }
.s3 { background-color: var(--seq-3); color: var(--seq-ink-3); }
.s4 { background-color: var(--seq-4); color: var(--seq-ink-4); }
.s5 { background-color: var(--seq-5); color: var(--seq-ink-5); }
.s6 { background-color: var(--seq-6); color: var(--seq-ink-6); }

.minis {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(290px, 1fr));
  gap: 16px;
}
.mini { margin: 0; border: 1px solid var(--hairline); background: var(--surface); }
.mini .scroller { border: 0; }
/* A small multiple is only readable if all of it is on screen at once, so
   the cells shrink to fit the card rather than the card scrolling. The
   scroller stays as the fallback for very narrow viewports. */
.mini .matrix { min-width: 100%; }
/* Specificity, not source order: .matrix--tight .cell sets its own
   min-width further down the sheet and would otherwise win this. */
.mini .matrix--tight .cell { min-width: 60px; }
.mini .col { padding-left: 7px; padding-right: 7px; }
.mini .rowhead { padding-right: 8px; }
.mini-cap {
  display: flex; align-items: baseline; justify-content: space-between;
  gap: 10px;
  padding: 9px 12px;
  background: var(--surface-2);
  border-bottom: 1px solid var(--rule);
}
.mini-cap .code { font-size: 0.95rem; }
.mini-best {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-variant-numeric: tabular-nums;
  font-size: 0.76rem;
  color: var(--ink-2);
}
.mini-nd {
  font-size: 0.66rem; letter-spacing: 0.05em; color: var(--muted);
}
.matrix--tight .cell { min-width: 74px; height: 40px; }
.matrix--tight .cell--seq .cell-price { padding: 10px 6px; }

/* coverage ---------------------------------------------------------- */
.covers { list-style: none; margin: 0; padding: 0;
  display: grid; gap: 1px; background: var(--hairline);
  border: 1px solid var(--hairline); }
.cover {
  background: var(--surface);
  display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px;
  padding: 12px 16px;
}
.cover-code {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 1rem; font-weight: 600; letter-spacing: 0.12em;
  min-width: 3.6em;
}
.cover-price {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-variant-numeric: tabular-nums;
  font-size: 0.88rem; font-weight: 500;
  padding: 3px 9px;
}
.cover-nd {
  display: inline-block; padding: 3px 9px; min-width: 4.6em;
}
.cover-basis { color: var(--muted); font-size: 0.8rem; margin-left: auto; }

/* pills ------------------------------------------------------------- */
.pill {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 3px 9px;
  font-size: 0.75rem;
  line-height: 1.4;
  white-space: nowrap;
  border: 1px solid transparent;
}
.pill-glyph { font-size: 0.66em; line-height: 1; }
.pill--clean, .pill--ok {
  color: var(--ink);
  background: color-mix(in srgb, var(--good) 16%, var(--surface));
  border-color: color-mix(in srgb, var(--good) 45%, var(--surface));
}
.pill--clean .pill-glyph, .pill--ok .pill-glyph { color: var(--good); }
.pill--justified {
  color: var(--ink);
  background: var(--surface-2);
  border-color: var(--rule);
  border-left: 3px solid var(--serious);
}
.pill--justified .pill-glyph { color: var(--serious); }
.pill--not_justified {
  color: var(--ink);
  background: color-mix(in srgb, var(--critical) 14%, var(--surface));
  border-color: color-mix(in srgb, var(--critical) 50%, var(--surface));
}
.pill--not_justified .pill-glyph { color: var(--critical); }
.pill--unknown, .pill--nd {
  color: var(--muted);
  background: transparent;
  border: 1px dashed var(--rule);
  font-style: italic;
}
.pill--unknown .pill-glyph, .pill--nd .pill-glyph {
  color: var(--muted); font-style: normal; font-weight: 700;
}

/* carriers & layovers ------------------------------------------------ */
.carriers { display: inline-flex; flex-wrap: wrap; gap: 4px 12px; }
.carrier {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 0.8rem; white-space: nowrap; color: var(--ink);
}
.dot { width: 9px; height: 9px; flex: 0 0 auto; border-radius: 2px; }
.c1 { background: var(--c1); } .c2 { background: var(--c2); }
.c3 { background: var(--c3); } .c4 { background: var(--c4); }
.c5 { background: var(--c5); } .c6 { background: var(--c6); }
.c7 { background: var(--c7); }
.c-other {
  background: var(--surface-2); box-shadow: inset 0 0 0 1px var(--rule);
}
.lays { display: inline-flex; flex-wrap: wrap; gap: 4px; }
.lay {
  display: inline-flex; align-items: baseline; gap: 5px;
  padding: 2px 7px;
  background: var(--surface-2);
  border: 1px solid var(--hairline);
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 0.72rem; letter-spacing: 0.06em;
}
.lay-min { color: var(--muted); letter-spacing: 0; }
.muted { color: var(--muted); font-size: 0.8rem; }

/* cards -------------------------------------------------------------- */
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(275px, 1fr));
  gap: 16px;
}
.card {
  background: var(--surface);
  border: 1px solid var(--hairline);
  border-top: 3px solid var(--ink);
  padding: 16px 18px 18px;
  display: flex; flex-direction: column; gap: 12px;
}
.card-why { display: flex; flex-wrap: wrap; gap: 6px; }
.why {
  font-size: 0.66rem; font-weight: 600; letter-spacing: 0.1em;
  text-transform: uppercase; color: var(--muted);
}
.card-head {
  display: flex; align-items: baseline; justify-content: space-between;
  gap: 12px; flex-wrap: wrap;
}
.card-route { margin: 0; display: flex; align-items: center; gap: 6px; }
.code {
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 1rem; font-weight: 600; letter-spacing: 0.1em;
}
.code--soft { color: var(--muted); font-weight: 500; }
.arrow { color: var(--muted); font-size: 0.8rem; }
.card-price {
  margin: 0;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-size: 1.55rem; font-weight: 500; letter-spacing: -0.02em;
  display: flex; align-items: baseline; gap: 6px;
}
.card-unit {
  font-family: "IBM Plex Sans Condensed", sans-serif;
  font-size: 0.66rem; font-weight: 600; letter-spacing: 0.12em;
  color: var(--muted);
}
.facts, .ground { margin: 0; display: grid; gap: 8px 14px; }
.facts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.facts dt, .ground dt {
  font-size: 0.63rem; font-weight: 600; letter-spacing: 0.12em;
  text-transform: uppercase; color: var(--muted);
}
.facts dd, .ground dd {
  margin: 0; font-size: 0.85rem;
  font-variant-numeric: tabular-nums;
}
.ground {
  border-top: 1px solid var(--hairline);
  padding-top: 12px;
}
.card-line { margin: 0; }
.card-go { margin: auto 0 0; }
.go {
  display: inline-block;
  font-size: 0.76rem; font-weight: 600; letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ink);
  text-decoration: none;
  border-bottom: 2px solid var(--focus);
  padding-bottom: 1px;
}
.go:hover { color: var(--focus); }
.go:focus-visible { outline: 2px solid var(--focus); outline-offset: 3px; }

/* board -------------------------------------------------------------- */
.scroller--board {
  max-height: min(72vh, 720px);
  overflow: auto;
  overscroll-behavior: contain;
}
.board { min-width: max-content; font-size: 0.86rem; }
.board th {
  position: sticky; top: 0; z-index: 1;
  background: var(--surface-2);
  color: var(--ink-2);
  text-align: left;
  font-size: 0.66rem; font-weight: 600; letter-spacing: 0.14em;
  text-transform: uppercase;
  padding: 9px 12px;
  border-bottom: 1px solid var(--rule);
  white-space: nowrap;
}
.board td {
  padding: 9px 12px;
  border-bottom: 1px solid var(--hairline);
  vertical-align: middle;
  white-space: nowrap;
}
.board tbody tr:last-child td { border-bottom: 0; }
.board tbody tr:hover td { background: var(--surface-2); }
.board .num { font-variant-numeric: tabular-nums; }
.b-price { padding-left: 12px; }
.chip {
  display: inline-block;
  min-width: 4.6em;
  text-align: center;
  padding: 4px 9px;
  font-family: "IBM Plex Mono", ui-monospace, monospace;
  font-variant-numeric: tabular-nums;
  font-size: 0.88rem; font-weight: 500;
}
.b-route { display: flex; align-items: center; gap: 6px; }
.b-route .code { font-size: 0.84rem; }

/* caveats ------------------------------------------------------------ */
.caveats {
  list-style: none; margin: 0; padding: 0;
  display: grid; gap: 1px;
  background: var(--hairline);
  border: 1px solid var(--hairline);
}
.caveats li { background: var(--surface); padding: 14px 18px 16px; }
.caveats p {
  margin: 0; max-width: 74ch; font-size: 0.87rem; color: var(--ink-2);
}

@media (max-width: 640px) {
  .page { padding: 28px 14px 72px; }
  .facts { grid-template-columns: 1fr 1fr; }
  .cover-basis { margin-left: 0; width: 100%; }
}
@media (prefers-reduced-motion: reduce) {
  * { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; }
}
</style>
"""


# --------------------------------------------------------------------------
# render
# --------------------------------------------------------------------------

def render(trips, params, coverage=None):
    """The whole page, as page content only.

    No doctype and no document wrapper: the Artifact tool supplies the
    skeleton at publish time, so this returns what goes inside it.
    """
    trips = list(trips or [])
    params = dict(params or {})
    coverage = dict(coverage or {})

    dest = params.get("dest") or "destination"
    origins = _origins(trips, params, coverage)
    rets = _ret_airports(trips, params, origins)
    pairs = _date_pairs(trips, params)
    domain = _price_domain(trips)
    colors = _carrier_colors(trips)
    notes = _ground_notes(params)
    priced = [t for t in trips if t.get("price_eur") is not None]
    cheapest = min(priced, key=lambda t: t["price_eur"], default=None)

    title = f"{params.get('dest_name') or dest} Fare Board"

    return "".join([
        f"<title>{esc(title)}</title>",
        FONTS,
        CSS,
        '<main class="page">',
        _masthead(trips, params, cheapest, domain),
        _origin_section(trips, origins, pairs, domain, cheapest),
        _coverage_section(trips, origins, coverage, domain),
        _airport_section(trips, origins, rets, domain),
        _candidate_section(trips, params, colors, notes, dest),
        _board_section(trips, colors, domain, dest),
        _caveats_section(trips, params, origins, coverage),
        "</main>",
    ])


# --------------------------------------------------------------------------
# CLI: build_board.py <run_dir>  ->  page fragment on stdout
# --------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import os
    import sys

    run_dir = sys.argv[1]
    trips = json.load(open(os.path.join(run_dir, "trips.json")))
    params = json.load(open(os.path.join(run_dir, "params.json")))

    coverage_path = os.path.join(run_dir, "coverage.json")
    if os.path.exists(coverage_path):
        coverage = json.load(open(coverage_path))
    else:
        # No explicit coverage file: an origin is "ok" if it shows up in at
        # least one trip, "not_determined" otherwise. Good enough for a run
        # that didn't bother to record coverage separately.
        seen = {t.get("origin") for t in trips if t.get("origin")}
        coverage = {}
        for origin in params.get("origins") or []:
            code = origin["code"] if isinstance(origin, dict) else origin
            coverage[code] = "ok" if code in seen else "not_determined"

    sys.stdout.write(render(trips, params, coverage))
