# TODO - Telegram Trading Bot (Advanced Full Upgrade)

## Completed
- [x] Base project scaffold
- [x] Multi-market scanner foundation (US/Saudi/Crypto)
- [x] EMA/RSI strategy
- [x] Telegram sender
- [x] Basic symbol files
- [x] Basic config and docs

## Advanced Upgrade Plan (User approved: "نفذ الكل")
- [ ] 1) Smart alerts (high-score only + deduplication)
- [ ] 2) Auto watchlist (top 20 per market daily)
- [ ] 3) Session-aware behavior by market hours
- [ ] 4) Advanced risk controls (max signals/day + cooldown per symbol)
- [ ] 5) Quality filters (volatility/liquidity/spread proxy)
- [ ] 6) Multi-timeframe confirmation (15m + 1h)
- [ ] 7) Daily/weekly PDF reports (win-rate/drawdown)
- [ ] 8) Advanced dashboard (sort/filter/search/API status/heatmap)
- [ ] 9) Strategy plugins system (enable/disable from config)
- [ ] 10) Semi-auto mode with Telegram /approve command flow

## Supporting Work
- [ ] Extend settings and env
- [ ] Add persistent state store
- [ ] Add command polling handler for Telegram
- [ ] Add resilient HTTP client (retry/backoff/circuit-breaker)
- [ ] Add backtesting engine
- [ ] Update README and examples

## Testing (currently skipped by user preference)
- [ ] Critical-path or thorough runtime verification
