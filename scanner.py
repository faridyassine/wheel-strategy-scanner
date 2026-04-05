# scanner.py — Core scanning logic for the Wheel Strategy Scanner
# Logique principale du scan pour chaque ticker et la watchlist complète

import logging

import config
import earnings_checker as ec
import indicators as ind

logger = logging.getLogger(__name__)


def scan_ticker(ticker: str) -> dict:
    """
    Runs all checks for a single ticker and returns a result dict.
    Exécute tous les checks pour un ticker et retourne un dictionnaire de résultats.

    Returns a dict with:
        ticker, price, rsi, ma50, ma200, uptrend, iv_rank, hv_30,
        next_earnings, days_to_earnings, earnings_safe, passes_all, reason_failed
    """
    logger.info("Scanning %s …", ticker)

    result = {
        "ticker": ticker,
        "price": None,
        "rsi": None,
        "ma50": None,
        "ma200": None,
        "uptrend": False,
        "iv_rank": None,
        "hv_30": None,
        "next_earnings": "N/A",
        "days_to_earnings": None,
        "earnings_safe": True,
        "passes_all": False,
        "reason_failed": "",
    }

    reasons = []

    # --- Price ---
    try:
        price = ind.get_current_price(ticker)
        result["price"] = price
        if price is None:
            reasons.append("No price data")
    except Exception as exc:
        logger.error("Price error for %s: %s", ticker, exc)
        reasons.append("Price fetch error")

    # --- RSI ---
    try:
        rsi = ind.get_rsi(ticker)
        result["rsi"] = rsi
        if rsi is None:
            reasons.append("No RSI data")
        elif rsi < config.RSI_MIN:
            reasons.append(f"RSI {rsi:.1f} < {config.RSI_MIN} (oversold/bearish)")
        elif rsi > config.RSI_MAX:
            reasons.append(f"RSI {rsi:.1f} > {config.RSI_MAX} (overbought)")
    except Exception as exc:
        logger.error("RSI error for %s: %s", ticker, exc)
        reasons.append("RSI error")

    # --- Moving averages & trend ---
    try:
        mas = ind.get_moving_averages(ticker)
        result["ma50"] = mas.get("ma50")
        result["ma200"] = mas.get("ma200")
        uptrend = ind.is_uptrend(ticker)
        result["uptrend"] = uptrend
        if not uptrend:
            reasons.append("Not in uptrend (MA50 < MA200)")
    except Exception as exc:
        logger.error("MA error for %s: %s", ticker, exc)
        reasons.append("MA error")

    # --- IV Rank ---
    try:
        iv_rank = ind.get_iv_rank(ticker)
        result["iv_rank"] = iv_rank
        if iv_rank is None:
            reasons.append("No IV Rank data")
        elif iv_rank < config.MIN_IV_RANK:
            reasons.append(f"IV Rank {iv_rank:.1f}% < {config.MIN_IV_RANK}% (low premium)")
    except Exception as exc:
        logger.error("IV Rank error for %s: %s", ticker, exc)
        reasons.append("IV Rank error")

    # --- Historical Volatility ---
    try:
        hv = ind.get_historical_volatility(ticker)
        result["hv_30"] = hv
    except Exception as exc:
        logger.error("HV error for %s: %s", ticker, exc)

    # --- Earnings ---
    try:
        next_date = ec.get_next_earnings_date(ticker)
        days = ec.days_until_earnings(ticker)
        safe = ec.is_earnings_safe(ticker)

        result["next_earnings"] = str(next_date) if next_date else "Unknown"
        result["days_to_earnings"] = days
        result["earnings_safe"] = safe

        if not safe:
            reasons.append(
                f"Earnings in {days} days (threshold: {config.EARNINGS_SAFE_DAYS})"
            )
    except Exception as exc:
        logger.error("Earnings error for %s: %s", ticker, exc)
        reasons.append("Earnings check error")

    # --- Final verdict ---
    result["passes_all"] = len(reasons) == 0
    result["reason_failed"] = "; ".join(reasons) if reasons else ""

    status = "✅ PASS" if result["passes_all"] else f"❌ FAIL ({result['reason_failed']})"
    logger.info("%s → %s", ticker, status)

    return result


def scan_all(watchlist: list[str] = None) -> list[dict]:
    """
    Scans all tickers in the watchlist and returns a list of result dicts.
    Scanne tous les tickers de la watchlist et retourne la liste des résultats.

    Args:
        watchlist: list of ticker symbols; defaults to config.WATCHLIST

    Returns:
        List of result dicts (all tickers, not just passing ones).
    """
    if watchlist is None:
        watchlist = config.WATCHLIST

    results = []
    total = len(watchlist)

    for i, ticker in enumerate(watchlist, 1):
        logger.info("[%d/%d] Scanning %s …", i, total, ticker)
        try:
            result = scan_ticker(ticker)
        except Exception as exc:
            logger.error("Unexpected error scanning %s: %s", ticker, exc)
            result = {
                "ticker": ticker,
                "price": None,
                "rsi": None,
                "ma50": None,
                "ma200": None,
                "uptrend": False,
                "iv_rank": None,
                "hv_30": None,
                "next_earnings": "Error",
                "days_to_earnings": None,
                "earnings_safe": False,
                "passes_all": False,
                "reason_failed": str(exc),
            }
        results.append(result)

    return results


def get_passing_tickers(results: list[dict]) -> list[dict]:
    """
    Filters and returns only tickers that pass ALL criteria.
    Filtre et retourne uniquement les tickers qui passent tous les critères.
    """
    return [r for r in results if r.get("passes_all")]
