"""Canonicalisation shared by every connector.

Two jobs that are easy to get subtly wrong and expensive to debug downstream:

1. **Country codes.** ISO alpha-3 is the join key everywhere. BIS uses 2-letter codes,
   PIP uses alpha-3 plus its own pseudo-economies. Mapping is explicit rather than
   library-driven so an unmapped code is a loud failure, not a silent drop.
2. **Aggregates.** Euro-area and "rest of world" style rows are not countries. Summing
   them alongside real economies double-counts; drawing them on a map is meaningless.
"""

from __future__ import annotations

import logging

import pandas as pd

log = logging.getLogger(__name__)

#: BIS ``REF_AREA`` (ISO alpha-2) -> ISO alpha-3. Covers all 49 areas the dataset serves.
BIS_AREA_TO_ALPHA3: dict[str, str] = {
    "AR": "ARG", "AT": "AUT", "AU": "AUS", "BE": "BEL", "BR": "BRA", "CA": "CAN",
    "CH": "CHE", "CL": "CHL", "CN": "CHN", "CO": "COL", "CZ": "CZE", "DE": "DEU",
    "DK": "DNK", "ES": "ESP", "FR": "FRA", "GB": "GBR", "GR": "GRC", "HK": "HKG",
    "HR": "HRV", "HU": "HUN", "ID": "IDN", "IL": "ISR", "IN": "IND", "IS": "ISL",
    "IT": "ITA", "JP": "JPN", "KR": "KOR", "KW": "KWT", "MA": "MAR", "MK": "MKD",
    "MX": "MEX", "MY": "MYS", "NL": "NLD", "NO": "NOR", "NZ": "NZL", "PE": "PER",
    "PH": "PHL", "PL": "POL", "PT": "PRT", "RO": "ROU", "RS": "SRB", "RU": "RUS",
    "SA": "SAU", "SE": "SWE", "TH": "THA", "TR": "TUR", "US": "USA", "ZA": "ZAF",
    # Not a country: the euro area as a currency union. Preserved as an aggregate.
    "XM": "XM",
}

#: Codes that are not sovereign states. Never drawn on the map, never summed with countries.
#:
#: Detection is *shape-based* (see :func:`is_aggregate`) rather than prefix-based, because
#: PIP's aggregate prefixes collide with real countries -- ``G001`` is "World" but ``GBR``,
#: ``GRC`` and ``GHA`` are countries, and ``U002`` is Africa. Anything that is not a
#: well-formed ISO alpha-3 code is treated as a non-country; this set holds the exceptions
#: that *look* like alpha-3 but are not current sovereign states.
AGGREGATES: frozenset[str] = frozenset(
    {
        "XM",  # BIS: euro area
        "EA20",  # OECD: euro area (20 members)
        "EA19",
        "EU27_2020",
        "W00",
        "_Z",
        "SDS",  # PIP: Small Developing States -- an aggregate despite the alpha-3 shape
        "SUN",  # PIP: USSR -- a defunct state, not a current issuer
    }
)

#: PIP codes that pass the alpha-3 shape test but denote unallocated or supranational
#: holdings. Kept separate from :data:`AGGREGATES` only for documentation; both are excluded.
UNALLOCATED = frozenset({"TX091", "TX093", "TX983"})

#: Jurisdictions whose reported holdings are dominated by fund domicile rather than by
#: residents actually financing anyone. PIP records holdings by *residence of the immediate
#: holder*, so these appear among the world's largest creditors as a legal artifact.
#:
#: They are kept in the data and flagged, never silently dropped: real flows genuinely do
#: route through them. The UI must show the conduit marker and explain the domicile bias.
CONDUIT_JURISDICTIONS: frozenset[str] = frozenset(
    {
        "LUX",  # Luxembourg -- fund domicile
        "IRL",  # Ireland -- fund domicile
        "CYM",  # Cayman Islands -- fund domicile
        "NLD",  # Netherlands -- financing/holding structures
        "BMU",  # Bermuda
        "JEY",  # Jersey
        "GGY",  # Guernsey
        "CUW",  # Curacao
        "VGB",  # British Virgin Islands
        "MLT",  # Malta
    }
)


class UnmappedCodeError(ValueError):
    """A country code could not be mapped to ISO alpha-3."""


def bis_to_alpha3(series: pd.Series, *, strict: bool = True) -> pd.Series:
    """Map a BIS ``REF_AREA`` column to ISO alpha-3.

    Raises on unmapped codes by default: BIS silently adding an area is something we want
    to hear about, not to drop on the floor.
    """
    mapped = series.map(BIS_AREA_TO_ALPHA3)
    missing = sorted(set(series[mapped.isna()].unique()))
    if missing:
        message = f"unmapped BIS area codes: {missing}"
        if strict:
            raise UnmappedCodeError(message)
        log.warning("%s (dropped)", message)
    return mapped


def is_aggregate(code: str) -> bool:
    """True for anything that is not a current sovereign state.

    Catches PIP's 88 group codes (``G001`` World, ``G120`` G20, ``U002`` Africa,
    ``GX031``, ``TX091`` International Organizations, ``GASEAN``, ...) by rejecting
    anything that is not a well-formed 3-letter alpha code, plus the explicit
    :data:`AGGREGATES` exceptions that do have that shape.

    Note this also excludes non-sovereign territories PIP reports separately, such as
    ``TX117`` (Jersey). That is intended: they are not sovereign bond issuers and do not
    belong on a map of governments. It does mean Jersey's conduit role is not represented.
    """
    if not isinstance(code, str):
        return True
    if code in AGGREGATES or code in UNALLOCATED:
        return True
    return not (len(code) == 3 and code.isalpha() and code.isupper())


def is_conduit(code: str) -> bool:
    """True for jurisdictions whose holdings reflect fund domicile more than real financing."""
    return code in CONDUIT_JURISDICTIONS


def drop_aggregates(frame: pd.DataFrame, *columns: str) -> pd.DataFrame:
    """Remove rows where any of ``columns`` holds an aggregate code."""
    mask = pd.Series(True, index=frame.index)
    for column in columns:
        mask &= ~frame[column].map(is_aggregate)
    dropped = int((~mask).sum())
    if dropped:
        log.info("dropped %d rows referencing aggregates", dropped)
    return frame[mask]


def annotate_conduits(frame: pd.DataFrame, *columns: str) -> pd.DataFrame:
    """Add a boolean ``conduit`` column true when any of ``columns`` is a conduit."""
    frame = frame.copy()
    mask = pd.Series(False, index=frame.index)
    for column in columns:
        mask |= frame[column].map(is_conduit)
    frame["conduit"] = mask
    return frame


def net_positions(holdings: pd.DataFrame) -> pd.DataFrame:
    """Derive each country's net creditor/debtor position for a single period.

    ``net = claims on others - own debt held by others``. Positive means net creditor.
    Aggregates are excluded first so the result sums to approximately zero.
    """
    clean = drop_aggregates(holdings, "creditor", "debtor")
    claims = clean.groupby("creditor")["usd"].sum().rename("claims")
    liabilities = clean.groupby("debtor")["usd"].sum().rename("liabilities")

    net = pd.concat([claims, liabilities], axis=1).fillna(0.0)
    net["net"] = net["claims"] - net["liabilities"]
    net.index.name = "country"
    return net.reset_index().sort_values("net", ascending=False).reset_index(drop=True)
