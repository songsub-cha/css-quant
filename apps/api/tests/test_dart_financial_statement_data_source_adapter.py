"""``DartFinancialStatementDataSource`` (SoT C1/A6.1/A6.7.2 — adapters).

Monkeypatches ``httpx.AsyncClient`` wholesale — same network-free rationale
as ``test_krx_fallback.py`` monkeypatching ``httpx.post``, adapted for the
async client this module uses. A fake corp_code zip is built in-memory with
the real ``zipfile``/XML machinery so ``_parse_corp_code_zip`` is exercised
for real, not mocked away.
"""

from __future__ import annotations

import asyncio
import io
import logging
import zipfile
from collections.abc import Awaitable, Callable
from datetime import date
from decimal import Decimal
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

import httpx
import pytest

from src.adapters.dart_financial_data_source import (
    _FISCAL_QUARTER_TO_REPRT_CODE,
    DartFinancialStatementDataSource,
    DartSystemicError,
    _mask_api_key,
)
from src.domain.financial_statement import ConsolidatedType, FiscalQuarter

_API_KEY = "super-secret-dart-key"


class _FakeResponse:
    def __init__(
        self,
        *,
        json_data: dict[str, Any] | None = None,
        content: bytes = b"",
        status_code: int = 200,
    ) -> None:
        self._json_data = json_data
        self.content = content
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://opendart.fss.or.kr/api/test")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError(
                f"status {self.status_code}", request=request, response=response
            )

    def json(self) -> dict[str, Any]:
        assert self._json_data is not None
        return self._json_data


class _FakeAsyncClient:
    def __init__(self, handler: Callable[[httpx.URL], Awaitable[_FakeResponse]]) -> None:
        self._handler = handler

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def get(self, url: httpx.URL, **kwargs: Any) -> _FakeResponse:
        return await self._handler(url)


def _install_fake_client(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.URL], Awaitable[_FakeResponse]]
) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: _FakeAsyncClient(handler))


async def _no_op_sleep(_seconds: float) -> None:
    return None


def _is_corp_code_url(url: httpx.URL) -> bool:
    return url.path.endswith("corpCode.xml")


def _build_corp_code_zip(entries: list[tuple[str, str, str]]) -> bytes:
    root = Element("result")
    for corp_code, corp_name, stock_code in entries:
        item = SubElement(root, "list")
        SubElement(item, "corp_code").text = corp_code
        SubElement(item, "corp_name").text = corp_name
        SubElement(item, "stock_code").text = stock_code
        SubElement(item, "modify_date").text = "20260101"
    xml_bytes = tostring(root, encoding="utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("CORPCODE.xml", xml_bytes)
    return buffer.getvalue()


_CORP_CODE_ZIP = _build_corp_code_zip(
    [
        ("00126380", "삼성전자", "005930"),
        ("00164779", "SK하이닉스", "000660"),
        ("00999999", "비상장기업", ""),
    ]
)


def _line_item(
    account_nm: str, amount: str, *, sj_div: str, rcept_no: str = "20260514000123"
) -> dict[str, str]:
    return {
        "rcept_no": rcept_no,
        "account_nm": account_nm,
        "thstrm_amount": amount,
        "sj_div": sj_div,
    }


_FULL_LINE_ITEMS = [
    _line_item("매출액", "300000000000000", sj_div="IS"),
    _line_item("영업이익", "40000000000000", sj_div="IS"),
    _line_item("당기순이익", "30000000000000", sj_div="IS"),
    _line_item("자산총계", "450000000000000", sj_div="BS"),
    _line_item("부채총계", "100000000000000", sj_div="BS"),
    _line_item("자본총계", "350000000000000", sj_div="BS"),
]


def _statement_json(
    status: str, *, message: str = "정상", list_items: list[dict[str, str]] | None = None
) -> dict[str, Any]:
    return {"status": status, "message": message, "list": list_items or []}


def test_get_quarterly_statements_uses_cfs_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    fs_div_calls: list[str] = []

    async def handler(url: httpx.URL) -> _FakeResponse:
        if _is_corp_code_url(url):
            return _FakeResponse(content=_CORP_CODE_ZIP)
        fs_div_calls.append(url.params["fs_div"])
        return _FakeResponse(json_data=_statement_json("000", list_items=_FULL_LINE_ITEMS))

    _install_fake_client(monkeypatch, handler)
    source = DartFinancialStatementDataSource(_API_KEY)

    statements = asyncio.run(
        source.get_quarterly_statements(["005930"], 2025, FiscalQuarter.ANNUAL)
    )

    assert fs_div_calls == ["CFS"]
    assert len(statements) == 1
    statement = statements[0]
    assert statement.consolidated_type == ConsolidatedType.CFS
    assert statement.revenue == Decimal("300000000000000")
    assert statement.operating_income == Decimal("40000000000000")
    assert statement.net_income == Decimal("30000000000000")
    assert statement.total_assets == Decimal("450000000000000")
    assert statement.total_liabilities == Decimal("100000000000000")
    assert statement.total_equity == Decimal("350000000000000")
    assert statement.disclosed_at == date(2026, 5, 14)
    assert statement.rcept_no == "20260514000123"


def test_get_quarterly_statements_falls_back_to_ofs_when_cfs_has_no_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fs_div_calls: list[str] = []

    async def handler(url: httpx.URL) -> _FakeResponse:
        if _is_corp_code_url(url):
            return _FakeResponse(content=_CORP_CODE_ZIP)
        fs_div = url.params["fs_div"]
        fs_div_calls.append(fs_div)
        if fs_div == "CFS":
            return _FakeResponse(
                json_data=_statement_json("013", message="조회된 데이타가 없습니다")
            )
        return _FakeResponse(json_data=_statement_json("000", list_items=_FULL_LINE_ITEMS))

    _install_fake_client(monkeypatch, handler)
    source = DartFinancialStatementDataSource(_API_KEY)

    statements = asyncio.run(
        source.get_quarterly_statements(["005930"], 2025, FiscalQuarter.ANNUAL)
    )

    assert fs_div_calls == ["CFS", "OFS"]
    assert statements[0].consolidated_type == ConsolidatedType.OFS


def test_get_quarterly_statements_skips_ticker_when_neither_cfs_nor_ofs_has_data(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def handler(url: httpx.URL) -> _FakeResponse:
        if _is_corp_code_url(url):
            return _FakeResponse(content=_CORP_CODE_ZIP)
        return _FakeResponse(json_data=_statement_json("013"))

    _install_fake_client(monkeypatch, handler)
    source = DartFinancialStatementDataSource(_API_KEY)

    with caplog.at_level(logging.WARNING):
        statements = asyncio.run(
            source.get_quarterly_statements(["005930"], 2025, FiscalQuarter.ANNUAL)
        )

    assert statements == []
    # "013" (no data) is a normal empty result, not a retry/skip-with-warning
    # candidate — see the module docstring's status-handling section.
    assert not any(r.levelno >= logging.WARNING for r in caplog.records)


def test_corp_code_map_skips_unlisted_entries_and_unknown_tickers_make_no_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statement_calls = {"n": 0}

    async def handler(url: httpx.URL) -> _FakeResponse:
        if _is_corp_code_url(url):
            return _FakeResponse(content=_CORP_CODE_ZIP)
        statement_calls["n"] += 1
        return _FakeResponse(json_data=_statement_json("013"))

    _install_fake_client(monkeypatch, handler)
    source = DartFinancialStatementDataSource(_API_KEY)

    asyncio.run(
        source.get_quarterly_statements(["005930", "999999"], 2025, FiscalQuarter.ANNUAL)
    )

    # "999999" was never in the corp_code map (and the unlisted-entry row has
    # no stock_code to match against either) -> no HTTP call made for it.
    # Only "005930"'s CFS + OFS attempts count.
    assert statement_calls["n"] == 2


def test_corp_code_map_is_lazily_loaded_once_and_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    corp_code_calls = {"n": 0}

    async def handler(url: httpx.URL) -> _FakeResponse:
        if _is_corp_code_url(url):
            corp_code_calls["n"] += 1
            return _FakeResponse(content=_CORP_CODE_ZIP)
        return _FakeResponse(json_data=_statement_json("013"))

    _install_fake_client(monkeypatch, handler)
    source = DartFinancialStatementDataSource(_API_KEY)

    asyncio.run(source.get_quarterly_statements(["005930"], 2025, FiscalQuarter.ANNUAL))
    asyncio.run(source.get_quarterly_statements(["005930"], 2025, FiscalQuarter.Q1))

    assert corp_code_calls["n"] == 1


def test_refresh_corp_code_map_forces_reload(monkeypatch: pytest.MonkeyPatch) -> None:
    corp_code_calls = {"n": 0}

    async def handler(url: httpx.URL) -> _FakeResponse:
        if _is_corp_code_url(url):
            corp_code_calls["n"] += 1
            return _FakeResponse(content=_CORP_CODE_ZIP)
        return _FakeResponse(json_data=_statement_json("013"))

    _install_fake_client(monkeypatch, handler)
    source = DartFinancialStatementDataSource(_API_KEY)

    asyncio.run(source.get_quarterly_statements(["005930"], 2025, FiscalQuarter.ANNUAL))
    asyncio.run(source.refresh_corp_code_map())
    asyncio.run(source.get_quarterly_statements(["005930"], 2025, FiscalQuarter.ANNUAL))

    assert corp_code_calls["n"] == 2


def test_systemic_status_aborts_batch_without_retry_or_further_ticker_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(asyncio, "sleep", _no_op_sleep)
    statement_calls = {"n": 0}

    async def handler(url: httpx.URL) -> _FakeResponse:
        if _is_corp_code_url(url):
            return _FakeResponse(content=_CORP_CODE_ZIP)
        statement_calls["n"] += 1
        return _FakeResponse(json_data=_statement_json("020", message="요청 제한 초과"))

    _install_fake_client(monkeypatch, handler)
    source = DartFinancialStatementDataSource(_API_KEY)

    with pytest.raises(DartSystemicError):
        asyncio.run(
            source.get_quarterly_statements(
                ["005930", "000660"], 2025, FiscalQuarter.ANNUAL
            )
        )

    # No retry (would be >1) and no second ticker or OFS fallback call.
    assert statement_calls["n"] == 1


@pytest.mark.parametrize("status", ["010", "011", "020", "800", "901"])
def test_all_documented_systemic_status_codes_raise(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    monkeypatch.setattr(asyncio, "sleep", _no_op_sleep)

    async def handler(url: httpx.URL) -> _FakeResponse:
        if _is_corp_code_url(url):
            return _FakeResponse(content=_CORP_CODE_ZIP)
        return _FakeResponse(json_data=_statement_json(status))

    _install_fake_client(monkeypatch, handler)
    source = DartFinancialStatementDataSource(_API_KEY)

    with pytest.raises(DartSystemicError):
        asyncio.run(source.get_quarterly_statements(["005930"], 2025, FiscalQuarter.ANNUAL))


def test_unrecognized_status_is_treated_as_transient_and_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(asyncio, "sleep", _no_op_sleep)
    statement_calls = {"n": 0}

    async def handler(url: httpx.URL) -> _FakeResponse:
        if _is_corp_code_url(url):
            return _FakeResponse(content=_CORP_CODE_ZIP)
        statement_calls["n"] += 1
        return _FakeResponse(json_data=_statement_json("100", message="부적절한 값"))

    _install_fake_client(monkeypatch, handler)
    source = DartFinancialStatementDataSource(_API_KEY)

    statements = asyncio.run(
        source.get_quarterly_statements(["005930"], 2025, FiscalQuarter.ANNUAL)
    )

    # 3 attempts for CFS + 3 attempts for OFS, both exhausted -> ticker skipped.
    assert statement_calls["n"] == 6
    assert statements == []


def test_network_exception_retries_then_skips_with_warning_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(asyncio, "sleep", _no_op_sleep)
    statement_calls = {"n": 0}

    async def handler(url: httpx.URL) -> _FakeResponse:
        if _is_corp_code_url(url):
            return _FakeResponse(content=_CORP_CODE_ZIP)
        statement_calls["n"] += 1
        raise httpx.ConnectTimeout("boom")

    _install_fake_client(monkeypatch, handler)
    source = DartFinancialStatementDataSource(_API_KEY)

    with caplog.at_level(logging.WARNING):
        statements = asyncio.run(
            source.get_quarterly_statements(["005930"], 2025, FiscalQuarter.ANNUAL)
        )

    assert statements == []
    assert statement_calls["n"] == 6  # 3 attempts x (CFS, OFS)
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_failure_logs_never_leak_the_raw_api_key(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(asyncio, "sleep", _no_op_sleep)

    async def handler(url: httpx.URL) -> _FakeResponse:
        if _is_corp_code_url(url):
            return _FakeResponse(content=_CORP_CODE_ZIP)
        return _FakeResponse(status_code=500)

    _install_fake_client(monkeypatch, handler)
    source = DartFinancialStatementDataSource(_API_KEY)

    with caplog.at_level(logging.DEBUG):
        asyncio.run(source.get_quarterly_statements(["005930"], 2025, FiscalQuarter.ANNUAL))

    for record in caplog.records:
        assert _API_KEY not in record.getMessage()


def test_mask_api_key_replaces_crtfc_key_value() -> None:
    url = httpx.URL(
        "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json",
        params={"crtfc_key": _API_KEY, "corp_code": "00126380"},
    )

    masked = _mask_api_key(url)

    assert _API_KEY not in masked
    assert "crtfc_key=%2A%2A%2A" in masked or "crtfc_key=***" in masked


@pytest.mark.parametrize(
    ("fiscal_quarter", "expected_reprt_code"),
    [
        (FiscalQuarter.Q1, "11013"),
        (FiscalQuarter.H1, "11012"),
        (FiscalQuarter.Q3, "11014"),
        (FiscalQuarter.ANNUAL, "11011"),
    ],
)
def test_fiscal_quarter_to_reprt_code_mapping(
    fiscal_quarter: FiscalQuarter, expected_reprt_code: str
) -> None:
    assert _FISCAL_QUARTER_TO_REPRT_CODE[fiscal_quarter] == expected_reprt_code


@pytest.mark.parametrize(
    ("fiscal_quarter", "expected_reprt_code"),
    [
        (FiscalQuarter.Q1, "11013"),
        (FiscalQuarter.H1, "11012"),
        (FiscalQuarter.Q3, "11014"),
        (FiscalQuarter.ANNUAL, "11011"),
    ],
)
def test_get_quarterly_statements_sends_expected_reprt_code(
    monkeypatch: pytest.MonkeyPatch, fiscal_quarter: FiscalQuarter, expected_reprt_code: str
) -> None:
    captured_reprt_codes: list[str] = []

    async def handler(url: httpx.URL) -> _FakeResponse:
        if _is_corp_code_url(url):
            return _FakeResponse(content=_CORP_CODE_ZIP)
        captured_reprt_codes.append(url.params["reprt_code"])
        return _FakeResponse(json_data=_statement_json("013"))

    _install_fake_client(monkeypatch, handler)
    source = DartFinancialStatementDataSource(_API_KEY)

    asyncio.run(source.get_quarterly_statements(["005930"], 2025, fiscal_quarter))

    assert captured_reprt_codes[0] == expected_reprt_code
