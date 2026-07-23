## What signal latency actually means for your bot {#what-latency-means}

Signal latency is the time between your strategy deciding to act and the broker confirming a position is open. It is **not** the same as your VPS's ping to the broker — that's just one part. The full path includes signal generation, network transit, broker order routing, and matching-engine fill.

For retail bots the right framing is **p50 vs p99**: the median trade vs the worst 1%. Strategies with thin edges live or die on p99, since a single 800 ms outlier can wipe out a day of good fills.

## The execution flow: from idea to filled order {#execution-flow}

Latency stacks up in predictable places. Most of the time your bot wastes is not on the wire — it's in the broker's own systems.

<!--CP_VISUAL:fig-flow-->

## Real broker latency numbers (p50 and p99) {#broker-numbers}

Public broker latency disclosures are rare, but you can derive plausible numbers from execution-quality reports. The chart below shows realistic ranges for three broker categories — ECN, market-maker, and crypto exchange — for a US-based VPS.

<!--CP_VISUAL:fig-broker-latency-->

The reason **p99 matters more than p50** is that thin-edge strategies leak their edge through the worst trades, not the median ones. A 540 ms p99 is not just three times worse than a 180 ms p99 — for a scalper, it's the difference between profitable and breakeven.

## When latency starts to hurt your P&L {#when-it-hurts}

Not every strategy is latency-sensitive. A breakout bot holding positions for hours barely notices an extra 100 ms. A scalping bot working a 5-pip range sees its win rate drop measurably above ~120 ms p99.

<!--CP_VISUAL:fig-strategy-table-->

Here is a hypothetical win-rate trend showing the same scalping strategy run on two setups across four months.

<!--CP_VISUAL:fig-winrate-->

If you're swing-trading via [signal bots](/signal-bots/), latency optimization is one of the last knobs to turn. Read the [risk warning](/risk-warning/) before optimizing for any single metric.

## How to measure your own latency in 10 minutes {#measure-yourself}

Three steps:

1. Timestamp the signal inside your strategy code at the moment of decision.
2. Timestamp the broker's order-acknowledgment callback.
3. Log both with millisecond precision and run across a normal session.

The histogram you get back is more honest than any broker brochure. If your p99 is comfortably below your strategy's threshold from the table above, save the VPS-upgrade money — spend it on backtests instead.

## FAQ {#faq}

### Does my VPS choice really matter for retail bots? {#faq-vps}

For sub-second strategies, yes — co-location near the broker's matching engine shaves real ms. For swing or position bots, almost not at all.

### What's a "good" p99 latency for a forex bot? {#faq-good-p99}

As a rule of thumb: under 80 ms for scalping, under 300 ms for most other strategies. Cheaper than chasing a faster VPS is fixing your broker's order-routing bottleneck.

## Conclusion {#conclusion}

Treat latency the way you treat slippage: measure it before you assume it. Most retail bots over-pay for speed and under-pay for execution-quality reports. Start by running the 10-minute measurement above; if your p99 is comfortably below your strategy threshold, spend that VPS-upgrade money on backtests instead.
