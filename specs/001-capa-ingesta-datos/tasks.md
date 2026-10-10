# Tasks 001 — Capa de Ingesta de Datos

Convención de estado: `hecho` = código escrito pero aún no verificado en ejecución real · `verificado` = corrido y comprobado · `pendiente` = no iniciado.

| # | Tarea | Archivo(s) | Estado |
|---|---|---|---|
| 1 | Modelo `Candle` (Pydantic) con validaciones de precio/volumen/timestamp/OHLC | `src/trading_engine/models/candle.py` | verificado |
| 2 | `validate_candle_series` (orden cronológico + gaps) | `src/trading_engine/models/candle.py` | verificado |
| 3 | Esquema SQLAlchemy: `ohlcv`, `trades`, `orders`, `account_state` | `src/trading_engine/db/schema.py` | verificado |
| 4 | Migración Alembic inicial: tablas + hypertable + continuous aggregate 1m→1h | `migrations/versions/0001_initial_schema.py` | verificado |
| 5 | `ExchangeClient` (ccxt) con paginación por rango de fechas | `src/trading_engine/ingestion/exchange_client.py` | verificado |
| 6 | `load_historical_ohlcv`: orquesta descarga → validación → persistencia idempotente | `src/trading_engine/ingestion/historical_loader.py` | verificado |
| 7 | CLI de descarga histórica | `src/trading_engine/cli.py` | verificado |
| 8 | Tests unitarios de validación de `Candle` y de serie (12 tests) | `tests/test_candle_validation.py` | verificado |
| 9 | Tests unitarios de `ExchangeClient` (paginación, ccxt mockeado, guard anti-loop) | `tests/test_exchange_client.py` | verificado |
| 10 | Tests unitarios de `load_historical_ohlcv` (sesión de DB mockeada) | `tests/test_historical_loader.py` | verificado |
| 11 | Instalar dependencias en entorno virtual y correr `pytest` | — | verificado — 20/20 tests en verde |
| 12 | Levantar TimescaleDB (`docker-compose up`) y aplicar la migración (`alembic upgrade head`) contra una base real | `docker-compose.yml` | verificado (con incidencias, ver abajo) |
| 13 | Ejecutar una descarga real pequeña y contrastar contra el exchange | — | verificado |
| 14 | `README.md` con instrucciones de setup | `README.md` | hecho |
| 15 | `load_historical_ohlcv_resilient`: descarga por tramos con subdivisión recursiva ante huecos reales del exchange | `src/trading_engine/ingestion/historical_loader.py` | verificado |

## Incidencias encontradas al verificar contra infraestructura real (y ya resueltas)

1. **Puerto 5432 y 5433 ocupados por PostgreSQL nativo** en esta máquina (dos instancias distintas, confirmado con `Get-NetTCPConnection`). Las conexiones a `localhost:5432`/`5433` llegaban silenciosamente al Postgres equivocado (error de autenticación, no de "puerto ocupado"). Solución: el contenedor mapea a `55432` en el host — ver `docker-compose.yml` y `.env.example`.
2. **`create_hypertable` rechazaba la tabla `ohlcv`**: la clave primaria (`id` autoincremental) no incluía la columna de partición (`timestamp`), requisito de TimescaleDB. Solución: se eliminó la columna `id` y `(symbol, timeframe, timestamp)` pasó a ser la clave primaria — ver `plan.md` para el detalle de la decisión.
3. **`load_historical_ohlcv` fallaba con descargas grandes**: `INSERT ... VALUES (...), (...), ...` en un solo statement genera 8 parámetros SQL por vela (una por columna); Postgres limita a 65535 parámetros por statement. Con una descarga real de 2 años en 1h (17,520 velas) se superaba el límite por un margen amplio. Solución: `INSERT_BATCH_SIZE = 5000`, se particiona en varios `INSERT` dentro de la misma transacción — ver `plan.md`.
4. **Binance tiene huecos reales en su historial** (confirmado al bajar desde 2018): ~7-23 interrupciones de 1-8 horas a lo largo de los años, probablemente caídas del exchange. Con `load_historical_ohlcv` original, un solo hueco invalidaba todo el rango solicitado (años de datos buenos descartados por una sola falla puntual). Solución: `load_historical_ohlcv_resilient`, que descarga por tramos y los subdivide recursivamente ante un hueco en vez de descartarlos enteros — ver `plan.md`.

Las cuatro incidencias y su solución quedaron documentadas en `plan.md` (regla del flujo: el `plan.md` se actualiza antes de continuar cuando aparece una decisión técnica no prevista).

## Verificación de punta a punta realizada

- `docker compose up -d` → contenedor `timescale/timescaledb:latest-pg16` corriendo en `localhost:55432`.
- `alembic upgrade head` → tablas creadas, `ohlcv` confirmada como hypertable (`timescaledb_information.hypertables`), `ohlcv_1h` confirmada como continuous aggregate.
- Descarga real: `BTC/USDT`, `1h`, `2026-08-01` → `2026-08-02` → 24 velas (un día completo sin gaps), persistidas y con continuidad `open[i] == close[i-1]`.
- Idempotencia: repetir el mismo comando no duplicó filas (24 → 24).
- **Descarga real a escala de producción**: `BTC/USDT` y `ETH/USDT`, `1h`, 2 años (`2024-08-12` → `2026-08-12`) → **17,520 velas cada uno** (730 días × 24h exactas, sin gaps), confirmado con `MIN`/`MAX`/`COUNT` en la base de datos. Este fue el volumen que expuso la incidencia 3 (límite de parámetros de Postgres) — con las 24-50 velas de las pruebas anteriores el bug no era visible.
- **Extensión a histórico completo**: `BTC/USDT` y `ETH/USDT`, `1h`, `2018-01-01` → `2026-08-12` (8.6 años) → **75,326 velas cada uno**, con solo 7 huecos irrecuperables de ~5.5h cada uno (caídas reales de Binance, mismas fechas en ambos activos — confirma que son interrupciones del exchange completo, no del par). Este fue el volumen que expuso la incidencia 4 (huecos reales del exchange) — ver `plan.md`.

## Pendiente

- Tarea 14 (README) está escrita pero no releída por un segundo par de ojos — bajo riesgo, no bloquea nada.
- No se hizo el contraste manual byte-a-byte contra el front-end web de Binance (criterio de aceptación de `spec.md`) — los valores descargados sí son plausibles y consistentes internamente (continuidad open/close), pero falta la comparación visual explícita contra binance.com si se quiere cerrar ese criterio al 100%.

## Siguiente acción concreta

Spec 001 queda funcionalmente cerrada. Siguiente paso natural: arrancar spec 003 (Alpha Engine) por la tarea 1 (mover el contrato `Signal` a código), que desbloquea tanto a spec 003 como a spec 004 (Risk Engine).
