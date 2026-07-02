# Telegram Trading Scanner Bot (US + Saudi + Crypto)

## Features
- Multi-market signal scanner:
  - US stocks (via TwelveData)
  - Saudi stocks (via TwelveData)
  - Crypto pairs including BTC (via Binance public API)
- Strategy: EMA crossover + RSI filter
- Telegram summary notifications (anti-spam chunking)
- JSONL logs:
  - `scanner_results.jsonl`
  - `scanner_errors.jsonl`

## Important Safety Notes
- This project is **not financial advice**.
- Default mode is signal scanning, not live order execution.
- Keep API keys secret.
- If bot token is exposed, regenerate it via BotFather.

## Setup

1) Create and activate virtual environment (Windows CMD):
```cmd
cd C:\Users\hidan\Desktop\telegram-trading-bot
python -m venv .venv
.venv\Scripts\activate
```

2) Install dependencies:
```cmd
pip install -r requirements.txt
```

3) Configure environment:
```cmd
copy .env.example .env
```
Then edit `.env` and set:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TWELVEDATA_API_KEY`

## Run scanner
```cmd
python scanner.py
```

## Optional legacy single-symbol paper mode
```cmd
python main.py
```

## Railway deployment
Railway uses `nixpacks.toml`, which starts the bot with:
```cmd
python start_prod.py
```

Set these environment variables in Railway:
- `BOT_TOKEN`
- `ADMIN_IDS`
- `DATABASE_URL`
- `MARKET_TIMEZONE=Asia/Riyadh`
- `DASHBOARD_BASE_URL` public Railway URL for VIP dashboard links, if `RAILWAY_PUBLIC_DOMAIN` is not available

## Symbol lists
Edit:
- `symbols_us.txt`
- `symbols_saudi.txt`
- `symbols_crypto.txt`

## Logs
- `scanner_results.jsonl`: per-symbol scan records
- `scanner_errors.jsonl`: API/network/symbol errors

## Testing Guidance
Recommended before production:
- Validate API keys and chat delivery
- Validate at least one symbol from each market
- Validate summary message chunking
- Validate handling of TwelveData rate limits/errors
