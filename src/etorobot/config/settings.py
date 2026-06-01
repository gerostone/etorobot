# src/etorobot/config/settings.py
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ETORO_", env_file=".env",
                                      extra="ignore")
    api_key: str
    user_key: str
    env: Literal["demo", "real"] = "demo"


class TelegramSecrets(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TELEGRAM_", env_file=".env",
                                      extra="ignore")
    token: str | None = None
    chat_id: str | None = None


class InstrumentConfig(BaseModel):
    symbol: str


class StrategyConfig(BaseModel):
    name: str
    params: dict = {}


class RiskConfig(BaseModel):
    position_size_pct: float
    max_open_positions: int
    max_positions_per_instrument: int
    default_stop_loss_pct: float
    default_take_profit_pct: float
    daily_loss_limit_pct: float


class BacktestConfig(BaseModel):
    commission_pct: float = 0.0
    slippage_pct: float = 0.0
    fill_price: Literal["open", "close"] = "close"


class AppConfig(BaseModel):
    timeframe: str
    instruments: list[InstrumentConfig]
    strategy: StrategyConfig
    risk: RiskConfig
    backtest: BacktestConfig
    secrets: Secrets
    telegram: TelegramSecrets


def load_config(path: str | Path) -> AppConfig:
    raw = yaml.safe_load(Path(path).read_text())
    raw["secrets"] = Secrets()
    raw["telegram"] = TelegramSecrets()
    return AppConfig(**raw)
