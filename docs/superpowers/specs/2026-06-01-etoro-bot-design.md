# eToro Trading Bot — Diseño

**Fecha:** 2026-06-01
**Estado:** Aprobado para planificación

## 1. Objetivo

Construir un **framework de trading algorítmico** para la API pública de eToro, en
Python, donde se puedan enchufar y probar distintas estrategias. La misma
estrategia debe correr de forma idéntica en **backtest** (datos históricos) y en
**vivo** (WebSocket en tiempo real), sin duplicar lógica.

### Decisiones tomadas

| Tema | Decisión |
|------|----------|
| Tipo de lógica | Framework de estrategias enchufables (con una de ejemplo) |
| Activos | Agnóstico — configurable por instrumento |
| Entorno inicial | Solo **Demo** (paper). Switch a Real por configuración más adelante |
| Stack | Python 3.11+ |
| Ejecución | Tiempo real vía **WebSocket** |
| Alcance v1 | Gestión de riesgo + Backtesting + Notificaciones (Telegram) + Logging/persistencia |

## 2. Restricciones de la API de eToro

- **Base URL:** `https://public-api.etoro.com/api/`
- **Auth por headers** (sin OAuth): `x-api-key` (Public API Key), `x-user-key`
  (User Key del usuario), `x-request-id` (UUID nuevo por request).
- La key se crea por **entorno** (Demo/Real) y con permisos **Read/Write**.
- **Rate limits** (por user key, ventana móvil de 1 min):
  - 60 GET/min (market data, portfolio, feeds)
  - 20 escrituras/min (órdenes, watchlists, posts)
  - Exceso → `429`; se requiere retry con backoff exponencial.
- **Trading:** `POST /api/v2/trading/execution/orders` (market/limit, leverage,
  SL/TP), cancelar órdenes, cerrar posiciones (total/parcial).
- **Market data:** velas históricas OHLCV, precios actuales, y **WebSocket** para
  streaming en tiempo real.
- **Portfolio:** posiciones abiertas, órdenes, PnL, cash disponible.
- La cuenta debe estar **verificada** para que aparezca la API key.

## 3. Arquitectura

Núcleo **event-driven asíncrono** (asyncio).

```
DataFeed ──MarketEvent──> Engine ──> Strategy ──Signal──> RiskManager ──Order──> Broker
   │                         │                                                      │
(WS live / histórico)   EventBus                                          (eToro live / simulado)
                             │
                        Persistence + Notifier (observan todos los eventos)
```

**Principio clave:** `Strategy`, `RiskManager`, `Persistence` y `Notifier` son
**idénticos** en backtest y en vivo. Solo se intercambian dos piezas detrás de
interfaces (clases base abstractas):

| Interfaz | Implementación Live | Implementación Backtest |
|----------|--------------------|--------------------------|
| `DataFeed` | WebSocket eToro (ticks → velas) | Reproductor de velas históricas (REST) |
| `Broker` | API REST eToro (demo/real) | Broker simulado (fills + comisión + slippage) |

### Estructura de módulos

```
core/         EventBus, tipos de eventos, Engine
feeds/        LiveFeed (WS), HistoricalFeed
brokers/      EtoroBroker, SimulatedBroker
strategies/   BaseStrategy + estrategia de ejemplo (SMA crossover)
risk/         RiskManager
data/         EtoroClient (auth, rate limiting, retry/backoff, caché)
persistence/  Repositorio SQLite (SQLAlchemy)
notify/       BaseNotifier + TelegramNotifier
config/       Carga y validación de config (Pydantic) + secrets (.env)
cli.py        Punto de entrada: run, backtest
```

## 4. Contratos del núcleo (`core/`)

Eventos que circulan por el `EventBus` (dataclasses inmutables):

- **`MarketEvent`** — `instrument_id`, `symbol`, `timestamp`, vela OHLCV cerrada
  (o tick). Dispara la evaluación de estrategias.
- **`Signal`** — emitido por una estrategia: `symbol`, `direction`
  (`BUY`/`SELL`/`CLOSE`), `strength` (0–1, opcional), `meta`. Es *intención*, no
  orden.
- **`OrderEvent`** — orden concreta tras pasar por riesgo: `transaction`,
  `order_type` (`mkt`/`limit`), `amount`/`units`, `leverage`, `stop_loss`,
  `take_profit`.
- **`FillEvent`** — confirmación de ejecución: precio, cantidad, comisión,
  `position_id`.

**Engine (loop asíncrono):**
1. `DataFeed` produce `MarketEvent` → EventBus.
2. Engine entrega el evento a cada `Strategy` suscrita → puede emitir `Signal`.
3. `RiskManager` recibe `Signal`, consulta estado de portfolio, decide y
   dimensiona → `OrderEvent` (o lo descarta con motivo).
4. `Broker` ejecuta `OrderEvent` → `FillEvent`.
5. `Persistence` y `Notifier` observan todo (señales, órdenes, fills, errores).

El mismo Engine corre en live y backtest; solo cambian las implementaciones de
`DataFeed` y `Broker` inyectadas.

## 5. Cliente eToro (`data/` + `feeds/` + `brokers/`)

**`EtoroClient` (REST, async con httpx):**
- Auth por headers (`x-api-key`, `x-user-key`, `x-request-id` UUID por request).
  Keys y entorno desde config.
- **Rate limiter** interno (token bucket): ventanas separadas de 60 GET/min y 20
  escrituras/min. En `429` → retry con backoff exponencial + jitter.
- **Caché local** de datos estables (instrument IDs por símbolo, tipos de
  instrumento) para preservar cuota.
- Métodos: `resolve_instrument(symbol)`, `get_candles(...)`, `get_rates(...)`,
  `get_portfolio()`, `create_order(...)`, `close_position(...)`,
  `cancel_order(...)`.

**`LiveFeed`** (asyncio + `websockets`): autentica, se suscribe a los
instrumentos configurados, normaliza ticks y **agrega velas** del timeframe
configurado (ej. 1m/5m); al cerrar una vela emite `MarketEvent`. Reconexión
automática y heartbeat.

**`HistoricalFeed`**: pide velas OHLCV vía REST para el rango configurado y las
reproduce en orden cronológico como `MarketEvent` (backtest).

**`EtoroBroker`**: traduce `OrderEvent` a llamadas REST de trading y devuelve
`FillEvent`. Apunta a **demo** según la key configurada.

## 6. Gestión de riesgo (`risk/`)

`RiskManager` se sitúa entre `Signal` y `OrderEvent`. Controles configurables:
- **Tamaño por posición:** % del equity o monto fijo por trade.
- **Máx. posiciones abiertas:** global y por instrumento (evita duplicar una
  posición ya abierta).
- **SL/TP automáticos:** aplica stop-loss y take-profit por defecto si la
  estrategia no los especifica.
- **Límite de pérdida diaria:** si el PnL del día cae bajo el umbral, **kill-switch**
  que bloquea nuevas órdenes hasta el próximo día.
- **Validación de cash disponible** antes de emitir la orden.

Si una `Signal` viola una regla, se descarta y se loguea/notifica el motivo.
Corre idéntico en backtest y live → el backtest respeta los mismos límites.

## 7. Backtesting (`brokers/SimulatedBroker` + runner)

Reusa todo el núcleo: se inyecta `HistoricalFeed` + `SimulatedBroker` en el mismo
Engine.
- **`SimulatedBroker`:** portfolio virtual (cash, posiciones). Ejecuta
  `OrderEvent` al precio de la vela (open/close configurable) con **comisión y
  slippage** parametrizables. Emite `FillEvent` y actualiza PnL.
- **Métricas:** retorno total, máx. drawdown, win rate, nº de trades, Sharpe
  simple. Salida por consola + CSV opcional de la curva de equity.
- Mismo `RiskManager` y misma `Strategy` que en vivo → resultados comparables.

## 8. Persistencia (`persistence/`)

**SQLite** vía **SQLAlchemy** (core/ORM). Tablas:
- `signals` — toda señal emitida (símbolo, dirección, timestamp, estrategia,
  aceptada/rechazada + motivo).
- `orders` — órdenes enviadas.
- `fills` — ejecuciones (precio, comisión, position_id).
- `equity_snapshots` — PnL/equity periódico.

Un archivo por entorno (`bot_demo.db`). En backtest, opcionalmente en memoria.

## 9. Notificaciones (`notify/`)

`BaseNotifier` (interfaz) + `TelegramNotifier` (HTTP a la Bot API; token +
chat_id desde config, sin dependencias pesadas). Notifica: trade ejecutado,
orden rechazada por riesgo, kill-switch activado, errores de feed/broker,
arranque/parada del bot. Niveles configurables para no spamear. Diseñado para
enchufar Discord/email después.

## 10. Configuración (`config/`)

- **`.env`** (secretos): `ETORO_API_KEY`, `ETORO_USER_KEY`, `ETORO_ENV=demo`,
  `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`.
- **`config.yaml`** (resto): instrumentos a operar, timeframe, parámetros de
  riesgo, estrategia activa y sus parámetros.
- Validación con **Pydantic** al arrancar (falla rápido si falta algo).

## 11. Estrategia de ejemplo

**SMA crossover** (media móvil rápida vs lenta): `BUY` en cruce alcista,
`CLOSE`/`SELL` en cruce bajista. Hereda de `BaseStrategy` y sirve de plantilla.

## 12. Testing

`pytest`, sin red real (se mockea `EtoroClient`). Cobertura:
- `RiskManager` — cada regla por separado.
- `SimulatedBroker` — fills, comisión, slippage, PnL.
- `LiveFeed` — agregación de ticks → velas.
- Rate limiter — ventanas y backoff.
- Estrategia de ejemplo — señales esperadas ante series de precios conocidas.

## 13. Stack final

`python 3.11+`, `asyncio`, `httpx`, `websockets`, `pydantic`, `pandas` +
`pandas-ta` (indicadores), `SQLAlchemy`, `pytest`. Gestión de entorno con `uv` o
`venv` + `pip`.

## 14. Fuera de alcance (v1)

- Operar en entorno **Real** (solo Demo en v1; el switch queda preparado por
  config pero no se valida con dinero real).
- Dashboard/UI web.
- Copy trading / replicar Pro Investors.
- Optimización de hiperparámetros / walk-forward.
- Canales de notificación más allá de Telegram (interfaz preparada, no
  implementados).
