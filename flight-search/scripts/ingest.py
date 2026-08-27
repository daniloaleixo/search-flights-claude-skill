"""Consume browser captures and turn them into records.

Two refusals live here, and they are refusals rather than warnings because
both failure modes are invisible in the output they corrupt:

  * A page whose selected tab is not "Cheapest". Best and Cheapest are two
    different result sets, and a Best page reports "Sorted by price" quite
    happily while its cheapest row sits 24% above the Cheapest tab's.
  * A page not sorted by price. Google's default "Top flights" order is not
    price order; on a measured page it led with a fare 10 EUR above the
    cheapest row on that same page.
  * A loaded page with zero parsed rows. That is a blocked or restructured
    page, and recording it as "no flights found" would quietly understate
    an origin for the rest of the run.
"""

from scripts.parse import ParseError, parse_row

PRICE_SORTED = "Sorted by price"
CHEAPEST_TAB = "Cheapest"


class SortOrderError(RuntimeError):
    """The captured page was not sorted by price."""


class ResultSetError(RuntimeError):
    """The captured page was not on the Cheapest tab."""


def assert_price_sorted(capture):
    sorted_by = capture.get("sortedBy")
    if sorted_by != PRICE_SORTED:
        raise SortOrderError(
            f"page reported {sorted_by!r}, expected {PRICE_SORTED!r}: "
            f"{capture.get('url', '')[:90]}"
        )


def assert_cheapest_tab(capture):
    active = capture.get("activeTab")
    if active != CHEAPEST_TAB:
        raise ResultSetError(
            f"page had the {active!r} tab selected, expected {CHEAPEST_TAB!r}: "
            f"{capture.get('url', '')[:90]}"
        )


def _price_basis(search):
    return "backfill" if search["id"].startswith("backfill-") else "sweep"


def ingest_capture(capture, search, strict=True):
    assert_cheapest_tab(capture)
    assert_price_sorted(capture)
    if not capture.get("rows"):
        raise ValueError(
            f"page loaded with zero result rows: {capture.get('url', '')[:90]}"
        )

    records = []
    for row in capture["rows"]:
        try:
            record = parse_row(row["aria"], row["text"], search["dep_date"])
        except ParseError:
            if strict:
                raise
            continue
        record.update({
            "search_id": search["id"],
            "tfs_url": capture["url"],
            "dep_date_searched": search["dep_date"],
            "ret_date": search["ret_date"],
            "max_stops": search["max_stops"],
            "price_basis": _price_basis(search),
            "legs_expanded": False,
            "night_layover": None,
            "ret_airport": None,
        })
        records.append(record)
    return records


def merge_captures(captures, searches):
    out = []
    for capture, search in zip(captures, searches):
        out.extend(ingest_capture(capture, search))
    return out
