# Spec 004 — Risk Engine

Capa D de la arquitectura ([docs/SDD.md](../../docs/SDD.md) §3.D). Formaliza en código las reglas de `docs/SDD.md` §5.2 y §5.3.

## Por qué

Es el cortafuegos financiero del sistema: tiene autoridad para bloquear cualquier señal del Alpha Engine, sin excepción, si viola un límite de riesgo. Es el componente donde un error de diseño se traduce directamente en pérdida de capital — de ahí que sus reglas estén formalizadas como fórmulas verificables, no como criterio implícito en el código.

## Alcance

**Incluye:**
- Sizing de posición basado en volatilidad (`docs/SDD.md` §5.2).
- Cálculo de stop-loss/take-profit por múltiplo de ATR.
- Reglas de portfolio heat, límite de correlación, circuit breakers de drawdown (mensual y diario), y verificación de kill switch.
- Emisión de `RiskDecision` (aprobar con sizing, o rechazar con motivo).

**No incluye:**
- Envío de la orden al bróker (spec 005).
- La fuente de datos de correlación entre pares en sí (se apoya en histórico ya cargado por spec 001).

## Requisitos funcionales

1. Dado un `Signal` con dirección `BUY`/`SELL` y el estado de cuenta (`equity`, posiciones abiertas), calcular el tamaño de posición con la fórmula de `docs/SDD.md` §5.2, arriesgando entre 0.5%-1% del capital total (configurable).
2. Calcular `stop_loss` a una distancia de 1.5-2× `ATR(14)` (configurable) del precio de entrada.
3. Rechazar la señal (`approved=False`) si el riesgo agregado abierto ("portfolio heat") superaría el 5-6% configurado.
4. Rechazar la señal si abrir la posición implicaría 2+ posiciones con correlación > 0.7 en la misma dirección.
5. Si el drawdown del mes supera -10% (o el acumulado -20%), pasar a modo "solo cierre": rechazar toda señal nueva hasta revisión manual, sin afectar posiciones ya abiertas.
6. Si la pérdida del día supera 3%, rechazar toda señal nueva por el resto del día.
7. Si el kill switch manual está activo, rechazar toda señal nueva incondicionalmente.
8. Toda decisión de rechazo debe incluir `rejection_reason` explícito e identificable (no un texto genérico).

## Criterios de aceptación

- El sizing calculado para un input conocido (capital, ATR, riesgo% fijos) coincide exactamente con el valor esperado calculado a mano — test unitario con la fórmula aplicada manualmente.
- Cada circuit breaker (drawdown mensual, drawdown diario, portfolio heat, correlación, kill switch) tiene al menos un test que lo dispara de forma aislada y confirma `approved=False` con el `rejection_reason` correcto.
- Ningún límite está hardcodeado en la lógica: todos vienen de un objeto de configuración (`RiskConfig`) con los valores por defecto de `docs/SDD.md` §5.3.
- El circuit breaker de drawdown bloquea señales nuevas pero un test confirma explícitamente que no genera ninguna acción sobre posiciones ya abiertas (no las cierra).

## Dependencias

- Spec 003 (Alpha Engine) — recibe su `Signal` como input.
- Spec 001 (Capa de Ingesta) — para el histórico de precios que alimenta el cálculo de correlación entre pares.
