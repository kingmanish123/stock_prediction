# Risk Rules (Non-Negotiable)

These rules are the difference between "engineer who traded" and "engineer who blew up their savings". Read often. Break never.

---

## Tier 1 — Capital safety (never break)

### R1. Never trade money you need within 3 years
Trading capital = money you can afford to lose 50% of without lifestyle impact. If losing it means can't pay rent/EMI → it's not trading capital.

### R2. Max 2% portfolio risk per trade
If portfolio = ₹5L, max loss per single trade = ₹10K. This is position size × (entry – stop loss) / entry.

### R3. Max 6% portfolio at-risk at any time
Total sum of all open position risks ≤ 6% of portfolio. Protects against correlated drawdowns.

### R4. Hard monthly loss limit = 8%
If portfolio down 8% in a month, **stop trading for the rest of the month**. Review, don't revenge trade.

### R5. Hard annual loss limit = 20%
If down 20% in a year, **pause for 3 months, review strategy from scratch**. Likely strategy doesn't work for current regime.

---

## Tier 2 — Discipline (don't break)

### R6. No leverage in Year 1
No futures (beyond cash-settled at nominal size), no margin trading, no options selling. Period.

### R7. No discretionary overrides
If the system says sell, sell. If it says buy, buy. If you "feel" otherwise, the system wasn't trusted → don't go live until it is.

### R8. Stop losses coded, not mental
Every live position must have a stop-loss order placed at time of entry. Mental stop-losses are not stops.

### R9. Paper trade 3 months minimum before live
Not just backtesting — live paper (real-time ticker, simulated orders). Backtests lie in subtle ways.

### R10. Journal every trade
Entry reason, exit reason, strategy name, position size, PnL. Weekly review of journal is mandatory.

---

## Tier 3 — Psychology (the silent killer)

### R11. No trading after losses > 2 days in a row
After 2 consecutive losing days, take next day off. Tilt is real.

### R12. No trading in first hour of major life events
Market doesn't care about your personal life. If emotional → don't click buy/sell.

### R13. No trading after 8 PM alcohol
(Doesn't apply to automated systems running themselves — only to any manual adjustments.)

### R14. No checking portfolio more than once a day
Intraday checking breeds overtrading and anxiety. Once daily for systematic strategies = enough.

### R15. Monthly honest self-review
Write a 200-word note: "This month I did X, I felt Y, strategy performed Z. I'm deceiving myself about ___ ."

---

## Strategy-level rules

### R16. Backtest ≠ reality
Backtest shows 25% annual? Expect 15% live. There's always a gap — overfit, slippage, regime shift.

### R17. Edge decays
A strategy that worked for 3 years may stop working. Review monthly. Rotate dead strategies out.

### R18. Diversify strategies when scaling
One strategy = concentration. 2–3 uncorrelated strategies = robustness.

### R19. Walk-forward, not static backtest
Test strategy on rolling windows (2015–2018 train, 2019 test; 2016–2019 train, 2020 test; …). Static backtests hide robustness issues.

### R20. Transaction costs matter
Always include brokerage + STT + GST + stamp duty + slippage in backtest. Strategies "profitable before costs" die in reality.

---

## Circuit breakers (coded in the live bot)

Auto-halt triggers:
- [ ] Daily loss > 3% → halt for day
- [ ] Weekly loss > 5% → halt for week
- [ ] Monthly loss > 8% → halt for month
- [ ] 5 consecutive losing trades → halt for 24 hr
- [ ] Unusual market conditions (VIX spike, gap >2%) → halt + alert
- [ ] API error rate > threshold → halt + alert

---

## "Pre-trade" checklist (before going live after paper trading)

- [ ] 3+ months of paper trading completed
- [ ] Paper trading Sharpe > 1.0 after realistic costs
- [ ] Max drawdown in paper <20%
- [ ] Strategy has passed walk-forward test on 5+ years historical
- [ ] Circuit breakers implemented + tested
- [ ] Trade journal set up
- [ ] Monthly review process set up
- [ ] Hard stop-loss on broker side coded
- [ ] Capital is "losable" without lifestyle impact
- [ ] Partner / family aware of decision (no secrets)

**If any checkbox is unchecked → do not go live.**

---

## Why these rules exist (honest reasons)

- **R1**: I've seen CTOs blow up trading with rent money. Don't.
- **R2–R4**: Kelly criterion + practical experience — 2% per trade caps blowup risk.
- **R9**: Personal history of every new trader: "backtest looks great! let me go live" → 30% drawdown in month 1.
- **R11**: Tilt after losses causes revenge trading. Revenge trading is the #1 cause of retail blowups.
- **R14**: Behavioral finance research — frequent checking correlates strongly with underperformance.
- **R17**: Renaissance Technologies rotates strategies constantly. If they do, you should.
