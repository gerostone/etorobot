# Agent Portfolio Trading — Design Spec

**Date:** 2026-08-04
**Status:** Approved
**Depends on:** the `feat/dashboard` run-lifecycle changes (`create_run`/`finish_run` in `do_run`).

## Goal

Let etorobot trade a real-money **eToro Agent Portfolio** through its scoped Bearer token, while market data (candles, instrument resolution, WebSocket ticks) keeps flowing through the existing key pair. Real-money sessions require an explicit `--real-money` CLI flag. Go-live is preceded by a supervised, **user-executed** validation round-trip — the assistant builds the harness but never places trades.

## Background

eToro's **Agent Portfolios** (Beta) are real-money sub-portfolios (minimum $200) created in the eToro desktop UI. Each has a dedicated **user token** — an OAuth Bearer credential (`Authorization: Bearer <token>`), *mutually exclusive* with the `x-api-key`/`x-user-key` header pair — carrying scopes `etoro-public:trade.real:read|write` or `trade.demo:read|write`, with optional expiry and IP whitelist. The token is shown only at creation. Trades route through the existing real/demo endpoint variants; the token scopes them to the portfolio server-side (this routing is the main assumption the validation run confirms).

The WebSocket feed (`wss://ws.etoro.com/ws`) authenticates only with `{userKey, apiKey}`; Bearer support is undocumented. This design therefore splits planes: **data plane** keeps the pair, **execution plane** uses the token.

## Architecture (Approach A — split-plane credentials)

```
                         ┌────────────────────────────┐
  candles / instruments  │ data client (pair auth,    │
  WS ticks ─────────────▶│ env=demo) + LiveFeed       │──▶ Engine
                         └────────────────────────────┘      │
                                                             ▼
                         ┌────────────────────────────┐   OrderEvent
  orders / close /       │ trade client (Bearer,      │◀─── Broker
  portfolio / history    │ env=demo|real)             │
                         └────────────────────────────┘
```

Rejected alternatives: **Bearer everywhere** (WS Bearer support unknown — dead on arrival if absent); **dedicated AgentClient class** (duplicates validated response parsing).

## Credentials & config

`Secrets` (`ETORO_` prefix, `config/settings.py`) gains one optional field:

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `ETORO_AGENT_TOKEN` | no | `None` | Scoped Agent Portfolio user token. When set, the **trading** client authenticates with `Authorization: Bearer <token>` instead of the key pair. |

Mode matrix (`ETORO_ENV` × token):

| `ETORO_ENV` | Token unset | Token set |
|---|---|---|
| `demo` | today's behavior (pair auth, demo paths) | Bearer trading client, demo paths — free smoke test of the plumbing |
| `real` | **refused at startup** (legacy unvalidated path, now blocked) | Bearer trading client, real paths, requires `--real-money` |

The `env=real` + no-token cell closes a latent gap: previously nothing stopped `ETORO_ENV=real` with pair auth. After this change the *only* real-money path is the scoped token.

## Component changes

### `EtoroClient` (`data/client.py`)

- `__init__(..., agent_token: str | None = None)` stores `self._agent_token`.
- `_headers()` branches: when `self._agent_token` is set, return `{"Authorization": f"Bearer {self._agent_token}", "x-request-id": str(uuid.uuid4()), "Content-Type": "application/json"}` — the pair headers are omitted (the API treats the two auth methods as mutually exclusive). Otherwise unchanged.
- No other changes: paths, rate limiting, retries, and response parsers stay as they are. The real/demo path selection keyed off `env` is unchanged.

### CLI (`cli.py`)

- `run` subparser gains `--real-money` (store_true, default False).
- Startup guard in `do_run` (before any network call):
  - `env == "real"` and no agent token → exit with error: real trading requires an Agent Portfolio token.
  - `env == "real"` and no `--real-money` flag → exit with error naming the flag.
- New subcommand **`validate-real`**: supervised round-trip harness (below).

### Wiring (`do_run`)

Two clients:
- `data_client = EtoroClient(api_key, user_key, env="demo")` — instrument resolution, candles; `LiveFeed` keeps taking the raw pair (unchanged).
- `trade_client = EtoroClient(api_key, user_key, env=env, agent_token=token)` — passed to `EtoroBroker`.

Engine, RiskManager, Repository, dashboard: untouched. Runs record `env="real"` and appear in the dashboard as-is.

## `validate-real` harness

A CLI subcommand the **user** runs interactively; every money-moving step requires typed confirmation:

1. Resolve one configured instrument; fetch current portfolio; print balances.
2. Print the intended minimum-size order (instrument, amount, SL/TP) and wait for typed `open` confirmation.
3. Place the order; poll for fill; print and persist the **raw** response JSON.
4. Wait for typed `close` confirmation; close the position; print/persist raw response.
5. Save all raw responses to `validation_real_<timestamp>.json` so real response shapes can be diffed against the demo shapes the parsers were built on.

Abort at any prompt leaves at most one open min-size position, reported clearly with its position ID.

## Error handling

- 401/403 from the Bearer client → clear startup failure naming the token as the likely cause (expired, IP whitelist, wrong scope); no retry loop.
- Existing observer isolation (repo/notifier failures swallowed) unchanged; broker failures propagate as today.

## Testing

- **Unit (offline, respx/mocks):** `_headers()` pair-vs-Bearer branch and mutual exclusion; mode-matrix guards (all four cells); `--real-money` flag parsing; `validate-real` prompt flow with a mocked client, including abort paths and refusal cases.
- **Live validation:** the `validate-real` runbook executed by the user against a funded portfolio, documented step-by-step in `docs/going-real.md`, which replaces the README's "Going to a real account (not yet validated)" section with the Agent Portfolio path.

## Out of scope (YAGNI)

Portfolio/token lifecycle via API (create/delete portfolio, mint/rotate tokens — done in eToro's UI), OAuth-scope introspection, multiple portfolios, WS Bearer auth, dashboard changes.

## Addendum (2026-08-04, post-merge): UI-issued key pairs

Field finding: eToro's desktop UI issues Agent Portfolio credentials as a
**scoped `x-api-key`/`x-user-key` pair**, not a Bearer token (the Bearer
flow exists only via the API's create-user-token endpoints). A scoped pair
works on the normal `/real/` trading paths, and has a reliable fingerprint:
`GET /api/v1/agent-portfolios` answers **403 "this gcid is an
agent-portfolio"** (a main-account pair answers 200).

Design change: the real-run guard accepts either scoped credential:

- `ETORO_AGENT_TOKEN` (Bearer, API-minted) — as designed; or
- `ETORO_AGENT_PORTFOLIO=true` — an explicit claim that the configured key
  pair is a UI-issued Agent Portfolio key. The claim is **verified at
  startup** with the read-only fingerprint probe; anything but the
  distinctive 403 refuses the session (fail-closed, so a main-account pair
  can never trade real money).

`--real-money` remains required per session. Demo paths reject
agent-portfolio pairs (403 InsufficientPermissions), so such a key is
real-only by construction.
