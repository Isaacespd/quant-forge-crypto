# Spec 003 — Alpha Engine

Capa C de la arquitectura ([docs/SDD.md](../../docs/SDD.md) §3.C). Implementa la estrategia de ejemplo definida en §5.1.

## Por qué

Es el "cerebro" que decide dirección (BUY/SELL/HOLD) a partir de datos de mercado. Se aísla de Risk Engine deliberadamente: un cambio de estrategia no debe poder tocar, ni siquiera por accidente, la lógica de cuánto arriesgar.

## Alcance

**Incluye:**
- Cálculo de indicadores técnicos: `EMA(20)`, `EMA(50)`, `ADX(14)`, `RSI(14)`, Bandas de Bollinger, `MACD`.
- Filtro de régimen (`ADX`) que alterna entre lógica tendencial y de reversión a la media.
- Emisión de `Signal` (BUY/SELL/HOLD + `confidence`) según el contrato Pydantic de `docs/SDD.md` §4.3.

**No incluye (restricción explícita, ver `docs/SDD.md` §3.C):**
- Conocimiento del capital disponible o del tamaño de cuenta.
- Cálculo de tamaño de posición, stop-loss o take-profit — es exclusivo de Risk Engine (spec 004).
- Cualquier llamado a un LLM o framework de agentes en esta ruta (`docs/SDD.md` §2, nota de riesgo).

## Requisitos funcionales

1. Dada una serie de velas OHLCV (mínimo el histórico necesario para calcular `EMA(50)`), calcular los indicadores de §5.1 para la última vela cerrada.
2. Si `ADX(14) > 20`: evaluar cruce `EMA(20)`/`EMA(50)` confirmado por el histograma de `MACD` → señal tendencial.
3. Si `ADX(14) <= 20`: evaluar `RSI(14)` en extremos (`<30`/`>70`) combinado con Bandas de Bollinger → señal de reversión a la media.
4. Calcular `confidence` (0-1) según cuántas condiciones de la estrategia activa se cumplen simultáneamente.
5. Emitir siempre un objeto `Signal` válido, incluso en `HOLD` (nunca `None` ni excepción por falta de señal).

## Criterios de aceptación

- Dado el mismo input exacto, la salida es bit-a-bit idéntica entre ejecuciones (determinismo).
- Con datos sintéticos de tendencia alcista clara y `ADX` alto, se dispara `BUY` cuando `EMA(20)` cruza sobre `EMA(50)` con `MACD` positivo.
- Con datos sintéticos de mercado lateral (`ADX` bajo) y `RSI` tocando extremos, se dispara la lógica de reversión y no la tendencial.
- El objeto `Signal` nunca incluye tamaño de posición, stop-loss ni take-profit — un test de contrato verifica que esos campos no existen en el modelo.

## Dependencias

- Spec 001 (Capa de Ingesta) — fuente de las velas OHLCV sobre las que se calculan los indicadores.
