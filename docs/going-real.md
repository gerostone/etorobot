# Going real: Agent Portfolios

Real-money trading in etorobot is supported **only** through an eToro **Agent Portfolio** — a dedicated sub-portfolio with its own scoped credential. Flipping `ETORO_ENV=real` without one is refused at startup.

## What an Agent Portfolio is

An [Agent Portfolio](https://www.etoro.com/news-and-analysis/etoro-updates/agent-portfolios-let-your-ai-agent-trade-for-you/) (Beta) is a real-money sub-portfolio inside your eToro account, built for AI agents and automated strategies:

- **Isolated allocation.** You fund it with an amount you choose (minimum **$200**). The bot can only ever touch that allocation — worst case is bounded by it, not by your account.
- **Scoped credential.** Each portfolio has its own *user token*: an OAuth **Bearer** credential (`Authorization: Bearer <token>`), mutually exclusive with the `x-api-key`/`x-user-key` pair the bot uses for market data. Tokens carry scopes (`etoro-public:trade.real:read|write`) and support an optional **expiry** and **IPv4 whitelist**.
- **Shown once.** The token value is only visible at creation. Store it immediately in `.env`.

This is why it is the only supported real path: the blast radius is capped, the credential is scoped, and revocation is one click in eToro's UI.

## Setup (your actions, in eToro's desktop platform)

1. Open **Agent Portfolios (Beta)** from the side menu.
2. Create a portfolio: name it, allocate the budget (≥ $200).
3. Mint a **real-scoped** user token. Recommended: set an **IP whitelist** (the machine that runs the bot) and an **expiry**.
4. Copy the token (it will not be shown again) and add it to `.env`:

```dotenv
ETORO_AGENT_TOKEN=your_scoped_token
ETORO_ENV=real
```

The existing `ETORO_API_KEY`/`ETORO_USER_KEY` pair stays in `.env` — it keeps serving candles, instrument lookup, and the WebSocket feed (none of which are portfolio-scoped).

## Validation runbook

Before letting the bot trade, validate the full order round-trip **yourself** with the supervised harness. It never acts without a typed confirmation:

```bash
etorobot validate-real --amount 10
```

(`--symbol BTC` to override the first configured instrument.)

What happens, step by step:

1. Resolves the instrument and prints your portfolio's available credit.
2. Shows the intended market **BUY** of `--amount` dollars (at most $1000), with a wide ±5% SL/TP bracket derived from the last candle, and waits. Type **`open`** to place it — anything else aborts (`before-open`, nothing placed).
3. Polls the order until it fills; prints the raw status. A rejected order stops with the API's error message (`order-rejected`). If the response shape is unexpected (`open-shape-unexpected`) or the order never resolves (`order-unresolved`), check the eToro app — in the latter case it may still fill.
4. Waits again. Type **`close`** to close the position — anything else aborts (`before-close`) **leaving the position open**; close it in the eToro app or re-run.
5. Polls trade history until the close settles (`close-unsettled` if it doesn't appear yet — verify in the app).

Every raw API response is saved to `validation_real_<timestamp>.json`. **Diff those shapes** against a demo run of the same command (`ETORO_ENV=demo`, no token needed) — the parsers were built against demo responses, and this file is the evidence the real ones match.

## Going live

Once validated:

```bash
etorobot --config config.yaml run --real-money
```

The startup guard enforces the full matrix:

| Condition | Result |
|---|---|
| `ETORO_ENV=real`, no `ETORO_AGENT_TOKEN` | refused — direct real-account trading is disabled |
| `ETORO_ENV=real`, token set, no `--real-money` | refused — the flag is the per-session consent |
| `ETORO_ENV=real`, token set, `--real-money` | trades the Agent Portfolio |
| `ETORO_ENV=demo` (with or without token) | demo behavior, no flag needed |

The bot remains **long-only**, with all existing risk limits (position sizing, per-instrument and global caps, SL/TP defaults, daily-loss kill-switch) applied unchanged. Runs appear in the dashboard like any other, with `env=real`.

## Rotation and revocation

Tokens are managed in eToro's UI. If a token leaks or a machine is decommissioned, revoke it there — the bot fails fast with a clear 401/403 error naming the token as the likely cause. Mint a new token and update `.env` to resume.
