# Plan 001 — Capa de Ingesta de Datos

## Decisiones técnicas

| Decisión | Elección | Alternativa descartada | Por qué |
|---|---|---|---|
| Cliente de exchange | `ccxt` | SDK específico de Binance | Abstrae el exchange; migrar a otro (o soportar varios) más adelante no toca el resto del sistema. |
| Validación de datos | Pydantic v2 (`Candle`) | Validación ad-hoc con `if`s sueltos | Contrato de datos explícito, reutilizable en el Motor de Backtesting y en la ingesta streaming futura. |
| Persistencia | PostgreSQL + extensión TimescaleDB | Postgres plano | Justificado en `docs/SDD.md` §4.2 (hypertables, continuous aggregates). |
| Idempotencia | `INSERT ... ON CONFLICT DO NOTHING` sobre `PRIMARY KEY(symbol, timeframe, timestamp)` | Borrar-y-reinsertar el rango completo | Más simple y seguro ante descargas parciales/reintentos; no hay lógica de "detectar qué borrar". |
| Migraciones | Alembic | Crear tablas a mano / `Base.metadata.create_all` | Evolucionar el esquema sin perder histórico ya cargado es un requisito desde el día 1 en un sistema que acumula años de datos. |
| Clave primaria de `ohlcv` | `PRIMARY KEY(symbol, timeframe, timestamp)`, sin columna `id` surrogate | `id BigInteger` autoincremental como PK, con `UNIQUE(symbol, timeframe, timestamp)` aparte | Descubierto al aplicar la migración real: `create_hypertable` rechaza la tabla si existe algún índice único/PK que no incluya la columna de partición (`timestamp`). Un `id` autoincremental solo no la incluye. La clave natural la resuelve sin necesitar una columna extra. |
| Puerto de Postgres en `docker-compose.yml` | `55432` (host) → `5432` (contenedor) | `5432` por defecto | Esta máquina ya tiene instancias nativas de PostgreSQL ocupando tanto el `5432` como el `5433` (confirmado con `Get-NetTCPConnection`); usar el default habría conectado silenciosamente al Postgres equivocado en vez de fallar. |
| Inserción de velas | `INSERT` por lotes de `INSERT_BATCH_SIZE = 5000` filas, dentro de la misma transacción | Un solo `INSERT ... VALUES (...), (...), ...` con todas las velas | Descubierto al descargar 2 años reales de 1h (17,520 velas): Postgres limita a 65535 parámetros por statement; con 8 columnas por vela el límite teórico son ~8191 filas por `INSERT`. Un solo statement con miles de velas lo supera ampliamente. 5000 deja margen amplio sin fragmentar demasiado la transacción. |
| Descarga resiliente a huecos reales del exchange (`load_historical_ohlcv_resilient`) | Descarga por tramos (`chunk_days`, default 30) que se **subdividen a la mitad recursivamente** si fallan la validación, hasta un piso de `min_chunk_hours` (default 6) | Descargar todo el rango en un solo bloque (falla completa por un solo hueco) o descartar el tramo completo sin subdividir | Descubierto al bajar histórico desde 2018: Binance tiene ~7-23 huecos reales de 1-8 horas a lo largo de los años (caídas del exchange). Con descarga en un solo bloque, **un hueco de 2 horas invalidaba años de datos buenos**. Con tramos fijos sin subdividir, invalidaba el mes completo (~720 velas) por el mismo hueco de 2 horas. La subdivisión recursiva bajó la pérdida real a ~7 tramos de ~5.5 horas cada uno — se recuperaron ~16,400 velas que se estaban descartando sin necesidad. |

## Contrato de datos

```python
class Candle(BaseModel):
    symbol: str
    timeframe: str        # uno de: 1m, 5m, 15m, 30m, 1h, 4h, 1d
    timestamp: datetime   # aware, se normaliza a UTC
    open: float            # > 0
    high: float            # > 0, >= low
    low: float             # > 0
    close: float           # > 0
    volume: float          # >= 0
```

Validaciones adicionales a nivel de serie (`validate_candle_series`): timestamps estrictamente ascendentes y paso constante igual al timeframe declarado (sin gaps).

## Esquema de base de datos

- `ohlcv` — hypertable particionada por `timestamp`, `PRIMARY KEY(symbol, timeframe, timestamp)` (sin `id` — ver tabla de decisiones).
- `ohlcv_1h` — continuous aggregate derivado de las velas `1m` de `ohlcv` (prueba de concepto de TimescaleDB, no se consume todavía).
- `trades`, `orders`, `account_state` — esqueleto de tablas que usarán las specs 002-005; se crean ahora para no tener que migrar el esquema de `ohlcv` por separado del resto.

## Diseño de módulos

```
src/trading_engine/
  models/candle.py          Candle (Pydantic) + validate_candle_series
  ingestion/
    exchange_client.py      ExchangeClient: wrapper ccxt, paginación por 'since'
    historical_loader.py    load_historical_ohlcv: orquesta fetch -> validar -> persistir
  db/
    schema.py                Modelos SQLAlchemy (OHLCV, Trade, Order, AccountState)
    session.py                Engine/sesión desde DATABASE_URL
  cli.py                      Entry point de línea de comandos
```

`ExchangeClient.fetch_ohlcv_range` pagina usando el patrón estándar de ccxt: `since = último_timestamp_recibido + 1`, hasta cubrir el rango o hasta que el exchange deje de devolver velas nuevas (evita loop infinito si el exchange no avanza).

## Riesgos técnicos y mitigación

- **Rate limiting del exchange**: `ccxt` se inicializa con `enableRateLimit: True`, que throttlea automáticamente las llamadas síncronas.
- **Cambios de esquema del exchange** (columnas OHLCV en otro orden, símbolos renombrados): mitigado parcialmente por la validación Pydantic (rechaza valores imposibles), pero un cambio de *orden* de columnas que produzca valores igual de "plausibles" no se detecta automáticamente — de ahí el criterio de aceptación de contrastar una muestra manualmente contra el exchange.
- **Reinicio a mitad de una descarga larga**: no hay checkpointing explícito todavía; al ser idempotente, simplemente se vuelve a lanzar el mismo comando con el mismo rango.
