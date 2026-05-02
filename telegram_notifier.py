# telegram_notifier.py — Telegram notifications for the Wheel Strategy Scanner

from __future__ import annotations

import requests


_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def send_message(text: str, token: str, chat_id: str) -> tuple[bool, str]:
    """
    Sends a Markdown-formatted message via Telegram.
    Returns (success: bool, feedback_message: str).
    """
    if not token or not token.strip():
        return False, "❌ Bot Token manquant. Configure-le dans la sidebar."
    if not chat_id or not chat_id.strip():
        return False, "❌ Chat ID manquant. Configure-le dans la sidebar."

    url = _TELEGRAM_API.format(token=token.strip())
    payload = {
        "chat_id": chat_id.strip(),
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        if data.get("ok"):
            return True, "✅ Message envoyé sur Telegram !"
        error_desc = data.get("description", "Erreur inconnue")
        return False, f"❌ Telegram API: {error_desc}"
    except requests.exceptions.ConnectionError:
        return False, "❌ Impossible de joindre Telegram (vérifier la connexion réseau)."
    except requests.exceptions.Timeout:
        return False, "❌ Timeout — Telegram n'a pas répondu dans les délais."
    except Exception as exc:  # noqa: BLE001
        return False, f"❌ Erreur inattendue: {exc}"


def build_scan_summary(results: list[dict], opportunities: list[dict]) -> str:
    """Builds a concise Telegram message summarising a scan."""
    total = len(results)
    passing = [r for r in results if r.get("passes_all")]
    passing_count = len(passing)

    lines = [
        "🎡 *Wheel Strategy Scanner — Résumé du scan*",
        f"📊 Tickers scannés : *{total}*",
        f"✅ Passent les filtres : *{passing_count}*",
        f"💰 Opportunités CSP : *{len(opportunities)}*",
    ]

    if passing:
        tickers_str = ", ".join(r["ticker"] for r in passing)
        lines.append(f"\n📋 *Tickers retenus :* {tickers_str}")

    if opportunities:
        avg_yield = sum(o.get("monthly_return_pct", 0) for o in opportunities) / len(opportunities)
        lines.append(f"📈 Rendement 30j moyen : *{avg_yield:.2f}%*")

        lines.append("\n🏆 *Top 3 opportunités :*")
        top3 = sorted(opportunities, key=lambda o: o.get("monthly_return_pct", 0), reverse=True)[:3]
        for o in top3:
            lines.append(
                f"• *{o['ticker']}* — Strike ${o.get('strike', '?'):.2f} | "
                f"Prime ${o.get('premium', 0):.2f} | "
                f"DTE {o.get('dte', '?')} | "
                f"Rdt {o.get('monthly_return_pct', 0):.2f}%"
            )

    lines.append("\n_Rappel : ce n'est pas un conseil financier._")
    return "\n".join(lines)


def build_opportunities_message(opportunities: list[dict]) -> str:
    """Builds a detailed Telegram message listing all CSP opportunities."""
    if not opportunities:
        return "⚠️ Aucune opportunité CSP disponible pour le moment."

    sorted_opps = sorted(opportunities, key=lambda o: o.get("monthly_return_pct", 0), reverse=True)

    lines = [f"💰 *Opportunités CSP ({len(sorted_opps)} trouvées)*\n"]
    for o in sorted_opps:
        capital = (o.get("strike", 0) or 0) * 100
        revenue = (o.get("premium", 0) or 0) * 100
        lines.append(
            f"📌 *{o['ticker']}*\n"
            f"  Strike: ${o.get('strike', 0):.2f} | Exp: {o.get('expiry', '?')} | DTE: {o.get('dte', '?')}\n"
            f"  Prime: ${o.get('premium', 0):.2f} ({revenue:.0f}$/contrat)\n"
            f"  Capital req.: ${capital:.0f} | Rdt 30j: *{o.get('monthly_return_pct', 0):.2f}%*\n"
        )

    lines.append("_Rappel : ce n'est pas un conseil financier._")
    return "\n".join(lines)
