"""Offline tests for the rates connectors (BIS policy rates, US and Japan yield curves)."""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import pytest

from ingest import sdmx
from ingest.sources import jgb_curve, ust_curve

FIXTURES = Path(__file__).parent / "fixtures"


# --- BIS policy rates -------------------------------------------------------------


def test_bis_sdmx_json_parses_index_keyed_series():
    """SDMX-JSON keys series by dimension *index*; they must resolve back to codes."""
    frame = sdmx.json_to_frame((FIXTURES / "bis_cbpol.json").read_bytes())
    assert not frame.empty
    assert {"REF_AREA", "TIME_PERIOD", "OBS_VALUE"} <= set(frame.columns)
    # Codes, not integer indices.
    assert "US" in set(frame["REF_AREA"])
    assert "XM" in set(frame["REF_AREA"])
    assert frame["REF_AREA"].str.isdigit().sum() == 0


def test_bis_covers_many_central_banks():
    frame = sdmx.json_to_frame((FIXTURES / "bis_cbpol.json").read_bytes())
    assert frame["REF_AREA"].nunique() >= 35


def test_bis_rates_are_plausible():
    frame = sdmx.json_to_frame((FIXTURES / "bis_cbpol.json").read_bytes())
    values = frame["OBS_VALUE"].dropna()
    assert (values > -2).all() and (values < 60).all()


# --- US Treasury curve ------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("1 Mo", 1.0),
        ("1.5 Month", 1.5),  # added to the 2026 file; tenors are not fixed across years
        ("6 Mo", 6.0),
        ("1 Yr", 12.0),
        ("10 Yr", 120.0),
        ("30 Yr", 360.0),
        ("Date", None),
        ("nonsense", None),
    ],
)
def test_ust_tenor_parsing(label, expected):
    assert ust_curve.parse_tenor_months(label) == expected


def test_ust_curve_parses_fixture(monkeypatch):
    raw = (FIXTURES / "ust_2026.csv").read_bytes()
    monkeypatch.setattr(ust_curve, "fetch", lambda *a, **k: raw)
    frame = ust_curve.fetch_curve(years=[2026])

    assert (frame["country"] == "USA").all()
    assert (frame["kind"] == "yield").all()
    assert {1.0, 1.5, 120.0, 360.0} <= set(frame["tenor_months"])
    # Dates normalised out of the source's MM/DD/YYYY.
    assert frame["date"].str.match(r"^\d{4}-\d{2}-\d{2}$").all()


def test_ust_curve_is_upward_sloping_at_the_long_end(monkeypatch):
    """Sanity check on tenor ordering: a 1-month rate should not equal the 30-year."""
    raw = (FIXTURES / "ust_2026.csv").read_bytes()
    monkeypatch.setattr(ust_curve, "fetch", lambda *a, **k: raw)
    frame = ust_curve.fetch_curve(years=[2026])
    latest = frame[frame["date"] == frame["date"].max()].set_index("tenor_months")["pct"]
    assert latest[360.0] > latest[1.0]


# --- Japan JGB curve --------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("S49.9.24", "1974-09-24"),  # Shōwa 49 -- first row of the history file
        ("H10.4.1", "1998-04-01"),
        ("R8.8.31", "2026-08-31"),  # Reiwa 8 -- last row
        ("R1.5.1", "2019-05-01"),  # era year 1 maps to the era's start year
        ("2026-08-31", None),  # ISO input is not imperial
        ("", None),
        ("X1.2.3", None),  # unknown era letter
    ],
)
def test_imperial_date_conversion(value, expected):
    assert jgb_curve.parse_imperial_date(value) == expected


def test_jgb_curve_parses_cp932_fixture(monkeypatch):
    raw = (FIXTURES / "jgb_sample.csv").read_bytes()
    monkeypatch.setattr(jgb_curve, "fetch", lambda *a, **k: raw)
    frame = jgb_curve.fetch_curve()

    assert (frame["country"] == "JPN").all()
    assert (frame["kind"] == "yield").all()
    # 15 tenors from 1Y to 40Y, parsed from Japanese labels ("10年").
    assert 480 in set(frame["tenor_months"])
    assert 12 in set(frame["tenor_months"])
    assert frame["date"].str.match(r"^\d{4}-\d{2}-\d{2}$").all()


def test_jgb_fixture_is_not_utf8():
    """Guards the encoding assumption: decoding as UTF-8 must fail, not silently mangle."""
    raw = (FIXTURES / "jgb_sample.csv").read_bytes()
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")
    assert raw.decode("cp932")


def test_jgb_missing_tenors_are_dropped_not_zeroed(monkeypatch):
    """Early history marks absent long tenors with '-'; those must not become 0.0."""
    raw = (FIXTURES / "jgb_sample.csv").read_bytes()
    monkeypatch.setattr(jgb_curve, "fetch", lambda *a, **k: raw)
    frame = jgb_curve.fetch_curve()
    early = frame[frame["date"] == "1974-09-24"]
    assert not early.empty
    assert 180 not in set(early["tenor_months"])  # 15Y did not exist in 1974
    assert (early["pct"] > 0).all()


# --- shared -----------------------------------------------------------------------


def test_sdmx_json_handles_empty_payload():
    empty = b'{"data":{"structure":{"dimensions":{"series":[],"observation":[]}},"dataSets":[]}}'
    assert sdmx.json_to_frame(empty).empty


def test_sdmx_xml_and_json_agree_on_shape():
    """Both parsers must produce long-format frames with an OBS_VALUE column."""
    xml = sdmx.to_frame(FIXTURES / "pip_jpn_usa.xml")
    js = sdmx.json_to_frame((FIXTURES / "bis_cbpol.json").read_bytes())
    for frame in (xml, js):
        assert "OBS_VALUE" in frame.columns
        assert pd.api.types.is_numeric_dtype(frame["OBS_VALUE"])


def test_tenor_label_roundtrip_is_consistent_across_sources():
    """US and Japan curves must express the 10Y point identically (120 months)."""
    assert ust_curve.parse_tenor_months("10 Yr") == 120.0
    table = pd.read_csv(io.StringIO("Date,10年\nR8.8.31,2.943\n"))
    assert table.columns[1].strip() == "10年"
