"""Fake-by-default + DART OpenAPI quarterly financial statement data source (SoT C1 — adapters).

SoT ADR 0004 (fake-by-default adapters) / B3: ``FakeFinancialStatementDataSource``
is the default, network-free implementation; ``DartFinancialStatementDataSource``
is the real one, selected via ``Settings.data_source`` in
``src/workers/settings.py`` — same pattern as ``PykrxDataSource``/``PykrxPriceDataSource``.

Kept in its own file rather than folded into ``data_sources.py``: DART is a
different provider family with a different auth model (a required API key,
``crtfc_key``), a different transport (``httpx.AsyncClient`` calling a JSON
REST API directly, not a scraping library wrapped in ``asyncio.to_thread``),
and a different per-call cardinality (one call per company; no bulk
all-tickers endpoint) — the same rationale ``krx_fallback.py`` is a separate
file from ``data_sources.py``.

**DART response status handling (three-way branch).** Unlike pykrx (which
raises Python exceptions on scrape failure), DART always returns HTTP 200
with a ``status`` field in the JSON body:

- ``"000"`` (success) — parse the response.
- ``"013"`` (no data for this company/period) — a normal empty result, not a
  retry candidate; try the other ``fs_div`` (CFS -> OFS) or move on.
- A systemic status (``010``/``011``/``020``/``800``/``901`` — bad/expired
  key, quota exceeded, maintenance) — the whole key is affected, not just
  this company, so per-company retry would only hammer an already-throttled
  key across the ~2,500-ticker universe. ``DartSystemicError`` is raised
  immediately and is never caught here or in
  ``src.services.financial_statement_sync`` — the batch aborts fail-closed
  and the caller (a later issue's cron wiring, #39/#40) sees the failure.
- Anything else (unrecognized status, or a network/HTTP exception) is
  treated as transient: retried up to ``_MAX_ATTEMPTS`` with exponential
  backoff, and on exhaustion that company is skipped with a warning log —
  mirroring ``PykrxIndexPriceDataSource``'s VKOSPI degrade-one-data-point
  precedent, but scoped to per-company failures only (see the class
  docstrings below for why that precedent does not extend to the systemic
  branch).

**API key log masking.** DART takes ``crtfc_key`` as a query parameter, not a
header, so any log line that includes a request URL risks leaking the key.
``_mask_api_key`` replaces the ``crtfc_key`` value before any URL is ever
logged, and every exception message this module raises past a failed HTTP
call is already-sanitized (never a raw ``httpx`` exception's ``str()``,
which would embed the unmasked URL) — the retry/log path never needs to
re-derive or re-check masking.
"""

from __future__ import annotations

import asyncio
import io
import logging
import zipfile
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from xml.etree import ElementTree

import httpx

from src.domain.financial_statement import ConsolidatedType, FinancialStatementInfo, FiscalQuarter

logger = logging.getLogger(__name__)

_DART_BASE_URL = "https://opendart.fss.or.kr/api"
_STATEMENT_ENDPOINT = f"{_DART_BASE_URL}/fnlttSinglAcntAll.json"
_CORP_CODE_ENDPOINT = f"{_DART_BASE_URL}/corpCode.xml"

_REQUEST_TIMEOUT_SECONDS = 10.0
_CORP_CODE_TIMEOUT_SECONDS = 30.0
_MAX_ATTEMPTS = 3
_INITIAL_BACKOFF_SECONDS = 1.0
_REQUEST_DELAY_SECONDS = 0.2

_STATUS_SUCCESS = "000"
_STATUS_NO_DATA = "013"
_SYSTEMIC_STATUS_CODES = frozenset({"010", "011", "020", "800", "901"})

# fiscal_quarter -> DART reprt_code (사업보고서 = 연간, no standalone "Q4"
# report exists — see FiscalQuarter's docstring).
_FISCAL_QUARTER_TO_REPRT_CODE: dict[FiscalQuarter, str] = {
    FiscalQuarter.Q1: "11013",
    FiscalQuarter.H1: "11012",
    FiscalQuarter.Q3: "11014",
    FiscalQuarter.ANNUAL: "11011",
}

# Only the six BS/IS top-level totals are matched by account_nm — these are
# standardized across nearly every KRX-listed company's filings, unlike the
# line items EV/EBITDA would need (see this module's docstring / the domain
# module's docstring on why those are out of scope).
_INCOME_STATEMENT_ACCOUNTS: dict[str, str] = {
    "매출액": "revenue",
    "영업이익": "operating_income",
    "당기순이익": "net_income",
}
_BALANCE_SHEET_ACCOUNTS: dict[str, str] = {
    "자산총계": "total_assets",
    "부채총계": "total_liabilities",
    "자본총계": "total_equity",
}
_INCOME_STATEMENT_DIVS = frozenset({"IS", "CIS"})
_BALANCE_SHEET_DIV = "BS"

_FAKE_STATEMENTS: tuple[tuple[str, int, int, int, int, int, int], ...] = (
    # ticker, revenue, operating_income, net_income, total_assets, total_liabilities, total_equity
    (
        "005930",
        300_000_000_000_000,
        40_000_000_000_000,
        30_000_000_000_000,
        450_000_000_000_000,
        100_000_000_000_000,
        350_000_000_000_000,
    ),
    (
        "000660",
        40_000_000_000_000,
        5_000_000_000_000,
        4_000_000_000_000,
        80_000_000_000_000,
        30_000_000_000_000,
        50_000_000_000_000,
    ),
    (
        "086520",
        1_500_000_000_000,
        200_000_000_000,
        150_000_000_000,
        3_000_000_000_000,
        1_000_000_000_000,
        2_000_000_000_000,
    ),
)

_FAKE_DISCLOSURE_MONTH_DAY: dict[FiscalQuarter, tuple[int, int]] = {
    FiscalQuarter.Q1: (5, 15),
    FiscalQuarter.H1: (8, 14),
    FiscalQuarter.Q3: (11, 14),
    FiscalQuarter.ANNUAL: (3, 31),
}


class DartSystemicError(RuntimeError):
    """A DART response ``status`` indicates the whole API key is affected (SoT plan).

    Deliberately never caught in this module or ``src.services.financial_statement_sync``
    — see the module docstring's status-handling section.
    """


def _mask_api_key(url: httpx.URL) -> str:
    """Return ``url`` as a string with ``crtfc_key`` replaced by ``***``.

    Every log line in this module that includes a request URL must go
    through this first — DART accepts the API key only as a query
    parameter, so an unmasked URL in a log line leaks ``DART_API_KEY``.
    """
    if "crtfc_key" not in url.params:
        return str(url)
    masked_params = dict(url.params)
    masked_params["crtfc_key"] = "***"
    return str(url.copy_with(params=masked_params))


def _fake_disclosed_at(fiscal_year: int, fiscal_quarter: FiscalQuarter) -> date:
    month, day = _FAKE_DISCLOSURE_MONTH_DAY[fiscal_quarter]
    year = fiscal_year + 1 if fiscal_quarter == FiscalQuarter.ANNUAL else fiscal_year
    return date(year, month, day)


class FakeFinancialStatementDataSource:
    """Deterministic stand-in for a real DART-backed provider.

    Never calls out to the network. Returns a fixed CFS sample for whichever
    of its known tickers appear in the requested ``tickers`` — unlike
    ``FakePriceDataSource``, this Protocol takes an explicit ``tickers``
    argument (DART has no bulk endpoint), so the fake must honor it rather
    than always returning every fixture row.
    """

    async def get_quarterly_statements(
        self, tickers: list[str], fiscal_year: int, fiscal_quarter: FiscalQuarter
    ) -> list[FinancialStatementInfo]:
        requested = set(tickers)
        disclosed_at = _fake_disclosed_at(fiscal_year, fiscal_quarter)
        return [
            FinancialStatementInfo(
                ticker=ticker,
                fiscal_year=fiscal_year,
                fiscal_quarter=fiscal_quarter,
                consolidated_type=ConsolidatedType.CFS,
                revenue=Decimal(revenue),
                operating_income=Decimal(operating_income),
                net_income=Decimal(net_income),
                total_assets=Decimal(total_assets),
                total_liabilities=Decimal(total_liabilities),
                total_equity=Decimal(total_equity),
                disclosed_at=disclosed_at,
                rcept_no=f"{disclosed_at.strftime('%Y%m%d')}{ticker}",
            )
            for (
                ticker,
                revenue,
                operating_income,
                net_income,
                total_assets,
                total_liabilities,
                total_equity,
            ) in _FAKE_STATEMENTS
            if ticker in requested
        ]


def _parse_corp_code_zip(content: bytes) -> dict[str, str]:
    """Blocking zip/XML parse — callers must run this via ``asyncio.to_thread``.

    Only rows with a non-empty ``stock_code`` are kept: unlisted companies
    have no ticker to key off of.
    """
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        xml_bytes = archive.read("CORPCODE.xml")
    root = ElementTree.fromstring(xml_bytes)
    mapping: dict[str, str] = {}
    for item in root.findall("list"):
        stock_code = (item.findtext("stock_code") or "").strip()
        corp_code = (item.findtext("corp_code") or "").strip()
        if stock_code:
            mapping[stock_code] = corp_code
    return mapping


def _extract_line_items(data: Mapping[str, Any]) -> tuple[dict[str, Decimal | None], str]:
    values: dict[str, Decimal | None] = dict.fromkeys(
        [*_INCOME_STATEMENT_ACCOUNTS.values(), *_BALANCE_SHEET_ACCOUNTS.values()]
    )
    rcept_no = ""
    for item in data.get("list") or []:
        account_nm = (item.get("account_nm") or "").strip()
        sj_div = item.get("sj_div")

        field = _INCOME_STATEMENT_ACCOUNTS.get(account_nm)
        if field is not None and sj_div not in _INCOME_STATEMENT_DIVS:
            continue
        if field is None:
            field = _BALANCE_SHEET_ACCOUNTS.get(account_nm)
            if field is not None and sj_div != _BALANCE_SHEET_DIV:
                continue
        if field is None:
            continue

        amount_str = str(item.get("thstrm_amount") or "").replace(",", "").strip()
        if amount_str:
            try:
                values[field] = Decimal(amount_str)
            except Exception:  # noqa: BLE001 - a malformed amount degrades to "not found", not a crash
                continue
        rcept_no = item.get("rcept_no") or rcept_no
    return values, rcept_no


def _rcept_no_to_disclosed_at(rcept_no: str) -> date:
    """DART receipt numbers are 14-digit strings; the first 8 are the filing date (YYYYMMDD)."""
    return datetime.strptime(rcept_no[:8], "%Y%m%d").date()


def _parse_statement(
    ticker: str,
    fiscal_year: int,
    fiscal_quarter: FiscalQuarter,
    consolidated_type: ConsolidatedType,
    data: Mapping[str, Any],
) -> FinancialStatementInfo | None:
    values, rcept_no = _extract_line_items(data)
    if not rcept_no:
        # DART reported "success" but none of the six known account names
        # matched anything in this company's response — treat as no usable
        # data rather than emitting a row with an invalid disclosed_at.
        return None
    return FinancialStatementInfo(
        ticker=ticker,
        fiscal_year=fiscal_year,
        fiscal_quarter=fiscal_quarter,
        consolidated_type=consolidated_type,
        revenue=values["revenue"],
        operating_income=values["operating_income"],
        net_income=values["net_income"],
        total_assets=values["total_assets"],
        total_liabilities=values["total_liabilities"],
        total_equity=values["total_equity"],
        disclosed_at=_rcept_no_to_disclosed_at(rcept_no),
        rcept_no=rcept_no,
    )


class DartFinancialStatementDataSource:
    """DART OpenAPI-backed quarterly financial statement provider (SoT C1/A6.1/A6.7.2).

    corp_code<->ticker mapping is lazily loaded from DART's ``corpCode.xml``
    on first use and cached on the instance; ``refresh_corp_code_map`` forces
    a reload (real periodic refresh is later cron-wiring's scope, #39/#40).
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._corp_code_map: dict[str, str] | None = None

    async def refresh_corp_code_map(self) -> None:
        url = httpx.URL(_CORP_CODE_ENDPOINT, params={"crtfc_key": self._api_key})
        async with httpx.AsyncClient(timeout=_CORP_CODE_TIMEOUT_SECONDS) as client:
            response = await client.get(url)
            response.raise_for_status()
            content = response.content
        # zip/XML parsing is synchronous CPU work — offloaded so it doesn't
        # block the event loop (the httpx download above stays async).
        self._corp_code_map = await asyncio.to_thread(_parse_corp_code_zip, content)

    async def _get_corp_code_map(self) -> dict[str, str]:
        if self._corp_code_map is None:
            await self.refresh_corp_code_map()
        assert self._corp_code_map is not None
        return self._corp_code_map

    async def _request_statement(
        self, corp_code: str, fiscal_year: int, reprt_code: str, consolidated_type: ConsolidatedType
    ) -> dict[str, Any]:
        """One DART API call.

        Raises ``DartSystemicError`` immediately on a systemic status code
        (no retry — see module docstring). Any other failure raises an
        already-masked ``RuntimeError`` for ``_fetch_with_retry`` to catch;
        the original ``httpx`` exception is intentionally not chained
        (``from None``) so its unmasked-URL message can never surface via
        traceback formatting either.
        """
        params = {
            "crtfc_key": self._api_key,
            "corp_code": corp_code,
            "bsns_year": str(fiscal_year),
            "reprt_code": reprt_code,
            "fs_div": consolidated_type.value,
        }
        url = httpx.URL(_STATEMENT_ENDPOINT, params=params)
        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.get(url)
                response.raise_for_status()
                data: dict[str, Any] = response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"DART request failed ({type(exc).__name__}) url={_mask_api_key(url)}"
            ) from None

        status = data.get("status")
        if status in _SYSTEMIC_STATUS_CODES:
            raise DartSystemicError(
                f"DART systemic error status={status} message={data.get('message')}"
                f" url={_mask_api_key(url)}"
            )
        if status not in (_STATUS_SUCCESS, _STATUS_NO_DATA):
            # An unrecognized status (e.g. a bad request-parameter code) is
            # treated the same as a network failure — transient, retried by
            # _fetch_with_retry — rather than silently skipped like "013".
            raise RuntimeError(
                f"DART unexpected status={status} message={data.get('message')}"
                f" url={_mask_api_key(url)}"
            )
        return data

    async def _fetch_with_retry(
        self, corp_code: str, fiscal_year: int, reprt_code: str, consolidated_type: ConsolidatedType
    ) -> dict[str, Any] | None:
        delay = _INITIAL_BACKOFF_SECONDS
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                return await self._request_statement(
                    corp_code, fiscal_year, reprt_code, consolidated_type
                )
            except DartSystemicError:
                raise
            except Exception as exc:  # noqa: BLE001 - transient boundary, mirrors data_sources._fetch_with_retry
                logger.warning(
                    "DART statement fetch failed for corp_code=%s (attempt %d/%d): %s",
                    corp_code,
                    attempt,
                    _MAX_ATTEMPTS,
                    exc,
                )
                if attempt < _MAX_ATTEMPTS:
                    await asyncio.sleep(delay)
                    delay *= 2
        logger.warning(
            "DART statement fetch exhausted retries for corp_code=%s fiscal_year=%s"
            " reprt_code=%s; skipping",
            corp_code,
            fiscal_year,
            reprt_code,
        )
        return None

    async def _get_statement_for_ticker(
        self,
        ticker: str,
        corp_code: str,
        fiscal_year: int,
        fiscal_quarter: FiscalQuarter,
        reprt_code: str,
    ) -> FinancialStatementInfo | None:
        for consolidated_type in (ConsolidatedType.CFS, ConsolidatedType.OFS):
            data = await self._fetch_with_retry(
                corp_code, fiscal_year, reprt_code, consolidated_type
            )
            if data is None:
                # Transient retries exhausted for this fs_div (already logged
                # above) — still try the other fs_div rather than giving up
                # on the whole ticker.
                continue
            status = data["status"]
            if status == _STATUS_SUCCESS:
                statement = _parse_statement(
                    ticker, fiscal_year, fiscal_quarter, consolidated_type, data
                )
                if statement is not None:
                    return statement
                continue
            if status == _STATUS_NO_DATA:
                logger.debug(
                    "DART has no %s data for corp_code=%s fiscal_year=%s reprt_code=%s",
                    consolidated_type.value,
                    corp_code,
                    fiscal_year,
                    reprt_code,
                )
                continue
        return None

    async def get_quarterly_statements(
        self, tickers: list[str], fiscal_year: int, fiscal_quarter: FiscalQuarter
    ) -> list[FinancialStatementInfo]:
        corp_code_map = await self._get_corp_code_map()
        reprt_code = _FISCAL_QUARTER_TO_REPRT_CODE[fiscal_quarter]
        statements: list[FinancialStatementInfo] = []
        for ticker in tickers:
            corp_code = corp_code_map.get(ticker)
            if corp_code is None:
                continue
            statement = await self._get_statement_for_ticker(
                ticker, corp_code, fiscal_year, fiscal_quarter, reprt_code
            )
            if statement is not None:
                statements.append(statement)
            await asyncio.sleep(_REQUEST_DELAY_SECONDS)
        return statements
