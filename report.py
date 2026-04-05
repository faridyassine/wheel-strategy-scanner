# report.py — Terminal output and CSV export using Rich
# Affichage terminal coloré et export CSV avec la bibliothèque Rich

import csv
import logging
import os
from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich import box
from rich.text import Text

import config

logger = logging.getLogger(__name__)
console = Console()


def _fmt_float(value, decimals: int = 2, suffix: str = "") -> str:
    """Format a float or return 'N/A' if None."""
    if value is None:
        return "N/A"
    return f"{value:.{decimals}f}{suffix}"


def _rsi_style(rsi) -> str:
    """Returns a Rich style string based on RSI value."""
    if rsi is None:
        return "dim"
    if rsi < config.RSI_MIN:
        return "red"
    if rsi > config.RSI_MAX:
        return "yellow"
    return "green"


def _ivr_style(ivr) -> str:
    """Returns a Rich style string based on IV Rank value."""
    if ivr is None:
        return "dim"
    if ivr >= 50:
        return "green"
    if ivr >= config.MIN_IV_RANK:
        return "yellow"
    return "red"


def print_banner() -> None:
    """Prints the scanner banner. / Affiche la bannière du scanner."""
    console.print()
    console.rule("[bold cyan]🎡 Wheel Strategy Scanner[/bold cyan]")
    console.print(
        "[bold white]Scanning for Cash Secured Put opportunities…[/bold white]",
        justify="center",
    )
    console.print(
        f"[dim]Watchlist: {', '.join(config.WATCHLIST)}[/dim]", justify="center"
    )
    console.print()


def print_summary_table(results: list[dict]) -> None:
    """
    Prints a formatted summary table for all scanned tickers.
    Affiche un tableau récapitulatif formaté pour tous les tickers scannés.
    """
    table = Table(
        title="📊 Scan Summary — All Tickers",
        box=box.ROUNDED,
        show_lines=True,
        header_style="bold magenta",
    )

    table.add_column("Ticker", style="bold white", justify="center")
    table.add_column("Price", justify="right")
    table.add_column("RSI", justify="right")
    table.add_column("MA50", justify="right")
    table.add_column("MA200", justify="right")
    table.add_column("Trend", justify="center")
    table.add_column("IVR %", justify="right")
    table.add_column("HV30 %", justify="right")
    table.add_column("Next Earnings", justify="center")
    table.add_column("DTE Earn.", justify="right")
    table.add_column("Status", justify="center")

    for r in results:
        rsi_style = _rsi_style(r.get("rsi"))
        ivr_style = _ivr_style(r.get("iv_rank"))
        trend_icon = "✅" if r.get("uptrend") else "❌"
        earn_safe = r.get("earnings_safe", True)
        earn_days = r.get("days_to_earnings")
        earn_style = "green" if earn_safe else "red"

        status_text = "[bold green]PASS ✅[/bold green]" if r.get("passes_all") else "[bold red]FAIL ❌[/bold red]"

        table.add_row(
            r.get("ticker", "?"),
            _fmt_float(r.get("price"), 2, "$"),
            Text(_fmt_float(r.get("rsi"), 1), style=rsi_style),
            _fmt_float(r.get("ma50"), 2),
            _fmt_float(r.get("ma200"), 2),
            trend_icon,
            Text(_fmt_float(r.get("iv_rank"), 1), style=ivr_style),
            _fmt_float(r.get("hv_30"), 1, "%"),
            r.get("next_earnings", "N/A"),
            Text(str(earn_days) if earn_days is not None else "N/A", style=earn_style),
            status_text,
        )

    console.print(table)
    passing = sum(1 for r in results if r.get("passes_all"))
    console.print(
        f"\n[bold]Results:[/bold] [green]{passing} passing[/green] / [white]{len(results)} total[/white]\n"
    )


def print_opportunities(options: list[dict]) -> None:
    """
    Prints best CSP opportunities in a formatted table.
    Affiche les meilleures opportunités CSP dans un tableau formaté.
    """
    if not options:
        console.print("[yellow]⚠️  No CSP opportunities found matching all criteria.[/yellow]\n")
        return

    table = Table(
        title="💰 Best Cash Secured Put Opportunities",
        box=box.ROUNDED,
        show_lines=True,
        header_style="bold green",
    )

    table.add_column("Ticker", style="bold white", justify="center")
    table.add_column("Price", justify="right")
    table.add_column("Strike", justify="right")
    table.add_column("Expiry", justify="center")
    table.add_column("DTE", justify="right")
    table.add_column("Premium", justify="right")
    table.add_column("OI", justify="right")
    table.add_column("Δ Approx", justify="right")
    table.add_column("30d Yield %", justify="right")

    for opt in options:
        table.add_row(
            opt.get("ticker", "?"),
            _fmt_float(opt.get("current_price"), 2, "$"),
            _fmt_float(opt.get("strike"), 2, "$"),
            opt.get("expiry", "N/A"),
            str(opt.get("dte", "N/A")),
            f"[bold green]{_fmt_float(opt.get('premium'), 2, '$')}[/bold green]",
            str(opt.get("open_interest", "N/A")),
            _fmt_float(opt.get("delta_approx"), 3),
            f"[bold cyan]{_fmt_float(opt.get('monthly_return_pct'), 2, '%')}[/bold cyan]",
        )

    console.print(table)
    console.print()


def print_earnings_warnings(results: list[dict]) -> None:
    """
    Highlights tickers with earnings within EARNINGS_SAFE_DAYS.
    Met en évidence les tickers avec des résultats dans EARNINGS_SAFE_DAYS jours.
    """
    warnings = [
        r for r in results
        if not r.get("earnings_safe", True) and r.get("days_to_earnings") is not None
    ]
    unknowns = [
        r for r in results
        if r.get("next_earnings") == "Unknown"
    ]

    console.print("[bold yellow]⚠️  Earnings Warnings[/bold yellow]")
    console.rule(style="yellow")

    if not warnings:
        console.print(f"[green]✅ No tickers have earnings within {config.EARNINGS_SAFE_DAYS} days.[/green]")
    else:
        for r in sorted(warnings, key=lambda x: x.get("days_to_earnings", 999)):
            console.print(
                f"  [bold red]⚠️  {r['ticker']}[/bold red] — earnings in "
                f"[bold]{r['days_to_earnings']} days[/bold] "
                f"(next: [italic]{r['next_earnings']}[/italic])"
            )

    if unknowns:
        console.print()
        for r in unknowns:
            console.print(
                f"  [dim]❓ {r['ticker']} — earnings date unknown[/dim]"
            )

    console.print()


def export_to_csv(results: list[dict], filename: str = None) -> str:
    """
    Exports scan results to a CSV file with a timestamp suffix.
    Exporte les résultats du scan dans un fichier CSV avec un suffixe de timestamp.

    Returns the path to the created file.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if filename is None:
        filename = f"wheel_scan_{timestamp}.csv"
    elif not filename.endswith(".csv"):
        filename = f"{filename}_{timestamp}.csv"

    fieldnames = [
        "ticker", "price", "rsi", "ma50", "ma200", "uptrend",
        "iv_rank", "hv_30", "next_earnings", "days_to_earnings",
        "earnings_safe", "passes_all", "reason_failed",
    ]

    try:
        with open(filename, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(results)
        logger.info("Results exported to %s", filename)
        console.print(f"[dim]📄 Results exported to [bold]{filename}[/bold][/dim]\n")
        return filename
    except Exception as exc:
        logger.error("Error exporting CSV: %s", exc)
        console.print(f"[red]Error exporting CSV: {exc}[/red]")
        return ""
