# Spec 001 — Capa de Ingesta de Datos

Capa A de la arquitectura ([docs/SDD.md](../../docs/SDD.md) §3.A). Habilita la Fase 1 (Backtesting) del roadmap (§6).

## Por qué

Sin datos históricos OHLCV limpios y confiables no tiene sentido construir el Motor de Backtesting ni el Alpha Engine — es la regla de oro cuant citada en `docs/SDD.md` §4.4: *garbage in, garbage out*. Esta es la primera pieza del sistema porque todo lo demás depende de ella.

## Alcance

**Incluye:**
- Descarga de histórico OHLCV desde un exchange de criptomonedas (modo *histórico*, no streaming en vivo).
- Validación de cada vela y de la serie completa antes de persistir.
- Persistencia idempotente en la base de datos (reejecutar la misma descarga no duplica datos).

**No incluye** (fuera de alcance de esta spec):
- Ingesta en modo streaming/WebSocket en vivo — se añade en la Fase 2 (paper trading), reutilizando el mismo modelo `Candle` y el mismo esquema de base de datos.
- Cualquier lógica de estrategia o cálculo de indicadores — eso es del Alpha Engine (spec 003).
- Soporte multi-exchange simultáneo — el cliente es agnóstico de exchange vía `ccxt`, pero por ahora se opera con uno a la vez.

## Requisitos funcionales

1. Dado un símbolo (ej. `BTC/USDT`), un timeframe (ej. `1h`, `1m`) y un rango de fechas, el sistema debe poder descargar todas las velas OHLCV de ese rango, paginando automáticamente si el exchange limita el tamaño de respuesta.
2. Cada vela debe validarse individualmente: precios positivos, `low <= open,close <= high`, volumen no negativo, timestamp con zona horaria (UTC).
3. La serie completa debe validarse en conjunto: timestamps estrictamente ascendentes y sin gaps de tiempo inexplicados para el timeframe declarado.
4. Una vela que no pase validación debe rechazar toda la carga con un error explícito (no se persisten datos parcialmente inválidos silenciosamente).
5. Volver a ejecutar la descarga del mismo rango no debe duplicar filas en la base de datos.

## Criterios de aceptación

- Dado un rango de fechas y un símbolo reales, el comando de descarga produce el número esperado de velas para ese rango y timeframe (sin huecos).
- Una muestra de al menos 10 velas descargadas coincide con los valores mostrados en el front-end público del exchange (descarta errores de mapeo de columnas open/high/low/close/volume).
- Un dataset con velas corruptas de prueba (nulos, `high < low`, volumen negativo, timestamp duplicado, gap de tiempo) es rechazado por el validador con un mensaje que identifica la vela/condición específica.
- Ejecutar el mismo comando de descarga dos veces sobre el mismo rango dos veces resulta en el mismo número de filas en la tabla `ohlcv` la segunda vez (idempotencia).

## Dependencias

Ninguna — es el primer componente del sistema.
