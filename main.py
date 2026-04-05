# main.py — Entry point for the Wheel Strategy Scanner
# Point d'entrée du scanner de stratégie de la roue

import logging
import sys

from rich.console import Console

import config
import report
import scanner
import screener

# ── Logging configuration ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("wheel_scanner.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)
console = Console()


def main() -> None:
    """
    Main entry point — orchestrates the full scan workflow.
    Point d'entrée principal — orchestre le flux de scan complet.
    """
    # 1. Print banner / Afficher la bannière
    report.print_banner()

    # 2. Scan all tickers / Scanner tous les tickers
    console.print("[bold]Step 1/4 — Scanning all tickers…[/bold]")
    results = scanner.scan_all()

    # 3. Print summary table / Afficher le tableau récapitulatif
    console.print("\n[bold]Step 2/4 — Summary table[/bold]")
    report.print_summary_table(results)

    # 4. For passing tickers, find best CSP opportunities
    #    Pour les tickers qui passent, trouver les meilleures opportunités CSP
    passing = scanner.get_passing_tickers(results)

    console.print(f"[bold]Step 3/4 — Finding best CSP for {len(passing)} passing ticker(s)…[/bold]")

    opportunities = []
    for r in passing:
        ticker = r["ticker"]
        price = r.get("price")
        console.print(f"  🔎 Analyzing options for [bold]{ticker}[/bold]…")
        try:
            csp = screener.find_best_csp(ticker, current_price=price)
            if csp:
                opportunities.append(csp)
        except Exception as exc:
            logger.error("Error finding CSP for %s: %s", ticker, exc)

    report.print_opportunities(opportunities)

    # 5. Print earnings warnings / Afficher les alertes earnings
    console.print("[bold]Step 4/4 — Earnings warnings[/bold]")
    report.print_earnings_warnings(results)

    # 6. Export to CSV / Exporter vers CSV
    report.export_to_csv(results)

    console.rule("[bold cyan]🎡 Scan Complete[/bold cyan]")
    console.print(
        "[dim]Disclaimer: This tool is for educational purposes only. "
        "Not financial advice.[/dim]\n"
    )


if __name__ == "__main__":
    main()
