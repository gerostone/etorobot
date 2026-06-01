# src/etorobot/strategies/registry.py
from __future__ import annotations

from etorobot.strategies.base import BaseStrategy
from etorobot.strategies.sma import SmaCrossover

STRATEGIES: dict[str, type[BaseStrategy]] = {
    "sma_crossover": SmaCrossover,
}


def build_strategy(name: str, params: dict) -> BaseStrategy:
    try:
        cls = STRATEGIES[name]
    except KeyError:
        raise ValueError(f"unknown strategy: {name}")
    return cls(**params)
