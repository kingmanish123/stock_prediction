# Tech Stack — Algo Trading System

## Overall architecture (target)

```
┌─────────────────────────────────────────────────────────────┐
│ DATA LAYER                                                  │
│  • Historical: yfinance (free, delayed) for backtesting     │
│  • Intraday historical: Kite Connect historical API         │
│  • Live: Kite Connect WebSocket                             │
│  • Fundamentals: screener.in scraper / Tickertape           │
│  • Storage: Parquet files (local) + PostgreSQL (metadata)   │
├─────────────────────────────────────────────────────────────┤
│ RESEARCH LAYER                                              │
│  • Jupyter Lab for exploration                              │
│  • pandas, NumPy, polars (for speed)                        │
│  • matplotlib, plotly for charts                            │
├─────────────────────────────────────────────────────────────┤
│ BACKTESTING LAYER                                           │
│  • Primary: vectorbt (fast, flexible)                       │
│  • Alternative: backtrader (more realistic, slower)         │
│  • Slippage + brokerage realistic modeling                  │
├─────────────────────────────────────────────────────────────┤
│ EXECUTION LAYER                                             │
│  • kiteconnect Python SDK (order placement)                 │
│  • Redis for live state management                          │
│  • APScheduler for cron-like strategy triggers              │
│  • Circuit breakers: max-loss, max-drawdown kill switches   │
├─────────────────────────────────────────────────────────────┤
│ MONITORING LAYER                                            │
│  • Telegram bot for alerts (trades, errors, daily PnL)      │
│  • Grafana + Prometheus (optional, later)                   │
│  • PostgreSQL trade journal                                 │
└─────────────────────────────────────────────────────────────┘
```

---

## Core tools

### Language & environment
- **Python 3.11+** (primary — overwhelming quant ecosystem)
- **venv / poetry / uv** for env management
- **VSCode** for IDE, **Jupyter Lab** for exploration
- **Git** for version control (private repo!)

### Data libraries
| Tool | Purpose |
|------|---------|
| `pandas` | Data manipulation |
| `numpy` | Numerics |
| `polars` | Fast alternative for big data (optional) |
| `yfinance` | Free EOD data (for backtesting only) |
| `nsepy` | NSE historical data (India) |
| `kiteconnect` | Zerodha live API |

### Backtesting libraries
| Tool | Notes |
|------|-------|
| `vectorbt` | Fast vectorized backtesting, great for portfolio-level |
| `backtrader` | Event-driven, more realistic, slower |
| `bt` | Simple, clean, good for factor strategies |

**Recommendation**: Start with `vectorbt` for momentum / portfolio strategies.

### Analytics
| Tool | Purpose |
|------|---------|
| `matplotlib` / `seaborn` | Static charts |
| `plotly` | Interactive charts |
| `quantstats` | Performance analytics (Sharpe, DD, etc.) |

### Infrastructure
| Tool | Purpose | Cost |
|------|---------|------|
| **Zerodha Kite Connect** | Broker API | ₹2,000/month |
| **DigitalOcean VPS** (for live bot) | 24/7 execution | ₹500/month |
| **PostgreSQL** (local or hosted) | Trade journal | Free/₹400/mo |
| **Redis** | Live state | Free (local) |
| **Telegram Bot API** | Alerts | Free |

### Trade journal tools
- `pandas` + `PostgreSQL` for logging every order + fill
- Web UI (optional): simple Flask/FastAPI dashboard

---

## Development environment setup checklist

- [ ] Install Python 3.11+ (pyenv)
- [ ] Create project: `algo-trading-system/` with poetry/uv
- [ ] Install: pandas, numpy, vectorbt, yfinance, matplotlib, jupyter, python-dotenv, kiteconnect
- [ ] Set up Jupyter Lab
- [ ] Set up .env for API keys (gitignored!)
- [ ] Create folder structure:
  ```
  algo-trading-system/
  ├── data/               # cached data
  ├── notebooks/          # research
  ├── strategies/         # strategy modules
  ├── backtests/          # results
  ├── live/               # live bot code
  ├── journal/            # trade logs
  └── tests/              # unit tests
  ```

---

## Zerodha Kite Connect setup (later, not Week 1)

**Steps**:
1. Register app at https://developers.kite.trade/
2. Pay ₹2,000/month (from Month 3+ only)
3. Generate API key + API secret
4. Implement OAuth login flow (one-time daily token)
5. Test order placement on small size

**Important**: Kite Connect access tokens expire daily at 6 AM. Automation needs daily login script (can't be fully hands-off).

---

## Python skeleton — backtest harness

```python
# strategies/momentum.py  (skeleton, not runnable)

import pandas as pd
import vectorbt as vbt

def momentum_strategy(
    universe: list[str],
    lookback_months: int = 3,
    top_n: int = 10,
    rebalance_freq: str = "M",
):
    prices = vbt.YFData.download(universe, start="2018-01-01").get("Close")

    monthly_returns = prices.resample(rebalance_freq).last().pct_change(lookback_months)

    ranks = monthly_returns.rank(axis=1, ascending=False)
    signals = (ranks <= top_n).astype(int) / top_n

    portfolio = vbt.Portfolio.from_holding_signals(
        prices, signals,
        fees=0.001,
        slippage=0.001,
    )

    return portfolio.stats()
```

(Real implementation in Week 2–3 after learning. This is a sketch.)

---

## Open tech decisions

- [ ] Backtest library: vectorbt vs backtrader (lean vectorbt for portfolio strategies)
- [ ] Data source: yfinance for free vs paid data later
- [ ] Dashboard: build custom vs Grafana (custom Flask for Month 6+)
- [ ] VPS: DigitalOcean vs Hetzner (Hetzner cheaper, ₹300/mo)
