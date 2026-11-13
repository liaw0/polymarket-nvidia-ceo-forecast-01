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

The prices move in steps — most minutes not at all, then a tick, now and
then a jump of many points (Colette Kress went 0.3535 to 0.59 in one minute,
and back to 0.4585 the next; in the practice data a market moves on only
6–23% of minutes). A plain normal random walk is the wrong shape for that,
so the forecaster is built around three ideas:

1. **Median — last price pulled toward the fair level.** The 24 outcomes are
   mutually exclusive, so their true probabilities sum to 1. In the practice
   the last prices sum to 1.02–1.08, i.e. the book is collectively a little
   over-priced, so each market's median is its last price `x` pulled halfway
   toward `x / S`, where `S` is the sum of all markets' last prices. No
   drift: at a 4-hour horizon the prices behave like a martingale — recent
   moves do not persist, and every drift variant tested on the practice made
   the median worse.
2. **Spread — a random-walk widening with a narrow core and fat tails.**
   The quantiles widen as `sigma * sqrt(h)`, but the 25/75% quantiles sit at
   z = ±0.4 and the 5/95% at z = ±2.2, instead of the normal ±0.674 /
   ±1.645: the interquartile range is much tighter than a normal walk and
   the tails much fatter, which is what step-like prices produce. Sigma is
   per market, `0.0012 * (0.6 + 1.2 * nz)`, where `nz` is the fraction of
   minutes with a price move in the last 720 minutes — quiet markets get a
   tighter core, busy ones a wider one. A plain realised volatility (RMS of
   minute changes) was tested and is far worse: it is dominated by the rare
   huge jumps and blows the spread up.
3. **One-sided jump allowances.** A walk's tails cannot cover a 0.24 jump
   in one minute, so both tails are widened beyond the walk, asymmetrically,
   because the big moves in the history are overwhelmingly collapses. The
   5% quantile is pushed down by `0.3 * x * (1 - exp(-h/240))`, and the 95%
   quantile up by `0.15 * x * (1 - exp(-h/240))` — the same saturating
   shape. The upside allowance is the missing half: the rules themselves
   cite a +0.24 one-minute jump, and the 95% level was the only quantile
   with clear headroom left. A symmetric widening was tested and hurts.

All quantiles are clamped to [0, 1], rounded to 6 decimals, and each row is
forced non-decreasing. The per-minute factors `sqrt(h)` and
`(1 - exp(-h/240))` are computed once per case and shared by all markets.
A market with no usable prices gets a neutral flat-0.5 forecast (house
baseline spread) instead of raising, so one malformed market can never
crash a run and invalidate the whole case.

## Local verification

The kit's practice answers for cases p00–p04 are recoverable from the next
case's input (each case's 240 forecast minutes sit inside the following
case's 72-hour history). Scored with the rules' pinball formula, as a
per-item mean over every case, market, minute and quantile (the definition
the ranking uses — note a plain average of the five per-case losses gives a
slightly different number, 0.3232, because the cases hold different market
counts):

| forecaster | loss on p00–p04 (per-item mean) |
|---|---|
| house baseline (starter) | 0.3925 |
| this entry | **0.3163** |

Per-case loss (this entry): p00 0.4537, p01 0.3120, p02 0.3578, p03 0.2742,
p04 0.2186; median error 0.8619, 90% coverage 0.9354. That is 19.4% below
the baseline on the same cases and the same scorer. The house baseline's
published practice loss over all six cases is 0.363589.

Alternatives tested and rejected (same scorer): level-scaled sigma (0.3182,
coverage collapses to 0.86), trailing-mean blended into the median (0.3255
at 25% blend), faster-saturating upside allowance (helps p00 but hurts
p03/p04), and further single-parameter moves of the fair pull, jump
allowances, tail/core z, sigma and activity window (all within ±0.004 —
noise; the model is at a local optimum).

Runtime: ~0.4 s for all six practice cases (cap is 8 s per case); outputs
216–279 KB (cap 1 MiB); two runs byte-identical.

## Build note

`main.py` was written in this session, which started after the competition
opened (09:00 UTC, 2026-11-13), so the transcript of this build falls
inside the competition's window. An earlier build session had started
before the opening and its transcript cannot be submitted; this rebuild
re-derives the same model from the rules and the practice data and produces
byte-identical outputs to that build.

Note: `makefun grade-local` refuses this kit — program/v1 competitions are
graded on the server only. The pre-submit check (`makefun check`) is run at
submit time by the parent agent, with the transcript bundle.
