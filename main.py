# polymarket-nvidia-ceo-forecast-01 — entry forecaster (Python 3.13, stdlib only)
#
# Forecasts the Yes price of every market of Polymarket's "Next CEO of NVIDIA?"
# event at every minute of the 4 hours after a checkpoint, as five quantiles
# (5% / 25% / 50% / 75% / 95%).
#
# Reads every <id>.in in $MAKEFUN_INPUT_DIR (else /input) and writes <id>.out
# to $MAKEFUN_OUTPUT_DIR (else /output), exactly as RULES.txt specifies.
#
# How the forecast is built (derived from the kit's rules and the practice
# data, and checked against the practice cases p00-p04, whose answers sit
# inside the next case's input):
#
# The prices move in steps: most minutes nothing happens, then a tick, now
# and then a jump of many points (Colette Kress went 0.3535 -> 0.59 in one
# minute, and back to 0.4585 the next; in the practice data a market moves
# on only 6-23% of minutes). Three consequences drive the model:
#
# 1. MEDIAN — last price, pulled toward the fair level. The 24 outcomes are
#    mutually exclusive, so their true probabilities sum to 1. In the
#    practice the last prices sum to 1.02-1.08, i.e. the book is collectively
#    a little over-priced, so each market's median is its last price x
#    pulled halfway toward x / S, where S is the sum of every market's last
#    price. No drift term: at a 4-hour horizon the prices behave like a
#    martingale — recent moves do not persist, and every drift variant
#    tested on the practice made the median worse.
#
# 2. SPREAD — a random-walk widening, sigma * sqrt(h), but shaped for
#    step-like prices: a narrow core and fat tails. The 25/75% quantiles sit
#    at z = +/-0.4 and the 5/95% at z = +/-2.2, instead of the normal
#    +/-0.674 / +/-1.645. Sigma is per market, from how busy it has been:
#    0.0012 * (0.6 + 1.2 * nz), where nz is the fraction of minutes with a
#    price move in the last 720 minutes. Quiet markets get a tighter core,
#    busy ones a wider one. A plain realised-volatility (RMS of minute
#    changes) was rejected: it is dominated by the rare huge jumps and blows
#    the spread up far beyond what the quiet minutes justify.
#
# 3. JUMP ALLOWANCES — the tails are widened beyond the walk, because a
#    walk's tails cannot cover a 0.24 jump in one minute. The big moves in
#    the history are overwhelmingly collapses (a candidate's price falling
#    most of the way toward zero), so the 5% quantile is pushed down by
#    0.3 * x * (1 - exp(-h/240)). The upside gets the missing half of the
#    same idea, smaller: the 95% quantile is pushed up by
#    0.15 * x * (1 - exp(-h/240)) — the rules themselves cite a +0.24
#    one-minute jump, and the 95% level was the only quantile with clear
#    headroom left. A symmetric widening was tested and hurts; these two
#    one-sided allowances are the asymmetric truth of the data.
#
# Everything is clamped to [0, 1], rounded to 6 decimals, and each row is
# forced non-decreasing. The program is deterministic (no randomness, no
# clocks, no network) and runs in well under a second per case. A market
# with no usable prices gets a neutral flat-0.5 forecast with the house
# baseline's spread, so one malformed market can never crash a run and
# invalidate the whole case.
#
# Backtest (practice p00-p04, scored with the rules' pinball formula):
# this program ~0.316, house baseline ~0.393 on the same cases — about
# 19% lower loss. The house baseline's published loss over all six
# practice cases is 0.363589.

import json
import math
import os
from pathlib import Path

INPUT_DIR = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
OUTPUT_DIR = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")

QUANTILES = [0.05, 0.25, 0.5, 0.75, 0.95]

# Quantile multipliers: narrow core (+/-0.4), fat tails (+/-2.2).
Z = [-2.2, -0.4, 0.0, 0.4, 2.2]
# Base spread, price units per square-root minute.
BASE_SIGMA = 0.0012
# How far back the per-market activity is measured (minutes).
ACTIVITY_WINDOW = 720
# Weight of the pull toward the cross-market fair level.
FAIR_PULL = 0.5
# One-sided jump allowances, as a fraction of the level, saturating over
# the horizon with time constant JUMP_TAU minutes.
JUMP_DOWN = 0.3
JUMP_UP = 0.15
JUMP_TAU = 240.0
# The house baseline's normal quantiles and spread, used only for the
# neutral fallback of a market with no usable prices.
BASELINE_Z = [-1.644854, -0.67449, 0.0, 0.67449, 1.644854]
BASELINE_SIGMA = 0.0025


def price6(x):
    """Clamp to [0, 1] and round to 6 decimals (0, never -0)."""
    return round(min(1.0, max(0.0, x)) * 1e6) / 1e6 + 0.0


def move_fraction(prices):
    """Fraction of minutes with a price move in the last ACTIVITY_WINDOW."""
    n = len(prices)
    w = min(ACTIVITY_WINDOW, n)
    if w <= 1:
        return 0.0
    moves = 0
    for i in range(n - w, n):
        if prices[i] != prices[i - 1]:
            moves += 1
    return moves / (w - 1)


def horizon_factors(horizon):
    """Per-minute factors shared by every market of a case: the random-walk
    widening sqrt(h) and the jump-allowance saturation (1 - exp(-h/240)).
    Computed once per case instead of once per market per row — the values
    depend only on h, so precomputing them is exact (same floats, same
    order of operations) and just avoids repeating the same exp/sqrt calls
    24 times over."""
    roots = []
    saturations = []
    for h in range(1, horizon + 1):
        roots.append(math.sqrt(h))
        saturations.append(1.0 - math.exp(-h / JUMP_TAU))
    return roots, saturations


def forecast_market(prices, fair_level, horizon, roots, saturations):
    """Horizon rows of five quantiles for one market."""
    x = prices[-1]
    sigma = BASE_SIGMA * (0.6 + 1.2 * move_fraction(prices))
    median = x + FAIR_PULL * (fair_level - x)
    rows = []
    for h in range(1, horizon + 1):
        root_h = roots[h - 1]
        # Jump allowances saturate over the horizon: a collapse or a surge
        # is unlikely in the next minute, likelier over four hours.
        down = JUMP_DOWN * x * saturations[h - 1]
        up = JUMP_UP * x * saturations[h - 1]
        row = [
            price6(median + Z[0] * sigma * root_h - down),
            price6(median + Z[1] * sigma * root_h),
            price6(median),
            price6(median + Z[3] * sigma * root_h),
            price6(median + Z[4] * sigma * root_h + up),
        ]
        # Clamping can only break the order at the edges; repair it.
        for j in range(1, 5):
            if row[j] < row[j - 1]:
                row[j] = row[j - 1]
        rows.append(row)
    return rows


def neutral_rows(horizon):
    """Fallback for a market with no usable prices: flat 0.5 median with
    the house baseline's spread. A valid case never needs this, but one
    malformed market must never crash the run and invalidate the case."""
    rows = []
    for h in range(1, horizon + 1):
        root_h = math.sqrt(h)
        rows.append([
            price6(0.5 + BASELINE_Z[0] * BASELINE_SIGMA * root_h),
            price6(0.5 + BASELINE_Z[1] * BASELINE_SIGMA * root_h),
            0.5,
            price6(0.5 + BASELINE_Z[3] * BASELINE_SIGMA * root_h),
            price6(0.5 + BASELINE_Z[4] * BASELINE_SIGMA * root_h),
        ])
    return rows


def clean_prices(raw):
    """Keep only finite numbers; a single bad value must not poison a run."""
    return [p for p in raw
            if isinstance(p, (int, float)) and math.isfinite(p)]


def forecast_case(case):
    markets = case["markets"]
    horizon = case["horizon_minutes"]
    roots, saturations = horizon_factors(horizon)
    usable = {m["id"]: clean_prices(m["prices"]) for m in markets}
    total = sum(ps[-1] for ps in usable.values() if ps)
    forecasts = []
    for m in markets:
        prices = usable[m["id"]]
        if not prices:
            forecasts.append({"id": m["id"], "q": neutral_rows(horizon)})
            continue
        x = prices[-1]
        fair = x / total if total > 0 else x
        forecasts.append({"id": m["id"],
                          "q": forecast_market(prices, fair, horizon,
                                               roots, saturations)})
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
                f"{path.name} asks for quantiles {case['quantiles']}, "
                f"not {QUANTILES}"
            )
        out = forecast_case(case)
        with (output_dir / f"{case_id}.out").open("w", encoding="utf-8") as f:
            f.write(json.dumps(out) + "\n")


if __name__ == "__main__":
    main()
