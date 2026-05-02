# telegram_bot.py — Telegram ↔ Groq bridge for the Wheel Strategy Scanner
#
# Flow: messages Telegram  →  commandes OU  Groq (LLM)  →  réponse Telegram
#
# Commandes supportées :
#   /start            — message de bienvenue
#   /reset            — vide l'historique du chat
#   /help             — liste des commandes
#   /watchlist        — affiche la watchlist courante
#   /results          — affiche les derniers résultats de scan
#   /scan <TICKER>    — scanne un ticker (RSI, IVR, uptrend, earnings)
#   /scan <TICKER> <PRIX> — scan + meilleur covered call si acheté à PRIX
#   /scan wheel <TICKER> — scan + meilleur CSP (put)
#   /csp <TICKER>     — trouve le meilleur CSP (put) pour un ticker
#
# Utilise le long-polling Telegram (getUpdates) dans un thread daemon.
# Ce module est lancé depuis app.py via start_polling().

from __future__ import annotations

import logging
import threading
import time
from typing import Optional

import requests

import config
import scanner as _scanner
import screener as _screener

logger = logging.getLogger(__name__)

_TELEGRAM_BASE = "https://api.telegram.org/bot{token}"

# Conserve l'historique de conversation par chat_id  {chat_id: [{"role":..,"content":..}]}
_histories: dict[str, list[dict]] = {}
_MAX_HISTORY = 12  # messages gardés en contexte

# Référence partagée vers les derniers résultats du scan (mise à jour depuis app.py)
_scan_context: dict = {
    "results": None,
    "opportunities": None,
}


def update_scan_context(results: list[dict] | None, opportunities: list[dict] | None) -> None:
    """Called from app.py after each scan to keep the bot context up to date."""
    _scan_context["results"] = results
    _scan_context["opportunities"] = opportunities


# ── Telegram helpers ──────────────────────────────────────────────────────────

def _tg(token: str, method: str, **kwargs) -> dict:
    url = f"{_TELEGRAM_BASE.format(token=token)}/{method}"
    try:
        resp = requests.post(url, json=kwargs, timeout=15)
        return resp.json()
    except Exception as exc:
        logger.error("Telegram %s error: %s", method, exc)
        return {"ok": False}


def _send(token: str, chat_id: str | int, text: str) -> None:
    _tg(token, "sendMessage",
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        disable_web_page_preview=True)


def _send_typing(token: str, chat_id: str | int) -> None:
    _tg(token, "sendChatAction", chat_id=chat_id, action="typing")


# ── Groq helper ───────────────────────────────────────────────────────────────

def _build_context_text() -> str:
    results = _scan_context.get("results")
    opportunities = _scan_context.get("opportunities") or []

    if not results:
        return (
            "Aucun scan exécuté pour le moment. "
            "L'utilisateur peut poser des questions générales sur la Wheel Strategy."
        )

    passing_count = sum(1 for r in results if r.get("passes_all"))
    tickers = [r.get("ticker", "?") for r in results[:20]]
    top_opps = opportunities[:5]
    top_opp_text = [
        (
            f"{o.get('ticker','?')}: strike={o.get('strike')}, premium={o.get('premium')}, "
            f"dte={o.get('dte')}, return30j={o.get('monthly_return_pct')}%"
        )
        for o in top_opps
    ]
    return (
        f"Résultats scan: {len(results)} tickers, {passing_count} passent les filtres. "
        f"Tickers: {', '.join(tickers)}. "
        f"Top opportunités CSP: {' | '.join(top_opp_text) if top_opp_text else 'Aucune'}"
    )


def _ask_groq(groq_api_key: str, chat_id: str, user_message: str) -> str:
    try:
        from groq import Groq  # type: ignore
    except ImportError:
        return "❌ Package `groq` non disponible. Installe-le avec `pip install groq`."

    if not groq_api_key:
        return "❌ Clé API Groq manquante. Configure `GROQ_API_KEY` dans l'application."

    history = _histories.setdefault(chat_id, [])
    history.append({"role": "user", "content": user_message})

    # Garde seulement les N derniers messages
    trimmed = history[-_MAX_HISTORY:]

    messages = [
        {
            "role": "system",
            "content": (
                "Tu es un assistant francophone expert en Wheel Strategy (options financières). "
                "Réponds de façon claire, concise et pédagogique. "
                "N'invente pas de données et précise quand une information manque. "
                "Rappelle que ce n'est pas un conseil financier."
            ),
        },
        {
            "role": "system",
            "content": f"Contexte application: {_build_context_text()}",
        },
        *trimmed,
    ]

    try:
        client = Groq(api_key=groq_api_key)
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            temperature=0.2,
            max_tokens=600,
        )
        content = response.choices[0].message.content
        answer = content.strip() if content else "Je n'ai pas pu générer de réponse."
    except Exception as exc:
        answer = f"❌ Erreur Groq : {exc}"

    history.append({"role": "assistant", "content": answer})
    return answer


# ── Polling loop ──────────────────────────────────────────────────────────────

def _poll(token: str, groq_api_key: str, stop_event: threading.Event) -> None:
    offset: Optional[int] = None
    logger.info("Telegram bot polling started.")

    while not stop_event.is_set():
        params: dict = {"timeout": 20, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset

        try:
            url = f"{_TELEGRAM_BASE.format(token=token)}/getUpdates"
            resp = requests.post(url, json=params, timeout=30)
            data = resp.json()
        except Exception as exc:
            logger.error("getUpdates failed: %s", exc)
            time.sleep(5)
            continue

        if not data.get("ok"):
            logger.error("getUpdates not ok: %s", data)
            time.sleep(5)
            continue

        for update in data.get("result", []):
            offset = update["update_id"] + 1
            message = update.get("message", {})
            chat_id = str(message.get("chat", {}).get("id", ""))
            text = message.get("text", "").strip()

            if not chat_id or not text:
                continue

            # Commande /start
            if text == "/start":
                _send(token, chat_id,
                      "👋 *Wheel Strategy Assistant*\n\n"
                      "Pose-moi une question sur la Wheel Strategy, les CSP, IVR, RSI, "
                      "DTE ou les résultats du dernier scan.\n\n"
                      "📋 *Commandes clés :*\n"
                      "`/help` — liste complète des commandes\n"
                      "`/scan AAPL` — scanner un ticker\n"
                      "`/scan SLV 70` — scan + meilleur covered call si acheté à 70\n"
                      "`/scan wheel MSFT` — scan + meilleur CSP/Put\n"
                      "`/top` — top 20 actions/ETFs actifs & volatils\n"
                      "`/watchlist` — voir la watchlist\n"
                      "`/results` — derniers résultats\n\n"
                      "_Ce n'est pas un conseil financier._")
                continue

            # Commande /reset — vide l'historique de ce chat
            if text == "/reset":
                _histories.pop(chat_id, None)
                _send(token, chat_id, "🔄 Historique de conversation réinitialisé.")
                continue

            # Commande /help
            if text == "/help":
                _send(token, chat_id,
                      "📋 *Commandes disponibles :*\n\n"
                      "`/start` — message de bienvenue\n"
                      "`/reset` — vider l'historique du chat\n"
                      "`/watchlist` — afficher la watchlist courante\n"
                      "`/results` — derniers résultats de scan\n"
                      "`/scan TICKER` — scanner un ticker (ex: `/scan AAPL`)\n"
                      "`/scan TICKER PRIX` — scan + meilleur Covered Call (ex: `/scan SLV 70`)\n"
                      "`/scan wheel TICKER` — scan + meilleur CSP/Put (ex: `/scan wheel MSFT`)\n"
                      "`/csp TICKER` — meilleur CSP/Put pour un ticker (ex: `/csp NVDA`)\n"
                      "`/top` — top 20 actions/ETFs les plus actifs et volatils\n"
                      "`/top 10` — top N (max 30)\n\n"
                      "Tu peux aussi écrire librement pour poser des questions à l'assistant IA.")
                continue

            # Commande /watchlist
            if text == "/watchlist":
                wl = config.WATCHLIST
                _send(token, chat_id,
                      f"📋 *Watchlist ({len(wl)} tickers) :*\n" + ", ".join(f"`{t}`" for t in wl))
                continue

            # Commande /results — affiche les derniers résultats de scan
            if text == "/results":
                results = _scan_context.get("results")
                if not results:
                    _send(token, chat_id, "⚠️ Aucun scan exécuté pour le moment.")
                else:
                    passing = [r for r in results if r.get("passes_all")]
                    lines = [f"📊 *Derniers résultats ({len(results)} tickers, {len(passing)} ✅ PASS) :*\n"]
                    for r in results:
                        icon = "✅" if r.get("passes_all") else "❌"
                        price = f"${r.get('price', '?'):.2f}" if r.get("price") else "?"
                        lines.append(f"{icon} `{r.get('ticker')}` {price}")
                    _send(token, chat_id, "\n".join(lines))
                continue

            # Commandes /scan et /csp
            cmd_parts = text.split()
            cmd = cmd_parts[0].lower()

            if cmd == "/scan":
                # /scan TICKER  ou  /scan TICKER COST_BASIS  ou  /scan wheel TICKER
                if len(cmd_parts) == 1:
                    _send(token, chat_id, "⚠️ Usage : `/scan TICKER` ou `/scan TICKER PRIX` ou `/scan wheel TICKER`")
                    continue

                wheel_mode = False
                ticker_arg = ""
                cost_basis = None

                if cmd_parts[1].lower() == "wheel":
                    if len(cmd_parts) < 3:
                        _send(token, chat_id, "⚠️ Usage : `/scan wheel TICKER`")
                        continue
                    wheel_mode = True
                    ticker_arg = cmd_parts[2].upper()
                else:
                    ticker_arg = cmd_parts[1].upper()
                    # Si 3ème paramètre : cost_basis pour covered call
                    if len(cmd_parts) >= 3:
                        try:
                            cost_basis = float(cmd_parts[2])
                        except ValueError:
                            _send(token, chat_id, f"⚠️ Prix invalide : `{cmd_parts[2]}`. Utilise un nombre.")
                            continue

                _send_typing(token, chat_id)
                result = _scanner.scan_ticker(ticker_arg)
                icon = "✅ PASS" if result.get("passes_all") else f"❌ FAIL"
                price = f"${result.get('price'):.2f}" if result.get("price") else "N/A"
                rsi = f"{result.get('rsi'):.1f}" if result.get("rsi") else "N/A"
                ivr = f"{result.get('iv_rank'):.1f}%" if result.get("iv_rank") else "N/A"
                uptrend = "✅" if result.get("uptrend") else "❌"
                earnings = result.get("next_earnings", "N/A")
                reason = result.get("reason_failed") or "—"

                msg = (
                    f"🔍 *Scan : {ticker_arg}*\n\n"
                    f"Statut : {icon}\n"
                    f"Prix : {price}\n"
                    f"RSI : {rsi}\n"
                    f"IV Rank : {ivr}\n"
                    f"Uptrend (MA50>MA200) : {uptrend}\n"
                    f"Prochains résultats : {earnings}\n"
                    f"Raison(s) échec : {reason}"
                )

                if wheel_mode:
                    # Meilleur CSP
                    csp = _screener.find_best_csp(ticker_arg, result.get("price"))
                    if csp:
                        ret = csp.get("monthly_return_pct") or csp.get("return_pct", 0)
                        msg += (
                            f"\n\n💡 *Meilleur CSP :*\n"
                            f"Strike : ${csp.get('strike')}\n"
                            f"Prime : ${csp.get('premium')}\n"
                            f"DTE : {csp.get('dte')} jours\n"
                            f"Expiration : {csp.get('expiration')}\n"
                            f"Rendement 30j : {ret:.2f}%"
                        )
                    else:
                        msg += "\n\n⚠️ Aucun CSP éligible trouvé pour ce ticker."
                elif cost_basis is not None:
                    # Meilleur Covered Call + résultats
                    cc = _screener.find_best_covered_call(ticker_arg, result.get("price"))
                    if cc and result.get("price"):
                        cc_result = _screener.calculate_cc_result(
                            current_price=result.get("price"),
                            cost_basis=cost_basis,
                            cc_premium=cc.get("premium"),
                            cc_strike=cc.get("strike"),
                            num_shares=100,
                        )
                        ret = cc.get("monthly_return_pct", 0)
                        msg += (
                            f"\n\n📈 *Meilleur Covered Call (si acheté à ${cost_basis}) :*\n"
                            f"Strike CC : ${cc_result['cc_strike']}\n"
                            f"Prime CC : ${cc_result['call_premium_per_share']}/action\n"
                            f"DTE : {cc.get('dte')} jours\n"
                            f"Expiration : {cc.get('expiration')}\n"
                            f"Rendement 30j (prime only) : {ret:.2f}%\n\n"
                            f"💰 *Résultat si assigné :*\n"
                            f"Prix d'équilibre : ${cc_result['breakeven_price']}\n"
                            f"Profit total : ${cc_result['profit_if_assigned']}\n"
                            f"Profit % : {cc_result['profit_pct_if_assigned']:.2f}%"
                        )
                    else:
                        msg += "\n\n⚠️ Aucun Covered Call éligible trouvé pour ce ticker."

                _send(token, chat_id, msg)
                continue

            if cmd == "/csp":
                if len(cmd_parts) < 2:
                    _send(token, chat_id, "⚠️ Usage : `/csp TICKER`")
                    continue
                ticker_arg = cmd_parts[1].upper()
                _send_typing(token, chat_id)
                csp = _screener.find_best_csp(ticker_arg)
                if not csp:
                    _send(token, chat_id, f"⚠️ Aucun CSP éligible trouvé pour `{ticker_arg}`.")
                else:
                    ret = csp.get("monthly_return_pct") or csp.get("return_pct", 0)
                    _send(token, chat_id,
                          f"💡 *Meilleur CSP pour {ticker_arg} :*\n\n"
                          f"Strike : ${csp.get('strike')}\n"
                          f"Prime : ${csp.get('premium')}\n"
                          f"DTE : {csp.get('dte')} jours\n"
                          f"Expiration : {csp.get('expiration')}\n"
                          f"Rendement 30j : {ret:.2f}%")
                continue

            if cmd == "/top":
                # /top  ou  /top 10
                n = 20
                if len(cmd_parts) >= 2:
                    try:
                        n = min(int(cmd_parts[1]), 30)
                    except ValueError:
                        pass
                _send_typing(token, chat_id)
                _send(token, chat_id, f"⏳ Récupération du top {n} en cours… (peut prendre 15-20s)")
                tops = _screener.get_top_active_volatile(count=n)
                if not tops:
                    _send(token, chat_id, "⚠️ Impossible de récupérer les données Yahoo Finance.")
                else:
                    lines = [f"🔥 *Top {len(tops)} actions/ETFs actifs & volatils :*\n"]
                    for i, t in enumerate(tops, 1):
                        chg = t.get("change_pct", 0)
                        chg_icon = "📈" if chg >= 0 else "📉"
                        hv = t.get("hv_30", 0)
                        price = f"${t['price']:.2f}" if t.get("price") else "N/A"
                        vol_m = f"{t['volume'] / 1_000_000:.1f}M" if t.get("volume") else "N/A"
                        hv_str = f"{hv:.1f}%" if hv else "N/A"
                        lines.append(
                            f"{i}. *{t['ticker']}* {chg_icon}{chg:+.1f}% | "
                            f"{price} | Vol:{vol_m} | HV:{hv_str}"
                        )
                    _send(token, chat_id, "\n".join(lines))
                continue

            # Message normal → Groq
            _send_typing(token, chat_id)
            answer = _ask_groq(groq_api_key, chat_id, text)
            _send(token, chat_id, answer)


# ── Public API ────────────────────────────────────────────────────────────────

_stop_event: threading.Event = threading.Event()
_poll_thread: Optional[threading.Thread] = None


def start_polling(token: str, groq_api_key: str) -> tuple[bool, str]:
    """
    Starts the polling thread.  Safe to call multiple times — stops the previous
    thread first.
    """
    global _stop_event, _poll_thread

    if not token or not token.strip():
        return False, "❌ Bot Token manquant."
    if not groq_api_key or not groq_api_key.strip():
        return False, "❌ Clé API Groq manquante."

    # Stop existing thread
    stop_polling()

    _stop_event = threading.Event()
    _poll_thread = threading.Thread(
        target=_poll,
        args=(token.strip(), groq_api_key.strip(), _stop_event),
        daemon=True,
        name="TelegramBotPoller",
    )
    _poll_thread.start()
    return True, "✅ Bot Telegram démarré — il répond maintenant aux messages !"


def stop_polling() -> None:
    """Signals the polling thread to stop."""
    global _poll_thread
    _stop_event.set()
    if _poll_thread and _poll_thread.is_alive():
        _poll_thread.join(timeout=3)
    _poll_thread = None


def is_polling() -> bool:
    """Returns True if the polling thread is alive."""
    return _poll_thread is not None and _poll_thread.is_alive()
