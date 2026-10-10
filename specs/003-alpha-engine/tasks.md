# Tasks 003 — Alpha Engine

| # | Tarea | Archivo(s) | Estado |
|---|---|---|---|
| 1 | Modelo `Signal` (Pydantic) — mover el contrato de `docs/SDD.md` §4.3 a código | `src/trading_engine/models/signal.py` | verificado |
| 2 | `indicators.py`: wrappers de `pandas-ta` (EMA20/50, ADX14, RSI14, Bollinger, MACD) | `src/trading_engine/alpha/indicators.py` | verificado |
| 3 | `AlphaEngine.evaluate`: filtro de régimen + lógica tendencial/reversión de `docs/SDD.md` §5.1 | `src/trading_engine/alpha/strategy.py` | verificado |
| 4 | Tests con datos sintéticos de tendencia clara y de mercado lateral | `tests/test_alpha_strategy.py` | verificado |
| 5 | Test de contrato: `Signal` no expone tamaño/stop-loss/take-profit | `tests/test_signal_contract.py` | verificado |
| 6 | Filtro de tendencia macro `EMA(200)` (agregado tras evidencia real de backtest) | `src/trading_engine/alpha/indicators.py`, `strategy.py` | verificado |

## Verificación realizada

- `pytest` completo (proyecto): **107/107 tests en verde**; de esta spec, 19 tests en `tests/test_alpha_strategy.py`.
- Cobertura de tests en dos niveles, a propósito:
  - **Unitarios puros** sobre `AlphaEngine._trend_signal` y `AlphaEngine._mean_reversion_signal` (staticmethods, reciben floats) — cubren las 7 combinaciones de la tabla de decisión de `docs/SDD.md` §5.1 sin depender de la numérica de `pandas-ta`.
  - **Integración de punta a punta con `pandas-ta` real** (sin mocks) sobre tres escenarios sintéticos verificados manualmente antes de fijar el corte exacto de velas:
    - Tramo plano → tendencia alcista: `AlphaEngine().evaluate` pasa de `HOLD` a `BUY` (confianza 1.0) exactamente en la vela donde `EMA(20)` cruza sobre `EMA(50)` con `ADX` alto y `MACD` positivo.
    - Mercado lateral con una vela de caída brusca aislada: `ADX` se mantiene bajo (régimen de reversión), `RSI` cae a zona de sobreventa y el precio toca la banda inferior de Bollinger → `BUY` confianza 1.0.
    - Simétrico al alza → `SELL` confianza 1.0.
  - Test explícito de determinismo (mismo input → misma salida) y de que datos insuficientes (`< MIN_CANDLES_FOR_INDICATORS`) devuelven `HOLD` explícito, nunca una excepción.

## Notas técnicas descubiertas al implementar

- El paquete `pandas-ta` instalado es la versión `0.4.71b0` (un fork activamente mantenido), no la `0.3.14b0` original de `twopirllc` — esa versión antigua está rota con NumPy ≥1.24 (`from numpy import NaN`, eliminado). Se verificó explícitamente que la versión instalada funciona con `numpy` 2.x y `pandas` 3.x antes de construir sobre ella.
- Un `ADX(14)` alto no es exclusivo de tendencias sostenidas: un movimiento brusco de 2-3 velas también lo eleva temporalmente. El diseño de los tests de mercado lateral tuvo que tenerlo en cuenta (una sola vela de spike y recuperación inmediata, en vez de una caída sostenida de varias velas) para mantener `ADX` por debajo del umbral de régimen.
- Advertencia de deprecación de `pandas-ta` sobre `mode.copy_on_write` con `pandas` 3.x — inofensiva (no afecta resultados), pendiente de que la librería la resuelva río arriba.

## Filtro de tendencia macro (agregado después del cierre inicial de esta spec)

Al correr el Motor de Backtesting (spec 002) contra 2 años reales de BTC/USDT, la estrategia original perdía las 18 operaciones del período — 15 de 18 eran `SELL` durante una tendencia alcista sostenida. Se agregó `EMA(200)` como filtro: solo se permite `BUY` si `close > ema_trend`, solo `SELL` si `close < ema_trend`, aplicado como último paso tras las ramas tendencial/reversión (`AlphaEngine._align_with_macro_trend`). Detalle completo de la evidencia y la métrica antes/después en `specs/002-motor-backtesting/tasks.md`.

Efecto secundario: `MIN_CANDLES_FOR_INDICATORS` subió de 64 a 214 velas (por el warm-up de `EMA(200)`), y los fixtures de test que dependían de historiales cortos se reconstruyeron con warm-up suficiente y verificación empírica de los valores de ADX/RSI/Bollinger/EMA-200 antes de fijar los parámetros exactos.

## Siguiente acción concreta

Spec 003 sigue funcionalmente cerrada. El filtro de tendencia mejoró el Sharpe pero no fue suficiente por sí solo para que la estrategia sea viable — el resto del diagnóstico (win rate 0% incluso con dirección correcta) resultó ser un problema del mecanismo de salida, no de esta spec — ver spec 002.
