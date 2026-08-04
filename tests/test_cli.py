# tests/test_cli.py
import sys
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest

from etorobot.config.settings import (
    AppConfig, Secrets, TelegramSecrets, InstrumentConfig, StrategyConfig,
    RiskConfig, BacktestConfig)
from etorobot.core.types import Candle
from etorobot import cli
from etorobot.cli import do_backtest, check_real_guard
from etorobot.persistence.repo import Repository


class FakeClient:
    async def resolve_instrument(self, symbol):
        return 100000

    async def get_candles(self, instrument_id, symbol, interval, count):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        closes = [10, 9, 8, 9, 10, 11, 12, 13, 14, 15]
        return [Candle(instrument_id, symbol, base + timedelta(minutes=i),
                       p, p, p, p, 1.0) for i, p in enumerate(closes)]

    async def __aenter__(self): return self
    async def __aexit__(self, *a): return None


def _config():
    return AppConfig(
        timeframe="FiveMinutes",
        instruments=[InstrumentConfig(symbol="BTC")],
        strategy=StrategyConfig(name="sma_crossover",
                                params={"fast": 2, "slow": 3}),
        risk=RiskConfig(position_size_pct=0.10, max_open_positions=3,
                        max_positions_per_instrument=1,
                        default_stop_loss_pct=0.02, default_take_profit_pct=0.04,
                        daily_loss_limit_pct=0.9),
        backtest=BacktestConfig(),
        secrets=Secrets(api_key="ak", user_key="uk", env="demo"),
        telegram=TelegramSecrets())


async def test_do_backtest_returns_metrics(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'bt.db'}"
    metrics = await do_backtest(_config(), client=FakeClient(),
                                candles_count=10, db_url=db_url)
    assert "total_return" in metrics and "num_trades" in metrics


async def test_do_backtest_records_a_finished_run(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'bt.db'}"
    await do_backtest(_config(), client=FakeClient(), candles_count=10,
                      db_url=db_url)
    repo = Repository(db_url)
    runs = repo.list_run_rows()
    assert len(runs) == 1
    assert runs[0]["mode"] == "backtest"
    assert runs[0]["status"] == "finished"
    assert runs[0]["ended_at"] is not None


def _secrets(env="demo", agent_token=None):
    return SimpleNamespace(env=env, agent_token=agent_token)


def test_guard_demo_always_passes():
    check_real_guard(_secrets("demo"), real_money=False)
    check_real_guard(_secrets("demo", "tok"), real_money=False)


def test_guard_real_without_token_refused():
    with pytest.raises(SystemExit, match="ETORO_AGENT_TOKEN"):
        check_real_guard(_secrets("real"), real_money=True)


def test_guard_real_without_flag_refused():
    with pytest.raises(SystemExit, match="--real-money"):
        check_real_guard(_secrets("real", "tok"), real_money=False)


def test_guard_real_with_token_and_flag_passes():
    check_real_guard(_secrets("real", "tok"), real_money=True)


def test_run_parser_accepts_real_money_flag(monkeypatch):
    seen = {}

    async def fake_do_run(config, client, real_money=False):
        seen["real_money"] = real_money

    monkeypatch.setattr(cli, "load_config", lambda p: SimpleNamespace())
    monkeypatch.setattr(cli, "_make_client", lambda c: object())
    monkeypatch.setattr(cli, "do_run", fake_do_run)
    monkeypatch.setattr(sys, "argv", ["etorobot", "run", "--real-money"])
    cli.main()
    assert seen["real_money"] is True
