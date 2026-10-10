# Spec 002 — Motor de Backtesting

Capa B de la arquitectura ([docs/SDD.md](../../docs/SDD.md) §3.B) — el componente que **no existía en el diseño original** y que esta revisión identificó como el gap más importante. Habilita la Fase 1 (Backtesting) del roadmap (§6).

## Por qué

Sin este componente no hay forma de saber si la estrategia del Alpha Engine tiene *edge* estadístico antes de arriesgar dinero real, ni siquiera antes de pasar a paper trading. Es el gate de la Fase 1 → Fase 2 del roadmap.

## Alcance

**Incluye:**
- Ejecutar Alpha Engine (spec 003) + Risk Engine (spec 004) — el mismo código que correría en producción — vela a vela sobre datos históricos.
- Simular fills de órdenes con comisión y slippage configurables.
- Walk-forward analysis: optimizar en una ventana, validar en la siguiente, deslizar.
- Calcular el set de métricas obligatorias de `docs/SDD.md` §5.4.

**No incluye:**
- Conexión a bróker real (spec 005).
- Paper trading en vivo (reutiliza este mismo motor con datos en streaming, pero es trabajo de una fase posterior).

## Requisitos funcionales

1. Dado un rango histórico de velas de un símbolo/timeframe, iterarlas en orden cronológico estricto, exponiendo en cada paso `t` solo los datos disponibles hasta el cierre de `t-1` para la decisión de entrada en `t` (salvo que la estrategia declare explícitamente que opera al cierre de la propia vela `t`).
2. Por cada vela, invocar Alpha Engine → `Signal`, luego Risk Engine → `RiskDecision`, sin reimplementar esa lógica dentro del motor de backtesting.
3. Si `RiskDecision.approved`, simular el fill aplicando comisión (% configurable) y slippage (modelo configurable, no cero por defecto) y actualizar el estado de cuenta simulado (equity, posiciones abiertas).
4. Soportar partición walk-forward: ventana de entrenamiento + ventana de validación, con paso configurable, sin mezclar datos de una ventana futura en el cálculo de una pasada.
5. Producir un reporte con: Sharpe ratio, Sortino ratio, máximo drawdown, win rate, profit factor, expectancy, número de operaciones.

## Criterios de aceptación

- Dos ejecuciones del backtest con los mismos parámetros y los mismos datos producen exactamente el mismo resultado (determinismo — condición necesaria dado que nada del pipeline de decisión usa LLMs, `docs/SDD.md` nota de riesgo en §2).
- El reporte de métricas incluye una advertencia explícita si el número de operaciones es menor a ~100 (significancia estadística, `docs/SDD.md` §5.4).
- Cambiar el modelo de slippage/comisión de "cero" a valores realistas cambia el resultado del backtest de forma medible (si no cambia nada, el modelo de costos no se está aplicando de verdad).
- Una prueba con look-ahead bias deliberadamente introducido (ej. usar el `close` de la vela `t` para decidir la entrada en `t` sin declararlo) debe ser detectable comparando resultados con/sin el fix — sirve como test de regresión del propio motor.

## Dependencias

- Spec 001 (Capa de Ingesta) — fuente de los datos históricos.
- Spec 003 (Alpha Engine) y Spec 004 (Risk Engine) — el motor no tiene lógica de decisión propia, solo orquesta.
