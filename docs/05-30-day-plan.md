# 30-Day Kickoff Plan — Algo Trading System

Daily: ~30 min (Phase 1 allocation)
Weekend: 2–3 hours each day

Goal of Month 1: Foundation laid — books read, backtest framework working, first strategy backtested honestly.

**No live capital deployed this month. No exceptions.**

---

## Week 1 — Foundations (Apr 22 – Apr 28)

### Goals
- Set up Python environment for trading work
- Start Ernie Chan book 1
- Complete Zerodha Varsity "Intro to Markets" module

### Daily tasks
| Day | Task | Hours |
|-----|------|-------|
| Mon | Setup: Python, poetry/uv, create `algo-trading-system/` repo | 0.5 |
| Tue | Install core libs (pandas, numpy, vectorbt, yfinance, jupyter). Verify. | 0.5 |
| Wed | Start Ernie Chan book 1 — chapters 1–2 | 0.5 |
| Thu | Continue Ernie Chan — chapter 3 | 0.5 |
| Fri | Complete Zerodha Varsity "Intro to Markets" | 0.5 |
| Sat | Read: "Risk & Trading Psychology" (Varsity) | 2 |
| Sun | Free exploration in Jupyter: download Nifty50 data via yfinance, plot | 2 |

### Week 1 output
- Dev env ready
- 3 chapters of Ernie Chan internalized
- Comfortable downloading + plotting price data

---

## Week 2 — First Backtest (Apr 29 – May 5)

### Goals
- Implement simplest possible momentum strategy
- Understand Sharpe, drawdown, basic metrics
- Read Ernie Chan book 1 chapters 4–6

### Daily tasks
| Day | Task | Hours |
|-----|------|-------|
| Mon | Chapter 4 of Ernie Chan — linear strategies | 0.5 |
| Tue | Chapter 5 Ernie Chan — mean reversion | 0.5 |
| Wed | Start coding: Nifty50 momentum strategy in Jupyter | 0.5 |
| Thu | Continue coding — run first naive backtest (no costs) | 0.5 |
| Fri | Add realistic costs (slippage 0.1%, brokerage, STT) | 0.5 |
| Sat | Analyze results — Sharpe, max DD, best/worst months | 2 |
| Sun | Read `vectorbt` docs, refactor code to use vectorbt | 3 |

### Week 2 output
- One working momentum backtest (with realistic costs)
- First experience of "oh, my strategy looked great until I added costs"

---

## Week 3 — Robustness (May 6 – May 12)

### Goals
- Walk-forward testing
- Multiple parameter variations
- Out-of-sample validation

### Daily tasks
| Day | Task | Hours |
|-----|------|-------|
| Mon | Walk-forward test implementation | 0.5 |
| Tue | Test lookback periods: 3, 6, 12 months | 0.5 |
| Wed | Test universe: Nifty50 vs Nifty100 vs Nifty500 | 0.5 |
| Thu | Test rebalance: monthly vs weekly | 0.5 |
| Fri | Compile results into summary doc | 0.5 |
| Sat | Research: read "Time Series Momentum" paper (Moskowitz et al.) | 2 |
| Sun | Ernie Chan book 1 completion (chapters 7–end) | 3 |

### Week 3 output
- Validated: does momentum actually work in Indian markets?
- Chosen parameters for Phase 2 paper trading
- Ernie Chan book 1 complete

---

## Week 4 — Paper Trading Prep (May 13 – May 19)

### Goals
- Design paper trading architecture
- Set up trade journaling
- Plan capital allocation

### Daily tasks
| Day | Task | Hours |
|-----|------|-------|
| Mon | Design: How will I track paper trades? (spreadsheet vs DB vs script) | 0.5 |
| Tue | Set up PostgreSQL locally, create trades schema | 0.5 |
| Wed | Write paper trading wrapper (logs orders, doesn't send them) | 0.5 |
| Thu | Test: run paper trading for 1 simulated day end-to-end | 0.5 |
| Fri | Set up Telegram bot for alerts | 0.5 |
| Sat | Write Month 1 retrospective + Month 2 plan | 2 |
| Sun | Rest | 0 |

### Week 4 output
- Paper trading system ready to run
- Trade journal operational
- Month 2 plan written

---

## End of Month 1 — success criteria

- [ ] Ernie Chan "Algorithmic Trading" (book 1) completed
- [ ] Zerodha Varsity: 3 modules completed minimum
- [ ] Working momentum strategy backtest (with realistic costs)
- [ ] Walk-forward test passed for at least 1 strategy
- [ ] Paper trading system built (not live yet)
- [ ] Trade journal set up
- [ ] No live capital deployed (discipline check)

## End of Month 1 — failure indicators (honest)

If at Day 30:
- Haven't finished at least 1 book → reading discipline broken
- Backtest has look-ahead bias or missing costs → fundamentally flawed
- Already traded live capital → **stop immediately, go back to books**
- Strategies show 50%+ returns in backtest → likely overfit, suspect

---

## Month 2 preview

- Paper trade strategy live
- Start Ernie Chan book 2
- Research second strategy (pair trading or factor)
- Understand: what does real slippage look like vs backtest assumptions?

## Month 3 preview

- Complete 3 months of paper trading
- Review: does paper performance match backtest?
- Decision: go live with small capital or iterate more?
