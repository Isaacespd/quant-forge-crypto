# QuantForge Crypto (Motor de Trading Algorítmico)

Fase actual: **backtesting-first**. Ver [`docs/SDD.md`](docs/SDD.md) para la visión y arquitectura completas, y [`specs/README.md`](specs/README.md) para el flujo de Spec-Driven Development y el estado de cada componente.

##  Características Implementadas

Actualmente, el motor cuenta con una sólida base para la simulación y descarga de datos:

- **Capa de Ingesta (`ingestion/`)**: Conexión con exchanges (usando `ccxt`) y un `historical_loader` para descargar velas (OHLCV) de forma idempotente.
- **Base de Datos (`db/`)**: Esquemas listos para TimescaleDB/PostgreSQL con SQLAlchemy.
- **Modelos Estrictos (`models/`)**: Modelado de datos robusto para velas, señales de trading y decisiones de riesgo.
- **Motor de Backtesting Avanzado**: Aunque el README se centraba en ingesta, ya existen implementaciones y tests robustos (`tests/`) para:
  - Simulador de Broker (`broker_sim`).
  - Motor de Riesgo (`risk_engine`).
  - Estrategias Alpha y evaluación de tendencias (`alpha_strategy`).
  - Optimización Walk-Forward (`walk_forward`).
  - Cálculo de métricas de backtesting.

## Requisitos

- Python 3.11+
- Docker Desktop (para TimescaleDB)

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

copy .env.example .env
# Edita .env si cambias usuario/password/puerto de la base de datos.

docker compose up -d
.\.venv\Scripts\python.exe -m dotenv run -- alembic upgrade head
```

## Descargar histórico OHLCV

```powershell
.\.venv\Scripts\python.exe -m trading_engine.cli `
  --exchange binance --symbol BTC/USDT --timeframe 1h `
  --since 2026-01-01 --until 2026-02-01
```

Vuelve a ejecutar el mismo comando sobre el mismo rango sin miedo: la carga es idempotente (`ON CONFLICT DO NOTHING` sobre `symbol, timeframe, timestamp`).

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

Los tests de `exchange_client` y `historical_loader` mockean ccxt y la sesión de base de datos — no requieren Docker ni red. Correr contra una base de datos real (Docker levantado + migración aplicada) es un paso manual adicional, ver `specs/001-capa-ingesta-datos/tasks.md`.
