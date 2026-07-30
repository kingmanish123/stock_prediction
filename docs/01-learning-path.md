# Learning Path

Rule: **read before you code, code before you trade with paper, paper trade before you trade live.**

No shortcuts. Trading losses to ignorance are expensive tuition.

---

## Phase 1 — Foundations (Month 1)

### Books (in this order)
1. **"Algorithmic Trading" by Ernie Chan** ⭐ — starting point. Teaches systematic mindset + basic strategies.
2. **"Quantitative Trading" by Ernie Chan** — deeper, follows naturally after book 1.

### Free resources
1. **Zerodha Varsity** (https://zerodha.com/varsity/) — complete these modules:
   - Introduction to Stock Markets
   - Futures Trading
   - Options Theory for Professional Trading
   - Trading Systems
   - **Do NOT skip**: "Risk & Trading Psychology"
2. **QuantInsti blog** — free articles on strategies
3. **YouTube: Moviing Avg** (Hindi), **PyQuant News**, **QuantInsti**

### Coding prerequisites
- Python intermediate (pandas, NumPy, matplotlib)
- SQL basics
- Git basics
If shaky on Python: 1-week refresh with "Python for Data Analysis" (Wes McKinney)

### Goal at end of Phase 1
Understand: what makes a strategy valid, how backtesting lies, what risk management actually means, why discipline > prediction.

---

## Phase 2 — Backtesting & Strategies (Month 2)

### Books
3. **"Active Portfolio Management" by Grinold & Kahn** (heavy, selective reading)
4. **"Trading Systems and Methods" by Perry Kaufman** (reference, don't read cover-to-cover)

### Technical resources
- `vectorbt` documentation + tutorials
- `backtrader` examples
- **Paper**: "Time Series Momentum" by Moskowitz, Ooi, Pedersen (AQR) — classic momentum factor paper
- **Paper**: "Value and Momentum Everywhere" by Asness, Moskowitz, Pedersen

### Goal at end of Phase 2
Built and backtested one working momentum strategy with realistic transaction costs. Understand Sharpe, max drawdown, Calmar ratio, look-ahead bias, survivorship bias.

---

## Phase 3 — Live Paper Trading (Month 3)

### Books
5. **"Advances in Financial ML" by Marcos López de Prado** (only if going ML route later — skip initially)

### Technical resources
- Kite Connect API documentation (https://kite.trade/docs/connect/v3/)
- `kiteconnect` Python package
- Zerodha Kite Connect Forum

### Goal at end of Phase 3
Live paper trading system running — orders logged but not executed. 30+ days of paper results. Ready to evaluate going live with real (small) capital.

---

## Phase 4 — Live Small Capital (Month 4–6)

### Books
6. **"The Man Who Solved the Market" by Gregory Zuckerman** — not technical; motivational + lessons from Renaissance
7. **"Market Wizards" series by Jack Schwager** — interviews, various styles
8. **"Option Volatility and Pricing" by Sheldon Natenberg** (only if moving to options later)

### Goal at end of Phase 4
6 months of live (small) data. Real psychological experience with drawdowns. Strategy either validated or honestly dropped.

---

## Optional advanced (Month 6+)

- "Advances in Financial ML" (López de Prado)
- "Elements of Statistical Learning" (Hastie, Tibshirani, Friedman) — if using ML
- Papers on **risk parity**, **factor investing**, **volatility targeting**

---

## Communities & signals

- **Reddit**: r/algotrading (quality varies, some good posts)
- **Twitter**: Follow @marcos_lopezdp, @ptaylor, @therobotjames, @euanjsinclair, @choffstein
- **Blogs**: QuantConnect, Quantopian archives, Alpha Architect, Winton research
- **India-specific**: r/IndianStreetBets (mostly noise but sometimes good threads), Zerodha Pulse

⚠️ Avoid: "Trading gurus" on YouTube selling courses, Telegram "tip" groups, Discord "signal" groups. Zero signal, high noise.

---

## Learning log template

Maintain a personal log of what you read + key insights:

```
## YYYY-MM-DD — [Book/Paper/Chapter]
Key insights:
- ...
- ...

Unanswered questions:
- ...

Actionable: What does this change about my approach?
```
