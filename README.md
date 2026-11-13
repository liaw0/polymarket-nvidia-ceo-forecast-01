# Polymarket NVIDIA CEO forecaster

Forecasts the Yes price of every market of Polymarket's **"Next CEO of NVIDIA?"**
event at every minute of the 4 hours after a checkpoint, as five quantiles
(5%, 25%, 50%, 75%, 95%) — entry for make.fun competition
`polymarket-nvidia-ceo-forecast-01`.

## Run

```sh
python3 main.py            # reads /input, writes /output
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

Python 3.13 target (also runs on 3.12), standard library only, no network,
deterministic: the same case always produces the same bytes.

## Model

Prices move in steps — most minutes not at all, then a tick, now and then a
jump — so a plain normal random walk is the wrong shape. This forecaster:

1. **Median** — the market's last price, pulled halfway toward its
   cross-market fair level `x / S`, where `S` is the sum of all markets' last
   prices. The 24 outcomes are mutually exclusive, so their true probabilities
   sum to 1; when the book is collectively over- or under-priced the pull
   corrects the level. No drift: short-horizon drift estimates were tested on
   the practice cases and hurt — prices behave like a martingale at these
   horizons.
2. **Spread** — a random walk widening `sigma * sqrt(h)`, but with a **narrow
   core and fat tails**: the 25/75% quantiles use z = ±0.4 and the 5/95%
   quantiles z = ±2.2 (vs the normal ±0.674 / ±1.645). Sigma is per market:
   `0.0012 * (0.6 + 1.2 * nz)`, where `nz` is the fraction of minutes with a
   price move in the last 720 minutes. A plain realised volatility (RMS of
   minute changes) was tested and is far worse — it is dominated by the rare
   huge jumps.
3. **Downside jump allowance** — the 5% quantile is widened downward by
   `0.3 * x * (1 - exp(-h/240))`. In the practice history the big moves are
   overwhelmingly collapses (a candidate's price falling most of the way to
   zero); a symmetric widening was tested and hurts.
4. **Upside jump allowance** — the 95% quantile is widened upward by
   `0.15 * x * (1 - exp(-h/240))`, the same shape as the downside one. The
   upside had no allowance, yet the rules cite a +0.24 one-minute jump
   (Colette Kress, 0.3535 to 0.59), and the 95% level was the only quantile
   with clear headroom: its loss falls 0.2064 to 0.1996 while the other four
   levels are untouched, and the value sits on a flat plateau (0.15 and 0.20
   score the same). This is the missing half of the jump allowance, not a
   repeat of the symmetric widening that was already tested and rejected.

All quantiles are clamped to [0, 1], rounded to 6 decimals, and each row is
forced non-decreasing. A market with no usable prices gets a neutral flat-0.5
forecast (house baseline spread) instead of raising, so one malformed market
can never crash a run and invalidate the whole case.

## Local verification

The kit's practice answers for cases p00–p04 are recoverable from the next
case's input (each case's 240 forecast minutes are inside the following case's
72-hour history). Scored that way (mean pinball loss, as the rules define):

| forecaster | loss on p00–p04 |
|---|---|
| house baseline (starter) | 0.3925 |
| this entry (first build) | 0.3177 |
| this entry (revised, in-window session) | **0.3163** |

Per-case revised loss: p00 0.4537, p01 0.3120, p02 0.3578, p03 0.2742,
p04 0.2186; 90% coverage 0.9354, median error 0.8619 (unchanged — the
revision moves only the 95% quantile). Alternatives tested in the revision
session and rejected: level-scaled sigma (0.3182, coverage 0.86), trailing
mean blended into the median (0.3255 at 25% blend), faster-saturating upside
allowance (helps p00 but hurts p03/p04), and further single-parameter moves
(SUM_PULL, JUMP_DOWN, tail/core z, SIGMA, activity window — all within
±0.004 of the first build, i.e. noise).

The house baseline's published practice loss over all six cases is 0.363589.
Runtime: ~0.4 s for all six practice cases (cap is 8 s per case); outputs
216–279 KB (cap 1 MiB).

Note: `makefun grade-local` refuses this kit — program/v1 competitions are
graded on the server only. The pre-submit check (`makefun check`) is run at
submit time by the parent agent, with the transcript bundle.
