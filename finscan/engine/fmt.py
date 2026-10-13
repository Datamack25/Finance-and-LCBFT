"""Mise en forme des montants et ratios (convention française)."""
from __future__ import annotations

NBSP = " "


SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF", "XOF": "FCFA"}


def symbol(currency: str) -> str:
    return SYMBOLS.get(currency, currency)


def money(v: float | None, currency: str = "EUR", compact: bool = True) -> str:
    if v is None:
        return "—"
    sym = symbol(currency)
    a = abs(v)
    if compact and a >= 1e9:
        s = f"{v / 1e9:,.1f}".replace(",", NBSP).replace(".", ",") + f"{NBSP}Md{sym}"
    elif compact and a >= 1e6:
        s = f"{v / 1e6:,.1f}".replace(",", NBSP).replace(".", ",") + f"{NBSP}M{sym}"
    else:
        s = f"{v:,.0f}".replace(",", NBSP) + f"{NBSP}{sym}"
    return s.replace("-", "−")


def number(v: float | None, dec: int = 0) -> str:
    if v is None:
        return "—"
    return f"{v:,.{dec}f}".replace(",", NBSP).replace(".", ",").replace("-", "−")


def ratio(v: float | None, kind: str) -> str:
    if v is None:
        return "—"
    if kind == "%":
        return f"{v * 100:.1f}".replace(".", ",").replace("-", "−") + f"{NBSP}%"
    if kind == "x":
        return f"{v:.2f}".replace(".", ",").replace("-", "−") + f"{NBSP}x"
    if kind == "j":
        return f"{v:.0f}{NBSP}j"
    return f"{v:.2f}".replace(".", ",")


def growth(n: float | None, n1: float | None) -> float | None:
    if n is None or n1 in (None, 0):
        return None
    return (n - n1) / abs(n1)


def variation(n: float | None, n1: float | None) -> str:
    d = growth(n, n1)
    if d is None:
        return "—"
    return (f"{d * 100:+.1f}".replace(".", ",") + f"{NBSP}%").replace("-", "−")


def pct(d: float | None, signed: bool = True) -> str:
    if d is None:
        return "—"
    s = f"{d * 100:+.1f}" if signed else f"{d * 100:.1f}"
    return (s.replace(".", ",") + f"{NBSP}%").replace("-", "−")
