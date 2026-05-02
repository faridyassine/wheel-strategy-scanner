# screener.py — Option chain analysis and best CSP finder
# Analyse de la chaîne d'options et recherche du meilleur Cash Secured Put
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

import requests
import yfinance as yf

import config

logger = logging.getLogger(__name__)

_YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def get_top_active_volatile(count: int = 20) -> list[dict]:
    """
    Returns the top N most active and volatile US stocks/ETFs.
    Uses Yahoo Finance predefined screeners:
      1. most_actives
      2. day_gainers
      3. day_losers
    Deduplicates, fetches HV-30 + IV Rank, and ranks by combined score.
    """
    tickers_seen: set[str] = set()
    candidates: list[dict] = []

    screener_ids = ["most_actives", "day_gainers", "day_losers"]

    for scrId in screener_ids:
        try:
            url = (
                "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
                f"?scrIds={scrId}&count=40&region=US&lang=en-US"
            )
            resp = requests.get(url, headers=_YAHOO_HEADERS, timeout=10)
            data = resp.json()
            quotes = (
                data.get("finance", {})
                .get("result", [{}])[0]
                .get("quotes", [])
            )
            for q in quotes:
                sym = q.get("symbol", "")
                if not sym or sym in tickers_seen:
                    continue
                tickers_seen.add(sym)
                candidates.append({
                    "ticker": sym,
                    "name": q.get("shortName", sym),
                    "price": q.get("regularMarketPrice"),
                    "volume": q.get("regularMarketVolume", 0),
                    "change_pct": q.get("regularMarketChangePercent", 0.0),
                    "market_cap": q.get("marketCap"),
                })
        except Exception as exc:
            logger.warning("Screener %s fetch error: %s", scrId, exc)

    if not candidates:
        return []

    # Enrich with HV-30
    enriched: list[dict] = []
    for c in candidates:
        try:
            hv = ind_get_hv(c["ticker"])
            c["hv_30"] = hv or 0.0
        except Exception:
            c["hv_30"] = 0.0
        enriched.append(c)

    # Score = normalized_volume * 0.5 + normalized_hv * 0.3 + abs(change_pct) * 0.2
    max_vol = max((c["volume"] for c in enriched), default=1) or 1
    max_hv = max((c["hv_30"] for c in enriched), default=1) or 1
    max_chg = max((abs(c["change_pct"]) for c in enriched), default=1) or 1

    for c in enriched:
        c["_score"] = (
            (c["volume"] / max_vol) * 0.5
            + (c["hv_30"] / max_hv) * 0.3
            + (abs(c["change_pct"]) / max_chg) * 0.2
        )

    enriched.sort(key=lambda x: x["_score"], reverse=True)
    return enriched[:count]


def ind_get_hv(ticker: str) -> float | None:
    """Quick HV-30 fetch for a single ticker."""
    try:
        import indicators as ind  # local import to avoid circular
        return ind.get_historical_volatility(ticker)
    except Exception:
        return None


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


def _approx_call_delta(strike: float, current_price: float) -> float:
    """
    Approximates call delta using moneyness (simple linear approximation).
    For a call option (opposite of put):
    - ATM (strike ≈ price) → delta ≈ 0.50
    - Deep OTM (strike >> price) → delta → 0
    - Deep ITM (strike << price) → delta → 1.0
    """
    if current_price <= 0:
        return 0.0
    moneyness = strike / current_price
    if moneyness <= 1.0:
        return 0.50 + (1.0 - moneyness) * 0.5  # ITM (strike < price)
    elif moneyness <= 1.05:
        return 0.50 - (moneyness - 1.0) * 6.0
    elif moneyness <= 1.15:
        return 0.20 - (moneyness - 1.05) * 0.5
    else:
        return max(0.01, 0.20 - (moneyness - 1.05) * 2.0)


def find_best_covered_call(ticker: str, current_price: float = None) -> dict | None:
    """
    Finds the best Covered Call opportunity for the ticker.
    Trouve la meilleure opportunité de Covered Call pour le ticker.

    For Covered Calls, we look for:
    - ATM to slightly OTM strikes (delta 0.30-0.50)
    - Higher premiums to maximize income
    - Strike above current price (to sell appreciated)

    Filters:
    - DTE between DTE_MIN and DTE_MAX
    - Approximate delta between 0.30-0.50 (ATM/slightly OTM)
    - Open Interest > MIN_OPEN_INTEREST
    - Ask price > MIN_PREMIUM

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
            calls = chain.calls
        except Exception as exc:
            logger.error("Error fetching calls for %s @ %s: %s", ticker, expiry, exc)
            continue

        if calls is None or calls.empty:
            continue

        for _, row in calls.iterrows():
            try:
                strike = float(row.get("strike", 0))
                ask = float(row.get("ask", 0))
                oi = int(row.get("openInterest", 0) or 0)

                # For CC, we want ATM to slightly OTM (strike >= current_price)
                if strike < current_price * 0.95:
                    continue

                # Filters
                if ask < config.MIN_PREMIUM:
                    continue
                if oi < config.MIN_OPEN_INTEREST:
                    continue

                # Call delta filter — prefer ATM/slightly OTM (0.30-0.50)
                delta_approx = _approx_call_delta(strike, current_price)
                if delta_approx < 0.25 or delta_approx > 0.60:
                    continue

                monthly_return = calculate_return(ask, strike, dte)

                candidates.append(
                    {
                        "ticker": ticker,
                        "strike": strike,
                        "expiry": expiry,
                        "dte": dte,
                        "premium": ask,
                        "open_interest": oi,
                        "delta_approx": round(delta_approx, 3),
                        "monthly_return_pct": monthly_return,
                        "current_price": current_price,
                    }
                )
            except Exception as exc:
                logger.debug("Error processing call row for %s: %s", ticker, exc)
                continue

    if not candidates:
        logger.info("No suitable covered call found for %s", ticker)
        return None

    # Rank by highest premium (best income)
    best = max(candidates, key=lambda c: c["premium"])
    logger.info(
        "Best CC for %s: strike=%.2f exp=%s premium=%.2f 30d_yield=%.2f%%",
        ticker,
        best["strike"],
        best["expiry"],
        best["premium"],
        best["monthly_return_pct"],
    )
    return best


def calculate_cc_result(
    current_price: float,
    cost_basis: float,
    cc_premium: float,
    cc_strike: float,
    num_shares: int = 100,
) -> dict:
    """
    Calculates the total return if selling covered calls.
    Calcule le rendement total si on vend des covered calls.

    Assumes 100 shares by default (1 option contract = 100 shares).

    Returns dict:
    - call_premium_per_share: Prime du call par action
    - total_proceeds_assigned: Résultat total si assigné (hors commissions)
    - profit_if_assigned: Profit total si assigné
    - profit_pct_if_assigned: % de rendement si assigné
    - breakeven_price: Prix d'équilibre (cost_basis - call_premium)
    - risk: Risque principal
    """
    if num_shares == 0:
        num_shares = 100

    call_income = cc_premium * num_shares  # Total premium received
    if_assigned_proceeds = cc_strike * num_shares  # Proceeds if stock called away

    profit_if_assigned = if_assigned_proceeds - (cost_basis * num_shares) + call_income
    profit_pct_if_assigned = (profit_if_assigned / (cost_basis * num_shares)) * 100 if cost_basis > 0 else 0

    breakeven_price = cost_basis - cc_premium

    return {
        "call_premium_per_share": round(cc_premium, 2),
        "total_call_premium": round(call_income, 2),
        "total_proceeds_if_assigned": round(if_assigned_proceeds, 2),
        "profit_if_assigned": round(profit_if_assigned, 2),
        "profit_pct_if_assigned": round(profit_pct_if_assigned, 2),
        "breakeven_price": round(breakeven_price, 2),
        "cost_basis": round(cost_basis, 2),
        "cc_strike": round(cc_strike, 2),
        "current_price": round(current_price, 2),
    }
