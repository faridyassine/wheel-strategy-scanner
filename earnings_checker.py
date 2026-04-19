# earnings_checker.py — Earnings date verification for the Wheel Strategy Scanner
# Vérification des dates de résultats d'entreprise (earnings)
from __future__ import annotations

import logging
from datetime import date, datetime

import yfinance as yf

import config

logger = logging.getLogger(__name__)


def get_next_earnings_date(ticker: str) -> date | None:
    """
    Returns the next earnings date for the ticker, or None if unavailable.
    Retourne la prochaine date de résultats pour le ticker, ou None si indisponible.
    """
    try:
        stock = yf.Ticker(ticker)
        calendar = stock.calendar

        if calendar is None or calendar.empty:
            logger.debug("No earnings calendar found for %s", ticker)
            return None

        # calendar is a DataFrame with dates in columns; earnings date is in the first row
        if "Earnings Date" in calendar.index:
            raw = calendar.loc["Earnings Date"]
        elif "Earnings Date" in calendar.columns:
            raw = calendar["Earnings Date"]
        else:
            # Try the first row / first column heuristically
            logger.debug("Unexpected calendar format for %s: %s", ticker, calendar)
            return None

        # raw may be a Series or a single value; grab the first future date
        today = date.today()
        candidates = []

        if hasattr(raw, "__iter__") and not isinstance(raw, str):
            for val in raw:
                dt = _parse_date(val)
                if dt and dt >= today:
                    candidates.append(dt)
        else:
            dt = _parse_date(raw)
            if dt and dt >= today:
                candidates.append(dt)

        if candidates:
            return min(candidates)

        return None

    except Exception as exc:
        logger.error("Error fetching earnings date for %s: %s", ticker, exc)
        return None


def _parse_date(value) -> date | None:
    """
    Converts various date representations to a date object.
    Convertit différentes représentations de dates en objet date.
    """
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if hasattr(value, "to_pydatetime"):
        # pandas Timestamp
        try:
            return value.to_pydatetime().date()
        except Exception:
            return None
    if isinstance(value, str):
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y"):
            try:
                return datetime.strptime(value[:10], fmt[:10]).date()
            except ValueError:
                continue
    return None


def days_until_earnings(ticker: str) -> int | None:
    """
    Returns the number of days until the next earnings date.
    Retourne le nombre de jours jusqu'aux prochains résultats.
    """
    next_date = get_next_earnings_date(ticker)
    if next_date is None:
        return None
    delta = (next_date - date.today()).days
    return delta


def is_earnings_safe(ticker: str, safe_days: int = None) -> bool:
    """
    Returns True if the next earnings date is more than safe_days away.
    Retourne True si les prochains résultats sont à plus de safe_days jours.

    Returns True by default if the earnings date is unknown (no data available).
    """
    if safe_days is None:
        safe_days = config.EARNINGS_SAFE_DAYS

    days = days_until_earnings(ticker)
    if days is None:
        # Unknown earnings date — treat as safe (warn in report)
        logger.debug("Earnings date unknown for %s — treating as safe", ticker)
        return True
    if days < safe_days:
        logger.warning(
            "⚠️  %s has earnings in %d days (threshold: %d)", ticker, days, safe_days
        )
        return False
    return True
