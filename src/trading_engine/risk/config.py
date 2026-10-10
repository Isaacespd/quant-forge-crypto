from typing import Literal

from pydantic import BaseModel, Field


class RiskConfig(BaseModel):
    """Umbrales de riesgo de docs/SDD.md §5.3, como defaults explícitos y auditables.

    Nunca hardcodear estos valores en la lógica de RiskEngine: si cambian, cambian aquí.
    """

    risk_per_trade_pct: float = Field(default=0.01, gt=0, le=1)
    stop_atr_multiplier: float = Field(default=2.0, gt=0)
    # `None` = sin techo (comportamiento previo, sin cambios). El sizing por volatilidad
    # expone más nocional en dólares cuanto menor es el ATR% del activo (nocional =
    # riesgo$ / (mult × ATR%)) — confirmado como la causa de la fragilidad a costos de
    # BTC frente a ETH/SOL (specs/002-motor-backtesting/tasks.md). Este techo limita el
    # nocional a una fracción fija del capital, independiente del ATR%.
    max_notional_pct: float | None = Field(default=None, gt=0, le=1)
    max_portfolio_heat_pct: float = Field(default=0.06, gt=0, le=1)
    max_correlation: float = Field(default=0.7, ge=0, le=1)
    monthly_drawdown_limit_pct: float = Field(default=0.10, gt=0, le=1)
    cumulative_drawdown_limit_pct: float = Field(default=0.20, gt=0, le=1)
    daily_loss_limit_pct: float = Field(default=0.03, gt=0, le=1)


class OpenPosition(BaseModel):
    """Posición ya abierta, tal como la necesita RiskEngine para portfolio heat y correlación.

    `risk_pct` es el riesgo (como fracción del capital) que se comprometió al abrirla —
    ya calculado en su momento, RiskEngine no lo recalcula a partir de precios históricos.
    """

    symbol: str
    direction: Literal["BUY", "SELL"]
    risk_pct: float = Field(gt=0, le=1)
