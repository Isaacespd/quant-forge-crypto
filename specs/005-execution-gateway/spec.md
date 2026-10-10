# Spec 005 — Execution Gateway (esqueleto)

Capa E de la arquitectura ([docs/SDD.md](../../docs/SDD.md) §3.E). Habilita la Fase 3 (Producción, capital limitado) del roadmap (§6).

> **Esta spec está deliberadamente en esqueleto.** Detallarla ahora significaría especificar producción antes de saber, por backtesting (spec 002), si la estrategia tiene algún edge — trabajo que probablemente se descartaría o reharía. Se completa (requisitos funcionales, criterios de aceptación, `plan.md`, `tasks.md`) al llegar el roadmap a Fase 3.

## Por qué (ya definido, no cambia con la fecha)

Traduce una `RiskDecision` aprobada al formato específico del bróker, envía la orden, escucha confirmación de fill, y actualiza el estado en base de datos.

## Requisito no negociable ya fijado en `docs/SDD.md` §3.E

Al reiniciar el proceso, **reconciliar contra el estado real del bróker antes de operar** — el bróker es la fuente de verdad, no la última copia local en Postgres. Esto evita operar sobre una posición "huérfana" que quedó sin stop-loss registrado localmente tras un reinicio a mitad de una orden.

## Pendiente de definir en Fase 3

- Bróker/exchange concreto para producción (puede no ser el mismo que se usó para histórico en spec 001).
- Mecanismo de mensajería con Risk Engine: cola de mensajes (Redis Streams/RabbitMQ) según `docs/SDD.md` §4.3, no HTTP síncrono.
- Manejo de fills parciales y rechazos del bróker.
- Alcance de esta spec en Fase 2 (paper trading): probablemente una versión simplificada que simula fills en vez de conectar a un bróker real, reutilizando el mismo contrato de `RiskDecision → Orden`.
