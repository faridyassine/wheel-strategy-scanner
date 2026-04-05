# screener.py — Option chain analysis and best CSP finder
# Analyse de la chaîne d'options et recherche du meilleur Cash Secured Put

import logging
from datetime import date, datetime, timedelta

import yfinance as yf

import config

logger = logging.getLogger(__name__)


def get_option_chain(ticker: str) -> list[str]:
    """
    Returns available option expiration dates for the ticker.
    Retourne les dates d'expiration disponibles pour le ticker.
    """
    try:
        stock = yf.Ticker(ticker)
        expirations = stock.options
        if not expirations:
            logger.warning("No options available for %s", ticker)
        return list(expirations) if expirations else []
    except Exception as exc:
        logger.error("Error fetching option chain for %s: %s", ticker, exc)
        return []


def _dte(expiry_str: str) -> int:
    """
    Returns the number of days to expiration from today.
    Retourne le nombre de jours jusqu'à l'expiration.
    """
    try:
        expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d").date()
        return (expiry_date - date.today()).days
    except Exception:
        return -1


def _approx_delta(strike: float, current_price: float) -> float:
    """
    Approximates put delta using moneyness (simple linear approximation).
    Approxime le delta du put par la moneyness (approximation linéaire simple).

    For a put option:
    - ATM (strike ≈ price) → delta ≈ -0.50
    - Deep OTM (strike << price) → delta → 0
    - Deep ITM (strike >> price) → delta → -1.0

    We use moneyness = strike / price and map it to an approximate delta.
    This is a heuristic — real delta requires IV and a pricing model.
    """
    if current_price <= 0:
        return 0.0
    moneyness = strike / current_price
    # Simple sigmoid-like mapping for put delta magnitude
    # moneyness = 1.0 → delta ≈ 0.50
    # moneyness = 0.90 → delta ≈ 0.20-0.25
    # moneyness = 0.85 → delta ≈ 0.15
    if moneyness >= 1.0:
        return 0.50 + (moneyness - 1.0) * 0.5  # ITM
    elif moneyness >= 0.95:
        return 0.50 - (1.0 - moneyness) * 6.0
    elif moneyness >= 0.85:
        return 0.20 - (0.95 - moneyness) * 0.5
    else:
        return max(0.01, 0.20 - (0.95 - moneyness) * 2.0)


def calculate_return(premium: float, strike: float, dte: int = 30) -> float:
    """
    Calculates the 30-day normalised return % for a cash secured put.
    Calcule le rendement normalisé sur 30 jours pour un cash secured put.

    return_pct = (premium / strike) * (30 / dte) * 100

    Normalising by DTE allows fair comparison across different expirations.
    If dte is not provided, defaults to 30 (no normalisation).
    """
    if strike <= 0 or dte <= 0:
        return 0.0
    return round((premium / strike) * (30 / dte) * 100, 3)


def find_best_csp(ticker: str, current_price: float = None) -> dict | None:
    """
    Finds the best Cash Secured Put opportunity for the ticker.
    Trouve la meilleure opportunité de Cash Secured Put pour le ticker.

    Filters:
    - DTE between DTE_MIN and DTE_MAX (21–45 days)
    - Approximate delta between TARGET_DELTA_MIN and TARGET_DELTA_MAX
    - Open Interest > MIN_OPEN_INTEREST
    - Bid price > MIN_PREMIUM

    Ranks candidates by:
    1. Highest premium (bid price) that meets all criteria

    Returns a dict with details or None if no suitable option found.
    """
    if current_price is None:
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="1d")
            if not hist.empty:
                current_price = float(hist["Close"].iloc[-1])
        except Exception as exc:
            logger.error("Could not fetch price for %s: %s", ticker, exc)
            return None

    if current_price is None or current_price <= 0:
        logger.warning("Invalid price for %s", ticker)
        return None

    expirations = get_option_chain(ticker)
    if not expirations:
        return None

    candidates = []

    for expiry in expirations:
        dte = _dte(expiry)
        if dte < config.DTE_MIN or dte > config.DTE_MAX:
            continue

        try:
            stock = yf.Ticker(ticker)
            chain = stock.option_chain(expiry)
            puts = chain.puts
        except Exception as exc:
            logger.error("Error fetching puts for %s @ %s: %s", ticker, expiry, exc)
            continue

        if puts is None or puts.empty:
            continue

        for _, row in puts.iterrows():
            try:
                strike = float(row.get("strike", 0))
                bid = float(row.get("bid", 0))
                oi = int(row.get("openInterest", 0) or 0)

                # Filters — Filtres
                if bid < config.MIN_PREMIUM:
                    continue
                if oi < config.MIN_OPEN_INTEREST:
                    continue

                # Approximate delta filter
                delta_approx = _approx_delta(strike, current_price)
                if delta_approx < config.TARGET_DELTA_MIN or delta_approx > config.TARGET_DELTA_MAX:
                    continue

                monthly_return = calculate_return(bid, strike, dte)

                candidates.append(
                    {
                        "ticker": ticker,
                        "strike": strike,
                        "expiry": expiry,
                        "dte": dte,
                        "premium": bid,
                        "open_interest": oi,
                        "delta_approx": round(delta_approx, 3),
                        "monthly_return_pct": monthly_return,
                        "current_price": current_price,
                    }
                )
            except Exception as exc:
                logger.debug("Error processing put row for %s: %s", ticker, exc)
                continue

    if not candidates:
        logger.info("No suitable CSP found for %s", ticker)
        return None

    # Rank by highest premium (best income)
    best = max(candidates, key=lambda c: c["premium"])
    logger.info(
        "Best CSP for %s: strike=%.2f exp=%s premium=%.2f 30d_yield=%.2f%%",
        ticker,
        best["strike"],
        best["expiry"],
        best["premium"],
        best["monthly_return_pct"],
    )
    return best
