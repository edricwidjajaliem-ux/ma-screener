import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import data


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
        "Profit Margin (%)": 15.0, "Debt/Equity": 50.0, "Current Price": 100.0, "Currency": "USD",
    }])


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
