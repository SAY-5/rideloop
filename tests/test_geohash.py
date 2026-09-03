import pytest

from rideloop_common import geohash


@pytest.mark.parametrize(
    ("lat", "lng", "precision", "expected"),
    [
        (42.605, -5.603, 5, "ezs42"),
        (57.64911, 10.40744, 11, "u4pruydqqvj"),
        (37.7749, -122.4194, 6, "9q8yyk"),
        (37.7749, -122.4194, 8, "9q8yyk8y"),
        (0.0, 0.0, 1, "s"),
        (-33.8688, 151.2093, 7, "r3gx2f7"),
        (90.0, 180.0, 4, "zzzz"),
        (-90.0, -180.0, 4, "0000"),
    ],
)
def test_encode_known_vectors(lat, lng, precision, expected):
    assert geohash.encode(lat, lng, precision) == expected


def test_default_precision_is_six():
    assert len(geohash.encode(48.8566, 2.3522)) == 6


def test_decode_returns_cell_center():
    lat, lng = geohash.decode("u4pruydqqvj")
    assert lat == pytest.approx(57.64911, abs=1e-5)
    assert lng == pytest.approx(10.40744, abs=1e-5)


def test_decode_bbox_contains_original_point():
    lat, lng = 37.7749, -122.4194
    h = geohash.encode(lat, lng, 5)
    lat_lo, lat_hi, lng_lo, lng_hi = geohash.decode_bbox(h)
    assert lat_lo <= lat <= lat_hi
    assert lng_lo <= lng <= lng_hi
    # precision 5 cells are roughly 0.044 degrees tall and wide
    assert lat_hi - lat_lo == pytest.approx(0.0439453125)
    assert lng_hi - lng_lo == pytest.approx(0.0439453125)


def test_prefix_is_a_containing_cell():
    full = geohash.encode(51.5074, -0.1278, 8)
    for n in range(1, 8):
        lo_lat, hi_lat, lo_lng, hi_lng = geohash.decode_bbox(full[:n])
        assert lo_lat <= 51.5074 <= hi_lat
        assert lo_lng <= -0.1278 <= hi_lng


def test_neighbors_reference_vector():
    assert geohash.neighbors("ezs42") == [
        "ezs48",
        "ezs49",
        "ezs43",
        "ezs41",
        "ezs40",
        "ezefp",
        "ezefr",
        "ezefx",
    ]


def test_adjacent_directions():
    assert geohash.adjacent("9q8yy", "n") == "9q8zn"
    assert geohash.adjacent("9q8yy", "s") == "9q8yw"
    assert geohash.adjacent("9q8yy", "e") == "9q8yz"
    assert geohash.adjacent("9q8yy", "w") == "9q8yv"


def test_neighbors_are_geometrically_adjacent():
    """Every neighbor's bbox must touch the center bbox on a side or a corner."""
    center = geohash.encode(37.7749, -122.4194, 6)
    c_lat_lo, c_lat_hi, c_lng_lo, c_lng_hi = geohash.decode_bbox(center)
    height = c_lat_hi - c_lat_lo
    width = c_lng_hi - c_lng_lo
    for n in geohash.neighbors(center):
        n_lat_lo, n_lat_hi, n_lng_lo, n_lng_hi = geohash.decode_bbox(n)
        assert abs((n_lat_lo + n_lat_hi) / 2 - (c_lat_lo + c_lat_hi) / 2) <= height + 1e-9
        assert abs((n_lng_lo + n_lng_hi) / 2 - (c_lng_lo + c_lng_hi) / 2) <= width + 1e-9
        assert n != center


def test_neighbors_are_unique_and_eight():
    block = geohash.cell_with_neighbors("u4pru")
    assert len(block) == 9
    assert len(set(block)) == 9
    assert block[0] == "u4pru"


def test_neighbor_crosses_parent_boundary():
    # 'ezs40' sits on the southern edge of parent 'ezs4', so the parent changes too
    south = geohash.adjacent("ezs40", "s")
    assert south == "ezs1b"
    assert south[:4] == geohash.adjacent("ezs4", "s")


@pytest.mark.parametrize(("lat", "lng"), [(91, 0), (-91, 0), (0, 181), (0, -181)])
def test_encode_rejects_out_of_range(lat, lng):
    with pytest.raises(ValueError):
        geohash.encode(lat, lng)


def test_encode_rejects_bad_precision():
    with pytest.raises(ValueError):
        geohash.encode(0, 0, 0)
    with pytest.raises(ValueError):
        geohash.encode(0, 0, 13)


def test_decode_rejects_invalid_characters():
    with pytest.raises(ValueError):
        geohash.decode("9q8a")  # 'a' is not in the geohash alphabet
    with pytest.raises(ValueError):
        geohash.decode("")
