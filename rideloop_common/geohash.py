"""Pure Python geohash encode/decode/neighbors.

Geohash interleaves longitude and latitude bits and packs them five at a time
into a base32 alphabet. A prefix of a geohash is a bounding box that contains
the full hash, which is what makes it useful as a partition key: every driver
inside one cell shares the same key prefix.
"""

from __future__ import annotations

BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"
_DECODE = {c: i for i, c in enumerate(BASE32)}

DEFAULT_PRECISION = 6

# Neighbor lookup tables (Chris Veness's algorithm). Index 0 is used when the
# hash length is even, index 1 when it is odd, because the last character of an
# even-length hash splits longitude first and the odd-length one latitude first.
_NEIGHBORS = {
    "n": ("p0r21436x8zb9dcf5h7kjnmqesgutwvy", "bc01fg45238967deuvhjyznpkmstqrwx"),
    "s": ("14365h7k9dcfesgujnmqp0r2twvyx8zb", "238967debc01fg45kmstqrwxuvhjyznp"),
    "e": ("bc01fg45238967deuvhjyznpkmstqrwx", "p0r21436x8zb9dcf5h7kjnmqesgutwvy"),
    "w": ("238967debc01fg45kmstqrwxuvhjyznp", "14365h7k9dcfesgujnmqp0r2twvyx8zb"),
}
_BORDERS = {
    "n": ("prxz", "bcfguvyz"),
    "s": ("028b", "0145hjnp"),
    "e": ("bcfguvyz", "prxz"),
    "w": ("0145hjnp", "028b"),
}


def _check_coords(lat: float, lng: float) -> None:
    if not -90.0 <= lat <= 90.0:
        raise ValueError(f"latitude out of range: {lat}")
    if not -180.0 <= lng <= 180.0:
        raise ValueError(f"longitude out of range: {lng}")


def encode(lat: float, lng: float, precision: int = DEFAULT_PRECISION) -> str:
    """Encode a coordinate pair into a geohash of the given character length."""
    _check_coords(lat, lng)
    if precision < 1 or precision > 12:
        raise ValueError("precision must be between 1 and 12")

    lat_lo, lat_hi = -90.0, 90.0
    lng_lo, lng_hi = -180.0, 180.0
    chars: list[str] = []
    bits = 0
    value = 0
    even = True
    while len(chars) < precision:
        if even:
            mid = (lng_lo + lng_hi) / 2
            if lng >= mid:
                value = (value << 1) | 1
                lng_lo = mid
            else:
                value <<= 1
                lng_hi = mid
        else:
            mid = (lat_lo + lat_hi) / 2
            if lat >= mid:
                value = (value << 1) | 1
                lat_lo = mid
            else:
                value <<= 1
                lat_hi = mid
        even = not even
        bits += 1
        if bits == 5:
            chars.append(BASE32[value])
            bits = 0
            value = 0
    return "".join(chars)


def decode_bbox(geohash: str) -> tuple[float, float, float, float]:
    """Return (lat_min, lat_max, lng_min, lng_max) for the cell."""
    if not geohash:
        raise ValueError("geohash must not be empty")
    lat_lo, lat_hi = -90.0, 90.0
    lng_lo, lng_hi = -180.0, 180.0
    even = True
    for ch in geohash:
        try:
            value = _DECODE[ch]
        except KeyError:
            raise ValueError(f"invalid geohash character: {ch!r}") from None
        for shift in (4, 3, 2, 1, 0):
            bit = (value >> shift) & 1
            if even:
                mid = (lng_lo + lng_hi) / 2
                if bit:
                    lng_lo = mid
                else:
                    lng_hi = mid
            else:
                mid = (lat_lo + lat_hi) / 2
                if bit:
                    lat_lo = mid
                else:
                    lat_hi = mid
            even = not even
    return lat_lo, lat_hi, lng_lo, lng_hi


def decode(geohash: str) -> tuple[float, float]:
    """Return the (lat, lng) center of the cell."""
    lat_lo, lat_hi, lng_lo, lng_hi = decode_bbox(geohash)
    return (lat_lo + lat_hi) / 2, (lng_lo + lng_hi) / 2


def adjacent(geohash: str, direction: str) -> str:
    """Return the neighboring cell in direction n, s, e or w."""
    if direction not in _NEIGHBORS:
        raise ValueError(f"direction must be one of n, s, e, w: {direction!r}")
    if not geohash:
        raise ValueError("geohash must not be empty")
    geohash = geohash.lower()
    last = geohash[-1]
    parent = geohash[:-1]
    kind = len(geohash) % 2
    if last in _BORDERS[direction][kind] and parent:
        parent = adjacent(parent, direction)
    idx = _NEIGHBORS[direction][kind].find(last)
    if idx < 0:
        raise ValueError(f"invalid geohash character: {last!r}")
    return parent + BASE32[idx]


def neighbors(geohash: str) -> list[str]:
    """Return the 8 surrounding cells, starting north and going clockwise."""
    n = adjacent(geohash, "n")
    s = adjacent(geohash, "s")
    return [
        n,
        adjacent(n, "e"),
        adjacent(geohash, "e"),
        adjacent(s, "e"),
        s,
        adjacent(s, "w"),
        adjacent(geohash, "w"),
        adjacent(n, "w"),
    ]


def cell_with_neighbors(geohash: str) -> list[str]:
    """The cell itself followed by its 8 neighbors: the 3x3 block used for lookups."""
    return [geohash, *neighbors(geohash)]
