# AGNTC Gold Trader

Flask dashboard for monitoring an Exness MT5 account and reviewing XAUUSD setups. The desktop dashboard has 15 individually routed navigation pages, account and connection status, and separate views for positions and trade history. Market Watch includes a live candlestick chart with M1, M5, M15, M30, H1, H4 and D1 timeframes.

## Run (Windows)
1. Install Python 3.10+ (64-bit) and MetaTrader 5; log into an Exness DEMO account; confirm the gold symbol in Market Watch.
2. `python -m venv venv` then `.\venv\Scripts\Activate.ps1`
3. `pip install -r requirements.txt`
4. `Copy-Item .env.example .env` and set a strong SECRET_KEY (leave MT5 credentials blank if the terminal is already logged in). Set `MT5_PATH` to the terminal executable or its containing folder to enable the dashboard's **Open MetaTrader** button. The `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD` values remain available as an administrator login.
5. `python app.py` and open http://127.0.0.1:5000. Choose **Create account** to register a dashboard user, or **Log in** to use an existing account.

If MetaTrader5 or pandas is unavailable, the login and dashboard UI can still start, but account data and market scans will remain unavailable until the project requirements are installed.

Registered users are stored in the local SQLite database with hashed passwords. All registered users access the same configured broker connection. The dashboard currently supports the account logged in through the configured MT5 terminal; switch accounts in MT5 before using a different account. Registration is open to anyone who can reach the app; keep the server bound to localhost unless you add appropriate deployment protections.

## Safety
- Live execution is OFF (`LIVE_TRADING_ENABLED=false`). Keep it off until tested on demo.
- Every signal needs your approval; trades are rejected if the broker's minimum lot risks more than the budget.
- The strategy is an unvalidated prototype. No profit is guaranteed; a $50 account may not fit XAUUSD minimum lot risk.
- Localhost only. Never commit `.env` or share broker passwords.
