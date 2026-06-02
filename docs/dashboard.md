# Dashboard

A **read-only** web view of the bot's runs — both live sessions (`etorobot run`) and backtests (`etorobot backtest`). It lists every run, and for each shows the metrics, equity curve, trades, and signals. Live runs update in **real time** over Server-Sent Events (SSE).

## What it is

The dashboard is a separate FastAPI process that runs **alongside** the bot on the same host. It opens the bot's SQLite database **read-only** (SELECT only — it never writes), tails it for new rows roughly every 1.5 s, and pushes those rows to the browser over SSE. Because the bot writes the same database in WAL mode, the two processes coexist without locking each other out.

```
            ┌─────────────┐  writes (WAL)   ┌──────────────┐
 bot ──────▶│  bot_<env>  │◀───── reads ────│  dashboard   │
 (run /     │   .db       │   (SELECT only) │  (FastAPI)   │
  backtest) └─────────────┘                 └──────┬───────┘
                                                   │ SSE / HTTP
                                                   ▼
                                               browser
```

A "run" is one bot session. Live runs are created when you start `etorobot run`; backtests are persisted durably when you run `etorobot backtest` (they no longer live only in memory). Each signal, fill, and equity snapshot is tagged with its `run_id`, which is how the dashboard groups them.

## Run it

```bash
# Set the shared token (required for any non-local exposure)
echo 'DASHBOARD_TOKEN=choose-a-long-random-string' >> .env

# Start the dashboard (defaults: --host 127.0.0.1 --port 8000)
etorobot --config config.yaml dashboard --host 127.0.0.1 --port 8000
```

Then open <http://127.0.0.1:8000/>. The run list links to a per-run report page.

By default the dashboard reads `bot_<ETORO_ENV>.db` (e.g. `bot_demo.db`), matching what the bot writes. Override the database with `--db path/to/other.db`.

## What "real-time" means

Updates are **event-paced**, not sub-second. New data appears when the bot produces it: per closed candle, per signal, per fill. There are **no live price ticks** between candles — if your timeframe is `FiveMinutes`, expect new equity points every five minutes while the market moves. A finished or errored run shows a final status and stops streaming.

## TLS / remote access

The app binds to `127.0.0.1` and serves **plain HTTP** by default. Do **not** expose that port directly to the internet. To reach it remotely, put a TLS-terminating reverse proxy (Caddy, nginx, …) in front and forward to `127.0.0.1:8000`.

Minimal Caddy config (Caddy provisions and renews the certificate automatically):

```
dash.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

SSE requires the proxy to **not** buffer the response. Caddy handles this correctly out of the box. For nginx, disable buffering on the stream location:

```nginx
location ~ ^/api/runs/.*/stream$ {
    proxy_pass http://127.0.0.1:8000;
    proxy_buffering off;
    proxy_cache off;
    proxy_set_header Connection '';
    proxy_http_version 1.1;
}
```

## Auth

A single shared token, set via `DASHBOARD_TOKEN` in `.env` (the `DASHBOARD_` prefix maps to `DashboardSecrets`). It is compared in constant time; a wrong or missing token returns `401`.

- **API calls** send it as an `Authorization: Bearer <token>` header.
- **The SSE stream** receives it as a `?token=<token>` query parameter, because the browser's `EventSource` cannot set custom headers. (A `dashboard_token` cookie is also accepted.)

The bundled UI prompts for the token once and stores it in `localStorage`.

If `DASHBOARD_TOKEN` is **unset**, auth is disabled entirely. That is only safe when the dashboard is bound to localhost. Always set a token before exposing it remotely.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Static UI (run list). |
| `GET` | `/api/runs` | All runs, newest first, with summary metrics and a `stale` flag. |
| `GET` | `/api/runs/{id}` | Full report for one run: run row, metrics, equity, fills, signals. `404` if unknown. |
| `GET` | `/api/runs/{id}/stream` | SSE stream of new fills/signals/equity for a running run; emits a final `run_status` event when the run ends. |

All `/api/*` endpoints require the token (when one is configured).
