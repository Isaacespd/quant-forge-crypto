from pydantic import BaseModel, Field


class RiskDecision(BaseModel):
    """Contrato de salida del Risk Engine (docs/SDD.md §4.3).

    `take_profit` no tiene fórmula definida en docs/SDD.md §5 — se deja en None
    hasta que exista una decisión explícita al respecto (no se inventa una acá).
    """

    approved: bool
    size: float | None = Field(default=None, gt=0)
    stop_loss: float | None = None
    take_profit: float | None = None
    rejection_reason: str | None = None
    capped: bool = False
