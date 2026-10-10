# Plan 004 — Risk Engine

## Decisiones técnicas

| Decisión | Elección | Alternativa descartada | Por qué |
|---|---|---|---|
| Configuración de límites | `RiskConfig` (Pydantic), un único objeto con todos los umbrales | Constantes sueltas en el código | Los valores de `docs/SDD.md` §5.3 son supuestos de negocio, no detalles de implementación — deben poder ajustarse (y auditarse) sin tocar lógica. |
| Fórmula de sizing | Volatility targeting (`docs/SDD.md` §5.2) | Kelly puro | Ya justificado en `docs/SDD.md` §5.2: Kelly puro sobreapalanca ante error de estimación de probabilidad/payoff. |
| Posiciones abiertas como input explícito (`OpenPosition`) | `OpenPosition{symbol, direction, risk_pct}` — `risk_pct` ya calculado al abrir la posición, no recalculado por Risk Engine | `RiskEngine` recalculando el riesgo de posiciones viejas a partir de precios históricos | Decisión no prevista en el plan original, tomada al implementar: mantiene `RiskEngine.evaluate` como función pura (sin acceso a histórico de precios) — coherente con el alcance de `spec.md` ("no incluye la fuente de datos de correlación en sí"). |
| Correlación como input explícito (`correlations: dict[symbol, float]`) | El llamador entrega la correlación ya calculada entre `signal.symbol` y cada símbolo con posición abierta | `RiskEngine` calculando correlación internamente | Mismo motivo: `RiskEngine` no tiene ni debe tener acceso a series de precios históricas — eso es responsabilidad de la Capa de Ingesta / Motor de Backtesting. |
| `take_profit` en `RiskDecision` | Se deja `None` — no hay fórmula de take-profit definida en `docs/SDD.md` §5 | Inventar un ratio riesgo/beneficio (ej. 2:1) no solicitado | No hay una decisión de negocio tomada al respecto; inventar una habría sido diseño no pedido. Queda como campo opcional del contrato hasta que se defina explícitamente. |

## Contrato de configuración

```python
class RiskConfig(BaseModel):
    risk_per_trade_pct: float = 0.01          # 1% del capital por operación
    stop_atr_multiplier: float = 2.0
    max_portfolio_heat_pct: float = 0.06       # 6% de riesgo agregado abierto
    max_correlation: float = 0.7
    monthly_drawdown_limit_pct: float = 0.10
    cumulative_drawdown_limit_pct: float = 0.20
    daily_loss_limit_pct: float = 0.03
```

## Diseño de módulos

```
src/trading_engine/risk/
  config.py           # RiskConfig, OpenPosition (Pydantic)
  sizing.py            # position_size_by_volatility(equity, atr, config) -> float
  engine.py             # RiskEngine.evaluate(signal, equity, atr, entry_price, open_positions,
                        #                      correlations, monthly/cumulative/daily drawdown, kill_switch)
                        #                      -> RiskDecision
src/trading_engine/models/risk_decision.py   # RiskDecision (Pydantic) — contrato compartido
```

Orden de evaluación dentro de `evaluate` (importa para los tests — cada circuit breaker se prueba aislado): kill switch → drawdown acumulado → drawdown mensual → pérdida diaria → señal `HOLD` → portfolio heat → correlación → cálculo de tamaño/stop-loss.

`RiskEngine.evaluate` es una función pura dado su input (sin I/O propio) — recibe el estado de cuenta y las posiciones abiertas ya cargadas por quien lo invoque (Motor de Backtesting o, en producción, el orquestador). Esto es lo que permite que el mismo código sirva en backtest y producción sin cambios (`docs/SDD.md` §3.B).

## Riesgos técnicos y mitigación

- **Cálculo de correlación costoso si se recalcula en cada señal**: para backtesting, precalcular una matriz de correlación por ventana en vez de recalcularla vela a vela.
- **Ambigüedad de "drawdown mensual" en un backtest que corre múltiples meses**: definir explícitamente que se resetea al inicio de cada mes calendario, y que el "acumulado" es desde el inicio del run — evita discrepancias entre el criterio usado en backtest y el que se use en producción.
- **El circuit breaker de drawdown acumulado bloquea "hasta revisión manual" — pero un backtest no tiene humano que revise**: confirmado como bug real al correr 8.6 años de historia (BTC quedó inactivo desde 2023-04-19 hasta el final del histórico, ~3.3 años). `RiskEngine` en sí no cambió — sigue siendo correcto que bloquee al cruzar el umbral — pero quien lo invoca en un backtest (`BacktestEngine`) necesita simular esa revisión manual con un cooldown, o el backtest queda permanentemente detenido apenas se cruza el umbral una vez. Ver `specs/002-motor-backtesting/plan.md` (`drawdown_cooldown_days`) para la solución — vive en el Motor de Backtesting, no aquí, porque decidir "cuándo se resetea" es una decisión de orquestación, no de la función pura de evaluación de riesgo.
