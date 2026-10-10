from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Signal(BaseModel):
    """Contrato de salida del Alpha Engine (docs/SDD.md §4.3).

    Deliberadamente no incluye tamaño de posición, stop-loss ni take-profit:
    eso es autoridad exclusiva del Risk Engine (docs/SDD.md §3.C).
    """

    symbol: str
    timeframe: str
    direction: Literal["BUY", "SELL", "HOLD"]
    confidence: float = Field(ge=0.0, le=1.0)
    timestamp: datetime
    strategy_id: str
