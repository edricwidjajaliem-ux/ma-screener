import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

import data


def run_app(monkeypatch, frame):
    monkeypatch.delenv("ENABLE_AGENT", raising=False)
    monkeypatch.setattr(data, "load_data", lambda universe: frame)
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


def test_sample_memo_still_shows_when_market_data_fails(monkeypatch):
    # Regression: a Yahoo block on Streamlit Cloud stopped the page before the sample memo.
    app = run_app(monkeypatch, pd.DataFrame())
    assert not app.exception
    assert "Unable to pull market data" in app.error[0].value
    assert [e.label for e in app.expander] == ["Sample buyer memo"]
    assert not any("Screened Results" in s.value for s in app.subheader)


def test_screener_and_sample_memo_both_show_when_data_loads(monkeypatch, screened_frame):
    app = run_app(monkeypatch, screened_frame)
    assert not app.exception
    assert not app.error
    assert any("Screened Results (1 companies)" in s.value for s in app.subheader)
    assert [e.label for e in app.expander] == ["Sample buyer memo"]


def test_run_button_stays_hidden_without_enable_agent(monkeypatch):
    app = run_app(monkeypatch, pd.DataFrame())
    assert not any("Run AI buyer analysis" in b.label for b in app.button)
