# Spec-Driven Development — Motor de Trading Algorítmico

Este proyecto sigue un flujo de **Spec-Driven Development (SDD)**: ningún código se escribe sin que exista primero una especificación aprobada. El orden siempre es:

```
spec.md   →   plan.md   →   tasks.md   →   código + tests
(qué/por qué)  (cómo, decisiones técnicas)   (tickets ejecutables)
```

## Jerarquía de documentos

1. **[../docs/SDD.md](../docs/SDD.md)** — la "constitución" del proyecto: visión, arquitectura de las 6 capas, principios no negociables (ej. "ningún LLM en la ruta crítica de decisión de orden", reglas de riesgo, metodología de backtesting). Cambia poco. Cualquier spec que lo contradiga está mal escrita, no al revés.
2. **`specs/<NNN>-<slug>/spec.md`** — qué debe hacer ese componente y por qué, con criterios de aceptación verificables. No habla de tecnología ni de cómo se implementa.
3. **`specs/<NNN>-<slug>/plan.md`** — decisiones técnicas concretas: esquema de datos, contratos (Pydantic/SQL), librerías, diseño de clases/módulos, riesgos técnicos y cómo se mitigan.
4. **`specs/<NNN>-<slug>/tasks.md`** — tickets numerados y accionables derivados del plan, cada uno con criterio de aceptación. Es la única unidad de trabajo que se marca como hecha/pendiente.

## Reglas del flujo

- Un ticket de `tasks.md` no se empieza a programar si su `spec.md`/`plan.md` no existen o están en borrador sin resolver.
- Si al programar aparece una decisión técnica no prevista en el `plan.md`, se actualiza el `plan.md` primero (aunque sea una línea) y luego se continúa el código — no al revés.
- El código y los tests son la fuente de verdad de *qué está hecho*; `tasks.md` es la fuente de verdad de *qué se planeó* y su estado (`pendiente` / `en progreso` / `hecho`).
- Los números de carpeta (`001`, `002`, ...) siguen el orden de las capas de arquitectura en `docs/SDD.md` §3, que a su vez sigue el roadmap de fases (`docs/SDD.md` §6): primero lo necesario para backtesting, después lo necesario para producción.

## Índice de specs

| # | Spec | Capa (docs/SDD.md §3) | Fase que habilita | Estado |
|---|---|---|---|---|
| [001](001-capa-ingesta-datos/spec.md) | Capa de Ingesta de Datos | A | 1. Backtesting | Cerrada — verificada con infraestructura real |
| [002](002-motor-backtesting/spec.md) | Motor de Backtesting | B | 1. Backtesting | Cerrada — 118/118 tests en verde. Validado con 8.6 años reales (BTC/ETH) tras corregir un bug crítico (circuit breaker de drawdown sin recuperación); ninguna variante de la estrategia pasa el gate de Fase 1, ver `tasks.md` |
| [003](003-alpha-engine/spec.md) | Alpha Engine (estrategia) | C | 1. Backtesting | Cerrada — filtro de tendencia macro agregado tras evidencia real, ver `tasks.md` |
| [004](004-risk-engine/spec.md) | Risk Engine | D | 1. Backtesting → 3. Producción | Cerrada — 17/17 tests en verde, ver `tasks.md` |
| [005](005-execution-gateway/spec.md) | Execution Gateway | E | 3. Producción | Esqueleto — se detalla al llegar a fase 3 |
| [006](006-observabilidad-kill-switch/spec.md) | Observabilidad y Kill Switch | F | 2. Paper trading → 3. Producción | Esqueleto — se detalla al llegar a fase 2 |

Las specs 005 y 006 están deliberadamente en esqueleto: detallarlas ahora sería especificar producción antes de saber si la estrategia tiene edge en backtesting — trabajo que se descartaría o reharía. Se profundizan cuando el roadmap (`docs/SDD.md` §6) llegue a esa fase.
