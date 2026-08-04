# Agent Portfolio Trading Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Trade a real-money eToro Agent Portfolio via its scoped Bearer token, gated behind `--real-money`, with a supervised user-executed `validate-real` round-trip harness.

**Architecture:** Split-plane credentials — the existing `x-api-key`/`x-user-key` pair keeps serving market data and the WebSocket feed; the Agent Portfolio Bearer token authenticates only the trading client passed to `EtoroBroker`. `ETORO_ENV=real` without a token is refused at startup. Spec: `docs/superpowers/specs/2026-08-04-agent-portfolio-design.md`.

**Tech Stack:** Python 3.11+, httpx, pydantic-settings, pytest (`asyncio_mode="auto"`, `pythonpath=["src"]`), respx. Use `.venv/bin/pytest` and `.venv/bin/ruff`.

**Safety invariant (applies to every task):** the assistant never runs `validate-real` against real endpoints and never places trades. Live execution is the user's, always.

---

### Task 1: `agent_token` secret

**Files:**
- Modify: `src/etorobot/config/settings.py` (the `Secrets` class)
- Test: `tests/config/test_agent_token.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/config/test_agent_token.py
from etorobot.config.settings import Secrets


def _clear(monkeypatch):
    for var in ("ETORO_API_KEY", "ETORO_USER_KEY", "ETORO_ENV",
                "ETORO_AGENT_TOKEN"):
        monkeypatch.delenv(var, raising=False)


def test_agent_token_defaults_to_none(monkeypatch):
    _clear(monkeypatch)
    s = Secrets(api_key="ak", user_key="uk", _env_file=None)
    assert s.agent_token is None


def test_agent_token_read_from_env(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("ETORO_AGENT_TOKEN", "agtok")
    s = Secrets(api_key="ak", user_key="uk", _env_file=None)
    assert s.agent_token == "agtok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/config/test_agent_token.py -v`
Expected: FAIL (`agent_token` attribute missing / unexpected env pickup)

- [ ] **Step 3: Implement**

In `src/etorobot/config/settings.py`, add one line to `Secrets` after `env`:

```python
class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ETORO_", env_file=".env",
                                      extra="ignore")
    api_key: str
    user_key: str
    env: Literal["demo", "real"] = "demo"
    agent_token: str | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/config/ -v`
Expected: PASS (all, including existing config tests)

- [ ] **Step 5: Commit**

```bash
git add src/etorobot/config/settings.py tests/config/test_agent_token.py
git commit -m "feat(config): optional ETORO_AGENT_TOKEN secret"
```

---

### Task 2: Bearer auth mode in `EtoroClient`

**Files:**
- Modify: `src/etorobot/data/client.py` (`__init__`, `_headers`)
- Test: `tests/data/test_client.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/data/test_client.py`:

```python
@respx.mock
async def test_agent_token_switches_to_bearer_auth():
    route = respx.get(f"{BASE}/api/v1/instruments/BTC").mock(
        return_value=httpx.Response(200, json={"instrumentId": 100000}))
    async with EtoroClient(api_key="ak", user_key="uk", env="demo",
                           agent_token="agtok") as c:
        await c.resolve_instrument("BTC")
    sent = route.calls[0].request
    assert sent.headers["Authorization"] == "Bearer agtok"
    # Bearer and the key pair are mutually exclusive on the eToro API.
    assert "x-api-key" not in sent.headers
    assert "x-user-key" not in sent.headers
    assert sent.headers["x-request-id"]


@respx.mock
async def test_no_agent_token_keeps_pair_auth():
    route = respx.get(f"{BASE}/api/v1/instruments/BTC").mock(
        return_value=httpx.Response(200, json={"instrumentId": 100000}))
    async with EtoroClient(api_key="ak", user_key="uk", env="demo") as c:
        await c.resolve_instrument("BTC")
    sent = route.calls[0].request
    assert sent.headers["x-api-key"] == "ak"
    assert sent.headers["x-user-key"] == "uk"
    assert "Authorization" not in sent.headers
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/data/test_client.py -v -k agent_token`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'agent_token'`

- [ ] **Step 3: Implement**

In `src/etorobot/data/client.py`:

```python
    def __init__(self, api_key: str, user_key: str, env: str = "demo",
                 agent_token: str | None = None) -> None:
        self._api_key = api_key
        self._user_key = user_key
        self._env = env
        self._agent_token = agent_token
        self._http = httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)
        self._read_bucket = TokenBucket(capacity=60, refill_per_sec=1.0)
        self._write_bucket = TokenBucket(capacity=20, refill_per_sec=20 / 60)
        self._instrument_cache: dict[str, int] = {}
```

```python
    def _headers(self) -> dict[str, str]:
        # Agent Portfolio tokens are OAuth Bearer credentials and are mutually
        # exclusive with the x-api-key/x-user-key pair on the eToro API.
        if self._agent_token is not None:
            return {
                "Authorization": f"Bearer {self._agent_token}",
                "x-request-id": str(uuid.uuid4()),
                "Content-Type": "application/json",
            }
        return {
            "x-api-key": self._api_key,
            "x-user-key": self._user_key,
            "x-request-id": str(uuid.uuid4()),
            "Content-Type": "application/json",
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/data/ -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add src/etorobot/data/client.py tests/data/test_client.py
git commit -m "feat(client): Bearer auth mode for agent-portfolio tokens"
```

---

### Task 3: real-run guard + `--real-money` flag + split-plane wiring

**Files:**
- Modify: `src/etorobot/cli.py` (`check_real_guard` new, `_make_trade_client` new, `do_run`, `main`)
- Test: `tests/test_cli.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py` (adapt imports to the file's existing ones — it already imports `etorobot.cli`; the tests below assume `from etorobot import cli` and `import pytest` are available, add them if missing):

```python
from types import SimpleNamespace

from etorobot.cli import check_real_guard


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
```

(`import sys` at the top of the file if not already present; `from etorobot import cli` likewise.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_cli.py -v -k "guard or real_money"`
Expected: FAIL with `ImportError: cannot import name 'check_real_guard'`

- [ ] **Step 3: Implement**

In `src/etorobot/cli.py`:

Add after `_make_client`:

```python
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
```

Change `do_run`'s signature and broker wiring:

```python
async def do_run(config: AppConfig, client, real_money: bool = False) -> None:
    check_real_guard(config.secrets, real_money)
    instruments: dict[int, str] = {}
    async with client:
        for inst in config.instruments:
            instruments[await client.resolve_instrument(inst.symbol)] = inst.symbol
    feed = LiveFeed(config.secrets.api_key, config.secrets.user_key,
                    instruments, config.timeframe)
    broker = EtoroBroker(_make_trade_client(config))
```

(The rest of `do_run` — repo, `create_run`, engine, `finish_run` — is unchanged.)

In `main()`, give the `run` subparser the flag and thread it through:

```python
    run_p = sub.add_parser("run")
    run_p.add_argument("--real-money", action="store_true")
```

and in the dispatch:

```python
    if args.command == "run":
        asyncio.run(do_run(config, _make_client(config),
                           real_money=args.real_money))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: PASS (all, including the pre-existing do_run/do_backtest tests — `real_money` defaults to False so they are unaffected)

- [ ] **Step 5: Commit**

```bash
git add src/etorobot/cli.py tests/test_cli.py
git commit -m "feat(cli): --real-money gate and split-plane trade client"
```

---

### Task 4: supervised validation harness

**Files:**
- Create: `src/etorobot/validate.py`
- Test: `tests/test_validate.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_validate.py
import json

from etorobot.validate import run_validation


class FakeClient:
    def __init__(self):
        self.calls = []

    async def resolve_instrument(self, symbol):
        self.calls.append("resolve")
        return 100000

    async def get_portfolio(self):
        self.calls.append("portfolio")
        return {"clientPortfolio": {"credit": 200.0, "positions": []}}

    async def create_order(self, **kw):
        self.calls.append("open")
        return {"token": "t", "orderId": 42, "referenceId": "r"}

    async def get_order(self, order_id):
        self.calls.append("get_order")
        return {"positions": [{"positionID": 7, "rate": 50000.0,
                               "units": 0.0002}]}

    async def close_position(self, position_id, instrument_id, units=None):
        self.calls.append("close")
        return {"token": "t2"}

    async def get_trade_history(self, min_date, page=1, page_size=50):
        self.calls.append("history")
        return [{"positionId": 7, "closeRate": 50100.0, "units": 0.0002,
                 "fees": 0.05}]


def _inputs(*answers):
    it = iter(answers)
    return lambda prompt: next(it)


async def test_abort_at_open_places_nothing(tmp_path):
    client = FakeClient()
    out = tmp_path / "v.json"
    result = await run_validation(client, "BTC", 10.0, str(out),
                                  input_fn=_inputs("no"), print_fn=lambda *_: None,
                                  poll_interval=0)
    assert "open" not in client.calls
    assert result["aborted"] == "before-open"
    assert json.loads(out.read_text())["aborted"] == "before-open"


async def test_full_round_trip_persists_raw_responses(tmp_path):
    client = FakeClient()
    out = tmp_path / "v.json"
    result = await run_validation(client, "BTC", 10.0, str(out),
                                  input_fn=_inputs("open", "close"),
                                  print_fn=lambda *_: None, poll_interval=0)
    assert client.calls.count("open") == 1
    assert client.calls.count("close") == 1
    saved = json.loads(out.read_text())
    assert saved["steps"]["open_response"]["orderId"] == 42
    assert saved["steps"]["order_status"]["positions"][0]["positionID"] == 7
    assert saved["steps"]["close_settle"]["closeRate"] == 50100.0
    assert result["aborted"] is None


async def test_abort_at_close_reports_open_position(tmp_path):
    client = FakeClient()
    out = tmp_path / "v.json"
    printed = []
    result = await run_validation(client, "BTC", 10.0, str(out),
                                  input_fn=_inputs("open", "nope"),
                                  print_fn=lambda *a: printed.append(" ".join(map(str, a))),
                                  poll_interval=0)
    assert "close" not in client.calls
    assert result["aborted"] == "before-close"
    assert any("7" in line and "OPEN" in line for line in printed)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_validate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'etorobot.validate'`

- [ ] **Step 3: Implement**

```python
# src/etorobot/validate.py
"""Supervised real-money validation round-trip.

This harness is run BY THE USER, interactively. Every money-moving step
requires a typed confirmation, and every raw API response is persisted so
real response shapes can be diffed against the demo shapes the parsers
were built on.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone


def _write(log: dict, out_path: str, print_fn) -> dict:
    with open(out_path, "w") as f:
        json.dump(log, f, indent=2, default=str)
    print_fn(f"Raw responses saved to {out_path}")
    return log


async def run_validation(client, symbol: str, amount: float, out_path: str,
                         input_fn=input, print_fn=print,
                         poll_attempts: int = 40,
                         poll_interval: float = 0.5) -> dict:
    log: dict = {"symbol": symbol, "amount": amount, "aborted": None,
                 "steps": {}}
    iid = await client.resolve_instrument(symbol)
    portfolio = await client.get_portfolio()
    log["steps"]["portfolio_before"] = portfolio
    print_fn(f"Instrument {symbol} -> {iid}")
    credit = portfolio.get("clientPortfolio", {}).get("credit")
    print_fn(f"Available credit: {credit}")
    print_fn(f"About to OPEN a market BUY of ${amount} {symbol}.")
    if input_fn("Type 'open' to place the order (anything else aborts): ") \
            != "open":
        log["aborted"] = "before-open"
        print_fn("Aborted before open. No orders placed.")
        return _write(log, out_path, print_fn)

    order = await client.create_order(symbol=symbol, instrument_id=iid,
                                      transaction="buy", amount=amount)
    log["steps"]["open_response"] = order
    print_fn(f"Open response: {json.dumps(order)}")

    info: dict = {}
    for _ in range(poll_attempts):
        info = await client.get_order(order["orderId"])
        if info.get("positions") or info.get("errorCode"):
            break
        await asyncio.sleep(poll_interval)
    log["steps"]["order_status"] = info
    print_fn(f"Order status: {json.dumps(info)}")
    positions = info.get("positions") or []
    if not positions:
        log["aborted"] = "order-unresolved"
        print_fn("Order did not resolve into a position. Check the eToro app "
                 "before retrying — it may still fill.")
        return _write(log, out_path, print_fn)
    position_id = str(positions[0]["positionID"])
    print_fn(f"Filled: position {position_id} at rate {positions[0]['rate']}")

    if input_fn(f"Type 'close' to close position {position_id} "
                f"(anything else aborts): ") != "close":
        log["aborted"] = "before-close"
        print_fn(f"Aborted with OPEN position {position_id} — close it in "
                 f"the eToro app, or re-run and close there.")
        return _write(log, out_path, print_fn)

    close = await client.close_position(position_id, iid)
    log["steps"]["close_response"] = close
    print_fn(f"Close response: {json.dumps(close)}")

    min_date = (datetime.now(timezone.utc)
                - timedelta(days=1)).strftime("%Y-%m-%d")
    settle: dict | None = None
    for _ in range(poll_attempts):
        trades = await client.get_trade_history(min_date)
        for trade in trades:
            if str(trade.get("positionId")) == position_id:
                settle = trade
                break
        if settle is not None:
            break
        await asyncio.sleep(poll_interval)
    if settle is None:
        log["aborted"] = "close-unsettled"
        print_fn("Close did not appear in trade history yet; verify in the "
                 "eToro app.")
        return _write(log, out_path, print_fn)
    log["steps"]["close_settle"] = settle
    print_fn(f"Close settled: {json.dumps(settle)}")
    print_fn("Round trip complete.")
    return _write(log, out_path, print_fn)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_validate.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/etorobot/validate.py tests/test_validate.py
git commit -m "feat(validate): supervised order round-trip harness"
```

---

### Task 5: `validate-real` CLI subcommand

**Files:**
- Modify: `src/etorobot/cli.py` (`do_validate_real` new, `main`)
- Test: `tests/test_cli.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_cli.py -v -k validate_real`
Expected: FAIL with `AttributeError: ... has no attribute 'do_validate_real'`

- [ ] **Step 3: Implement**

In `src/etorobot/cli.py`, add after `do_dashboard`:

```python
async def do_validate_real(config: AppConfig, amount: float,
                           symbol: str | None = None) -> None:
    # The interactive typed confirmations inside run_validation are the
    # consent gate, so no --real-money flag is required here; the token
    # requirement for env=real still applies.
    check_real_guard(config.secrets, real_money=True)
    from etorobot.validate import run_validation

    symbol = symbol or config.instruments[0].symbol
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = f"validation_{config.secrets.env}_{stamp}.json"
    client = _make_trade_client(config)
    async with client:
        await run_validation(client, symbol, amount, out_path)
```

Add the imports `from datetime import datetime, timezone` at the top of `cli.py`.

In `main()`, add the subparser and dispatch:

```python
    val = sub.add_parser("validate-real")
    val.add_argument("--amount", type=float, required=True)
    val.add_argument("--symbol", default=None)
```

```python
    elif args.command == "validate-real":
        asyncio.run(do_validate_real(config, amount=args.amount,
                                     symbol=args.symbol))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_cli.py -v && .venv/bin/etorobot validate-real --help`
Expected: PASS; help text shows `--amount` (required) and `--symbol`

- [ ] **Step 5: Commit**

```bash
git add src/etorobot/cli.py tests/test_cli.py
git commit -m "feat(cli): validate-real supervised round-trip subcommand"
```

---

### Task 6: documentation

**Files:**
- Create: `docs/going-real.md`
- Modify: `README.md` (CLI section, "Going to a real account" section, Documentation list)
- Modify: `docs/configuration.md` (Secrets table)

- [ ] **Step 1: Write `docs/going-real.md`**

Cover, in order:
1. **What Agent Portfolios are**: real-money sub-portfolios (min $200) with a scoped OAuth Bearer token (`Authorization: Bearer`), mutually exclusive with the key pair; scopes `etoro-public:trade.real:*`; optional expiry + IP whitelist; token shown only at creation. Why this is the only supported real path (capped blast radius).
2. **Setup (user actions, in eToro's desktop UI)**: create the portfolio, fund it, mint a real-scoped token (recommend IP whitelist + expiry), then `echo 'ETORO_AGENT_TOKEN=...' >> .env`.
3. **Validation runbook**: run `etorobot validate-real --amount 10`; what each prompt does (`open` / `close` typed confirmations); where raw responses land (`validation_real_<stamp>.json`); diff the shapes against a demo run of the same command; what to do on each abort path (`before-open`, `order-unresolved`, `before-close`, `close-unsettled`).
4. **Going live**: `etorobot run --real-money`; the guard matrix (env=real refuses without token, refuses without flag); note that the bot remains long-only with the existing risk limits.
5. **Rotation/revocation**: tokens are managed in eToro's UI; revoke there if compromised.

- [ ] **Step 2: Update `README.md`**

- CLI block: add `--real-money` to `run` and the new `validate-real --amount N [--symbol S]` command with one-line descriptions.
- Replace the entire "## Going to a real account (not yet validated)" section body with a short paragraph: real trading is supported only through an eToro **Agent Portfolio** (scoped Bearer token, capped allocation); validation is a supervised round-trip you run yourself; link to `docs/going-real.md`. Retitle the section "## Going to a real account (Agent Portfolios)".
- Documentation list: add `- [Going real: Agent Portfolios](docs/going-real.md) — scoped-token setup and the supervised validation runbook`.

- [ ] **Step 3: Update `docs/configuration.md`**

Add a row to the `ETORO_` Secrets table:

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `ETORO_AGENT_TOKEN` | no | `None` | Agent Portfolio user token (Bearer). When set, the trading client authenticates with it instead of the key pair. Required for `ETORO_ENV=real`. See [docs/going-real.md](going-real.md). |

Also update the `ETORO_ENV` row's note: `real` now additionally requires `ETORO_AGENT_TOKEN` and `--real-money`.

- [ ] **Step 4: Verify links resolve**

Run: `grep -o "docs/going-real.md" README.md && ls docs/going-real.md`
Expected: path prints; file exists

- [ ] **Step 5: Commit**

```bash
git add docs/going-real.md README.md docs/configuration.md
git commit -m "docs: agent-portfolio going-real runbook, ETORO_AGENT_TOKEN"
```

---

## Final verification

- [ ] Full suite: `.venv/bin/pytest -q` — all green.
- [ ] Lint: `.venv/bin/ruff check` — clean.
- [ ] `.venv/bin/etorobot run --help` shows `--real-money`; `validate-real --help` shows `--amount`/`--symbol`.
- [ ] Guard smoke (no network): `ETORO_ENV=real` without token → `etorobot run` exits with the token message.
- [ ] **User-executed** (not the assistant): demo rehearsal `etorobot validate-real --amount 10` with a demo-scoped or pair credential, then the real run per `docs/going-real.md`.
- [ ] After all tasks: use **superpowers:finishing-a-development-branch** to complete the work.

## Self-review notes (author)

- Spec coverage: config field (T1), Bearer client (T2), guard matrix + split wiring (T3), harness with typed confirmations + raw persistence + abort paths (T4), CLI subcommand (T5), runbook + README + config docs (T6). Error-handling note (401/403 clarity) is inherent: `httpx.raise_for_status` surfaces the status; the runbook documents the token as the likely cause.
- Type consistency: `check_real_guard(secrets, real_money)` used identically in T3/T5; `run_validation(client, symbol, amount, out_path, input_fn, print_fn, poll_attempts, poll_interval)` matches all T4 tests and the T5 call (defaults used there).
- No placeholders: every code step ships complete code; T6 doc steps enumerate exact content requirements.
