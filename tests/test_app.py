from types import SimpleNamespace

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import data
from memo import build_prompt


def run_app(monkeypatch, frame, snapshot=(pd.DataFrame(), None)):
    monkeypatch.delenv("ENABLE_AGENT", raising=False)
    monkeypatch.setattr(data, "load_data", lambda universe: frame)
    monkeypatch.setattr(data, "load_snapshot", lambda: snapshot)
    app = AppTest.from_file("app.py", default_timeout=30)
    app.secrets["ANTHROPIC_API_KEY"] = ""
    return app.run()


@pytest.fixture
def screened_frame():
    return pd.DataFrame([{
        "Ticker": "AAA", "Name": "Test Co", "Country": "United States", "Sector": "Industrials",
        "Market Cap": 20e9, "Total Revenue": 5e9, "EV/EBITDA": 10.0, "Revenue Growth (%)": 8.0,
        "Profit Margin (%)": 15.0, "Debt/Equity": 50.0, "P/B": 3.0, "ROE (%)": 12.0, "Current Price": 100.0,
        "Currency": "USD", "Valuation Basis": "earnings",
    }])


@pytest.fixture
def bank_row():
    return {
        "Ticker": "D05.SI", "Name": "DBS", "Country": "Singapore", "Sector": "Financial Services",
        "Market Cap": 155e9, "Total Revenue": 15e9, "EV/EBITDA": float("nan"), "Revenue Growth (%)": 6.8,
        "Profit Margin (%)": 49.5, "Debt/Equity": float("nan"), "P/B": 2.9, "ROE (%)": 16.2,
        "Current Price": 70.88, "Currency": "SGD", "Valuation Basis": "book",
    }


@pytest.fixture
def full_frame(screened_frame):
    rows = [{**screened_frame.iloc[0].to_dict(), "Ticker": f"T{i}"} for i in range(data.MIN_LIVE_ROWS)]
    return pd.DataFrame(rows)


def test_sample_memo_still_shows_with_no_data_and_no_snapshot(monkeypatch):
    # Regression: a Yahoo block on Streamlit Cloud stopped the page before the sample memo.
    app = run_app(monkeypatch, pd.DataFrame())
    assert not app.exception
    assert "Unable to pull market data" in app.error[0].value
    assert [e.label for e in app.expander] == ["Sample buyer memo"]
    assert not any("Screened Results" in s.value for s in app.subheader)


def test_screener_and_sample_memo_both_show_when_data_loads(monkeypatch, full_frame):
    app = run_app(monkeypatch, full_frame)
    assert not app.exception
    assert not app.error and not app.warning
    assert any(f"Screened Results ({len(full_frame)} companies)" in s.value for s in app.subheader)
    assert [e.label for e in app.expander] == ["Sample buyer memo"]


def test_run_button_stays_hidden_without_enable_agent(monkeypatch):
    app = run_app(monkeypatch, pd.DataFrame())
    assert not any("Run AI buyer analysis" in b.label for b in app.button)


@pytest.mark.parametrize("live", ["empty", "partial"])
def test_saved_data_shows_with_its_date_when_yahoo_is_blocked(monkeypatch, screened_frame, live):
    frame = pd.DataFrame() if live == "empty" else screened_frame
    app = run_app(monkeypatch, frame, snapshot=(screened_frame, "2026-11-03"))
    assert not app.exception
    assert not app.error
    assert "saved data from 2026-11-03" in app.warning[0].value
    assert any("Screened Results (1 companies)" in s.value for s in app.subheader)
    assert any("saved data from 2026-11-03" in c.value for c in app.caption)
    assert not any("Last updated" in c.value for c in app.caption)


def test_partial_live_data_is_kept_when_there_is_no_snapshot(monkeypatch, screened_frame):
    app = run_app(monkeypatch, screened_frame)
    assert not app.error
    assert any("Screened Results (1 companies)" in s.value for s in app.subheader)


def test_snapshot_round_trip_keeps_missing_values(tmp_path, screened_frame):
    path = tmp_path / "snapshots" / "snap.json"
    frame = screened_frame.assign(**{"Total Revenue": float("nan")})
    data.save_snapshot(frame, path)
    saved, as_of = data.load_snapshot(path)
    assert as_of and saved.loc[0, "Ticker"] == "AAA"
    assert saved.loc[0, "Market Cap"] == 20e9
    assert pd.isna(saved.loc[0, "Total Revenue"])


@pytest.mark.parametrize("contents", [None, "not json", '{"rows": []}'])
def test_unusable_snapshot_loads_as_empty(tmp_path, contents):
    path = tmp_path / "snap.json"
    if contents:
        path.write_text(contents)
    saved, as_of = data.load_snapshot(path)
    assert saved.empty and as_of is None


def test_bank_shows_in_screener_with_book_metrics(monkeypatch, full_frame, bank_row):
    frame = pd.concat([full_frame, pd.DataFrame([bank_row])], ignore_index=True)
    app = run_app(monkeypatch, frame)
    assert not app.exception
    table = app.dataframe[0].value
    row = table[table["Ticker"] == "D05.SI"].iloc[0]
    assert (row["EV/EBITDA"], row["Debt/Equity"], row["P/B"], row["ROE (%)"]) == ("n.m.", "n.m.", "2.9x", "16.2%")
    assert "70.88 SGD" in row["Current Price"]


def filter_frame(bank_row, screened_frame):
    return pd.concat([screened_frame, pd.DataFrame([bank_row])], ignore_index=True)


def test_banks_skip_earnings_filters_and_others_skip_book_filters(bank_row, screened_frame):
    frame = filter_frame(bank_row, screened_frame)
    kept = data.apply_filters(frame, max_ev_ebitda=20, min_profit_margin=60, max_debt_equity=150)
    assert list(kept["Ticker"]) == ["D05.SI"]
    kept = data.apply_filters(frame, max_price_to_book=1.0, min_roe=50)
    assert list(kept["Ticker"]) == ["AAA"]


@pytest.mark.parametrize("filters", [{"max_price_to_book": 2.0}, {"min_roe": 20}, {"min_revenue_growth": 10},
                                     {"market_cap_range": (10, 100)}])
def test_banks_still_have_to_pass_their_own_filters(bank_row, screened_frame, filters):
    frame = pd.DataFrame([bank_row])
    assert data.apply_filters(frame, **filters).empty


def _info(**fields):
    base = {"longName": "Co", "sector": "Financials", "marketCap": 50e9, "totalRevenue": 5e9, "revenueGrowth": 0.1,
            "profitMargins": 0.2, "currentPrice": 10.0}
    return {**base, **fields}


@pytest.mark.parametrize("ticker,info,kept", [
    ("D05.SI", _info(priceToBook=2.0, returnOnEquity=0.15), True),
    ("D05.SI", _info(returnOnEquity=0.15), False),
    ("D05.SI", _info(priceToBook=2.0), False),
    ("AME", _info(enterpriseToEbitda=10.0), True),
    ("AME", _info(priceToBook=2.0, returnOnEquity=0.15), False),
])
def test_load_data_requires_the_right_metrics_for_each_company(monkeypatch, ticker, info, kept):
    data.st.cache_data.clear()
    monkeypatch.setattr(data.yf, "Ticker", lambda t: SimpleNamespace(info=info))
    frame = data.load_data({ticker: ("Singapore", "USD")})
    data.st.cache_data.clear()
    assert (ticker in set(frame["Ticker"])) is kept


def test_bank_roe_is_stored_as_a_percent(monkeypatch):
    data.st.cache_data.clear()
    monkeypatch.setattr(data.yf, "Ticker", lambda t: SimpleNamespace(info=_info(priceToBook=2.0, returnOnEquity=0.15)))
    frame = data.load_data({"D05.SI": ("Singapore", "USD")})
    data.st.cache_data.clear()
    assert frame.iloc[0]["ROE (%)"] == pytest.approx(15.0)


def test_memo_prompt_values_banks_on_book_metrics(bank_row):
    prompt = build_prompt(pd.Series(bank_row))
    assert "Price/Book: 2.9x" in prompt and "Return on Equity: 16.2%" in prompt
    assert "EV/EBITDA" not in prompt and "Debt/Equity" not in prompt and ": nan" not in prompt
    assert "foreign ownership" in prompt
    assert "70.88 SGD" in prompt


def test_memo_prompt_is_unchanged_for_other_companies(screened_frame):
    prompt = build_prompt(screened_frame.iloc[0])
    assert "EV/EBITDA: 10.0x" in prompt and "Debt/Equity: 50.0" in prompt
    assert "Price/Book" not in prompt and "foreign ownership" not in prompt
