# indicators.py — Technical indicators for the Wheel Strategy Scanner
# Indicateurs techniques : RSI, moyennes mobiles, IV Rank, volatilité historique
from __future__ import annotations

import logging
import numpy as np
import pandas as pd
import yfinance as yf

import config

logger = logging.getLogger(__name__)


def _download_history(ticker: str, period: str = "1y") -> pd.DataFrame:
    """
    Download historical price data for a ticker.
    Télécharge l'historique des prix pour un ticker.
    """
    try:
        data = yf.download(ticker, period=period, progress=False, auto_adjust=True)
        if data.empty:
            logger.warning("No price data found for %s", ticker)
        return data
    except Exception as exc:
        logger.error("Error downloading data for %s: %s", ticker, exc)
        return pd.DataFrame()


def get_current_price(ticker: str) -> float | None:
    """
    Returns the last closing price for the ticker.
    Retourne le dernier prix de clôture pour le ticker.
    """
    data = _download_history(ticker, period="5d")
    if data.empty:
        return None
    try:
        close = data["Close"]
        # Handle MultiIndex columns from yfinance
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        return float(close.dropna().iloc[-1])
    except Exception as exc:
        logger.error("Error getting price for %s: %s", ticker, exc)
        return None


def get_rsi(ticker: str, period: int = None) -> float | None:
    """
    Returns the current RSI value for the ticker.
    Retourne la valeur RSI actuelle pour le ticker.

    Uses a simple Wilder RSI calculation over 1 year of daily data.
    """
    if period is None:
        period = config.RSI_PERIOD

    # Need at least period*2 days of data for a stable RSI
    data = _download_history(ticker, period="1y")
    if data.empty or len(data) < period + 1:
        return None

    try:
        close = data["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        close = close.dropna()

        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        # Wilder smoothing (exponential)
        avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1])
    except Exception as exc:
        logger.error("Error computing RSI for %s: %s", ticker, exc)
        return None


def get_moving_averages(ticker: str) -> dict:
    """
    Returns MA20, MA50, MA200 for the ticker.
    Retourne les moyennes mobiles MA20, MA50, MA200.
    """
    data = _download_history(ticker, period="1y")
    result = {"ma20": None, "ma50": None, "ma200": None}
    if data.empty:
        return result

    try:
        close = data["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        close = close.dropna()

        if len(close) >= 20:
            result["ma20"] = float(close.rolling(20).mean().iloc[-1])
        if len(close) >= 50:
            result["ma50"] = float(close.rolling(50).mean().iloc[-1])
        if len(close) >= 200:
            result["ma200"] = float(close.rolling(200).mean().iloc[-1])
    except Exception as exc:
        logger.error("Error computing moving averages for %s: %s", ticker, exc)

    return result


def is_uptrend(ticker: str) -> bool:
    """
    Returns True if MA50 > MA200 (bullish long-term trend).
    Retourne True si MA50 > MA200 (tendance haussière long terme).
    """
    mas = get_moving_averages(ticker)
    if mas["ma50"] is None or mas["ma200"] is None:
        return False
    return mas["ma50"] > mas["ma200"]


def get_historical_volatility(ticker: str, window: int = None) -> float | None:
    """
    Returns annualized historical volatility (HV) for the ticker.
    Retourne la volatilité historique annualisée (HV) du ticker.

    HV = standard deviation of log returns * sqrt(252)
    """
    if window is None:
        window = config.HV_WINDOW

    # Download extra data to have enough for the rolling window
    data = _download_history(ticker, period="6mo")
    if data.empty or len(data) < window + 1:
        return None

    try:
        close = data["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        close = close.dropna()

        log_returns = np.log(close / close.shift(1)).dropna()
        hv = float(log_returns.rolling(window).std().iloc[-1]) * np.sqrt(
            config.TRADING_DAYS_PER_YEAR
        )
        return round(hv * 100, 2)  # Return as percentage
    except Exception as exc:
        logger.error("Error computing HV for %s: %s", ticker, exc)
        return None


def get_iv_rank(ticker: str) -> float | None:
    """
    Estimates IV Rank using the 52-week high/low of historical volatility.
    Estime l'IV Rank à partir du plus haut/bas de la HV sur 52 semaines.

    IV Rank = (current HV - 52w low HV) / (52w high HV - 52w low HV) * 100

    Note: This is an approximation using HV since yfinance does not provide
    real-time implied volatility for free.
    """
    data = _download_history(ticker, period="1y")
    if data.empty or len(data) < config.HV_WINDOW + 1:
        return None

    try:
        close = data["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        close = close.dropna()

        log_returns = np.log(close / close.shift(1)).dropna()
        # Rolling HV series (annualized, as fraction not percentage here)
        hv_series = (
            log_returns.rolling(config.HV_WINDOW).std()
            * np.sqrt(config.TRADING_DAYS_PER_YEAR)
        ).dropna()

        if len(hv_series) == 0:
            return None

        current_hv = float(hv_series.iloc[-1])
        hv_high = float(hv_series.max())
        hv_low = float(hv_series.min())

        if hv_high == hv_low:
            return 50.0  # No spread → assume mid-rank

        iv_rank = (current_hv - hv_low) / (hv_high - hv_low) * 100
        return round(iv_rank, 2)
    except Exception as exc:
        logger.error("Error computing IV Rank for %s: %s", ticker, exc)
        return None
