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
    monkeypatch.setattr(cli, "_make_data_client", lambda c: object())
    monkeypatch.setattr(cli, "do_run", fake_do_run)
    monkeypatch.setattr(sys, "argv", ["etorobot", "run", "--real-money"])
    cli.main()
    assert seen["real_money"] is True


def test_validate_real_dispatch(monkeypatch):
    seen = {}

    async def fake_validate(config, amount, symbol=None):
        seen["amount"] = amount
        seen["symbol"] = symbol

    monkeypatch.setattr(cli, "load_config", lambda p: SimpleNamespace())
    monkeypatch.setattr(cli, "do_validate_real", fake_validate)
    monkeypatch.setattr(
        sys, "argv",
        ["etorobot", "validate-real", "--amount", "10", "--symbol", "BTC"])
    cli.main()
    assert seen == {"amount": 10.0, "symbol": "BTC"}


async def test_do_validate_real_refuses_real_without_token():
    config = SimpleNamespace(
        secrets=SimpleNamespace(env="real", agent_token=None,
                                api_key="ak", user_key="uk"),
        instruments=[SimpleNamespace(symbol="BTC")])
    with pytest.raises(SystemExit, match="ETORO_AGENT_TOKEN"):
        await cli.do_validate_real(config, amount=10.0)


async def test_make_data_client_pinned_to_demo():
    # async: EtoroClient's TokenBucket needs a running event loop.
    config = SimpleNamespace(secrets=SimpleNamespace(
        env="real", agent_token="tok", api_key="ak", user_key="uk"))
    c = cli._make_data_client(config)
    assert c._env == "demo"
    assert c._agent_token is None


async def test_do_validate_real_rejects_bad_amounts():
    config = SimpleNamespace(
        secrets=SimpleNamespace(env="demo", agent_token=None,
                                api_key="ak", user_key="uk"),
        instruments=[SimpleNamespace(symbol="BTC")])
    with pytest.raises(SystemExit, match="amount"):
        await cli.do_validate_real(config, amount=0)
    with pytest.raises(SystemExit, match="amount"):
        await cli.do_validate_real(config, amount=-5)
    with pytest.raises(SystemExit, match="amount"):
        await cli.do_validate_real(config, amount=5000)


async def test_do_validate_real_requires_an_instrument_or_symbol():
    config = SimpleNamespace(
        secrets=SimpleNamespace(env="demo", agent_token=None,
                                api_key="ak", user_key="uk"),
        instruments=[])
    with pytest.raises(SystemExit, match="symbol"):
        await cli.do_validate_real(config, amount=10.0)


async def test_do_run_splits_planes_bearer_broker_pair_feed(monkeypatch):
    captured = {}

    class FakeFeed:
        def __init__(self, api_key, user_key, instruments, timeframe):
            captured["feed_keys"] = (api_key, user_key)

    class FakeBroker:
        def __init__(self, client):
            captured["broker_client"] = client

    class FakeEngine:
        def __init__(self, **kw):
            pass

        async def run(self):
            return None

    class FakeRepo:
        def __init__(self, url):
            pass

        def create_run(self, **kw):
            return 1

        def finish_run(self, run_id, status):
            pass

    class FakeDataClient:
        async def resolve_instrument(self, symbol):
            return 100000

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

    monkeypatch.setattr(cli, "LiveFeed", FakeFeed)
    monkeypatch.setattr(cli, "EtoroBroker", FakeBroker)
    monkeypatch.setattr(cli, "Engine", FakeEngine)
    monkeypatch.setattr(cli, "Repository", FakeRepo)
    monkeypatch.setattr(cli, "build_strategy", lambda name, params: object())
    monkeypatch.setattr(cli, "RiskManager", lambda risk: object())
    config = SimpleNamespace(
        secrets=SimpleNamespace(env="demo", agent_token="agtok",
                                api_key="ak", user_key="uk"),
        instruments=[SimpleNamespace(symbol="BTC")],
        timeframe="OneMinute",
        strategy=SimpleNamespace(name="s", params={}),
        risk=object(),
        telegram=SimpleNamespace(token=None, chat_id=None))
    await cli.do_run(config, FakeDataClient())
    # The broker's client authenticates with the scoped Bearer token...
    assert captured["broker_client"]._agent_token == "agtok"
    # ...while the WebSocket feed keeps the raw key pair.
    assert captured["feed_keys"] == ("ak", "uk")


async def test_do_validate_real_wires_data_client(monkeypatch):
    seen = {}

    async def fake_run_validation(client, symbol, amount, out_path,
                                  data_client=None, **kw):
        seen["client"] = client
        seen["data_client"] = data_client

    monkeypatch.setattr("etorobot.validate.run_validation",
                        fake_run_validation)
    config = SimpleNamespace(
        secrets=SimpleNamespace(env="demo", agent_token="agtok",
                                api_key="ak", user_key="uk"),
        instruments=[SimpleNamespace(symbol="BTC")])
    await cli.do_validate_real(config, amount=10.0)
    # Trade plane carries the Bearer token; data plane is the demo pair.
    assert seen["client"]._agent_token == "agtok"
    assert seen["data_client"]._agent_token is None
    assert seen["data_client"]._env == "demo"


def test_guard_real_with_pair_flag_and_real_money_passes():
    s = SimpleNamespace(env="real", agent_token=None, agent_portfolio=True)
    check_real_guard(s, real_money=True)


def test_guard_real_with_pair_flag_still_needs_real_money():
    s = SimpleNamespace(env="real", agent_token=None, agent_portfolio=True)
    with pytest.raises(SystemExit, match="--real-money"):
        check_real_guard(s, real_money=False)


async def test_verify_agent_pair_refuses_unverified_claim(monkeypatch):
    class FakeProbe:
        async def is_agent_portfolio_key(self):
            return False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

    monkeypatch.setattr(cli, "_make_trade_client", lambda c: FakeProbe())
    config = SimpleNamespace(secrets=SimpleNamespace(
        env="real", agent_token=None, agent_portfolio=True,
        api_key="ak", user_key="uk"))
    with pytest.raises(SystemExit, match="does not verify"):
        await cli._verify_agent_pair(config)


async def test_verify_agent_pair_passes_verified_claim(monkeypatch):
    class FakeProbe:
        async def is_agent_portfolio_key(self):
            return True

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

    monkeypatch.setattr(cli, "_make_trade_client", lambda c: FakeProbe())
    config = SimpleNamespace(secrets=SimpleNamespace(
        env="real", agent_token=None, agent_portfolio=True,
        api_key="ak", user_key="uk"))
    await cli._verify_agent_pair(config)  # must not raise


async def test_verify_agent_pair_skipped_for_demo_and_bearer():
    # Demo env and Bearer-token sessions never probe; no client is built,
    # so reaching a network call would blow up the test.
    await cli._verify_agent_pair(SimpleNamespace(secrets=SimpleNamespace(
        env="demo", agent_token=None, agent_portfolio=True)))
    await cli._verify_agent_pair(SimpleNamespace(secrets=SimpleNamespace(
        env="real", agent_token="tok", agent_portfolio=False)))
