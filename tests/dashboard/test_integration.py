# tests/dashboard/test_integration.py
from datetime import datetime, timezone, timedelta

from fastapi.testclient import TestClient

from etorobot.cli import do_backtest
from etorobot.config.settings import (
    AppConfig, Secrets, TelegramSecrets, InstrumentConfig, StrategyConfig,
    RiskConfig, BacktestConfig)
from etorobot.core.types import Candle
from etorobot.dashboard.app import create_app


class FakeClient:
    async def resolve_instrument(self, symbol):
        return 100000

    async def get_candles(self, instrument_id, symbol, interval, count):
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        closes = [10, 9, 8, 9, 10, 11, 12, 11, 10, 8, 7, 9, 11, 13, 15]
        return [Candle(instrument_id, symbol, base + timedelta(minutes=i),
                       p, p, p, p, 1.0) for i, p in enumerate(closes)]

    async def __aenter__(self): return self
    async def __aexit__(self, *a): return None


def _config():
    return AppConfig(
        timeframe="OneMinute",
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


async def test_backtest_then_dashboard_report(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'e2e.db'}"
    await do_backtest(_config(), client=FakeClient(), candles_count=15,
                      db_url=db_url)

    client = TestClient(create_app(db_url, token=None))
    runs = client.get("/api/runs").json()
    assert len(runs) == 1
    run_id = runs[0]["id"]
    assert runs[0]["status"] == "finished"

    report = client.get(f"/api/runs/{run_id}").json()
    assert report["metrics"]["num_trades"] >= 1
    assert len(report["equity"]) >= 1
    assert len(report["signals"]) >= 1
