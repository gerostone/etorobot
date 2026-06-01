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


def _make_notifier(config: AppConfig):
    if config.telegram.token and config.telegram.chat_id:
        return TelegramNotifier(config.telegram.token, config.telegram.chat_id)
    return NullNotifier()


async def do_backtest(config: AppConfig, client, candles_count: int = 500) -> dict:
    candles_by_instrument = {}
    async with client:
        for inst in config.instruments:
            iid = await client.resolve_instrument(inst.symbol)
            candles_by_instrument[iid] = await client.get_candles(
                iid, inst.symbol, config.timeframe, count=candles_count)
    return await run_backtest(candles_by_instrument, config.strategy,
                              config.risk, config.backtest)


async def do_run(config: AppConfig, client) -> None:
    instruments: dict[int, str] = {}
    async with client:
        for inst in config.instruments:
            instruments[await client.resolve_instrument(inst.symbol)] = inst.symbol
    feed = LiveFeed(config.secrets.api_key, config.secrets.user_key,
                    instruments, config.timeframe)
    broker = EtoroBroker(_make_client(config))
    repo = Repository(f"sqlite:///bot_{config.secrets.env}.db")
    strategies = {iid: [build_strategy(config.strategy.name,
                                       config.strategy.params)]
                  for iid in instruments}
    engine = Engine(feed=feed, strategies=strategies,
                    risk=RiskManager(config.risk), broker=broker, repo=repo,
                    notifier=_make_notifier(config))
    await engine.run()


def main() -> None:
    parser = argparse.ArgumentParser(prog="etorobot")
    parser.add_argument("--config", default="config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run")
    bt = sub.add_parser("backtest")
    bt.add_argument("--candles", type=int, default=500)
    args = parser.parse_args()
    config = load_config(args.config)

    if args.command == "run":
        asyncio.run(do_run(config, _make_client(config)))
    elif args.command == "backtest":
        metrics = asyncio.run(
            do_backtest(config, _make_client(config), args.candles))
        for k, v in metrics.items():
            print(f"{k}: {v}")


if __name__ == "__main__":
    main()
