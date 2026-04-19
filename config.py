# config.py — Configuration for the Wheel Strategy Scanner
# Fichier de configuration pour le scanner de stratégie de la roue

# === Watchlist — Liste des titres à surveiller ===
WATCHLIST = [
    "AAPL",   # Apple
    "MSFT",   # Microsoft
    "AMD",    # Advanced Micro Devices
    "NVDA",   # NVIDIA
    "SPY",    # S&P 500 ETF
    "QQQ",    # Nasdaq 100 ETF
    "TSLA",   # Tesla
    "AMZN",   # Amazon
    "GOOGL",  # Alphabet
    "META",   # Meta Platforms
    "JPM",    # JPMorgan Chase
    "BAC",    # Bank of America
    "XOM",    # ExxonMobil
    "GLD",    # Gold ETF
    "SOFI",   # SoFi Technologies
    "SLV",    # Silver ETF
]

# === Thresholds — Seuils de filtrage ===

# IV Rank minimum (%) — rang de volatilité implicite minimum
MIN_IV_RANK = 30

# Open Interest minimum — intérêt ouvert minimum pour la liquidité
MIN_OPEN_INTEREST = 500

# Prime minimum (bid price) en dollars
MIN_PREMIUM = 0.50

# Delta cible pour les Cash Secured Puts (approximé par moneyness)
TARGET_DELTA_MIN = 0.15
TARGET_DELTA_MAX = 0.35

# Jours jusqu'à l'expiration (DTE) — Days to Expiration
DTE_MIN = 21
DTE_MAX = 45

# Jours de sécurité avant les résultats d'entreprise (earnings)
EARNINGS_SAFE_DAYS = 30

# RSI — Relative Strength Index
RSI_MIN = 40
RSI_MAX = 65

# Période RSI (jours)
RSI_PERIOD = 14

# Fenêtre pour la volatilité historique (jours)
HV_WINDOW = 30

# Nombre de jours de trading dans une année (pour annualisation HV)
TRADING_DAYS_PER_YEAR = 252
