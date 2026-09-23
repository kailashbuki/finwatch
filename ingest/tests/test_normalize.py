"""Tests for canonicalisation: country codes, aggregates, conduits, net positions."""

from __future__ import annotations

import pandas as pd
import pytest

from ingest import normalize

# --- aggregate detection ----------------------------------------------------------
# PIP ships 88 group codes whose prefixes collide with real countries, so these cases
# are the ones that actually broke a build.


@pytest.mark.parametrize(
    "code",
    [
        "G001",  # World -- appeared as a -$24T "net debtor" before this was filtered
        "G110",  # Advanced Economies
        "G120",  # G20
        "G163",  # Euro Area
        "GASEAN",
        "GSAC",
        "GX031",  # World Minus 25 Significant Financial Centers
        "U002",  # Africa
        "U150",  # Europe
        "TX091",  # International Organizations
        "TX093",  # SEFER + SSIO
        "TX983",  # Not Specified (including Confidential)
        "SDS",  # Small Developing States -- alpha-3 shaped but an aggregate
        "SUN",  # USSR -- defunct
        "XM",  # BIS euro area
        "EA20",
        "",
    ],
)
def test_aggregates_are_detected(code):
    assert normalize.is_aggregate(code)


@pytest.mark.parametrize("code", ["USA", "JPN", "DEU", "GBR", "GRC", "GHA", "GTM", "CHN", "LUX"])
def test_real_countries_are_not_aggregates(code):
    """Guards the prefix collision: GBR/GRC/GHA/GTM must survive a 'G' rule."""
    assert not normalize.is_aggregate(code)


def test_non_string_is_treated_as_aggregate():
    assert normalize.is_aggregate(None)
    assert normalize.is_aggregate(float("nan"))


# --- BIS code mapping -------------------------------------------------------------


def test_bis_alpha2_maps_to_alpha3():
    got = normalize.bis_to_alpha3(pd.Series(["US", "JP", "GB", "DE", "XM"]))
    assert list(got) == ["USA", "JPN", "GBR", "DEU", "XM"]


def test_bis_mapping_covers_every_area_the_api_serves():
    """All 49 areas in WS_CBPOL must map; a new one should fail loudly, not vanish."""
    assert len(normalize.BIS_AREA_TO_ALPHA3) == 49


def test_unmapped_bis_code_raises_by_default():
    with pytest.raises(normalize.UnmappedCodeError, match="ZZ"):
        normalize.bis_to_alpha3(pd.Series(["US", "ZZ"]))


def test_unmapped_bis_code_can_be_tolerated():
    got = normalize.bis_to_alpha3(pd.Series(["US", "ZZ"]), strict=False)
    assert got.iloc[0] == "USA"
    assert pd.isna(got.iloc[1])


# --- conduits ---------------------------------------------------------------------


def test_conduit_detection():
    for code in ("LUX", "IRL", "CYM", "NLD", "BMU"):
        assert normalize.is_conduit(code)
    for code in ("USA", "JPN", "DEU", "CHN"):
        assert not normalize.is_conduit(code)


def test_annotate_conduits_flags_either_side():
    frame = pd.DataFrame(
        {"creditor": ["JPN", "LUX", "USA"], "debtor": ["USA", "DEU", "CYM"], "usd": [1, 2, 3]}
    )
    out = normalize.annotate_conduits(frame, "creditor", "debtor")
    assert list(out["conduit"]) == [False, True, True]


# --- net positions ----------------------------------------------------------------


def test_net_positions_sum_to_zero():
    """Every claim is someone else's liability, so the system must net to zero."""
    frame = pd.DataFrame(
        {
            "creditor": ["JPN", "JPN", "DEU", "USA"],
            "debtor": ["USA", "DEU", "USA", "JPN"],
            "usd": [1000.0, 200.0, 300.0, 50.0],
        }
    )
    net = normalize.net_positions(frame)
    assert net["net"].sum() == pytest.approx(0.0, abs=1e-6)


def test_net_positions_signs_are_right():
    frame = pd.DataFrame({"creditor": ["JPN"], "debtor": ["USA"], "usd": [1000.0]})
    net = normalize.net_positions(frame).set_index("country")["net"]
    assert net["JPN"] == pytest.approx(1000.0)  # creditor is positive
    assert net["USA"] == pytest.approx(-1000.0)


def test_net_positions_excludes_aggregates():
    """A 'World' row would otherwise dominate the whole ranking."""
    frame = pd.DataFrame(
        {
            "creditor": ["JPN", "G001"],
            "debtor": ["USA", "USA"],
            "usd": [1000.0, 24_000_000.0],
        }
    )
    net = normalize.net_positions(frame)
    assert "G001" not in set(net["country"])
    assert net["net"].sum() == pytest.approx(0.0, abs=1e-6)


def test_drop_aggregates_removes_either_side():
    frame = pd.DataFrame(
        {"creditor": ["JPN", "G001", "USA"], "debtor": ["USA", "USA", "U002"], "usd": [1, 2, 3]}
    )
    assert list(normalize.drop_aggregates(frame, "creditor", "debtor")["usd"]) == [1]
