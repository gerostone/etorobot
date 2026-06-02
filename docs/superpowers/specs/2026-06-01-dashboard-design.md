# Dashboard de Ejecuciones — Diseño

**Fecha:** 2026-06-01
**Estado:** Aprobado (brainstorming) — pendiente plan de implementación

## Objetivo

Un dashboard web que permita **seguir en tiempo real las ejecuciones del bot** y consultar **el reporte de cada ejecución**. Una "ejecución" es un *run* (sesión) del bot: tanto un `etorobot run` (live demo/real) como un `etorobot backtest`.

## Decisiones de alcance (definidas en brainstorming)

| Tema | Decisión |
|------|----------|
| Qué es una "ejecución" | Un **run/sesión** del bot (no una orden individual). |
| Tipos de run cubiertos | **Live y backtests**, ambos como ejecuciones con reporte. Los backtests deben persistirse a una DB durable (hoy usan SQLite en memoria). |
| Despliegue | **Remoto / accesible desde afuera** (necesita auth + HTTPS). |
| Topología | Bot y backend del dashboard en el **mismo host**, compartiendo la misma SQLite. |
| Autenticación | **Una contraseña / token único** + HTTPS. |
| Acciones | **Solo lectura** en v1. El dashboard no controla el bot (no lanza ni frena runs). El bot se sigue manejando por CLI. |
| Contenido del reporte | Métricas de performance, equity curve, lista de trades, y señales con accepted/reason. |
| Stack | **Opción A**: FastAPI + Server-Sent Events (SSE) + HTML server-rendered con JS mínimo y librería de charts liviana. |
| Cadencia de "tiempo real" | *Event-paced* (por candle cerrada / fill / señal), no sub-segundo. Sin live-tick de precio entre candles. |

## Arquitectura general

El dashboard es un **proceso separado** del bot, en el mismo host, que lee la SQLite que el bot escribe y la transmite a navegadores remotos por HTTPS. El bot no conoce al dashboard (mismo patrón desacoplado de observers que ya usa el proyecto).

```
┌─────────────┐   escribe    ┌──────────────┐   tailea (poll)   ┌──────────────────┐   SSE/HTTPS   ┌─────────┐
│  etorobot   │ ───────────▶ │  bot_<env>.db │ ◀──────────────── │ dashboard backend │ ────────────▶ │ browser │
│ (run/bt)    │   (WAL)      │   (SQLite)    │     lee runs/     │  (FastAPI+uvicorn)│   + token     │ (HTML/JS)│
└─────────────┘              └──────────────┘   fills/signals/   └──────────────────┘               └─────────┘
                                                 equity                    │
                                                                    static HTML + charts
```

- **Bot (productor):** sin cambios de comportamiento, salvo que registra un `run` al arrancar/terminar y estampa `run_id` en lo que persiste. La SQLite se abre en modo **WAL** para permitir lecturas concurrentes sin bloqueos.
- **Dashboard backend (consumidor):** app FastAPI servida por uvicorn. Expone (a) endpoints JSON para listar runs y traer el reporte de un run, (b) un endpoint **SSE** que empuja eventos nuevos del run activo, (c) sirve el HTML/JS estático. Protegido por token único + HTTPS (TLS terminado por un reverse proxy adelante).
- **Frontend:** HTML server-rendered + JS mínimo. Vista de lista de runs y vista de detalle/reporte. Equity curve con librería de charts liviana.

**"Tiempo real" es event-paced.** El bot persiste por candle cerrada (cada `timeframe`) y por cada fill/señal. El backend tailea la DB cada ~1–2 s y empuja sólo filas nuevas; el navegador ve cada trade/señal/snapshot apenas se persiste. No se muestra el precio tickeando entre candles (vive sólo en el WebSocket del bot, no se persiste).

## Modelo de datos

Hoy no existe el concepto de "run": `bot_<env>.db` guarda `signals`, `fills`, `equity_snapshots` de forma global, y los backtests usan SQLite en memoria. Cambios necesarios:

- **Nueva tabla `runs`:** `id`, `mode` (live/backtest), `env` (demo/real), `strategy`, `params` (JSON/texto), `timeframe`, `instruments` (texto), `started_at`, `ended_at` (nullable), `status` (running/finished/error), `starting_cash`.
- **Agregar `run_id` (FK)** a `signals`, `fills`, `equity_snapshots`.
- **Persistir los backtests** a la DB durable (no `:memory:`) para que aparezcan en el historial con su reporte.
- Una sola DB compartida en el host; el bot escribe, el backend lee (solo SELECT).

## Componentes y estructura de archivos

**Persistencia (compartida por bot y dashboard):**
```
src/etorobot/persistence/
  models.py     # MODIFICAR: nueva RunRow; agregar run_id (FK) a SignalRow/FillRow/EquityRow
  repo.py       # MODIFICAR: create_run(), finish_run(status); record_* aceptan run_id;
                #            queries de lectura (list_runs, get_run, run_signals,
                #            run_fills, run_equity); habilitar WAL al crear el engine
```

**Wiring del bot (para estampar run_id):**
```
src/etorobot/core/engine.py     # MODIFICAR: el engine recibe run_id y lo pasa a los record_*
src/etorobot/backtest/runner.py # MODIFICAR: persistir a DB durable; crear/cerrar run
src/etorobot/cli.py             # MODIFICAR: do_run/do_backtest crean el run y marcan finished/error
```

**Paquete nuevo del dashboard (consumidor, read-only):**
```
src/etorobot/dashboard/
  __init__.py
  app.py        # FastAPI: arma la app, monta rutas y estáticos, auth dependency
  auth.py       # verificación de token único (header/cookie); lee DASHBOARD_TOKEN del entorno
  reads.py      # capa de lectura: consulta la DB y arma DTOs del reporte
  metrics.py    # reusa backtest/metrics.compute_metrics para runs live
  tailer.py     # DbTailer: poll incremental por id; entrega filas nuevas desde el último visto
  sse.py        # endpoint SSE: suscribe un cliente, stream de eventos del run activo
  static/
    index.html  # lista de runs
    run.html    # detalle/reporte de un run
    app.js      # fetch de la API, suscripción SSE, render de tablas
    charts.js   # equity curve con la librería de charts
    styles.css
```

**Config:**
```
src/etorobot/config/settings.py  # MODIFICAR: DashboardSecrets (DASHBOARD_TOKEN), prefijo DASHBOARD_
```

**CLI nuevo:**
```
etorobot dashboard [--host 0.0.0.0] [--port 8000] [--db bot_demo.db]
```
Lanza uvicorn con la app. El TLS lo pone un reverse proxy adelante (se documenta cómo).

**Principios de diseño:** el dashboard es read-only y aislado en su paquete; solo `reads.py`/`metrics.py` tocan la DB (de lectura). `tailer.py` y `reads.py` son testeables sin levantar el server.

## Flujo de datos

**A. Ciclo de vida de un run (lado bot):**
1. `do_run`/`do_backtest` llama `repo.create_run(...)` → devuelve `run_id`, fila con `status="running"`, `started_at=now`.
2. Se pasa `run_id` al `Engine`. En cada señal/fill/equity, los `record_*` estampan ese `run_id`.
3. Al terminar `engine.run()`: `repo.finish_run(run_id, status="finished")` (o `"error"` si la excepción se propaga, en `finally`/`except`). Setea `ended_at`.
4. Backtest: igual, pero instantáneo; queda persistido con su `run_id`.

**B. Listar runs (vista índice):**
- `GET /api/runs` → `reads.list_runs()` devuelve filas de `runs` (id, mode, env, strategy, status, started/ended, resumen: nº trades, total_return). El front las pinta; el run con `status="running"` se marca "en vivo".

**C. Reporte de un run (vista detalle):**
- `GET /api/runs/{id}` → `reads.get_run(id)` arma el DTO completo:
  - **métricas:** `compute_metrics(run_equity(id), run_trade_pnls(id))` (reusa `backtest/metrics.py`),
  - **equity curve:** `run_equity(id)` (equity/cash/timestamp),
  - **trades:** `run_fills(id)` (open/close con precio, units, monto, comisión; PnL emparejando close→open por position_id),
  - **señales/rechazos:** `run_signals(id)` (accepted + reason).
- El front renderiza tablas + equity curve con `charts.js`.
- Reporte armado **on-demand** desde la DB (sin cache en v1).

**D. Run en vivo (push por SSE):**
- El navegador abre `GET /api/runs/{id}/stream` (SSE) para el run activo.
- El backend corre un `DbTailer` que cada ~1–2 s consulta "¿hay filas con id > último visto?" en signals/fills/equity para ese `run_id`, y emite cada novedad como evento SSE tipado (`event: fill` / `signal` / `equity` / `run_status`).
- El front, al recibir un evento, **appendea** la fila a la tabla y actualiza la equity curve y las métricas, sin recargar.
- Al llegar `run_status: finished/error`, el front cierra el stream y muestra el reporte final.
- Concurrencia: la DB en **WAL** permite que el tailer lea mientras el bot escribe; el tailer solo hace `SELECT`.

## Manejo de errores

Principio: **el dashboard nunca afecta al bot**; un bot caído o una DB a medio escribir nunca rompen el dashboard.

**Lado bot (productor):**
- Falla al crear/cerrar el run → se envuelve con el patrón observer existente (`_record`): loguea y sigue.
- Bot crashea sin cerrar el run → la fila queda `status="running"`. El dashboard lo detecta como **run huérfano/stale** (status running pero sin escrituras nuevas hace > N intervalos del timeframe) y lo muestra con badge "stale", sin inventar que terminó bien. No se toca la DB para "arreglarlo" (read-only).

**Lado dashboard (consumidor):**
- DB ausente o ruta inválida al arrancar → error claro y salida (no levanta el server a ciegas).
- `database is locked` puntual → WAL lo evita en el caso normal; igual, lecturas con reintento corto y backoff. Si persiste → 503 y el front muestra "reintentando".
- Run id inexistente → 404 con mensaje claro.
- Cliente SSE desconectado → el backend detecta el cierre y limpia el tailer asociado (sin leaks de tasks). El navegador reintenta con el reconnect nativo de `EventSource`.
- Auth: sin token o inválido → 401 en la API y redirect a pantalla de "ingresá el token" en las vistas HTML. Comparación de token constante (anti-timing). El token nunca se loguea.
- Excepción inesperada en un endpoint → handler global → 500 con cuerpo JSON genérico (sin stack trace al cliente), log del lado server.

**Transversal:** el dashboard hace **solo SELECT**. No hay path de escritura a la DB del bot, así que ningún bug del dashboard puede corromper datos de trading.

## Estrategia de testing

Todo offline, sin levantar uvicorn ni tocar la red, alineado con el suite actual (`pytest`, `asyncio_mode="auto"`, `respx`).

**Persistencia (unit, SQLite tmp/memoria):**
- `create_run` crea fila con `status="running"`, `started_at` seteado, `ended_at` nulo.
- `finish_run` setea `status` y `ended_at`; idempotente ante doble llamada.
- `record_signal/fill/equity` estampan el `run_id` correcto; quedan aislados por run.
- `list_runs`/`get_run`/`run_signals`/`run_fills`/`run_equity` filtran por `run_id` y no mezclan runs.
- WAL: verificar que se habilita (`PRAGMA journal_mode=wal`).

**Lectura/reporte (`reads.py`, `metrics.py`):**
- El DTO de reporte arma métricas correctas reusando `compute_metrics` (caso con ganadores/perdedores, caso sin trades).
- Emparejado close→open por `position_id` para PnL por trade.
- Run inexistente → error/None que el endpoint mapea a 404.

**Tailer (`tailer.py`, unit, sin red):**
- Dada una DB con N filas, el primer poll entrega todas; tras insertar M nuevas, el siguiente poll entrega solo esas M (cursor por id).
- Run huérfano: sin filas nuevas pasado el umbral → marca "stale".

**API (FastAPI `TestClient`, sin server real):**
- `GET /api/runs` lista; `GET /api/runs/{id}` arma reporte; `{id}` inexistente → 404.
- Auth: sin token → 401; token válido → 200; comparación de token constante.
- SSE: con `TestClient`, suscribir y verificar que una fila nueva insertada en la DB se emite como evento tipado; desconexión limpia el tailer.

**Frontend:** sin framework de test JS en v1 (mantener liviano). Validación manual; la lógica de negocio vive en el backend, que sí está cubierto.

**Integración (1 test end-to-end):** correr un mini-backtest real → persiste un run → `get_run` devuelve un reporte coherente (métricas + trades + señales). Ata productor con consumidor.

## Fuera de alcance (v1)

- Control del bot desde la web (lanzar/frenar runs, cerrar posiciones).
- Cuentas de usuario individuales (solo token único).
- Live-tick de precio sub-segundo entre candles.
- Cache del reporte / capa de agregación; los reportes se arman on-demand.
- Tests automatizados de frontend.
