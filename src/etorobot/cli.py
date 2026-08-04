# src/etorobot/cli.py
from __future__ import annotations

import argparse
import asyncio

from etorobot.backtest.runner import run_backtest
from etorobot.brokers.etoro import EtoroBroker
from etorobot.config.settings import AppConfig, load_config
from etorobot.core.engine import Engine
from etorobot.data.client import EtoroClient
from etorobot.feeds.live import LiveFeed
from etorobot.notify.base import NullNotifier
from etorobot.notify.telegram import TelegramNotifier
from etorobot.persistence.repo import Repository
from etorobot.risk.manager import RiskManager
from etorobot.strategies.registry import build_strategy


def _make_client(config: AppConfig) -> EtoroClient:
    return EtoroClient(config.secrets.api_key, config.secrets.user_key,
                       config.secrets.env)


def _make_trade_client(config: AppConfig) -> EtoroClient:
    # Execution-plane client: authenticates with the scoped Agent Portfolio
    # Bearer token when one is configured, else falls back to the key pair.
    return EtoroClient(config.secrets.api_key, config.secrets.user_key,
                       config.secrets.env,
                       agent_token=config.secrets.agent_token)


def check_real_guard(secrets, real_money: bool) -> None:
    """Refuse real-money sessions that lack the token or the explicit flag."""
    if secrets.env != "real":
        return
    if not secrets.agent_token:
        raise SystemExit(
            "ETORO_ENV=real requires an Agent Portfolio token "
            "(ETORO_AGENT_TOKEN). Direct real-account trading without a "
            "scoped token is disabled.")
    if not real_money:
        raise SystemExit(
            "Refusing to start a real-money session without --real-money. "
            "Re-run as: etorobot run --real-money")


def _make_notifier(config: AppConfig):
    if config.telegram.token and config.telegram.chat_id:
        return TelegramNotifier(config.telegram.token, config.telegram.chat_id)
    return NullNotifier()


async def do_backtest(config: AppConfig, client, candles_count: int = 500,
                      db_url: str | None = None) -> dict:
    candles_by_instrument = {}
    symbols: dict[int, str] = {}
    async with client:
        for inst in config.instruments:
            iid = await client.resolve_instrument(inst.symbol)
            symbols[iid] = inst.symbol
            candles_by_instrument[iid] = await client.get_candles(
                iid, inst.symbol, config.timeframe, count=candles_count)
    db_url = db_url or f"sqlite:///bot_{config.secrets.env}.db"
    repo = Repository(db_url)
    run_id = repo.create_run(
        mode="backtest", env=config.secrets.env,
        strategy=config.strategy.name, params=config.strategy.params,
        timeframe=config.timeframe,
        instruments=",".join(symbols.values()), starting_cash=1000.0)
    status = "finished"
    try:
        return await run_backtest(candles_by_instrument, config.strategy,
                                  config.risk, config.backtest,
                                  repo=repo, run_id=run_id)
    except Exception:
        status = "error"
        raise
    finally:
        repo.finish_run(run_id, status)


async def do_run(config: AppConfig, client, real_money: bool = False) -> None:
    check_real_guard(config.secrets, real_money)
    instruments: dict[int, str] = {}
    async with client:
        for inst in config.instruments:
            instruments[await client.resolve_instrument(inst.symbol)] = inst.symbol
    feed = LiveFeed(config.secrets.api_key, config.secrets.user_key,
                    instruments, config.timeframe)
    broker = EtoroBroker(_make_trade_client(config))
    repo = Repository(f"sqlite:///bot_{config.secrets.env}.db")
    run_id = repo.create_run(
        mode="live", env=config.secrets.env,
        strategy=config.strategy.name, params=config.strategy.params,
        timeframe=config.timeframe,
        instruments=",".join(instruments.values()), starting_cash=0.0)
    strategies = {iid: [build_strategy(config.strategy.name,
                                       config.strategy.params)]
                  for iid in instruments}
    engine = Engine(feed=feed, strategies=strategies,
                    risk=RiskManager(config.risk), broker=broker, repo=repo,
                    notifier=_make_notifier(config), run_id=run_id)
    status = "finished"
    try:
        await engine.run()
    except Exception:
        status = "error"
        raise
    finally:
        repo.finish_run(run_id, status)


def do_dashboard(host: str, port: int, db_url: str) -> None:
    import uvicorn

    from etorobot.config.settings import DashboardSecrets
    from etorobot.dashboard.app import create_app

    token = DashboardSecrets().token
    uvicorn.run(create_app(db_url, token=token), host=host, port=port)


def main() -> None:
    parser = argparse.ArgumentParser(prog="etorobot")
    parser.add_argument("--config", default="config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run")
    run_p.add_argument("--real-money", action="store_true")
    bt = sub.add_parser("backtest")
    bt.add_argument("--candles", type=int, default=500)
    dash = sub.add_parser("dashboard")
    dash.add_argument("--host", default="127.0.0.1")
    dash.add_argument("--port", type=int, default=8000)
    dash.add_argument("--db", default=None)
    args = parser.parse_args()
    config = load_config(args.config)

    if args.command == "run":
        asyncio.run(do_run(config, _make_client(config),
                           real_money=args.real_money))
    elif args.command == "backtest":
        metrics = asyncio.run(
            do_backtest(config, _make_client(config), args.candles))
        for k, v in metrics.items():
            print(f"{k}: {v}")
    elif args.command == "dashboard":
        db = args.db or f"bot_{config.secrets.env}.db"
        do_dashboard(args.host, args.port, f"sqlite:///{db}")


if __name__ == "__main__":
    main()
