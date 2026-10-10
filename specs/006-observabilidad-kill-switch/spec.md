# Spec 006 — Observabilidad y Kill Switch (esqueleto)

Capa F de la arquitectura ([docs/SDD.md](../../docs/SDD.md) §3.F). Habilita la Fase 2 (Paper trading) en adelante del roadmap (§6).

> **Esta spec está deliberadamente en esqueleto.** El kill switch *manual* y los circuit breakers *automáticos* de drawdown ya están especificados como reglas de negocio en `docs/SDD.md` §5.3 y viven, en código, dentro de Risk Engine (spec 004) — no son un componente aparte. Lo que falta especificar aquí es la capa delgada de métricas/alertas y el mecanismo operable por un humano para el kill switch, que se detalla al llegar a Fase 2.

## Por qué (ya definido, no cambia con la fecha)

Un evento de mercado anómalo no debería poder seguir generando órdenes sin que exista una forma rápida de detenerlo desde fuera del propio proceso de decisión.

## Pendiente de definir en Fase 2

- Mecanismo concreto del kill switch (flag en base de datos consultado en cada ciclo, variable de entorno + restart, endpoint administrativo).
- Qué métricas se exponen (drawdown, PnL diario, latencia de ingesta) y a dónde (log estructurado, dashboard, alerta activa vía algún canal).
- Umbral y canal de alerta para los SPOF identificados en `docs/SDD.md` §4.1 (caída de DB, caída de conexión al exchange).
