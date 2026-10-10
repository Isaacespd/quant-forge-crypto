# Tasks 004 — Risk Engine

| # | Tarea | Archivo(s) | Estado |
|---|---|---|---|
| 1 | `RiskConfig` (Pydantic) con los defaults de `docs/SDD.md` §5.3 | `src/trading_engine/risk/config.py` | verificado |
| 2 | `position_size_by_volatility`: fórmula de `docs/SDD.md` §5.2 | `src/trading_engine/risk/sizing.py` | verificado |
| 3 | `RiskEngine.evaluate`: portfolio heat, correlación, circuit breakers, kill switch | `src/trading_engine/risk/engine.py` | verificado |
| 4 | Tests: sizing contra valor calculado a mano | `tests/test_risk_engine.py` | verificado |
| 5 | Tests: un circuit breaker por caso, aislado | `tests/test_risk_engine.py` | verificado |

## Verificación realizada

- `pytest` completo: **56/56 tests en verde** (17 nuevos de esta spec + 39 de specs 001/003).
- Sizing verificado contra un cálculo a mano exacto: `(100_000 × 0.01) / (50 × 2.0) = 10.0`.
- Cada circuit breaker probado de forma aislada con su `rejection_reason` explícito: `kill_switch_active`, `cumulative_drawdown_limit_exceeded`, `monthly_drawdown_limit_exceeded`, `daily_loss_limit_exceeded`, `portfolio_heat_exceeded`, `correlation_limit_exceeded`, `signal_is_hold`.
- Test explícito de que el circuit breaker de drawdown no muta ni cierra posiciones ya abiertas (`open_positions` queda idéntico tras el rechazo).
- Test explícito de que ningún umbral está hardcodeado: con un `RiskConfig` deliberadamente laxo (todos los límites en 0.99), un escenario que rechazaría con los defaults queda aprobado.
- Dos decisiones de diseño no previstas en el `plan.md` original tuvieron que resolverse antes de escribir código (ya documentadas en `plan.md`): cómo representar posiciones abiertas (`OpenPosition`) y correlación (`dict[symbol, float]`) sin que `RiskEngine` necesite acceso a histórico de precios.

## Siguiente acción concreta

Spec 004 queda funcionalmente cerrada. Con esto, specs 001, 003 y 004 están cerradas — spec 002 (Motor de Backtesting) ya no tiene bloqueos: Alpha Engine y Risk Engine existen y tienen contratos (`Signal`, `RiskDecision`) estables para orquestar.
