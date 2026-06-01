# tests/config/test_settings.py
import textwrap
import pytest
from etorobot.config.settings import AppConfig, load_config


def _write(tmp_path, body):
    p = tmp_path / "config.yaml"
    p.write_text(textwrap.dedent(body))
    return p


def test_load_valid_config(tmp_path, monkeypatch):
    monkeypatch.setenv("ETORO_API_KEY", "ak")
    monkeypatch.setenv("ETORO_USER_KEY", "uk")
    monkeypatch.setenv("ETORO_ENV", "demo")
    path = _write(tmp_path, """
        timeframe: FiveMinutes
        instruments:
          - symbol: BTC
        strategy:
          name: sma_crossover
          params: {fast: 10, slow: 30}
        risk:
          position_size_pct: 0.05
          max_open_positions: 3
          max_positions_per_instrument: 1
          default_stop_loss_pct: 0.02
          default_take_profit_pct: 0.04
          daily_loss_limit_pct: 0.05
        backtest:
          commission_pct: 0.001
          slippage_pct: 0.0005
          fill_price: close
    """)
    cfg = load_config(path)
    assert isinstance(cfg, AppConfig)
    assert cfg.secrets.api_key == "ak"
    assert cfg.instruments[0].symbol == "BTC"
    assert cfg.risk.max_open_positions == 3


def test_missing_secret_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("ETORO_API_KEY", raising=False)
    monkeypatch.setenv("ETORO_USER_KEY", "uk")
    path = _write(tmp_path, """
        timeframe: OneHour
        instruments: [{symbol: BTC}]
        strategy: {name: sma_crossover, params: {}}
        risk:
          position_size_pct: 0.05
          max_open_positions: 3
          max_positions_per_instrument: 1
          default_stop_loss_pct: 0.02
          default_take_profit_pct: 0.04
          daily_loss_limit_pct: 0.05
        backtest: {commission_pct: 0.0, slippage_pct: 0.0, fill_price: close}
    """)
    with pytest.raises(Exception):
        load_config(path)
