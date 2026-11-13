# polymarket-nvidia-ceo-forecast-01 — entry forecaster (Python 3.13, standard library only)
#
# Forecasts the Yes price of every market of Polymarket's "Next CEO of NVIDIA?" event
# at every minute of the 4 hours after a checkpoint, as five quantiles (5/25/50/75/95%).
#
# Reads every <id>.in in $MAKEFUN_INPUT_DIR (else /input) and writes <id>.out to
# $MAKEFUN_OUTPUT_DIR (else /output), exactly as RULES.txt specifies.
#
# Model (tuned on the kit's practice cases p00-p04, whose answers are recoverable from
# the next case's input; the house baseline scores 0.3925 on those five cases, this
# program 0.3163 — about 19% lower pinball loss; the house baseline's published
# practice loss over all six cases is 0.363589):
#
#   * Median: the market's last price, pulled halfway toward its cross-market fair
#     level x / S, where S is the sum of all markets' last prices. The 24 outcomes
#     are mutually exclusive, so their true probabilities sum to 1; when the book
#     is collectively over- or under-priced the pull corrects the level. No drift:
#     short-horizon drift estimates were tested and hurt (prices behave like a
#     martingale at these horizons; recent moves do not persist).
#   * Spread: a random-walk widening, sigma * sqrt(h), but with a *narrow core and
#     fat tails*: the 25/75% quantiles use z = +/-0.4 and the 5/95% quantiles
#     z = +/-2.2, instead of the normal +/-0.674 / +/-1.645. The prices move in
#     steps — most minutes not at all, then a tick, now and then a jump — so the
#     interquartile range is much tighter than a normal walk and the tails much
#     fatter. Sigma is per market: 0.0012 * (0.6 + 1.2 * nz), where nz is the
#     fraction of minutes with a price move in the last 720 minutes (quiet markets
#     get a tighter core, active ones a wider one). A plain realised-volatility
#     (RMS of minute changes) was tested and is far worse: it is dominated by the
#     rare huge jumps and blows the spread up.
#   * Downside jump allowance: the 5% quantile is widened downward by
#     0.3 * x * (1 - exp(-h/240)). In the practice history the big moves are
#     overwhelmingly collapses (a candidate's price falling most of the way to
#     zero), while upward jumps of that size are rare; the symmetric widening was
#     tested and hurts. The 95% quantile gets a smaller upside allowance of
#     the same shape, 0.15 * x * (1 - exp(-h/240)): the upside had none, yet
#     the rules cite a +0.24 one-minute jump, and the 95% level was the only
#     quantile with clear headroom (its loss falls 0.2064 to 0.1996, the
#     others untouched). The value sits on a flat plateau (0.15 and 0.20
#     score the same), not a knife edge.
#   * All quantiles are clamped to [0, 1], rounded to 6 decimals, and each row is
#     forced non-decreasing. The program is deterministic (no randomness, no
#     clocks, no network) and runs in well under a second per case. A market
#     with no usable prices gets a neutral flat-0.5 forecast instead of
#     raising, so one malformed market can never crash the run and invalidate
#     the whole case.

import json
import math
import os
from pathlib import Path

INPUT_DIR = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
OUTPUT_DIR = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")

QUANTILES = [0.05, 0.25, 0.5, 0.75, 0.95]

# Quantile multipliers: narrow core (+/-0.4), fat tails (+/-2.2).
Z = [-2.2, -0.4, 0.0, 0.4, 2.2]
# Base spread in price units per square-root minute.
SIGMA = 0.0012
# Activity window (minutes) for the per-market activity factor.
ACTIVITY_WINDOW = 720
# Weight of the cross-market fair-level pull on the median.
SUM_PULL = 0.5
# Downside collapse allowance on the 5% quantile, as a fraction of the level.
JUMP_DOWN = 0.3
JUMP_TAU = 240.0
# Upside jump allowance on the 95% quantile, as a fraction of the level,
# with the same (1 - exp(-h/240)) shape as the downside one. The downside
# allowance existed from the start, but the upside had none — yet the rules
# themselves cite a +0.24 one-minute jump (Colette Kress, 0.3535 to 0.59),
# and on the practice the 95% quantile was the only level with clear
# headroom. Adding it cuts the mean pinball loss from 0.3177 to 0.3163,
# with the gain isolated to tau=0.95 (0.2064 to 0.1996, other levels
# untouched); the value sits on a flat plateau (0.15 and 0.20 score the
# same), not a knife edge. A symmetric widening was tested before and
# hurts — because the downside was already covered; this is the missing
# half, not a repeat of it.
JUMP_UP = 0.15


def price6(x):
    """Clamp to [0, 1] and round to 6 decimals (0, never -0)."""
    return round(min(1.0, max(0.0, x)) * 1e6) / 1e6 + 0.0


def activity_factor(prices):
    """Fraction of minutes with a price move in the last ACTIVITY_WINDOW minutes."""
    n = len(prices)
    w = min(ACTIVITY_WINDOW, n)
    if w <= 1:
        return 0.0
    moves = 0
    for i in range(n - w, n):
        if prices[i] != prices[i - 1]:
            moves += 1
    return moves / (w - 1)


def forecast_market(prices, fair_level, horizon):
    """240 (or horizon) rows of five quantiles for one market."""
    x = prices[-1]
    sigma = SIGMA * (0.6 + 1.2 * activity_factor(prices))
    median = x + SUM_PULL * (fair_level - x)
    rows = []
    for h in range(1, horizon + 1):
        root_h = math.sqrt(h)
        collapse = JUMP_DOWN * x * (1.0 - math.exp(-h / JUMP_TAU))
        surge = JUMP_UP * x * (1.0 - math.exp(-h / JUMP_TAU))
        row = [
            price6(median + Z[0] * sigma * root_h - collapse),
            price6(median + Z[1] * sigma * root_h),
            price6(median),
            price6(median + Z[3] * sigma * root_h),
            price6(median + Z[4] * sigma * root_h + surge),
        ]
        # Enforce non-decreasing (clamping can only break order at the edges).
        for j in range(1, 5):
            if row[j] < row[j - 1]:
                row[j] = row[j - 1]
        rows.append(row)
    return rows


def neutral_rows(horizon):
    """Fallback forecast for a market with no usable prices: a flat 0.5
    median with the house baseline's spread. A valid case never needs this
    (every market has at least one price by construction), but one malformed
    market must never crash the run and invalidate the whole case."""
    rows = []
    for h in range(1, horizon + 1):
        root_h = math.sqrt(h)
        rows.append([
            price6(0.5 - 1.644854 * 0.0025 * root_h),
            price6(0.5 - 0.674490 * 0.0025 * root_h),
            0.5,
            price6(0.5 + 0.674490 * 0.0025 * root_h),
            price6(0.5 + 1.644854 * 0.0025 * root_h),
        ])
    return rows


def forecast_case(case):
    markets = case["markets"]
    horizon = case["horizon_minutes"]
    # Sanitize: drop non-finite prices (a strict JSON case has none, but a
    # single bad value must not poison the whole run). Markets left with no
    # usable price get the neutral fallback instead of raising.
    clean = {}
    for m in markets:
        clean[m["id"]] = [p for p in m["prices"]
                          if isinstance(p, (int, float)) and math.isfinite(p)]
    total = sum(ps[-1] for ps in clean.values() if ps)
    forecasts = []
    for m in markets:
        prices = clean[m["id"]]
        if not prices:
            forecasts.append({"id": m["id"], "q": neutral_rows(horizon)})
            continue
        x = prices[-1]
        fair = x / total if total > 0 else x
        forecasts.append({"id": m["id"], "q": forecast_market(prices, fair, horizon)})
    return {"forecasts": forecasts}


def main():
    input_dir = Path(INPUT_DIR)
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    inputs = sorted(p for p in input_dir.iterdir() if p.name.endswith(".in"))
    for path in inputs:
        case_id = path.name[: -len(".in")]
        with path.open("r", encoding="utf-8") as f:
            case = json.load(f)
        if list(case["quantiles"]) != QUANTILES:
            raise ValueError(
                f"{path.name} asks for quantiles {case['quantiles']}, not {QUANTILES}"
            )
        out = forecast_case(case)
        with (output_dir / f"{case_id}.out").open("w", encoding="utf-8") as f:
            f.write(json.dumps(out) + "\n")


if __name__ == "__main__":
    main()
