# 🎡 Wheel Strategy Scanner

A complete Python-based scanner for the **Wheel Strategy** (options trading). Identifies
Cash Secured Put (CSP) opportunities and checks earnings dates to help traders avoid
unexpected earnings risk.

> **Disclaimer**: This tool is for **educational purposes only**. It is not financial
> advice. Options trading involves significant risk. Always do your own due diligence.

---

## 📁 Project Structure

```
├── main.py                  # Entry point
├── scanner.py               # Core scanning logic
├── earnings_checker.py      # Earnings date verification
├── indicators.py            # Technical indicators (RSI, MA, IV Rank, HV)
├── screener.py              # Option chain analysis / best CSP finder
├── report.py                # Terminal output (Rich) + CSV export
├── config.py                # Configuration (tickers, thresholds)
├── requirements.txt         # Python dependencies
└── README.md                # This file
```

---

## ⚙️ Installation

```bash
# 1. Clone the repository
git clone https://github.com/faridyassine/wheel-strategy-scanner.git
cd wheel-strategy-scanner

# 2. Create a virtual environment (recommended)
python -m venv venv
source venv/bin/activate       # Linux / macOS
venv\Scripts\activate          # Windows

# 3. Install dependencies
pip install -r requirements.txt
```

---

## 🚀 Usage

```bash
python main.py
```

The scanner will:
1. Print a banner
2. Scan all tickers in the watchlist
3. Display a colour-coded summary table
4. Find the best CSP for each passing ticker
5. Print earnings warnings
6. Export results to a timestamped CSV file

---

## 🔍 Checks Performed

| Check | Condition | Notes |
|---|---|---|
| **RSI** | 40 ≤ RSI ≤ 65 | Avoids oversold/overbought extremes |
| **Trend** | MA50 > MA200 | Confirms bullish long-term trend |
| **IV Rank** | IVR ≥ 30% | Ensures premium is worth selling |
| **Earnings** | > 30 days away | Avoids earnings volatility risk |
| **Premium** | Bid ≥ $0.50 | Minimum income per contract |
| **Open Interest** | OI ≥ 500 | Ensures liquidity |
| **DTE** | 21–45 days | Theta decay sweet spot |
| **Delta** | 0.15–0.35 (approx) | Out-of-the-money puts |

---

## ⚙️ Configuration (`config.py`)

All thresholds are configurable:

```python
WATCHLIST = ["AAPL", "MSFT", "AMD", "NVDA", "SPY", "QQQ", "TSLA", ...]

MIN_IV_RANK       = 30    # Minimum IV Rank (%)
MIN_OPEN_INTEREST = 500   # Minimum open interest
MIN_PREMIUM       = 0.50  # Minimum bid price ($)
TARGET_DELTA_MIN  = 0.15  # Minimum approximate delta
TARGET_DELTA_MAX  = 0.35  # Maximum approximate delta
DTE_MIN           = 21    # Minimum days to expiration
DTE_MAX           = 45    # Maximum days to expiration
EARNINGS_SAFE_DAYS = 30   # Minimum days until earnings
RSI_MIN           = 40    # Minimum RSI
RSI_MAX           = 65    # Maximum RSI
```

---

## 📊 Example Output

```
╭──────────────────────────────────────────────╮
│     🎡 Wheel Strategy Scanner                │
│  Scanning for Cash Secured Put opportunities │
╰──────────────────────────────────────────────╯

Step 1/4 — Scanning all tickers…
Step 2/4 — Summary table

╭────────┬─────────┬──────┬────────┬────────┬───────┬──────┬────────┬───────────────┬──────────┬────────╮
│ Ticker │  Price  │ RSI  │  MA50  │ MA200  │ Trend │ IVR% │ HV30 % │ Next Earnings │ DTE Earn │ Status │
├────────┼─────────┼──────┼────────┼────────┼───────┼──────┼────────┼───────────────┼──────────┼────────┤
│  AAPL  │ 185.92$ │ 52.3 │ 183.10 │ 178.40 │  ✅   │ 42.1 │ 18.5%  │  2024-08-01   │    45    │ PASS ✅│
│  TSLA  │ 178.21$ │ 28.7 │ 195.30 │ 215.10 │  ❌   │ 65.2 │ 55.3%  │  2024-07-17   │    12    │ FAIL ❌│
╰────────┴─────────┴──────┴────────┴────────┴───────┴──────┴────────┴───────────────┴──────────┴────────╯

Step 3/4 — Finding best CSP for 1 passing ticker(s)…

╭────────┬─────────┬────────┬────────────┬─────┬─────────┬──────┬─────────┬───────────╮
│ Ticker │  Price  │ Strike │   Expiry   │ DTE │ Premium │  OI  │ Δ Approx│ Monthly % │
├────────┼─────────┼────────┼────────────┼─────┼─────────┼──────┼─────────┼───────────┤
│  AAPL  │ 185.92$ │ 175.00$│ 2024-08-16 │  32 │  1.45$  │ 2340 │   0.220 │   0.76%   │
╰────────┴─────────┴────────┴────────────┴─────┴─────────┴──────┴─────────┴───────────╯

⚠️  Earnings Warnings
────────────────────────────────────────────────────
  ⚠️  TSLA — earnings in 12 days (next: 2024-07-17)

📄 Results exported to wheel_scan_20240705_143022.csv
```

---

## 📝 Notes

- **IV Rank is approximated** using 52-week historical volatility (HV). Real implied
  volatility requires a paid data feed. The approximation works well for relative
  comparisons within the watchlist.
- **Delta is approximated** using moneyness (strike / price). For precise delta values,
  use a broker platform with live Greeks (e.g., Thinkorswim, Tastyworks, IBKR).
- **yfinance** is used as the sole data source — it is free and requires no API key, but
  data quality and availability may vary.
- All external data calls have `try/except` error handling and will log warnings if data
  is unavailable for a ticker.

---

## 📦 Dependencies

| Package | Purpose |
|---|---|
| `yfinance` | Market data (prices, options, earnings calendar) |
| `pandas` | Data manipulation |
| `numpy` | Numerical calculations (HV, RSI) |
| `rich` | Beautiful coloured terminal output |
| `tabulate` | Table formatting (optional) |
| `requests` | HTTP requests |

---

## 📜 License

MIT License — see [LICENSE](LICENSE) for details.

