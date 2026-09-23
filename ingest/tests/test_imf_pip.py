"""Golden-file tests for the IMF PIP connector.

These run offline against captured fixtures, so they catch parser regressions and
upstream schema drift independently of network availability.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ingest import sdmx
from ingest.sources import imf_pip as pip

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def jpn_usa():
    return sdmx.to_frame(FIXTURES / "pip_jpn_usa.xml")


@pytest.fixture
def deu_ita():
    return sdmx.to_frame(FIXTURES / "pip_deu_ita.xml")


def test_parses_series_and_observations(jpn_usa):
    assert not jpn_usa.empty
    assert {"COUNTRY", "COUNTERPART_COUNTRY", "TIME_PERIOD", "OBS_VALUE"} <= set(jpn_usa.columns)
    assert (jpn_usa["COUNTRY"] == "JPN").all()
    assert (jpn_usa["COUNTERPART_COUNTRY"] == "USA").all()


def test_japan_us_debt_securities_2023(jpn_usa):
    """Spot-check against the value verified live on 2026-09-23."""
    row = jpn_usa[(jpn_usa["TIME_PERIOD"] == "2023") & (jpn_usa["COUNTERPART_SECTOR"] == "S1")]
    assert len(row) == 1
    assert row["OBS_VALUE"].iloc[0] == pytest.approx(1.130632457544e12, rel=1e-9)


def test_germany_italy_government_debt_2023(deu_ita):
    """Germany's holdings of Italian *government* debt, verified live."""
    row = deu_ita[(deu_ita["TIME_PERIOD"] == "2023") & (deu_ita["COUNTERPART_SECTOR"] == "S13")]
    assert len(row) == 1
    assert row["OBS_VALUE"].iloc[0] == pytest.approx(5.902136499999999e10, rel=1e-9)


def test_japan_reports_no_government_issuer_split(jpn_usa):
    """Japan reports only the S1 total -- the constraint driving the hybrid edge rule.

    If this ever starts failing, Japan began reporting issuer sector and the network
    view can upgrade JPN edges from 'all debt' to 'government'.
    """
    assert "S13" not in set(jpn_usa["COUNTERPART_SECTOR"])


def test_germany_does_report_government_issuer_split(deu_ita):
    assert "S13" in set(deu_ita["COUNTERPART_SECTOR"])


def test_government_debt_is_a_subset_of_all_debt(deu_ita):
    """Accounting sanity: the S13 issuer slice cannot exceed the S1 total."""
    for period in deu_ita["TIME_PERIOD"].unique():
        year = deu_ita[deu_ita["TIME_PERIOD"] == period]
        total = year[year["COUNTERPART_SECTOR"] == "S1"]["OBS_VALUE"].iloc[0]
        gov = year[year["COUNTERPART_SECTOR"] == "S13"]["OBS_VALUE"].iloc[0]
        assert 0 <= gov <= total, f"{period}: government {gov} exceeds total {total}"


def test_key_builder_has_six_dots():
    """PIP has 7 dimensions; a 7th dot returns HTTP 400."""
    key = pip._key(country="JPN", counterpart_country="USA")
    assert key.count(".") == 6
    assert key == "JPN.A.P_F3_P_USD...USA.A"


def test_key_builder_wildcards_with_empty_string():
    """Wildcarding uses an empty segment, never the literal 'all'."""
    assert pip._key().startswith(".A.")


def test_aggregate_detection():
    assert pip.is_aggregate("TX091")  # International Organizations
    assert pip.is_aggregate("GX031")  # World Minus 25 Significant Financial Centers
    assert not pip.is_aggregate("USA")
    assert not pip.is_aggregate("JPN")


def test_blocked_host_is_refused():
    from ingest.fetch import UpstreamError, fetch

    with pytest.raises(UpstreamError, match="blocks cloud IPs"):
        fetch("https://www.imf.org/en/Publications/WP/Issues/2014/03/07/whatever")
