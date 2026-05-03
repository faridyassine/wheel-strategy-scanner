# app.py — Streamlit dashboard for the Wheel Strategy Scanner
# Interface visuelle pour le scanner de stratégie de la roue
from __future__ import annotations

import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

try:
    from groq import Groq
except Exception:
    Groq = None

import config
import scanner
import screener
import telegram_bot
import telegram_notifier


def _get_groq_api_key() -> str | None:
    """Returns Groq API key from session, Streamlit secrets, or environment."""
    session_key = st.session_state.get("groq_api_key")
    if session_key:
        return session_key

    secret_key = None
    try:
        secret_key = st.secrets.get("GROQ_API_KEY")
    except Exception:
        secret_key = None
    if secret_key:
        return secret_key

    return os.getenv("GROQ_API_KEY")


def _build_chat_context(results: list[dict] | None, opportunities: list[dict] | None) -> str:
    """Builds compact context from latest scan to help chatbot answers."""
    if not results:
        return (
            "Aucun scan exécuté pour le moment. "
            "L'utilisateur peut poser des questions générales sur la Wheel Strategy."
        )

    passing_count = sum(1 for r in results if r.get("passes_all"))
    tickers = [r.get("ticker", "?") for r in results[:20]]
    top_opps = (opportunities or [])[:5]
    top_opp_text = [
        (
            f"{o.get('ticker', '?')}: strike={o.get('strike')}, premium={o.get('premium')}, "
            f"dte={o.get('dte')}, return30j={o.get('monthly_return_pct')}%"
        )
        for o in top_opps
    ]

    return (
        f"Résultats scan: {len(results)} tickers, {passing_count} passent les filtres. "
        f"Tickers: {', '.join(tickers)}. "
        f"Top opportunités CSP: {' | '.join(top_opp_text) if top_opp_text else 'Aucune'}"
    )


def _ask_groq(chat_messages: list[dict], context: str) -> str:
    """Calls Groq chat completion with app context."""
    if Groq is None:
        return (
            "Le package `groq` n'est pas disponible dans cet environnement. "
            "Installe-le avec `pip install groq`."
        )

    api_key = _get_groq_api_key()
    if not api_key:
        return (
            "Ajoute ta clé API Groq (`GROQ_API_KEY`) dans les variables d'environnement "
            "ou dans le champ dédié de l'interface."
        )

    client = Groq(api_key=api_key)
    history = chat_messages[-8:] if len(chat_messages) > 8 else chat_messages
    messages = [
        {
            "role": "system",
            "content": (
                "Tu es un assistant francophone expert en Wheel Strategy. "
                "Réponds de façon claire, concise, pédagogique. "
                "N'invente pas de données et précise quand une information manque. "
                "Rappelle que ce n'est pas un conseil financier."
            ),
        },
        {"role": "system", "content": f"Contexte application: {context}"},
        *history,
    ]

    response = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=messages,
        temperature=0.2,
        max_tokens=500,
    )
    content = response.choices[0].message.content
    return content.strip() if content else "Je n'ai pas pu générer de réponse."


def _render_chatbot(results: list[dict] | None = None, opportunities: list[dict] | None = None) -> None:
    """Renders chatbot UI and handles message flow."""
    st.subheader("🤖 Assistant Wheel (Groq)")
    st.caption("Pose des questions sur IVR, HV30, choix de strikes, DTE, ou résultats du scan.")

    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = [
            {
                "role": "assistant",
                "content": (
                    "Salut 👋 Je peux expliquer les métriques du scanner et t'aider "
                    "à interpréter les opportunités CSP."
                ),
            }
        ]

    with st.expander("⚙️ Configuration API Groq", expanded=False):
        st.caption("Option 1: variable d'environnement `GROQ_API_KEY` (recommandé)")
        st.caption("Option 2: coller la clé ici pour la session courante")
        user_api_key = st.text_input(
            "GROQ API Key (session)",
            type="password",
            key="groq_api_key_input",
            placeholder="gsk_...",
        )
        if user_api_key:
            st.session_state.groq_api_key = user_api_key.strip()
            st.success("Clé Groq chargée pour cette session.")

    context = _build_chat_context(results, opportunities)

    for message in st.session_state.chat_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    prompt = st.chat_input("Ex: Pourquoi AAPL passe et TSLA échoue ?")
    if prompt:
        st.session_state.chat_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Réflexion en cours..."):
                try:
                    answer = _ask_groq(st.session_state.chat_messages, context)
                except Exception as exc:
                    answer = f"Erreur Groq: {exc}"
                st.markdown(answer)

        st.session_state.chat_messages.append({"role": "assistant", "content": answer})


@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_fundamentals(ticker: str) -> dict:
    """Fetches basic fundamentals from yfinance (cached for 1h)."""
    try:
        info = yf.Ticker(ticker).info or {}
        return info if isinstance(info, dict) else {}
    except Exception:
        return {}


def _to_float(value):
    """Converts value to float when possible."""
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _long_term_score_row(ticker: str, scan_data: dict) -> dict:
    """Builds a long-term checklist row and score on 10."""
    info = _fetch_fundamentals(ticker)

    revenue_growth = _to_float(info.get("revenueGrowth"))
    earnings_growth = _to_float(info.get("earningsGrowth"))
    roe = _to_float(info.get("returnOnEquity"))
    operating_margin = _to_float(info.get("operatingMargins"))
    debt_to_equity = _to_float(info.get("debtToEquity"))
    free_cashflow = _to_float(info.get("freeCashflow"))
    trailing_pe = _to_float(info.get("trailingPE"))
    peg = _to_float(info.get("pegRatio"))

    rsi = scan_data.get("rsi")
    uptrend = bool(scan_data.get("uptrend"))

    checks = {
        "Rev > 8%": revenue_growth is not None and revenue_growth >= 0.08,
        "EPS > 8%": earnings_growth is not None and earnings_growth >= 0.08,
        "ROE > 12%": roe is not None and roe >= 0.12,
        "Marge op > 15%": operating_margin is not None and operating_margin >= 0.15,
        "Dette OK": debt_to_equity is not None and debt_to_equity <= 100,
        "FCF positif": free_cashflow is not None and free_cashflow > 0,
        "PE raisonnable": trailing_pe is not None and trailing_pe > 0 and trailing_pe <= 30,
        "PEG <= 2": peg is not None and peg > 0 and peg <= 2,
        "Tendance LT": uptrend,
        "RSI 45-65": rsi is not None and 45 <= rsi <= 65,
    }

    score = sum(1 for ok in checks.values() if ok)

    return {
        "Ticker": ticker,
        "Score (/10)": score,
        "Verdict": "✅ Solide" if score >= 8 else ("🟡 Correct" if score >= 6 else "🔴 Risqué"),
        "Croissance CA": f"{revenue_growth * 100:.1f}%" if revenue_growth is not None else "N/A",
        "Croissance EPS": f"{earnings_growth * 100:.1f}%" if earnings_growth is not None else "N/A",
        "ROE": f"{roe * 100:.1f}%" if roe is not None else "N/A",
        "Marge op.": f"{operating_margin * 100:.1f}%" if operating_margin is not None else "N/A",
        "Debt/Equity": f"{debt_to_equity:.1f}" if debt_to_equity is not None else "N/A",
        "FCF": f"{free_cashflow:,.0f}" if free_cashflow is not None else "N/A",
        "PE": f"{trailing_pe:.1f}" if trailing_pe is not None else "N/A",
        "PEG": f"{peg:.2f}" if peg is not None else "N/A",
        "RSI": f"{rsi:.1f}" if rsi is not None else "N/A",
        "Uptrend": "✅" if uptrend else "❌",
        "Checks OK": f"{score}/10",
    }

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="🎡 Wheel Strategy Scanner",
    page_icon="🎡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ─────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    .metric-card { background: #1e1e2e; border-radius: 10px; padding: 1rem; }
    .pass-badge  { color: #00e676; font-weight: bold; }
    .fail-badge  { color: #ff5252; font-weight: bold; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Sidebar — Configuration ────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ Configuration")
    st.markdown("---")

    # Watchlist editor
    st.subheader("📋 Watchlist")
    watchlist_input = st.text_area(
        "Tickers (un par ligne)",
        value="\n".join(config.WATCHLIST),
        height=280,
    )
    watchlist = [t.strip().upper() for t in watchlist_input.splitlines() if t.strip()]

    st.markdown("---")
    st.subheader("🎛️ Filtres")

    min_iv_rank = st.slider("IV Rank minimum (%)", 0, 100, config.MIN_IV_RANK)
    rsi_min = st.slider("RSI minimum", 0, 100, config.RSI_MIN)
    rsi_max = st.slider("RSI maximum", 0, 100, config.RSI_MAX)
    dte_min = st.slider("DTE minimum", 1, 60, config.DTE_MIN)
    dte_max = st.slider("DTE maximum", 1, 90, config.DTE_MAX)
    min_premium = st.number_input("Prime minimum ($)", value=config.MIN_PREMIUM, step=0.10)
    min_oi = st.number_input("Open Interest minimum", value=config.MIN_OPEN_INTEREST, step=100)
    earnings_safe_days = st.slider("Sécurité earnings (jours)", 7, 90, config.EARNINGS_SAFE_DAYS)

    # Override config temporarily for the scan
    config.MIN_IV_RANK = min_iv_rank
    config.RSI_MIN = rsi_min
    config.RSI_MAX = rsi_max
    config.DTE_MIN = dte_min
    config.DTE_MAX = dte_max
    config.MIN_PREMIUM = min_premium
    config.MIN_OPEN_INTEREST = int(min_oi)
    config.EARNINGS_SAFE_DAYS = earnings_safe_days

    st.markdown("---")
    run_btn = st.button("🚀 Lancer le scan", use_container_width=True, type="primary")

    st.markdown("---")
    st.subheader("📩 Telegram")
    _default_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    _default_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    tg_token = st.text_input(
        "Bot Token",
        value=st.session_state.get("tg_token", _default_token),
        type="password",
        placeholder="123456:ABC-DEF...",
        key="tg_token_input",
    )
    tg_chat_id = st.text_input(
        "Chat ID",
        value=st.session_state.get("tg_chat_id", _default_chat_id),
        placeholder="-100123456789",
        key="tg_chat_id_input",
    )
    if tg_token:
        st.session_state.tg_token = tg_token.strip()
    if tg_chat_id:
        st.session_state.tg_chat_id = tg_chat_id.strip()
    if st.button("🔔 Tester la connexion Telegram", use_container_width=True):
        _token = st.session_state.get("tg_token") or os.getenv("TELEGRAM_BOT_TOKEN", "")
        _chat_id = st.session_state.get("tg_chat_id") or os.getenv("TELEGRAM_CHAT_ID", "")
        ok, msg = telegram_notifier.send_message(
            "✅ Wheel Scanner connecté !",
            token=_token,
            chat_id=_chat_id,
        )
        st.success(msg) if ok else st.error(msg)

    st.markdown("---")
    st.subheader("🤖 Bot Telegram ↔️ Groq")
    bot_running = telegram_bot.is_polling()

    # Auto-start once per Streamlit session when credentials are available.
    if not bot_running and not st.session_state.get("tg_autostart_attempted", False):
        st.session_state.tg_autostart_attempted = True
        _tg_token = st.session_state.get("tg_token") or os.getenv("TELEGRAM_BOT_TOKEN", "")
        _groq_key = st.session_state.get("groq_api_key") or os.getenv("GROQ_API_KEY", "")
        if _tg_token and _groq_key:
            ok, msg = telegram_bot.start_polling(_tg_token, _groq_key)
            st.session_state.tg_autostart_msg = msg
            if ok:
                st.rerun()

    st.caption("🟢 Bot actif" if bot_running else "🔴 Bot arrêté")

    autostart_msg = st.session_state.pop("tg_autostart_msg", None)
    if autostart_msg:
        if telegram_bot.is_polling():
            st.success(f"Auto-start: {autostart_msg}")
        else:
            st.warning(f"Auto-start: {autostart_msg}")

    if not bot_running:
        if st.button("▶️ Démarrer le bot", use_container_width=True):
            _tg_token = st.session_state.get("tg_token") or os.getenv("TELEGRAM_BOT_TOKEN", "")
            _groq_key = st.session_state.get("groq_api_key") or os.getenv("GROQ_API_KEY", "")
            ok, msg = telegram_bot.start_polling(_tg_token, _groq_key)
            st.success(msg) if ok else st.error(msg)
            st.rerun()
    else:
        if st.button("⏹️ Arrêter le bot", use_container_width=True):
            telegram_bot.stop_polling()
            st.info("⏹️ Bot Telegram arrêté.")
            st.rerun()

    st.markdown("---")
    if st.button("🧹 Vider l'historique du chat", use_container_width=True):
        st.session_state.chat_messages = []

# ── Main area ──────────────────────────────────────────────────────────────────
st.title("🎡 Wheel Strategy Scanner")
st.caption("Scanner automatique de Cash Secured Put — données en temps réel via yfinance")

# ── State persistence ──────────────────────────────────────────────────────────
if "results" not in st.session_state:
    st.session_state.results = None
if "opportunities" not in st.session_state:
    st.session_state.opportunities = []
if "long_term_rows" not in st.session_state:
    st.session_state.long_term_rows = None
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []

# ── Run scan ───────────────────────────────────────────────────────────────────
if run_btn:
    with st.spinner(f"⏳ Scan de {len(watchlist)} tickers en cours…"):
        results = scanner.scan_all(watchlist)
        passing = scanner.get_passing_tickers(results)

        opportunities = []
        progress = st.progress(0, text="Analyse des options…")
        for i, r in enumerate(passing):
            ticker = r["ticker"]
            try:
                csp = screener.find_best_csp(ticker, current_price=r.get("price"))
                if csp:
                    opportunities.append(csp)
            except Exception:
                pass
            progress.progress((i + 1) / max(len(passing), 1), text=f"Options : {ticker}")
        progress.empty()

        st.session_state.results = results
        st.session_state.opportunities = opportunities
        st.session_state.long_term_rows = None
        telegram_bot.update_scan_context(results, opportunities)
    st.success("✅ Scan terminé !")

# ── Display results ─────────────────────────────────────────────────────────────
if st.session_state.results:
    results = st.session_state.results
    opportunities = st.session_state.opportunities
    passing_count = sum(1 for r in results if r.get("passes_all"))

    # ── KPI Metrics ──────────────────────────────────────────────────────────
    st.markdown("### 📊 Résumé")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Tickers scannés", len(results))
    col2.metric("✅ Passent les filtres", passing_count)
    col3.metric("💰 Opportunités CSP", len(opportunities))
    avg_yield = (
        round(sum(o["monthly_return_pct"] for o in opportunities) / len(opportunities), 2)
        if opportunities else 0
    )
    col4.metric("📈 Rendement 30j moyen", f"{avg_yield}%")

    st.markdown("---")

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
        [
            "📋 Tableau complet",
            "💰 Opportunités CSP",
            "📈 Graphiques",
            "⚠️ Alertes Earnings",
            "🏦 Achat Long Terme",
            "🤖 Chatbot",
        ]
    )

    # ── Tab 1 : Summary table ─────────────────────────────────────────────────
    with tab1:
        st.subheader("Résultats de tous les tickers")

        df = pd.DataFrame([
            {
                "Ticker":        r["ticker"],
                "Prix ($)":      r.get("price"),
                "RSI":           r.get("rsi"),
                "MA50":          r.get("ma50"),
                "MA200":         r.get("ma200"),
                "Tendance":      "✅" if r.get("uptrend") else "❌",
                "IVR (%)":       r.get("iv_rank"),
                "HV30 (%)":      r.get("hv_30"),
                "Prochains Earl.": r.get("next_earnings", "N/A"),
                "J. avant Earl.": r.get("days_to_earnings"),
                "Statut":        "✅ PASS" if r.get("passes_all") else "❌ FAIL",
                "Raison":        r.get("reason_failed", ""),
            }
            for r in results
        ])

        def _style_row(row):
            color = "#1a472a" if row["Statut"] == "✅ PASS" else "#5c1a1a"
            return [f"background-color: {color}; color: white"] * len(row)

        def _style_rsi(val):
            try:
                v = float(val)
                if v < config.RSI_MIN:
                    return "color: #ff5252"
                if v > config.RSI_MAX:
                    return "color: #ffab40"
                return "color: #00e676"
            except Exception:
                return ""

        def _style_ivr(val):
            try:
                v = float(val)
                if v >= 50:
                    return "color: #00e676"
                if v >= config.MIN_IV_RANK:
                    return "color: #ffab40"
                return "color: #ff5252"
            except Exception:
                return ""

        styled = (
            df.style
            .apply(_style_row, axis=1)
            .map(_style_rsi, subset=["RSI"])
            .map(_style_ivr, subset=["IVR (%)"])
            .format({
                "Prix ($)": lambda x: f"{x:.2f}" if x else "N/A",
                "RSI":      lambda x: f"{x:.1f}" if x else "N/A",
                "MA50":     lambda x: f"{x:.2f}" if x else "N/A",
                "MA200":    lambda x: f"{x:.2f}" if x else "N/A",
                "IVR (%)":  lambda x: f"{x:.1f}" if x else "N/A",
                "HV30 (%)": lambda x: f"{x:.1f}" if x else "N/A",
            }, na_rep="N/A")
        )
        st.dataframe(styled, use_container_width=True, height=500)

        # Download CSV
        csv_data = df.to_csv(index=False).encode("utf-8")
        col_dl, col_tg = st.columns(2)
        with col_dl:
            st.download_button(
                "⬇️ Télécharger CSV",
                data=csv_data,
                file_name="wheel_scan.csv",
                mime="text/csv",
            )
        with col_tg:
            if st.button("📩 Envoyer résumé Telegram", use_container_width=True, key="tg_summary"):
                passing = [r for r in results if r.get("passes_all")]
                text = telegram_notifier.build_scan_summary(results, opportunities)
                _token = st.session_state.get("tg_token") or os.getenv("TELEGRAM_BOT_TOKEN", "")
                _chat_id = st.session_state.get("tg_chat_id") or os.getenv("TELEGRAM_CHAT_ID", "")
                ok, msg = telegram_notifier.send_message(
                    text,
                    token=_token,
                    chat_id=_chat_id,
                )
                st.success(msg) if ok else st.error(msg)

    # ── Tab 2 : CSP Opportunities ─────────────────────────────────────────────
    with tab2:
        if not opportunities:
            st.warning("⚠️ Aucune opportunité CSP trouvée avec les critères actuels.")
        else:
            st.subheader(f"💰 {len(opportunities)} meilleures opportunités de Cash Secured Put")

            df_opp = pd.DataFrame([
                {
                    "Ticker":        o["ticker"],
                    "Prix actuel ($)": o.get("current_price"),
                    "Strike ($)":    o.get("strike"),
                    "Expiration":    o.get("expiry"),
                    "DTE":           o.get("dte"),
                    "Prime ($)":     o.get("premium"),
                    "Open Interest": o.get("open_interest"),
                    "Δ Approx":      o.get("delta_approx"),
                    "Rendement 30j (%)": o.get("monthly_return_pct"),
                    "Capital requis ($)": round(o.get("strike", 0) * 100, 2),
                    "Revenu/contrat ($)": round(o.get("premium", 0) * 100, 2),
                }
                for o in opportunities
            ]).sort_values("Rendement 30j (%)", ascending=False)

            def _style_yield(val):
                try:
                    v = float(val)
                    if v >= 3:
                        return "color: #00e676; font-weight: bold"
                    if v >= 1.5:
                        return "color: #ffab40"
                    return "color: #ff5252"
                except Exception:
                    return ""

            def _bg_yield(val):
                try:
                    v = float(val)
                    if v >= 3:
                        return "background-color: #27ae60; color: white; font-weight: bold"
                    if v >= 1.5:
                        return "background-color: #e67e22; color: white; font-weight: bold"
                    return "background-color: #e74c3c; color: white; font-weight: bold"
                except Exception:
                    return ""

            styled_opp = (
                df_opp.style
                .map(_bg_yield, subset=["Rendement 30j (%)"])
                .format({
                    "Prix actuel ($)":    "{:.2f}",
                    "Strike ($)":         "{:.2f}",
                    "Prime ($)":          "{:.2f}",
                    "Δ Approx":           "{:.3f}",
                    "Rendement 30j (%)":  "{:.2f}%",
                    "Capital requis ($)":  "{:.0f}",
                    "Revenu/contrat ($)":  "{:.0f}",
                }, na_rep="N/A")
            )
            st.dataframe(styled_opp, use_container_width=True)

            if st.button("📩 Envoyer opportunités Telegram", use_container_width=True, key="tg_opps"):
                text = telegram_notifier.build_opportunities_message(opportunities)
                _token = st.session_state.get("tg_token") or os.getenv("TELEGRAM_BOT_TOKEN", "")
                _chat_id = st.session_state.get("tg_chat_id") or os.getenv("TELEGRAM_CHAT_ID", "")
                ok, msg = telegram_notifier.send_message(
                    text,
                    token=_token,
                    chat_id=_chat_id,
                )
                st.success(msg) if ok else st.error(msg)

            # Best pick highlight
            best = df_opp.iloc[0]
            st.markdown("---")
            st.markdown(f"### 🏆 Meilleure opportunité : **{best['Ticker']}**")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Strike", f"${best['Strike ($)']:.2f}")
            c2.metric("Prime / contrat", f"${best['Revenu/contrat ($)']:.0f}")
            c3.metric("Rendement 30j", f"{best['Rendement 30j (%)']:.2f}%")
            c4.metric("Expiration", best["Expiration"])

    # ── Tab 3 : Charts ────────────────────────────────────────────────────────
    with tab3:
        st.subheader("📈 Visualisation des indicateurs")

        tickers_clean = [r["ticker"] for r in results]
        rsi_vals  = [r.get("rsi") or 0 for r in results]
        ivr_vals  = [r.get("iv_rank") or 0 for r in results]
        hv_vals   = [r.get("hv_30") or 0 for r in results]
        colors    = ["#00e676" if r.get("passes_all") else "#ff5252" for r in results]

        col_a, col_b = st.columns(2)

        # RSI chart
        with col_a:
            fig_rsi = go.Figure(go.Bar(
                x=tickers_clean,
                y=rsi_vals,
                marker_color=colors,
                text=[f"{v:.1f}" for v in rsi_vals],
                textposition="outside",
            ))
            fig_rsi.add_hline(y=config.RSI_MIN, line_dash="dash", line_color="orange",
                              annotation_text=f"RSI min {config.RSI_MIN}")
            fig_rsi.add_hline(y=config.RSI_MAX, line_dash="dash", line_color="red",
                              annotation_text=f"RSI max {config.RSI_MAX}")
            fig_rsi.update_layout(
                title="RSI par ticker",
                yaxis_range=[0, 100],
                plot_bgcolor="#0e1117",
                paper_bgcolor="#0e1117",
                font_color="white",
            )
            st.plotly_chart(fig_rsi, use_container_width=True)

        # IV Rank chart
        with col_b:
            fig_ivr = go.Figure(go.Bar(
                x=tickers_clean,
                y=ivr_vals,
                marker_color=colors,
                text=[f"{v:.1f}%" for v in ivr_vals],
                textposition="outside",
            ))
            fig_ivr.add_hline(y=config.MIN_IV_RANK, line_dash="dash", line_color="orange",
                              annotation_text=f"IVR min {config.MIN_IV_RANK}%")
            fig_ivr.update_layout(
                title="IV Rank (%) par ticker",
                yaxis_range=[0, 110],
                plot_bgcolor="#0e1117",
                paper_bgcolor="#0e1117",
                font_color="white",
            )
            st.plotly_chart(fig_ivr, use_container_width=True)

        # HV30 chart (full width)
        fig_hv = go.Figure(go.Bar(
            x=tickers_clean,
            y=hv_vals,
            marker_color="#4fc3f7",
            text=[f"{v:.1f}%" for v in hv_vals],
            textposition="outside",
        ))
        fig_hv.update_layout(
            title="Volatilité Historique 30j (HV30) par ticker",
            yaxis_title="HV30 (%)",
            plot_bgcolor="#0e1117",
            paper_bgcolor="#0e1117",
            font_color="white",
        )
        st.plotly_chart(fig_hv, use_container_width=True)

        # Scatter : IVR vs RSI
        if opportunities:
            st.markdown("#### Rendement 30j vs Capital requis (opportunités CSP)")
            fig_scatter = go.Figure()
            for o in opportunities:
                fig_scatter.add_trace(go.Scatter(
                    x=[o["strike"] * 100],
                    y=[o["monthly_return_pct"]],
                    mode="markers+text",
                    text=[o["ticker"]],
                    textposition="top center",
                    marker=dict(size=14, color="#00e676"),
                    name=o["ticker"],
                    showlegend=False,
                ))
            fig_scatter.update_layout(
                xaxis_title="Capital requis ($)",
                yaxis_title="Rendement 30j (%)",
                plot_bgcolor="#0e1117",
                paper_bgcolor="#0e1117",
                font_color="white",
            )
            st.plotly_chart(fig_scatter, use_container_width=True)

    # ── Tab 4 : Earnings Warnings ─────────────────────────────────────────────
    with tab4:
        st.subheader("⚠️ Alertes Earnings")

        danger = [r for r in results if not r.get("earnings_safe", True)]
        unknown = [r for r in results if r.get("next_earnings") == "Unknown"]
        safe = [r for r in results if r.get("earnings_safe", True) and r.get("next_earnings") != "Unknown"]

        if danger:
            st.error(f"🚨 {len(danger)} ticker(s) ont des earnings dans moins de {config.EARNINGS_SAFE_DAYS} jours !")
            for r in danger:
                st.warning(
                    f"**{r['ticker']}** — Earnings dans **{r['days_to_earnings']} jours** "
                    f"({r.get('next_earnings', 'N/A')})"
                )
        else:
            st.success(f"✅ Aucun ticker n'a d'earnings dans les {config.EARNINGS_SAFE_DAYS} prochains jours.")

        if unknown:
            st.markdown("---")
            st.markdown("**❓ Dates d'earnings inconnues :**")
            cols = st.columns(5)
            for i, r in enumerate(unknown):
                cols[i % 5].info(r["ticker"])

        if safe:
            st.markdown("---")
            st.markdown("**✅ Tickers avec earnings sécurisés :**")
            df_safe = pd.DataFrame([
                {"Ticker": r["ticker"], "Prochains Earl.": r.get("next_earnings"), "Jours restants": r.get("days_to_earnings")}
                for r in safe if r.get("next_earnings") not in ("Unknown", "N/A")
            ])
            if not df_safe.empty:
                st.dataframe(df_safe, use_container_width=True)

    # ── Tab 5 : Long-term stock checklist ────────────────────────────────────
    with tab5:
        st.subheader("🏦 Checklist d'achat Long Terme")
        st.caption("Module additionnel. Les fonctionnalités options CSP existantes sont inchangées.")

        col_l1, col_l2 = st.columns([2, 1])
        with col_l1:
            st.markdown(
                """
                **Score basé sur 10 critères :** croissance CA, croissance EPS, ROE, marge,
                dette, cashflow, valorisation, tendance et RSI.
                """
            )
        with col_l2:
            run_long_term = st.button("📚 Analyser Long Terme", use_container_width=True)

        if run_long_term or st.session_state.long_term_rows is not None:
            if run_long_term:
                scan_lookup = {r["ticker"]: r for r in results}
                tickers = [r["ticker"] for r in results]
                rows = []
                prog = st.progress(0, text="Récupération des fondamentaux…")
                for i, t in enumerate(tickers):
                    rows.append(_long_term_score_row(t, scan_lookup.get(t, {})))
                    prog.progress((i + 1) / max(len(tickers), 1), text=f"Analyse long terme : {t}")
                prog.empty()
                st.session_state.long_term_rows = rows

            rows = st.session_state.long_term_rows or []
            if rows:
                df_lt = pd.DataFrame(rows).sort_values("Score (/10)", ascending=False)

                def _style_verdict(val):
                    if "Solide" in str(val):
                        return "background-color: #27ae60; color: white; font-weight: bold"
                    if "Correct" in str(val):
                        return "background-color: #e67e22; color: white; font-weight: bold"
                    return "background-color: #e74c3c; color: white; font-weight: bold"

                styled_lt = (
                    df_lt.style
                    .map(_style_verdict, subset=["Verdict"])
                )
                st.dataframe(styled_lt, use_container_width=True, height=520)

                top = df_lt.iloc[0]
                c1, c2, c3 = st.columns(3)
                c1.metric("Meilleur score", f"{top['Ticker']} ({top['Score (/10)']}/10)")
                c2.metric("Nombre d'actions solides", int((df_lt["Score (/10)"] >= 8).sum()))
                c3.metric("Score moyen", f"{df_lt['Score (/10)'].mean():.1f}/10")

                st.info(
                    "Règle simple: privilégier les actions ≥ 8/10, renforcer progressivement (DCA), "
                    "et éviter une concentration excessive sur un seul secteur."
                )
            else:
                st.warning("Aucune donnée long terme disponible pour le moment.")

    # ── Tab 6 : Chatbot ──────────────────────────────────────────────────────
    with tab6:
        _render_chatbot(results=results, opportunities=opportunities)

else:
    # ── Welcome screen ────────────────────────────────────────────────────────
    st.markdown(
        """
        ## Bienvenue 👋

        Ce dashboard vous permet de scanner automatiquement des opportunités de **Cash Secured Put**
        en appliquant les critères de la **Wheel Strategy**.

        ### Comment l'utiliser :
        1. 📋 **Configurez votre watchlist** dans le panneau gauche
        2. 🎛️ **Ajustez les filtres** (IV Rank, RSI, DTE, etc.)
        3. 🚀 **Cliquez sur "Lancer le scan"**
        4. 📊 **Explorez les résultats** dans les 4 onglets

        ### Ce qui est analysé pour chaque ticker :
        | Critère | Description |
        |---------|-------------|
        | **RSI** | Ni suracheté ni survendu |
        | **Tendance** | MA50 > MA200 (Golden Cross) |
        | **IV Rank** | Prime suffisamment élevée |
        | **Earnings** | Résultats pas trop proches |
        """,
        unsafe_allow_html=False,
    )
    st.info("👈 Configurez et lancez le scan depuis le panneau de gauche.")
    st.markdown("---")
    _render_chatbot(results=None, opportunities=None)
