"""The market maker's prices. Pure arithmetic, no database: ledger.py calls it.

Middle price  = fair value x (1 + lean) ^ (shares the market holds / shares per step)
Players buy at the middle + half the spread and sell at the middle - half the spread, and every share of a block is
priced on its own: buying share number h+1 when the market holds h costs mid(h) x (1 + spread/2); selling one when
the market holds h pays mid(h - 1) x (1 - spread/2). So buying a share and selling it straight back always loses the
spread, whatever the holdings, and a block costs the same bought at once or one share at a time.

Totals are rounded against the player (buys up to the next cent, sales down), so rounding can never create money.
"""
import math


def _q(mm, step_shares):
    return (1 + mm["lean_per_step"]) ** (1 / step_shares)


def mid(fair_value, held, step_shares, mm):
    return fair_value * _q(mm, step_shares) ** held


def _geometric(q, start, n):
    """sum of q^(start + i) for i in 0..n-1"""
    if n <= 0:
        return 0.0
    if abs(q - 1) < 1e-15:
        return float(n)
    return q ** start * (q ** n - 1) / (q - 1)


def buy_cost_cents(fair_value, held, n, step_shares, mm):
    q = _q(mm, step_shares)
    exact = fair_value * (1 + mm["spread"] / 2) * _geometric(q, held, n) * 100
    return math.ceil(round(exact, 6))  # round(…, 6) first so 1234.0000000001 isn't charged an extra cent


def sell_proceeds_cents(fair_value, held, n, step_shares, mm):
    q = _q(mm, step_shares)
    exact = fair_value * (1 - mm["spread"] / 2) * _geometric(q, held - n, n) * 100
    return math.floor(round(exact, 6))


def quote(fair_value, held, step_shares, mm):
    """The price of the next single share each way: (players sell at, players buy at)."""
    m = mid(fair_value, held, step_shares, mm)
    return m / _q(mm, step_shares) * (1 - mm["spread"] / 2), m * (1 + mm["spread"] / 2)


def most_affordable(fair_value, held, cash_cents, step_shares, mm):
    """The largest number of shares cash_cents can buy (for an 'all in' button)."""
    lo, hi = 0, 1
    while buy_cost_cents(fair_value, held, hi, step_shares, mm) <= cash_cents:
        lo, hi = hi, hi * 2
        if hi > 10_000_000:
            break
    while hi - lo > 1:
        m = (lo + hi) // 2
        if buy_cost_cents(fair_value, held, m, step_shares, mm) <= cash_cents:
            lo = m
        else:
            hi = m
    return lo
