"""Distance from a listing's map pin to the beachfront road.

Airbnb blurs every pin by up to roughly 150 m, so a distance here is the pin's
distance, not the door's. Callers band the result rather than cut on it.
"""
import json
import math

EARTH_M = 6371000.0


def _xy(lat, lng, lat0):
    """Project to local metres; accurate to well under 1 % across a city."""
    x = math.radians(lng) * EARTH_M * math.cos(math.radians(lat0))
    y = math.radians(lat) * EARTH_M
    return x, y


def _seg_dist(p, a, b):
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def load_lines(path):
    """Polylines as lists of [lat, lng] pairs."""
    with open(path) as f:
        return json.load(f)


def distance_to_lines(lat, lng, lines):
    """Shortest distance in metres from (lat, lng) to any polyline segment."""
    p = _xy(lat, lng, lat)
    best = float("inf")
    for line in lines:
        pts = [_xy(a, b, lat) for a, b in line]
        for a, b in zip(pts, pts[1:]):
            best = min(best, _seg_dist(p, a, b))
    return best


def blocks(metres, block_m):
    """Blocks back from the beachfront road, rounded; 0 means on it."""
    return int(round(metres / block_m))
