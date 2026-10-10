# Tasks 002 — Motor de Backtesting

| # | Tarea | Archivo(s) | Estado |
|---|---|---|---|
| 1 | `BacktestEngine`: loop vela-a-vela, orquesta Alpha Engine → Risk Engine → fill simulado | `src/trading_engine/backtesting/engine.py` | verificado |
| 2 | `SimulatedBroker`: aplica comisión/slippage, mantiene equity y posiciones | `src/trading_engine/backtesting/broker_sim.py` | verificado |
| 3 | `metrics.py`: Sharpe, Sortino, max drawdown, win rate, profit factor, expectancy | `src/trading_engine/backtesting/metrics.py` | verificado |
| 4 | `walk_forward.py`: generador de particiones train/test | `src/trading_engine/backtesting/walk_forward.py` | verificado |
| 5 | Migración: tabla `backtest_runs` + `trades.run_id` + helper de persistencia | `migrations/versions/0002_backtest_runs.py`, `src/trading_engine/backtesting/persistence.py` | verificado |
| 6 | Tests: determinismo, ausencia de look-ahead, métricas contra casos con resultado conocido a mano | `tests/test_backtest_engine.py`, `tests/test_backtest_metrics.py`, `tests/test_walk_forward.py`, `tests/test_broker_sim.py` | verificado |
| 7 | Trailing stop en `SimulatedBroker` (agregado tras evidencia real, ver abajo) | `src/trading_engine/backtesting/broker_sim.py` | verificado |
| 8 | `evaluate_walk_forward`: conecta el generador de ventanas con `BacktestEngine`, métricas solo sobre la porción de test | `src/trading_engine/backtesting/walk_forward.py` | verificado |
| 9 | `AlphaEngine(enable_trend_following=False)`: variante solo-reversión para contrastar ramas en walk-forward | `src/trading_engine/alpha/strategy.py` | verificado |
| 10 | `drawdown_cooldown_days` + `SimulatedBroker.reset_drawdown_peak`: cooldown del circuit breaker de drawdown acumulado (bug crítico, ver abajo) | `src/trading_engine/backtesting/engine.py`, `broker_sim.py` | verificado |

## Verificación realizada

- `pytest` completo: **118/118 tests en verde**.
- Cooldown del circuit breaker: probado de forma aislada y determinista (`tests/test_backtest_engine.py::test_drawdown_breaker_releases_after_cooldown_and_resets_peak`, `tests/test_broker_sim.py::test_reset_drawdown_peak_*`) — se libera tras el cooldown y resetea el pico, sin tocar equity ni posiciones abiertas.
- Test de regresión de look-ahead: el fill de entrada se confirma exactamente igual a `candles[i+1].open × (1 + slippage)`, nunca a `candles[i].close`.
- Determinismo: dos corridas con los mismos datos/parámetros producen trades, curva de equity y métricas idénticas.
- Modelo de costos: probado de forma aislada y determinista sobre `SimulatedBroker` (`tests/test_broker_sim.py`) — comisión/slippage cambian el fill y el pnl de forma verificable a mano.
- Advertencia de significancia: una corrida con pocas operaciones (<100) incluye la advertencia en el reporte.
- Trailing stop: probado de forma aislada — se mueve a favor de la posición, nunca en contra (`tests/test_broker_sim.py`).
- Migración `0002` aplicada contra la base real (`alembic upgrade head`), verificada con `\d` sobre `backtest_runs` y `trades.run_id`.

## Evolución de la estrategia contra datos reales (BTC/USDT, 1h, 2024-08-12 → 2026-08-11, 17,520 velas)

Tres corridas reales, cada una motivada por evidencia de la corrida anterior — no ajustes a ciegas. Las tres persistidas en `backtest_runs` (id=1, 2, 3).

| Versión | Cambio | Operaciones | Win rate | Sharpe | Profit factor | Equity final |
|---|---|---|---|---|---|---|
| v1 — `trend_regime_v1` | Estrategia original de `docs/SDD.md` §5.1, sin filtro de tendencia ni trailing | 18 (15 SELL, 3 BUY) | 0% | -3.46 | 0.0 | $79,920 (-20.1%) |
| v2 — `trend_regime_v2_macro_filter` | + filtro de tendencia macro EMA(200) (`specs/003-alpha-engine/plan.md`) | 19 (10 BUY, 9 SELL) | 0% | -2.14 | 0.0 | $79,137 (-20.9%) |
| v3 — `trend_regime_v3_trailing_stop` | + trailing stop (este documento) | 67 | **31.3%** | **-0.36** | **0.47** | $79,571 (-20.4%) |

**Diagnóstico entre v1→v2**: 15 de 18 operaciones v1 eran SELL durante un período de tendencia alcista sostenida de BTC — la estrategia apostaba sistemáticamente en contra de la dirección de fondo. El filtro de tendencia mejoró la mezcla direccional (10 BUY/9 SELL) y el Sharpe, pero **el win rate se mantuvo en 0%** — la dirección no era la única causa raíz.

**Diagnóstico entre v2→v3**: se inspeccionaron las 19 operaciones de v2 una por una. Todas las BUY cerraban por debajo de su entrada y todas las SELL por encima — matemáticamente inevitable, porque la única forma de cerrar una posición era el stop-loss (sin take-profit, sin trailing). Caso que lo confirmó sin ambigüedad: una compra en $87,992 (2024-11-14) que llegó a **$109,588** (+24.5% no realizado) antes de caer y cerrar en pérdida en $85,348 porque el stop nunca se movió. El trailing stop ataca esto directamente: win rate subió de 0% a 31.3%, Sharpe de -2.14 a -0.36, profit factor de 0.0 a 0.47.

**Estado tras v3 en BTC, con honestidad**: sigue **sin pasar el gate de Fase 1** (`docs/SDD.md` §6) — profit factor 0.47 < 1 significa que, en conjunto, las pérdidas siguen superando a las ganancias, y el drawdown máximo (~-20.7%) no mejoró. El progreso es real (cada cambio se justificó con evidencia y cada uno movió las métricas en la dirección correcta), pero la estrategia de plantilla todavía no es viable en BTC. Las 67 operaciones ya empiezan a acercarse al umbral de 100 para significancia estadística, pero no lo alcanzan.

## v3 en ETH/USDT (mismo período, misma configuración) — resultado notablemente distinto

Corrida real sobre las 17,520 velas de `ETH/USDT` 1h, `strategy_id='trend_regime_v3_trailing_stop'`, persistida en `backtest_runs` (id=4).

| Métrica | BTC/USDT | ETH/USDT |
|---|---|---|
| Operaciones | 67 | **205** — ya supera el umbral de 100, sin advertencia de significancia |
| Win rate | 31.3% | **36.6%** |
| Sharpe | -0.36 | **-0.085** |
| Profit factor | 0.47 | **0.93** — a centésimas del punto de equilibrio |
| Expectancy | -$234/operación | **-$33.5/operación** |
| Drawdown máximo | -20.7% | -20.0% |
| Equity final | $79,571 | $81,700 |

**No es ruido en el agregado**: con 205 operaciones la misma estrategia se comporta sustancialmente mejor en ETH que en BTC en el mismo período completo. Pero el análisis por decomposición de rama (abajo) y la validación walk-forward (más abajo) matizan bastante esta lectura inicial — ver ambas secciones antes de sacar conclusiones del número agregado solo.

## Decomposición por rama: tendencial vs. reversión (sobre las corridas v3 completas)

Se separó cada operación según qué regla la disparó (cruce EMA+MACD vs. RSI+Bollinger):

| | Rama | Operaciones | Win rate | PnL total |
|---|---|---|---|---|
| BTC | Tendencial | 31 | 29.0% | -$7,299 |
| BTC | Reversión | 36 | 33.3% | -$8,404 |
| ETH | Tendencial | 122 | 36.9% | -$8,764 |
| ETH | Reversión | 83 | 36.1% | **+$1,891** |

En BTC ninguna rama funciona (pérdida similar en ambas). En ETH, la rama de reversión ya era rentable sola en el período completo, y la tendencial es la que arrastra el resultado a negativo — hipótesis que se puso a prueba con walk-forward.

## Validación walk-forward: `AlphaEngine(enable_trend_following=False)` vs. baseline, 5 ventanas de ~90 días

Se agregó una variante que desactiva la rama tendencial (tarea 9) y se corrió con `evaluate_walk_forward` (tarea 8) sobre 5 ventanas fuera de muestra independientes (`train_size=1200, test_size=2160, step=3360`), en vez de confiar en el número agregado de un solo período de 2 años.

**BTC/USDT** — PnL por ventana:

| Ventana | Baseline (ambas ramas) | Solo reversión |
|---|---|---|
| 1 | -$175 | +$229 |
| 2 | -$3,696 | +$1,851 |
| 3 | -$5,882 | -$3,771 |
| 4 | -$7,898 | -$2,886 |
| 5 | -$1,105 | -$1,603 |
| **Total** | **-$18,756** | **-$6,180** |

**ETH/USDT** — PnL por ventana:

| Ventana | Baseline (ambas ramas) | Solo reversión |
|---|---|---|
| 1 | -$3,793 | -$5,705 (7.7% acierto) |
| 2 | +$3,015 | +$4,357 |
| 3 | +$194 | +$8,412 (77.8% acierto, n=9) |
| 4 | +$2,861 | -$3,435 |
| 5 | -$8,348 | -$2,533 |
| **Total** | **-$6,071** | **+$1,095** |

### Lectura estadística — esto es lo que cambia la conclusión

- **Lo único robusto**: la rama tendencial en BTC pierde en **5 de 5 ventanas**, sin una sola excepción. Esa es una señal limpia, no ruido — desactivarla reduce la pérdida agregada de forma consistente en ambos activos (BTC: -$18,756 → -$6,180; ETH: -$6,071 → +$1,095).
- **Lo que NO es robusto**: el resultado positivo agregado de "solo reversión" en ETH (+$1,095) es la suma de una ventana muy mala (-$5,705, 7.7% de acierto) y una ventana excepcional (+$8,412, 77.8% de acierto sobre solo 9 operaciones) que casi se cancelan. Un 77.8% de acierto en 9 operaciones no es evidencia confiable — el número agregado del período completo (que mostró la reversión como "ya rentable" en ETH) escondía esta inconsistencia. Sin el walk-forward, se habría confundido esto con una ventaja real.
- **Conclusión honesta**: desactivar la rama tendencial es una simplificación bien respaldada — nunca mostró ventaja en ningún activo, en ningún tramo, bajo ninguna prueba (agregado ni por ventana). La estrategia de reversión sola **todavía no pasa una prueba de robustez** — su desempeño varía demasiado entre ventanas independientes para confiar en ella como edge real.

## Extensión a 8.6 años de histórico (2018-01-01 → 2026-08-11, 75,326 velas) y bug crítico encontrado

Tras el walk-forward con solo 2 años, se descargó histórico completo desde 2018 (ver `specs/001-capa-ingesta-datos/tasks.md`, incidencia 4) para tener ventanas más grandes. Las primeras corridas completas sobre 8.6 años (`v4_full_history_baseline`/`v4_full_history_solo_reversion`, `backtest_runs` id=5-8) dieron resultados sorprendentemente cercanos al punto de equilibrio (profit factor 0.93 en BTC solo-reversión, 0.87 en ETH) — **pero resultaron ser un espejismo**.

**Bug encontrado**: BTC dejó de operar por completo desde 2023-04-19 hasta el final del histórico (2026-08-11) — casi 3.3 años sin una sola operación. Diagnóstico (instrumentando el loop directamente): una pérdida el 2023-04-19 cruzó el circuit breaker de drawdown acumulado (-20%, `docs/SDD.md` §5.3, "hasta revisión manual"). En un backtest sin humano, esto es un candado que se cierra solo: sin operaciones nuevas la equity queda congelada, y sin que la equity cambie el drawdown nunca mejora. **El resultado "casi rentable" que vimos con 2 años de historia, y el primer resultado con 8.6 años, en realidad reflejaban solo la porción del histórico anterior al bloqueo — no el período completo.**

**Solución** (tarea nueva, ver `plan.md`): `BacktestEngine.drawdown_cooldown_days` (default 30) — tras ese período bloqueado, se resetea el pico de referencia del drawdown a la equity actual y se reanuda, simulando que un humano revisó la caída y decidió continuar con el capital que queda. Probado de forma aislada y determinista en `tests/test_broker_sim.py` y `tests/test_backtest_engine.py::test_drawdown_breaker_releases_after_cooldown_and_resets_peak`.

### Resultado definitivo, con el bug corregido (`v5_full_history_*_fixed`, `backtest_runs` id=9-12)

| | BTC baseline | BTC solo-reversión | ETH baseline | ETH solo-reversión |
|---|---|---|---|---|
| Operaciones | 767 | 403 | 784 | 371 |
| Win rate | 32.1% | 31.5% | 33.4% | 32.9% |
| Sharpe | -0.134 | -0.101 | -0.086 | -0.051 |
| Profit factor | 0.764 | 0.743 | 0.837 | **0.895** |
| Expectancy | -$64.60/op | -$93.06/op | -$45.93/op | -$41.62/op |
| Drawdown máximo | **-82.2%** | -62.5% | -63.5% | **-36.8%** |
| Equity final | $18,066 (-82%) | $37,607 (-62%) | $36,944 (-63%) | $65,659 (-34%) |

**Dos lecturas, una que se sostiene y una que se corrige**:

1. **Se sostiene**: desactivar la rama tendencial sigue siendo la decisión correcta — gana en las 4 métricas comparables, en ambos activos, ahora con muestras grandes (371-403 operaciones) y sin el sesgo del bug. Esto no cambió.
2. **Se corrige de raíz**: el "casi punto de equilibrio" (profit factor ~0.9) que parecía mostrar la corrida sin corregir **era el bug, no la estrategia**. Con el fix, **ninguna de las 4 variantes es rentable en 8.6 años** — la mejor (ETH solo-reversión) todavía pierde 34% del capital, y la peor (BTC baseline) pierde 82%.

**Matiz importante para producción** (no solo para el backtest): el circuit breaker original — bloquear al -20% "hasta revisión manual" — en los hechos **protegió capital correctamente**. Si un humano lo hubiera revisado en ese punto real (2023-04-19 en BTC), lo razonable habría sido concluir "esta estrategia no funciona, hay que detenerla", no "continuar". El `drawdown_cooldown_days` es necesario para que el *backtest* mida el verdadero comportamiento de largo plazo de una estrategia — pero no implica que producción deba reanudar sola tras un cooldown automático. En producción, el diseño original de `docs/SDD.md` §5.3 (esperar revisión humana explícita, sin reanudación automática) sigue siendo el correcto — este hallazgo es evidencia a favor de mantenerlo así, no en contra.

## Simplificaciones deliberadas de este MVP (no son bugs — ver `plan.md`)

- Un solo símbolo por corrida, una sola posición abierta a la vez.
- Sale por stop-loss con trailing (sin `take_profit` — no definido en `docs/SDD.md` §5).
- Curva de equity por operación cerrada (realizado), no mark-to-market vela a vela.
- `walk_forward.py` tiene generador de ventanas y runner (`evaluate_walk_forward`), pero sin optimizador de parámetros — Alpha Engine no expone parámetros ajustables todavía; cada ventana solo re-ejecuta la misma configuración fija, no ajusta nada en "train".
- `drawdown_cooldown_days` es una simulación para *backtesting* de la revisión manual del circuit breaker — no está pensado como comportamiento de producción (ver matiz arriba).

## `SimpleTrendAlphaEngine`: aislar el filtro de tendencia macro (nueva iteración)

El único componente que consistentemente ayudó en la plantilla original fue el filtro EMA(200) (§5.1). `src/trading_engine/alpha/simple_trend.py` aísla esa única señal: `BUY` si el precio está claramente sobre su EMA-200, `SELL` si está claramente debajo, `HOLD` en la banda intermedia — sin RSI, sin Bollinger, sin ADX.

**Primer intento fallido (sin banda)**: comparar precio vs. EMA-200 vela a vela sin histéresis generó ~2,700-4,500 operaciones en 8.6 años y destruyó 96-99.6% del capital — la dirección elegida era casi siempre correcta (profit factor cercano a 1), pero el volumen de operaciones (comisión + slippage en cada whipsaw trivial) fue lo que perdió.

**Segundo intento — `buffer_pct` fijo**: histéresis con un % fijo alrededor de la EMA. Barrido sobre BTC encontró un óptimo aparente en 8% (profit factor 1.07), pero el mismo rango de `buffer_pct` en ETH nunca superó profit factor 1.0. **Diagnóstico (evidencia externa, confirmado)**: esto era sobreajuste estadístico puro sobre la ventana de BTC — activos con volatilidad intrínseca distinta (ETH es sistemáticamente más volátil que BTC) no comparten un buffer porcentual óptimo. Un % fijo no se adapta a la volatilidad real de cada activo/período.

### Refactor: banda dinámica basada en ATR (5 restricciones)

Se reemplazó `buffer_pct` por `k × ATR(14)`: `upper = ema_trend + k·ATR`, `lower = ema_trend - k·ATR` — se ensancha sola en activos/períodos más volátiles, se angosta en los tranquilos. Cambios verificados con 135 tests (`pytest` completo en verde):

1. **ATR con suavizado de Wilder (RMA), no SMA**: `compute_atr`/`compute_indicators` fijan `mamode="rma"` explícitamente en `pandas-ta` (era ya el default real de la librería, confirmado por inspección de código fuente — se fija sin ambigüedad de todos modos). `k` expuesto como parámetro de `SimpleTrendAlphaEngine`.
2. **Motor agnóstico de timeframe**: `BacktestEngine`/`SimulatedBroker` no asumen una resolución — se probó corriendo 1H/4H/1D sin cambios de código (ver barrido abajo).
3. **Look-ahead verificado con test preciso** (`test_exit_on_opposite_signal_fills_at_next_bar_open_not_signal_bar_close`): la salida por señal opuesta llena exactamente al `open` de la vela `t+1`, nunca al `close` de `t` — antes solo se verificaba que el precio de salida fuera "razonable", no una igualdad exacta.
4. **MDD intrabar (mark-to-market)**: `SimulatedBroker.mark_to_market_equity(low, high)` valora la posición abierta al precio más adverso de cada vela (low en BUY, high en SELL) sin cerrarla ni tocar la equity real. `BacktestEngine.run` alimenta esta curva más fina (no la realizada) a `compute_metrics` — el MDD ahora refleja la excursión adversa máxima real, no solo la pérdida al cerrar. Confirmado con test que fuerza una mecha profunda que el cierre real (por stop) no alcanza a reflejar (`test_intrabar_low_captures_deeper_drawdown_than_realized_equity_alone`).
5. **`exit_on_opposite_signal` ya era secuencial y correcto**: liquidar al open de `t+1` → descontar comisión/slippage → nueva posición dimensionada solo sobre el capital resultante — verificado, no requirió cambios.

Adicional (no pedido explícitamente, detectado durante el refactor): `ALPHA_LOOKBACK_WINDOW`/warm-up eran una sola constante de clase (`1200`/`MIN_CANDLES_FOR_INDICATORS=214`) pensada para el stack de indicadores completo (con ADX). Ahora son configurables por instancia (`warmup_candles`, `alpha_lookback_window`) — los defaults no cambian para `AlphaEngine`, pero `SimpleTrendAlphaEngine` puede usar `MIN_CANDLES_FOR_TREND_ONLY` (200, sin el margen de ADX que no necesita).

### Barrido de `k` (1.5–3.0, paso 0.25) sobre BTC/USDT y ETH/USDT, 2018-01-01 → 2026-08-11

Histórico descargado sin huecos en 1H (ya existente, 75,326 velas), 4H (18,854 velas) y 1D (3,145 velas) para ambos símbolos. `exit_on_opposite_signal=True`, `allow_short=False`, `RiskConfig()` default.

| Timeframe | BTC profit factor | ETH profit factor | BTC drawdown | ETH drawdown | BTC Sharpe | ETH Sharpe |
|---|---|---|---|---|---|---|
| 1H | 0.97–1.01 | 0.95–1.00 | -83% a -91% | -77% a -88% | negativo | negativo |
| 4H | 1.18–1.28 | 1.22–1.29 | -14% a -21% | -15% a -20% | 0.04–0.08 | 0.09–0.11 |
| 1D | 1.47–1.58 | 1.53–1.96 | -6% a -9% | -6% a -11% | 0.14–0.16 | 0.16–0.24 |

(Detalle completo de las 42 corridas — 2 símbolos × 3 timeframes × 7 valores de `k` — en [`evidence/sweep_k_2018_2026.log`](evidence/sweep_k_2018_2026.log).)

**Lectura**:
- **1H sigue sin edge** en todo el rango de `k`, en ambos activos — el ruido de esa resolución no se resuelve ensanchando la banda, es un problema de la resolución misma.
- **4H y 1D son rentables en los 7 valores de `k` probados, en ambos activos** — esta vez el parámetro **sí generaliza entre BTC y ETH**, a diferencia del `buffer_pct` fijo. Es la evidencia de robustez que faltaba: no es un pico aislado de un solo valor de `k` en un solo activo.
- **1D es el mejor timeframe**: profit factor y Sharpe más altos, drawdown más bajo, en ambos activos. ETH en 1D incluso supera a BTC (profit factor hasta 1.96 con k=3.0) — un giro completo respecto al hallazgo original de la plantilla, donde ETH nunca era rentable.
- **Aviso de significancia**: en ETH 1D las operaciones van de 77 a 102 según `k` — al límite o por debajo del umbral de 100 (`docs/SDD.md` §5.4). Estos números son prometedores pero no concluyentes por tamaño de muestra pequeño.
- **Pendiente antes de considerar esto validado**: walk-forward (no solo un backtest agregado sobre todo el período — la lección de la sección anterior de este documento aplica igual de fuerte aquí) y verificar que el resultado no dependa de un solo período de mercado dominante (ej. 2020-2021 alcista). Sin eso, esto es evidencia prometedora, no una estrategia lista para las siguientes fases del roadmap (`docs/SDD.md` §6).

## Walk-forward de `SimpleTrendAlphaEngine` en 4H/1D — corrige la conclusión del barrido agregado

Se descartó 1H por completo (sin edge en ningún `k` probado, ver arriba). Para 4H y 1D, en vez de seguir ajustando `k` sobre el agregado de 8.6 años, se corrió walk-forward real: ventanas de test **no solapadas** cubriendo todo el histórico (`generate_walk_forward_windows`/`evaluate_walk_forward`, ya existentes de la spec original), con dos valores de `k` representativos (2.0 y 3.0 — deliberadamente no el "mejor" del barrido agregado, para no sesgar la validación hacia el punto que ya se veía bien in-sample).

- **4H**: `train_size=1200, test_size=1500` (velas) → 11 ventanas de test por símbolo, sin solape, ~2018-07 a ~2026-01.
- **1D**: `train_size=400, test_size=300` → 9 ventanas. Nota honesta: 400 velas de historia previa no alcanza la convergencia asintótica de EMA-200 recomendada (~1000-1200, ver comentario en `engine.py`) — es un compromiso forzado por el tamaño del dataset (solo 3,145 velas diarias en 8.6 años). Los resultados de 1D deben leerse con ese matiz.

Detalle completo (11+9 ventanas × 2 símbolos × 2 valores de `k`) en [`evidence/walk_forward_simple_trend_4h_1d.log`](evidence/walk_forward_simple_trend_4h_1d.log).

### 4H se sostiene fuera de muestra

| | BTC k=2.0 | BTC k=3.0 | ETH k=2.0 | ETH k=3.0 |
|---|---|---|---|---|
| Ventanas rentables | 8/11 | 8/11 | 9/11 | 9/11 |
| PnL total (test) | +$54,255 | +$69,289 | +$72,680 | +$68,925 |

Las ventanas perdedoras se concentran de forma reconocible en 2018 (cola bajista) y 2021-12→2022-08 (crash de 2022) — el perfil de riesgo esperable de una estrategia tendencial (pierde en reversiones/crashes, gana en tendencias sostenidas), no una dispersión aleatoria. Las ganancias más grandes caen en las ventanas de 2019-2021 (el bull run), pero **sin que una sola ventana concentre la mayoría del resultado** — en ningún caso una ventana supera ~34% del PnL total.

### 1D no se sostiene igual — el "mejor timeframe" del agregado era, en gran parte, una sola ventana

| | BTC k=2.0 | BTC k=3.0 | ETH k=2.0 | ETH k=3.0 |
|---|---|---|---|---|
| Ventanas rentables | 6/9 | 5/9 | 5/9 | 5/9 |
| PnL total (test) | +$15,255 | +$16,983 | +$18,891 | +$24,529 |
| % del PnL total en la ventana más grande | 67% (win 3) | **88% (win 3)** | 52% (win 3) | 60% (win 3) |

En los 4 casos, la ventana 3 (2020-09 → 2021-07/08, el bull run post-COVID) concentra entre poco más de la mitad y casi el 90% del PnL total. En BTC k=3.0, sin esa única ventana el resto del período (8 de 9 ventanas) apenas deja +$2,095 — prácticamente plano. Varias ventanas además tienen tan pocas operaciones (0-4) que su profit factor individual no es informativo (ej. ETH k=3.0 ventana 5: 0 operaciones).

**Esto es el mismo patrón que ya se documentó arriba con la reversión pura en ETH** (agregado positivo sostenido por una ventana excepcional que casi se cancela con una mala) — la lección de esa sección se repite aquí: un número agregado sobre todo el período puede esconder que el "edge" es 1-2 ventanas, no un comportamiento repetible.

### Conclusión, con la corrección explícita

El barrido de `k` sobre el agregado completo (sección anterior) reportó **1D como el mejor timeframe** (profit factor 1.47-1.96). El walk-forward **no confirma esa conclusión**: 4H tiene evidencia bastante más sólida (8-9 de 11 ventanas independientes rentables, sin concentración en una sola) que 1D (5-6 de 9 ventanas, resultado dominado por una ventana). **Se corrige la recomendación: 4H es el timeframe con mejor evidencia hasta ahora, no 1D.** 1D no se descarta —sigue siendo direccionalmente positivo, y el matiz de warm-up corto puede estar penalizándolo— pero no debe tratarse como validado sin una ventana de entrenamiento más larga (lo que requeriría más historia de la disponible, o aceptar menos ventanas de test).

## Sesgo direccional y sensibilidad a costos en 4H (BTC/ETH, k=2.0 y k=3.0)

Con 4H ya validado como el timeframe más creíble (walk-forward, arriba), se corrieron dos análisis adicionales sobre la variante `allow_short=False` que ya se usó en ese walk-forward — para saber si su buen resultado depende de supuestos frágiles. Detalle completo en [`evidence/4h_direction_and_cost_sensitivity.log`](evidence/4h_direction_and_cost_sensitivity.log).

### `allow_short`: el resultado es asimétrico entre activos, no un sesgo oculto uniforme

| | BTC k=2.0 | BTC k=3.0 | ETH k=2.0 | ETH k=3.0 |
|---|---|---|---|---|
| Equity final, solo largo | $130,233 | $152,110 | $158,670 | $158,166 |
| Equity final, largo+corto | $99,463 | $122,439 | $199,001 | $183,454 |
| PnL de las SELL (solo en la variante largo+corto) | **-$2,787** | **-$18,499** | +$29,241 | +$23,897 |
| Max drawdown, largo+corto | -32.3% | -31.7% | -28.8% | -27.7% |

En **BTC, permitir cortos activamente resta** — las operaciones SELL pierden dinero en neto, el profit factor baja, el drawdown casi se duplica, y con k=2.0 la equity con cortos habilitados queda por debajo del capital inicial. En **ETH pasa lo contrario** — las SELL ganan y la equity final con cortos es mayor que solo-largo, pero a costa de mucho más drawdown y menor Sharpe (peor perfil riesgo/retorno, no un error).

**Por qué esto importa más allá del número**: confirma que el edge no es simplemente "estar largo en un mercado que subió" — si lo fuera, los cortos en ambos activos deberían restar por igual (perder la subida no explica por qué las SELL de BTC pierden dinero en absoluto, no solo en relativo). El patrón real es que el filtro EMA-200+ATR tiene una lectura de tendencia más confiable en el lado largo para BTC específicamente. La elección `allow_short=False` usada en el walk-forward queda justificada para BTC por evidencia directa, y para ETH es una decisión de apetito de riesgo (más conservadora, no una corrección de sesgo).

### Desglose por año: el patrón de ganar/perder por régimen se confirma, con una nota sobre 2025-2026

| Año | BTC k=2.0 | BTC k=3.0 | ETH k=2.0 | ETH k=3.0 |
|---|---|---|---|---|
| 2018 | -$4,091 | -$615 | -$132 | +$2,260 |
| 2019 | +$16,180 | +$24,545 | +$1,150 | +$16,531 |
| 2020 | +$31,427 | +$36,934 | +$42,888 | +$39,997 |
| 2021 | **-$6,805** | **-$7,103** | +$20,200 | +$18,359 |
| 2022 | -$10,596 | -$8,605 | +$8,376 | -$2,891 |
| 2023 | +$30,373 | +$36,907 | +$1,176 | -$717 |
| 2024 | +$11,490 | +$11,151 | -$957 | +$2,366 |
| 2025 | -$2,723 | -$4,834 | +$14,640 | +$14,556 |
| 2026 (parcial, ene-ago) | -$9,872 | -$11,622 | -$8,020 | -$13,855 |

BTC pierde en 4 de 9 años del calendario (2018, 2021 —pese a ser recordado como año alcista, tuvo dos crashes intermedios que generaron whipsaw—, 2022, 2025) más el tramo parcial de 2026. ETH es más consistente (solo 2018, 2024 y el tramo de 2026 en rojo). El tramo de 2026 es el más reciente de todo el histórico y cierra en pérdida para ambos activos — vale monitorearlo, no es solo un dato histórico lejano.

### Sensibilidad a costos de transacción: la fragilidad más seria encontrada hasta ahora

Se dobló comisión (0.1%→0.2%) y slippage (0.05%→0.1%) — no un escenario exótico, es lo esperable con peor slippage en momentos de volatilidad o con tamaños de posición que generan impacto de mercado.

| | BTC k=2.0 | BTC k=3.0 | ETH k=2.0 | ETH k=3.0 |
|---|---|---|---|---|
| Retorno con costos base | +30.2% | +52.1% | +58.7% | +58.2% |
| Retorno con costos 2x | **-17.3%** | **-10.8%** | +8.8% | +19.7% |

**En BTC, duplicar los costos revierte la ganancia en pérdida en los dos valores de `k` probados.** ETH aguanta (sigue positivo) pero el retorno se reduce 70-85%. Esta es la fragilidad más seria encontrada en esta iteración: el margen de la estrategia sobre BTC es delgado, no robusto a un supuesto de fricción apenas más realista que el usado por defecto.

## Tres investigaciones de seguimiento: causa raíz del margen delgado en BTC, punto de quiebre de costos, y un tercer activo (SOL)

### 1. Por qué el margen es tan delgado en BTC específicamente — causa mecánica, no de señal

Hipótesis: el position sizing por volatilidad (`riesgo% / (ATR × multiplicador_stop)`, §5.2) asigna **más nocional en dólares por operación cuando la volatilidad relativa del activo (ATR como % del precio) es más baja**, para el mismo 1% de riesgo. Si BTC tiene ATR% sistemáticamente menor que ETH/SOL, cada operación mueve más dólares — y comisión/slippage, que son % del nocional, le pegan proporcionalmente más fuerte. Se verificó calculando ATR% promedio, nocional promedio por operación y fricción total (comisión+slippage estimada, exacta a partir de `entry_price`/`exit_price`/`size` de cada `BacktestTrade`) contra la ganancia bruta, para BTC/ETH 4h, k=2.0 y k=3.0. Detalle en [`evidence/btc_eth_margin_cost_curve.log`](evidence/btc_eth_margin_cost_curve.log).

| | BTC | ETH |
|---|---|---|
| ATR% promedio (ATR/close) | **1.87%** | 2.47% |
| Nocional promedio por operación (ida+vuelta) | **$85,975-$101,223** | $73,020-$77,516 |
| Fricción estimada / ganancia bruta | **20.9-21.3%** | 16.1% |

**Confirmado**: BTC tiene la volatilidad relativa más baja de los dos, el nocional por operación más alto, y la fricción se lleva una porción mayor de la ganancia bruta — la cadena causal se sostiene con los números. **No es que BTC tenga peor señal direccional** (el profit factor bruto de las operaciones es similar o mejor que ETH, ver barrido de `k`) — es que el mismo % de riesgo termina moviendo más dólares por operación cuando el activo es relativamente menos volátil, y eso encarece proporcionalmente el costo fijo por operación.

**Implicación práctica (no implementada, fuera del alcance de esta investigación)**: esto sugiere que ajustar el sizing —ej. un piso al ATR% usado para dimensionar, o escalar `risk_per_trade_pct` según volatilidad relativa del activo— podría mejorar la robustez a costos en BTC sin tocar la lógica de entrada/salida. Quedaría como propuesta de diseño para Risk Engine, no como cambio ya hecho.

### 2. Curva de sensibilidad a costos: punto de quiebre por activo

Se corrió la sensibilidad no solo en 1.0x/2.0x sino en pasos de 0.25x (1.0x a 2.0x), para BTC/ETH/SOL 4h, k=2.0 y k=3.0. Detalle en los mismos logs de evidencia.

| Activo | k=2.0 quiebre aprox. | k=3.0 quiebre aprox. |
|---|---|---|
| BTC | **~1.40x** | ~1.83x |
| ETH | >2.15x (extrapolado) | claramente >2.0x |
| SOL | ~2.39x (extrapolado) | ~2.26x (extrapolado) |

BTC es, con diferencia, el más frágil a un supuesto de costos más realista — confirma el hallazgo anterior desde otro ángulo. ETH y SOL tienen un colchón considerablemente mayor antes de que la ganancia se revierta.

### 3. Tercer activo — SOL/USDT 4h (2020-08 → 2026-08, 13,151 velas, sin huecos)

Detalle completo (barrido de `k`, walk-forward de 7 ventanas, sesgo direccional, costos) en [`evidence/sol_third_asset_analysis.log`](evidence/sol_third_asset_analysis.log). ATR% promedio 3.49% — la volatilidad relativa más alta de los tres activos probados, consistente con la sección 1.

**Refuerza la generalización**: profit factor 1.18-1.24 en todo el rango de `k` — el mismo rango que BTC (1.18-1.28) y ETH (1.22-1.29). Es la evidencia más resistente a costos de los tres activos (nunca se revierte, incluso a 2x costos, en ninguno de los dos valores de `k` probados) — consistente con tener el ATR% más alto.

**Pero con matices que no se pueden ignorar**:
- **Walk-forward más débil**: solo 4 de 7 ventanas rentables (57%, vs. 73-82% en BTC/ETH). PnL total (`k=2.0`: +$39,851; `k=3.0`: +$26,555) concentrado en gran parte en la ventana 1 (2021-02 a 2021-11 — el rally parabólico de SOL tras su listado) — 52-65% del total en una sola ventana. Es el mismo patrón de concentración que ya penalizó a 1D, aunque menos extremo.
- **Sesgo direccional, un tercer patrón**: las SELL en SOL son casi neutras (+$3,750 con k=2.0, -$603 con k=3.0) — ni claramente dañinas (BTC) ni claramente rentables (ETH). Refuerza que `allow_short=False` es una elección conservadora razonable en los tres activos, nunca claramente la equivocada.
- **La más importante: las ventanas más recientes son planas o negativas en los TRES activos**. SOL: ventana 6 (2024-07→2025-04) -$309, ventana 7 (2025-04→2025-12) apenas +$265 con k=2.0, y negativas con k=3.0. Esto coincide con BTC/ETH, donde 2025 y el tramo de 2026 también fueron flojos o negativos (ver desglose por año arriba). **En los tres activos probados, el período más reciente (~últimos 12-18 meses) es donde el edge se ve más débil o ausente** — es la parte más relevante para decidir si operar esto hoy, no solo un dato histórico.

## ¿La debilidad reciente es cambio de régimen o varianza normal? — investigación con datos, no narrativa

Se probaron dos hipótesis con datos reales (no con la narrativa genérica de "el mercado cambió"), para BTC/ETH/SOL 4h: (a) ¿bajó la fuerza de tendencia (ADX)?, (b) ¿bajó la volatilidad relativa (ATR%)? Y se calculó el z-score de las ventanas walk-forward más recientes contra la distribución completa de todas las ventanas, para saber si son estadísticamente atípicas o están dentro de la variación normal ya observada en todo el período. Detalle completo (ADX/ATR% año por año, estadísticas de operaciones, z-scores) en [`evidence/recent_weakness_investigation.log`](evidence/recent_weakness_investigation.log).

### ADX (fuerza de tendencia): estable, sin declive — se descarta esta hipótesis

ADX promedio por año se mantiene en el rango 25-30 en los tres activos, en los 6-9 años de historia disponible, **sin tendencia a la baja reciente** (BTC 2025=26.2, 2026=28.4; ETH 2025=27.6, 2026=26.9; SOL 2025=26.6, 2026=28.5 — todos dentro del rango histórico normal). El mercado no se volvió más lateral/menos tendencial recientemente — la lógica de entrada de `SimpleTrendAlphaEngine` (que depende de que haya tendencia) sigue teniendo el mismo terreno que antes.

### ATR% (volatilidad relativa): declive real y medible desde 2023 en los tres activos

| Año | BTC ATR% | ETH ATR% | SOL ATR% |
|---|---|---|---|
| Promedio 2018-2022 (o desde inicio de datos) | ~2.2% | ~2.9% | ~5.6% (2020-2022) |
| 2023 | 1.23% | 1.37% | 2.94% |
| 2024 | 1.59% | 1.94% | 2.89% |
| 2025 | 1.29% | 2.22% | 2.63% |
| 2026 (parcial) | 1.34% | 1.81% | 1.99% |

**Este sí es un cambio real y medible**, no ruido — los tres activos muestran volatilidad relativa estructuralmente más baja desde 2023 que en años anteriores (SOL de forma monótona: 5.67% en 2020 hasta 1.99% en 2026). Consistente con una narrativa de "maduración" del mercado cripto (más capitalización, más participación institucional), aunque esta investigación no depende de esa narrativa — se apoya en el ATR% medido, no en una historia externa.

### La conexión con el hallazgo de la sección 1: es la MISMA causa raíz, no un problema nuevo

Ya se había establecido que un ATR% más bajo implica más nocional por operación (sizing por volatilidad) y por lo tanto más fricción de costos por dólar de ganancia. La caída de ATR% desde 2023 **intensifica exactamente ese mismo mecanismo** en el período más reciente — no es una tendencia nueva y distinta, es el problema de la sección 1 volviéndose más severo porque su causa (volatilidad relativa baja) también empeoró recientemente.

### Z-scores: las ventanas recientes NO son estadísticamente atípicas

| | Ventana más reciente | z-score | ¿Atípica? |
|---|---|---|---|
| BTC | 2025-05 → 2026-01 | **-1.61** | Marginal, dentro de lo normal para 11 muestras |
| ETH | 2025-05 → 2026-01 | -0.29 | No, normal |
| SOL | 2025-04 → 2025-12 | -0.65 | No, normal |

Ninguna ventana reciente supera ±2 desviaciones estándar de la distribución completa de ventanas walk-forward de su propio activo — la variación ya existía a lo largo de todo el período (2018 y 2022 también tuvieron ventanas muy negativas, con z-scores similares o peores). **La debilidad reciente no es estadísticamente distinguible de la varianza normal de este backtest.**

### Conclusión de esta investigación

No hay evidencia de que el mercado se haya vuelto "menos operable" para esta estrategia (ADX estable). Sí hay evidencia real de que la volatilidad relativa bajó desde 2023, y eso **intensifica un problema ya identificado y entendido** (sizing por volatilidad + bajo ATR% = más fricción de costos), no revela uno nuevo. Estadísticamente, ninguna ventana reciente es un caso atípico — es ruido normal de una serie con pocas muestras, agravado por una tendencia real (la caída de ATR%) que ya tiene explicación mecánica. **Esto refuerza, no cambia, la recomendación de la sección 1**: el ajuste de sizing (piso al ATR% usado, o escalar `risk_per_trade_pct` por volatilidad relativa) es la intervención con mayor probabilidad de mejorar la robustez de la estrategia — antes que buscar una señal de entrada distinta.

## Techo de nocional implementado (`max_notional_pct`) — resultado honesto: ayuda a ETH, no resuelve BTC

Se implementó la intervención sugerida en la sección anterior: `RiskConfig.max_notional_pct` (`None` = sin techo, comportamiento previo intacto) limita el nocional de cada operación a una fracción fija del capital, sin importar qué tan bajo sea el ATR% del activo. `RiskEngine.evaluate` aplica el techo vía `apply_notional_cap` (`src/trading_engine/risk/sizing.py`) y expone `RiskDecision.capped`. Para trazabilidad (evitar el "risk undershoot" silencioso — un trade capado con menos riesgo real del nominal no debe leerse como pérdida de edge), `BacktestTrade` ahora guarda `risk_pct` y `capped` por operación (`src/trading_engine/backtesting/broker_sim.py`). 8 tests nuevos, 143/143 en verde (`tests/test_risk_engine.py`, `tests/test_broker_sim.py`, `tests/test_backtest_engine.py`).

Se probó con `max_notional_pct` en `{0.35, 0.25, 0.15}` contra el baseline sin techo, para BTC/ETH 4h, k=2.0 y k=3.0. Detalle completo en [`evidence/notional_cap_sweep.log`](evidence/notional_cap_sweep.log) y [`evidence/notional_cap_cost_breakeven.log`](evidence/notional_cap_cost_breakeven.log).

### Pregunta 1 (la literal): ¿bajó la fricción del 21% en BTC sin destruir el profit factor? — Sí

| | BTC k=2.0 sin techo | BTC k=2.0 cap=0.15 | ETH k=2.0 sin techo | ETH k=2.0 cap=0.15 |
|---|---|---|---|---|
| Fricción/ganancia bruta | 21.3% | **18.6%** | 16.1% | **14.5%** |
| Profit factor | 1.18 | 1.15 (-2.5% relativo) | 1.26 | **1.28** (mejora) |
| Operaciones capadas | 0 | 550 de 586 | 0 | 491 de 567 |

La fricción baja de forma monótona con el techo más estricto, en ambos activos, y el profit factor no se destruye — en BTC cae marginalmente, en ETH mejora. Confirmado también matemáticamente: el Sharpe (calculado sobre retorno % por operación, no en dólares) queda **exactamente igual** en todos los niveles de techo — capar el tamaño escala el pnl de cada operación capada proporcionalmente, sin cambiar su retorno relativo. La equity final en dólares sí baja con el techo (menos capital desplegado = menos ganancia absoluta) — es el costo esperado de operar más chico, no un defecto.

### Pregunta 2 (la que realmente importa): ¿mejoró la robustez real a costos? — No en BTC, sí en ETH

Se repitió la curva de sensibilidad a costos (1.0x-2.0x) con el techo activado, para ver si el punto de quiebre de BTC (~1.4x-1.8x sin techo) se corrió hacia arriba:

| | BTC k=2.0 | BTC k=3.0 | ETH k=2.0 | ETH k=3.0 |
|---|---|---|---|---|
| Quiebre sin techo | ~1.40x | ~1.83x | >2.15x | nunca en el rango probado |
| Quiebre con cap=0.25 | ~1.44x (≈igual) | ~1.82x (≈igual) | >3x (mejora clara) | mejora el margen en todos los niveles |
| Quiebre con cap=0.15 | **~1.38x (peor)** | ~1.82x (≈igual) | ~2.4x (mejora) | mejora el margen en todos los niveles |

**En BTC, el techo de nocional no mueve el punto de quiebre de forma significativa** — con el cap más agresivo (0.15) incluso es marginalmente peor. La explicación: la reducción de fricción se cancela casi exactamente con la caída de profit factor base, dejando la robustez real a costos prácticamente sin cambio. **En ETH sí es una mejora real y consistente** en todos los niveles de techo probados — mejora tanto el profit factor base como el margen frente a costos más altos.

### Conclusión honesta: la hipótesis de causa raíz era parcialmente correcta, pero el remedio no es suficiente para BTC

El diagnóstico (ATR% bajo → más nocional → más fricción) sigue siendo matemáticamente correcto y se confirmó otra vez (la fricción sí bajó como predijo la fórmula). Pero **arreglar el síntoma (nocional excesivo) no arregla el resultado (robustez a costos) en BTC específicamente** — sugiere que hay algo más en la composición de las operaciones de BTC (quizás qué operaciones específicas se capan, o una diferencia más profunda en la calidad de la señal en el régimen de baja volatilidad de BTC) que este ajuste puntual no captura. No se descarta seguir iterando sobre el sizing, pero **no hay que seguir invirtiendo en esta dirección específica para BTC sin una hipótesis nueva** — la que teníamos ya se probó con evidencia y el resultado es negativo para ese activo, aunque positivo para ETH.

## Cuarto activo — BNB/USDT 4h (2018-2026, 18,854 velas, sin huecos): resultado desfavorable

Se corrió la misma batería completa (barrido de `k`, walk-forward de 11 ventanas, sesgo direccional, sensibilidad a costos, desglose por año) que a BTC/ETH/SOL. Detalle en [`evidence/bnb_fourth_asset_analysis.log`](evidence/bnb_fourth_asset_analysis.log). ATR% promedio 2.43% — similar al de ETH (2.47%), así que la hipótesis de "ATR% bajo = frágil" **no explica** lo que se encontró acá; BNB tiene volatilidad relativa parecida a ETH pero un resultado mucho peor.

| | BTC | ETH | SOL | **BNB** |
|---|---|---|---|---|
| Profit factor (agregado) | 1.18-1.28 | 1.22-1.29 | 1.18-1.24 | **1.06-1.14** (el más bajo) |
| Max drawdown | -14% a -21% | -15% a -20% | -12% a -20% | **-22% a -32%** (el peor) |
| Ventanas walk-forward rentables | 8/11 (73%) | 9/11 (82%) | 4/7 (57%) | 7/11 (64%) |
| Quiebre de costos (k=3.0) | ~1.83x | nunca en el rango | ~2.26x | **~1.05x** (se rompe casi de inmediato) |

**BNB es, con diferencia, el más frágil a costos de los cuatro** — con k=3.0 el retorno base ya es casi nulo (+0.3%) y se revierte en pérdida con solo 1.25x costos, peor que BTC. Esto contradice la hipótesis de causa raíz de la sección anterior (ATR% bajo → fragilidad): el ATR% de BNB es similar al de ETH, así que la explicación mecánica de sizing no es lo que está pasando acá — hay algo distinto en la calidad de la señal específica de BNB, no en su volatilidad relativa.

**2024 es un año de pérdida severa y aislada**: -$16,157 con win_rate de solo 26.9% (el más bajo de cualquier año en cualquier activo probado), coincidiendo con la ventana 10 del walk-forward (pf=0.29-0.33, la peor ventana de las 44 corridas en los 4 activos). 3 de 9 años del calendario en rojo (2018, 2024, 2026-parcial).

**Conclusión**: BNB no confirma el patrón favorable de ETH/SOL — es una pieza de evidencia genuinamente negativa, no una simple "confirmación débil". No se recomienda incluirlo en la variante que se lleve adelante.

## Siguiente acción concreta

La plantilla original de `docs/SDD.md` §5.1 (EMA/RSI/Bollinger/ADX con este stop/trailing) queda descartada — no tiene edge, pierde dinero de forma sostenida y consistente entre activos (profit factor 0.74-0.90). No se recomienda seguir ajustando parámetros sobre esa base.

`SimpleTrendAlphaEngine` con banda ATR dinámica en **4H, largo únicamente**, sigue siendo la variante más creíble encontrada — generaliza a un tercer activo (SOL), y el techo de nocional mejora tanto el profit factor como la robustez a costos en ETH. **Pero BTC sigue siendo frágil a costos incluso después de este ajuste** — la causa raíz identificada (sizing por volatilidad + ATR% bajo) explica la fricción observada, pero corregirla no fue suficiente para mover el punto de quiebre real. Esto sigue sin pasar el gate de Fase 1 (`docs/SDD.md` §6). Antes de seguir: (a) si se va a producción con esta estrategia, considerar aplicarla solo a ETH/SOL (donde la evidencia es más sólida en todos los frentes) y dejar BTC fuera o con capital reducido hasta encontrar una explicación mejor de su fragilidad; (b) costos calibrados al exchange/cuenta real específicos, no un supuesto genérico; (c) si se quiere insistir con BTC, la siguiente hipótesis debería salir de examinar qué distingue a las operaciones de BTC que sí funcionan de las que no, no de otro ajuste de sizing genérico. 1D queda como línea secundaria, pendiente de una ventana de entrenamiento más larga que el dataset actual no permite sin sacrificar cobertura de test.
