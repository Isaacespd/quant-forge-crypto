# Plan 003 — Alpha Engine

## Decisiones técnicas

| Decisión | Elección | Alternativa descartada | Por qué |
|---|---|---|---|
| Librería de indicadores técnicos | `pandas-ta>=0.4.71b0` | `TA-Lib` | `TA-Lib` requiere compilar/instalar una librería C nativa — fricción real en un entorno Windows sin toolchain de compilación garantizado. `pandas-ta` es Python puro, se instala con `pip` sin dependencias del sistema. |
| Contrato de señal | Modelo Pydantic `Signal` compartido, definido una sola vez | Definirlo por separado en Alpha y en Risk | Evita que los dos motores diverjan en el contrato — ya se especificó en `docs/SDD.md` §4.3, falta moverlo a código. |
| Versión mínima de `pandas-ta` | `>=0.4.71b0` (pin explícito) | Dejar sin pin (`pandas-ta` a secas) | La versión `0.3.14b0` del paquete original (`twopirllc/pandas-ta`) está rota con NumPy ≥1.24 (usa `numpy.NaN`, eliminado). El fork `0.4.71b0` sí funciona con NumPy 2.x/Pandas 3.x — verificado con un smoke test antes de construir `indicators.py` sobre él. |
| Filtro de tendencia macro | `EMA(200)` — solo se permite `BUY` si `close > ema_trend`, solo `SELL` si `close < ema_trend`, aplicado como último paso tras las ramas tendencial/reversión | Sin filtro (estrategia simétrica original) | **Agregado tras evidencia real de backtest** (`specs/002-motor-backtesting/tasks.md`): la v1 sin filtro perdía las 18 operaciones de un backtest real de 2 años sobre BTC/USDT — 15 de 18 eran SELL en un período de tendencia alcista sostenida. El filtro no arregla la calidad de la señal en sí, evita operar en contra de la dirección de fondo. `MIN_CANDLES_FOR_INDICATORS` subió de 64 a 214 (`EMA_TREND_LENGTH + ADX_LENGTH`) como consecuencia. |

## Diseño de módulos

```
src/trading_engine/models/signal.py   # Signal (Pydantic) — mover aquí desde docs/SDD.md §4.3
src/trading_engine/alpha/
  indicators.py                        # wrappers sobre pandas-ta: ema, adx, rsi, bollinger, macd
  strategy.py                          # AlphaEngine.evaluate(candles) -> Signal
```

`AlphaEngine.evaluate` recibe una lista/DataFrame de `Candle` ya validadas (spec 001) — no vuelve a validar OHLC, confía en el contrato que ya pasó por la Capa de Ingesta.

## Riesgos técnicos y mitigación

- **Datos insuficientes para calcular `EMA(50)`** (ej. al arrancar un backtest justo al inicio del histórico disponible): `AlphaEngine.evaluate` debe devolver `HOLD` explícito en vez de fallar, hasta acumular suficientes velas.
- **Cambio de estrategia futuro**: al ser un módulo aislado detrás de la interfaz `evaluate(candles) -> Signal`, cambiar de estrategia (o añadir un ensamble de varias) no debería requerir tocar Risk Engine ni Motor de Backtesting.
- **`ADX(14)` alto no distingue tendencia sostenida de un movimiento brusco aislado** (confirmado empíricamente al construir los tests): un spike de 2-3 velas puede elevar `ADX` por encima del umbral de régimen igual que una tendencia real, activando la lógica tendencial en vez de la de reversión justo en el peor momento (un movimiento que en realidad debería tratarse como sobreventa/sobrecompra puntual). No se corrige en esta spec — queda anotado para que el Motor de Backtesting (spec 002) lo capture como parte de la evaluación de la estrategia, no como un bug del Alpha Engine.
