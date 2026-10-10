from trading_engine.risk.config import RiskConfig


def position_size_by_volatility(equity: float, atr: float, config: RiskConfig) -> float:
    """Volatility targeting (docs/SDD.md §5.2): arriesga risk_per_trade_pct del capital,
    con el stop a stop_atr_multiplier × ATR de distancia.
    """
    if atr <= 0:
        raise ValueError(f"ATR debe ser > 0 para calcular el tamaño de posición, recibido {atr}")

    return (equity * config.risk_per_trade_pct) / (atr * config.stop_atr_multiplier)


def apply_notional_cap(size: float, entry_price: float, equity: float, config: RiskConfig) -> tuple[float, bool]:
    """Limita el nocional (size × entry_price) a `max_notional_pct` del capital, si está
    configurado. Devuelve (tamaño_final, se_recortó).

    Sin este techo, `position_size_by_volatility` expone más nocional cuanto menor es el
    ATR% del activo — el riesgo en dólares se mantiene constante, pero el nocional (y por
    lo tanto la comisión/slippage, que son % del nocional) no. Confirmado empíricamente
    como la causa de que BTC sea más frágil a costos que ETH/SOL (mismo riesgo%, más
    dólares movidos por operación porque su volatilidad relativa es menor).
    """
    if config.max_notional_pct is None:
        return size, False

    max_size = (equity * config.max_notional_pct) / entry_price
    if size > max_size:
        return max_size, True
    return size, False
