# Decision Log — Pre-Market Stock Prediction System

Log every non-trivial decision here. Revisit before changing.

Format:
```
## YYYY-MM-DD — Decision title
**Options**:
- A: ...
- B: ...

**Chosen**: B
**Why**: ...
**Revisit if**: (condition that would trigger reversal)
```

---

## 2026-04-22 — Build trading system for personal use only, not for selling
**Options**:
- A: Build and sell stock prediction tool / tips service
- B: Build systematic trading for personal capital only

**Chosen**: B
**Why**:
- Selling tips/predictions in India requires SEBI RIA registration (legal risk)
- Real edge (if any) is better kept private — selling dilutes it
**Revisit if**: Never — this is a long-term ethical + legal stance

---

## 2026-04-22 — 🔄 PIVOT: Switch from execution trading system to pure prediction tool
**Options**:
- A: Original architecture — systematic trading with broker integration, risk manager, order execution
- B: Pure pre-market prediction system, local only, no execution — user reads predictions, decides manually

**Chosen**: B
**Why**:
- User explicitly wants to "play with data + numbers and validate through output"
- No SEBI concerns since no advisory service
- No live trading = no capital at risk during experimentation
- Much simpler scope — can validate hypothesis faster
- If predictions show edge, can always add execution later
- Prevents over-engineering early when we don't know if the signal exists
**Revisit if**: Predictions show strong edge (>65% directional accuracy, >3.5/5 top-5 hit rate) for 6+ months AND user wants to deploy capital

**Impact on existing docs**:
- ARCHITECTURE.md — completely rewritten (v2.0)
- REQUIREMENTS.md — new doc
- README.md — updated scope
- 02-strategy-options.md — partially obsolete (kept for reference)
- 04-risk-rules.md — N/A (no trading)
- 05-30-day-plan.md — needs rewrite
- 06-capital-plan.md — N/A
- 03-tech-stack.md — superseded by REQUIREMENTS.md §4–5

---

## 2026-04-22 — Universe: Nifty 50 only in Phase 1
**Options**:
- A: Nifty 50
- B: Nifty 100
- C: Nifty 500
- D: All NSE stocks

**Chosen**: A (Nifty 50)
**Why**:
- Most liquid, most news-covered → best signal-to-noise
- 50 stocks × 5 years = manageable compute
- If Phase 1 shows edge, expand to Nifty 100 in Phase 2
**Revisit if**: Phase 1 validation period completes successfully (Month 3+)

---

## 2026-04-22 — Validation: 60% directional accuracy primary, 3/5 top picks secondary
**Options**:
- A: Direction only (binary up/down accuracy)
- B: Price range accuracy (actual within predicted range)
- C: Top-N hit rate
- D: Simulated P&L

**Chosen**: A + C combined
**Why**:
- Directional accuracy is the cleanest, simplest metric
- Top-N hit rate is what user actually cares about ("3 of 5 picks work")
- Range accuracy is a bonus — won't gate decisions on it
- P&L simulation will be tracked but not a primary gate (too many trading-cost assumptions)
**Revisit if**: Metrics prove to not correlate with usefulness

---

## 2026-04-22 — News sources: free tier first, paid only if Phase 1 signal is weak
**Options**:
- A: Free-only (NSE/BSE + RSS feeds)
- B: Paid baseline (MarketAux + free)
- C: Premium (EventRegistry, etc.)

**Chosen**: A for V1, B from V2 if needed
**Why**:
- Validate the system design first before spending
- Free sources genuinely cover ~80% of relevant Indian financial news
- MarketAux ($29/mo) is best-value V2 upgrade if V1 shows weak accuracy
**Revisit if**: V1 validation (Month 2–3) shows <55% accuracy and error analysis suggests news gaps

---

## 2026-04-22 — Horizon: intraday + next 1–3 days
**Options**:
- A: Intraday only (today)
- B: Multi-day (1–3 days)
- C: Week-ahead

**Chosen**: A + B (intraday today + 1–3 day forward)
**Why**: Both have signal, different use cases. Same model architecture can produce both.

---

## 2026-04-22 — Local-only, no servers/cloud
**Options**:
- A: Cloud-hosted (AWS/DigitalOcean)
- B: Local on user's Mac
- C: Hybrid

**Chosen**: B
**Why**:
- User explicitly said no server needed
- Simpler ops, no recurring infra costs
- 8 AM manual run works fine locally
- No SLA / uptime constraints (user is the only consumer)
**Revisit if**: System becomes hands-off and user travels frequently

---

## 2026-04-22 — Focus on systematic, not predictive
**Options**:
- A: ML prediction models (LSTM, transformers, etc.)
- B: Systematic rule-based strategies

**Chosen**: Hybrid — ML for ranking/direction + LLM for reasoning + systematic rules for final filtering
**Why** (updated post-pivot):
- User explicitly wants to "play with numbers" — ML is the right tool for this
- LLM layer adds interpretability (why this stock)
- Rule-based filters ensure calibration + sanity
- Pure ML = overfit risk; pure rules = no adaptation
**Revisit**: Will tune mix based on what works

---

## 2026-04-22 — Python for all tooling
**Options**:
- A: Python
- B: Node.js
- C: Go/Rust

**Chosen**: A
**Why**: Quant + NLP + ML ecosystem is Python-first. No contenders.

---

## PENDING — LLM provider
**Options**:
- A: Anthropic Claude
- B: OpenAI GPT-4o
- C: Open-source via Ollama (local Llama)

**Question to user**: Which coupon do you have?

---

## PENDING — Folder rename
**Options**:
- A: Keep `algo-trading-system/` (current)
- B: Rename to `stock-prediction-system/`

**Consideration**: Current name misleading; new name reflects reality. But requires updating all references.
**Recommendation**: Rename when comfortable; not urgent.

---

## PENDING — Telegram phone push
**Options**:
- A: Terminal + Markdown + JSON only
- B: Also push daily summary to Telegram

**Consideration**: Low effort (15 min setup), lets you see report on phone.
