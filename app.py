import os, json, hmac, secrets, sqlite3, re
from datetime import datetime, timezone
from functools import wraps

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

try:
    import pandas as pd
except ImportError:
    pd = None

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from dotenv import load_dotenv
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "false").lower() == "true",
)

USERNAME = os.getenv("DASHBOARD_USERNAME", "")
PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")
MT5_PATH = os.getenv("MT5_PATH", "").strip()
MT5_LOGIN = os.getenv("MT5_LOGIN", "").strip()
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "").strip()
MT5_SERVER = os.getenv("MT5_SERVER", "").strip()
SYMBOL = os.getenv("MT5_SYMBOL", "XAUUSD").strip()
LIVE_TRADING_ENABLED = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"
RISK_PERCENT = float(os.getenv("RISK_PERCENT", "0.5"))
MAX_DAILY_LOSS_PERCENT = float(os.getenv("MAX_DAILY_LOSS_PERCENT", "2"))
MAX_SPREAD_POINTS = int(os.getenv("MAX_SPREAD_POINTS", "80"))
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "1"))
DB_PATH = os.getenv("DATABASE_PATH", "trading.db")


# ---------- database ----------
def db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def initialize_database():
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL,
            symbol TEXT NOT NULL, side TEXT, entry REAL, stop_loss REAL,
            take_profit REAL, status TEXT NOT NULL, reason TEXT, execution TEXT)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL COLLATE NOCASE UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL)""")


initialize_database()


def save_signal(s):
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO signals (created_at,symbol,side,entry,stop_loss,take_profit,status,reason) VALUES (?,?,?,?,?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), s["symbol"], s["side"], s["entry"],
             s["stop_loss"], s["take_profit"], s["status"], json.dumps(s["reasons"])))
        return cur.lastrowid


def get_signals():
    with db() as conn:
        rows = conn.execute("SELECT * FROM signals ORDER BY id DESC LIMIT 50").fetchall()
    return [dict(r) for r in rows]


def update_signal(signal_id, status, execution=None):
    with db() as conn:
        conn.execute("UPDATE signals SET status=?, execution=? WHERE id=?",
                     (status, json.dumps(execution, default=str) if execution else None, signal_id))


# ---------- auth ----------
def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **k):
        if not session.get("logged_in"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("login"))
        return fn(*a, **k)
    return wrapper


def valid_csrf():
    supplied = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
    expected = session.get("csrf_token", "")
    return bool(expected and supplied and hmac.compare_digest(str(expected), str(supplied)))


@app.before_request
def ensure_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)


def start_user_session(user_id=None):
    session.clear()
    session["logged_in"] = True
    if user_id is not None:
        session["user_id"] = user_id
    session["csrf_token"] = secrets.token_urlsafe(32)


@app.route("/")
def landing():
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        if not valid_csrf():
            flash("Your session expired. Please try again.", "error")
            return redirect(url_for("login"))
        u, p = request.form.get("username", "").strip(), request.form.get("password", "")
        if USERNAME and PASSWORD and hmac.compare_digest(u, USERNAME) and hmac.compare_digest(p, PASSWORD):
            start_user_session()
            return redirect(url_for("dashboard"))
        with db() as conn:
            user = conn.execute("SELECT id, password_hash FROM users WHERE username=?", (u,)).fetchone()
        if user and check_password_hash(user["password_hash"], p):
            start_user_session(user["id"])
            return redirect(url_for("dashboard"))
        flash("Incorrect username or password.", "error")
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("logged_in"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        if not valid_csrf():
            flash("Your session expired. Please try again.", "error")
            return redirect(url_for("register"))
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirmation = request.form.get("password_confirmation", "")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username):
            flash("Username must be 3-32 characters using letters, numbers, dots, underscores or hyphens.", "error")
        elif len(password) < 12:
            flash("Password must be at least 12 characters.", "error")
        elif len(password) > 1024:
            flash("Password must be 1024 characters or fewer.", "error")
        elif password != confirmation:
            flash("Passwords do not match.", "error")
        else:
            try:
                with db() as conn:
                    cur = conn.execute(
                        "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                        (username, generate_password_hash(password), datetime.now(timezone.utc).isoformat()))
                start_user_session(cur.lastrowid)
                return redirect(url_for("dashboard"))
            except sqlite3.IntegrityError:
                flash("That username is already registered.", "error")
    return render_template("register.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    if not valid_csrf():
        return "Invalid security token", 400
    session.clear()
    return redirect(url_for("login"))


# ---------- MT5 ----------
def connect_mt5():
    if mt5 is None:
        raise RuntimeError("MetaTrader5 is not installed. Install the project requirements to connect to a trading account.")
    if mt5.terminal_info() is not None:
        return True
    kwargs = {"path": MT5_PATH} if MT5_PATH else {}
    if not mt5.initialize(**kwargs):
        raise RuntimeError(f"MT5 initialization failed: {mt5.last_error()}")
    if MT5_LOGIN and MT5_PASSWORD and MT5_SERVER:
        if not mt5.login(int(MT5_LOGIN), password=MT5_PASSWORD, server=MT5_SERVER):
            err = mt5.last_error()
            mt5.shutdown()
            raise RuntimeError(f"MT5 login failed: {err}")
    return True


def get_symbol_info():
    connect_mt5()
    info = mt5.symbol_info(SYMBOL)
    if info is None:
        raise RuntimeError(f"Symbol '{SYMBOL}' not found. Check the exact Exness symbol name.")
    if not info.visible and not mt5.symbol_select(SYMBOL, True):
        raise RuntimeError(f"Could not enable {SYMBOL} in Market Watch.")
    return mt5.symbol_info(SYMBOL)


def get_account():
    connect_mt5()
    a = mt5.account_info()
    if a is None:
        raise RuntimeError("Unable to retrieve MT5 account information.")
    return a._asdict()


def get_candles(tf, count=300):
    connect_mt5()
    if pd is None:
        raise RuntimeError("pandas is not installed. Install the project requirements to scan market data.")
    frames = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5, "M15": mt5.TIMEFRAME_M15}
    rates = mt5.copy_rates_from_pos(SYMBOL, frames[tf], 0, count)
    if rates is None or len(rates) < 60:
        raise RuntimeError(f"Insufficient {tf} market data.")
    return pd.DataFrame(rates)


def calculate_indicators(df):
    df = df.copy()
    df["ema9"] = df["close"].ewm(span=9, adjust=False).mean()
    df["ema21"] = df["close"].ewm(span=21, adjust=False).mean()
    d = df["close"].diff()
    gain = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    df["rsi"] = 100 - (100 / (1 + gain / loss.replace(0, float("nan"))))
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    return df


def generate_signal():
    m1 = calculate_indicators(get_candles("M1"))
    m5 = calculate_indicators(get_candles("M5"))
    m15 = calculate_indicators(get_candles("M15"))
    a, b, c = m1.iloc[-2], m5.iloc[-2], m15.iloc[-2]  # completed candles only
    quote = mt5.symbol_info_tick(SYMBOL)
    info = get_symbol_info()
    if quote is None:
        raise RuntimeError("Market quote unavailable.")
    spread = (quote.ask - quote.bid) / info.point
    side, reasons = None, []
    bullish = c.ema9 > c.ema21 and b.ema9 > b.ema21 and a.ema9 > a.ema21 and 50 <= a.rsi <= 70
    bearish = c.ema9 < c.ema21 and b.ema9 < b.ema21 and a.ema9 < a.ema21 and 30 <= a.rsi <= 50
    if spread > MAX_SPREAD_POINTS:
        reasons.append("Rejected: spread is above the configured threshold.")
    elif bullish:
        side = "BUY"
        reasons += ["Bullish EMA alignment across M1, M5 and M15.", "M1 RSI momentum confirmation."]
    elif bearish:
        side = "SELL"
        reasons += ["Bearish EMA alignment across M1, M5 and M15.", "M1 RSI momentum confirmation."]
    else:
        reasons.append("No qualifying setup.")
    entry = sl = tp = None
    if side:
        entry = quote.ask if side == "BUY" else quote.bid
        dist = max(float(a.atr) * 1.5, info.point * 20)
        sl, tp = ((entry - dist, entry + dist * 1.5) if side == "BUY" else (entry + dist, entry - dist * 1.5))
    f = lambda v: float(v) if v is not None else None
    return {"symbol": SYMBOL, "side": side, "entry": f(entry), "stop_loss": f(sl), "take_profit": f(tp),
            "spread": float(spread), "reasons": reasons, "status": "PENDING_APPROVAL" if side else "NO_SIGNAL"}


def calculate_position_size(side, entry, stop_loss):
    account, info = get_account(), get_symbol_info()
    risk = account["equity"] * RISK_PERCENT / 100
    ot = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
    vmin, vmax, step = info.volume_min, info.volume_max, info.volume_step
    min_loss = mt5.order_calc_profit(ot, SYMBOL, vmin, entry, stop_loss)
    if min_loss is None:
        raise RuntimeError("Broker could not calculate minimum-lot risk.")
    min_loss = abs(min_loss)
    if min_loss <= 0 or min_loss > risk:
        raise ValueError(f"Trade rejected: minimum lot risks about ${min_loss:.2f}, above the ${risk:.2f} risk budget.")
    vol = vmin
    for n in range(int((vmax - vmin) / step) + 1):
        cand = round(vmin + n * step, 8)
        l = mt5.order_calc_profit(ot, SYMBOL, cand, entry, stop_loss)
        if l is None or abs(l) > risk:
            break
        vol = cand
    est = abs(mt5.order_calc_profit(ot, SYMBOL, vol, entry, stop_loss))
    margin = mt5.order_calc_margin(ot, SYMBOL, vol, entry)
    if margin is None or margin > account["margin_free"]:
        raise ValueError("Insufficient free margin for this order.")
    return {"volume": vol, "estimated_loss": est, "risk_budget": risk, "margin_required": margin}


def daily_loss_check():
    account = get_account()
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    deals = mt5.history_deals_get(start, now)
    if deals is None:
        raise RuntimeError("Unable to retrieve daily trading history.")
    realized = sum(d.profit + d.commission + d.swap + d.fee for d in deals if d.entry == mt5.DEAL_ENTRY_OUT)
    if realized <= -(account["balance"] * MAX_DAILY_LOSS_PERCENT / 100):
        raise ValueError("Daily realized-loss limit reached.")
    return realized


def execute_approved_trade(signal):
    if not LIVE_TRADING_ENABLED:
        raise RuntimeError("Live trading is disabled in .env.")
    if not get_account()["trade_allowed"]:
        raise RuntimeError("Trading is not permitted by the MT5 account.")
    daily_loss_check()
    if len(mt5.positions_get(symbol=SYMBOL) or []) >= MAX_OPEN_POSITIONS:
        raise RuntimeError("Maximum open positions reached.")
    sizing = calculate_position_size(signal["side"], signal["entry"], signal["stop_loss"])
    quote = mt5.symbol_info_tick(SYMBOL)
    ot = mt5.ORDER_TYPE_BUY if signal["side"] == "BUY" else mt5.ORDER_TYPE_SELL
    req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": SYMBOL, "volume": sizing["volume"], "type": ot,
           "price": quote.ask if signal["side"] == "BUY" else quote.bid,
           "sl": signal["stop_loss"], "tp": signal["take_profit"], "deviation": 30,
           "magic": 26091109, "comment": "AGNTC manual-approved trade", "type_time": mt5.ORDER_TIME_GTC}
    result, last_error = None, None
    for filling in (mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN):
        req["type_filling"] = filling
        check = mt5.order_check(req)
        if check is None or check.retcode != 0:
            last_error = str(check)
            continue
        result = mt5.order_send(req)
        if result is not None and result.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED):
            break
        last_error = str(result)
    if result is None or result.retcode not in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED):
        raise RuntimeError(f"Order was not executed: {last_error}")
    return {"ticket": result.order, "volume": sizing["volume"],
            "estimated_loss": sizing["estimated_loss"], "result": result._asdict()}


# ---------- routes ----------
@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", csrf_token=session["csrf_token"],
                           risk_percent=RISK_PERCENT,
                           max_daily_loss_percent=MAX_DAILY_LOSS_PERCENT,
                           max_open_positions=MAX_OPEN_POSITIONS)


@app.route("/api/status")
@login_required
def api_status():
    try:
        acc, info = get_account(), get_symbol_info()
        q = mt5.symbol_info_tick(SYMBOL)
        if q is None:
            raise RuntimeError("No current quote available.")
        return jsonify({
            "connected": True,
            "account": {k: acc[k] for k in ("login", "balance", "equity", "profit", "currency", "server")},
            "market": {"symbol": SYMBOL, "bid": q.bid, "ask": q.ask, "spread": (q.ask - q.bid) / info.point,
                       "minimum_lot": info.volume_min, "contract_size": info.trade_contract_size},
            "open_positions": len(mt5.positions_get(symbol=SYMBOL) or []),
            "live_enabled": LIVE_TRADING_ENABLED})
    except Exception as e:
        return jsonify({"connected": False, "error": str(e)}), 503


@app.route("/api/signals")
@login_required
def api_signals():
    return jsonify(get_signals())


@app.route("/api/scan", methods=["POST"])
@login_required
def api_scan():
    if not valid_csrf():
        return jsonify({"error": "Invalid security token"}), 400
    try:
        s = generate_signal()
        return jsonify({"id": save_signal(s), **s})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/approve/<int:signal_id>", methods=["POST"])
@login_required
def api_approve(signal_id):
    if not valid_csrf():
        return jsonify({"error": "Invalid security token"}), 400
    with db() as conn:
        row = conn.execute("SELECT * FROM signals WHERE id=?", (signal_id,)).fetchone()
    if not row:
        return jsonify({"error": "Signal not found"}), 404
    if row["status"] != "PENDING_APPROVAL":
        return jsonify({"error": "Signal is no longer pending"}), 409
    body = request.get_json(silent=True) or {}
    if body.get("approved") is not True:
        update_signal(signal_id, "REJECTED")
        return jsonify({"status": "REJECTED", "message": "Signal declined."})
    sig = {k: row[k] for k in ("symbol", "side", "entry", "stop_loss", "take_profit")}
    if not LIVE_TRADING_ENABLED:
        update_signal(signal_id, "APPROVED_NOT_EXECUTED", {"reason": "Live execution disabled in configuration"})
        return jsonify({"status": "APPROVED_NOT_EXECUTED", "message": "Approval recorded. No live order was sent."})
    try:
        ex = execute_approved_trade(sig)
        update_signal(signal_id, "EXECUTED", ex)
        return jsonify({"status": "EXECUTED", "message": f"Order sent, ticket {ex['ticket']}.", "execution": ex})
    except Exception as e:
        update_signal(signal_id, "EXECUTION_REJECTED", {"error": str(e)})
        return jsonify({"error": str(e)}), 400


@app.route("/api/positions")
@login_required
def api_positions():
    try:
        if mt5 is None:
            raise RuntimeError("MetaTrader5 is not installed. Install the project requirements to retrieve positions.")
        return jsonify([{"ticket": p.ticket, "type": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                         "volume": p.volume, "entry": p.price_open, "current_price": p.price_current,
                         "stop_loss": p.sl, "take_profit": p.tp, "profit": p.profit}
                        for p in (mt5.positions_get(symbol=SYMBOL) or [])])
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/performance")
@login_required
def api_performance():
    try:
        if mt5 is None:
            raise RuntimeError("MetaTrader5 is not installed. Install the project requirements to retrieve performance.")
        acc = get_account()
        now = datetime.now(timezone.utc)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        all_d, today_d = mt5.history_deals_get(0, now), mt5.history_deals_get(start, now)
        if all_d is None or today_d is None:
            raise RuntimeError("Unable to retrieve account deal history.")
        net = lambda d: d.profit + d.commission + d.swap + d.fee
        ca = [d for d in all_d if d.entry == mt5.DEAL_ENTRY_OUT]
        ct = [d for d in today_d if d.entry == mt5.DEAL_ENTRY_OUT]
        wins, losses = sum(1 for d in ct if net(d) > 0), sum(1 for d in ct if net(d) < 0)
        return jsonify({"balance": acc["balance"], "equity": acc["equity"], "floating_profit": acc["profit"],
                        "total_realized_profit": sum(net(d) for d in ca), "realized_today": sum(net(d) for d in ct),
                        "closed_trades": len(ct), "wins": wins, "losses": losses,
                        "win_rate": wins / len(ct) * 100 if ct else 0})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/history")
@login_required
def api_history():
    try:
        if mt5 is None:
            raise RuntimeError("MetaTrader5 is not installed. Install the project requirements to retrieve trade history.")
        connect_mt5()
        deals = mt5.history_deals_get(0, datetime.now(timezone.utc))
        if deals is None:
            raise RuntimeError("Unable to retrieve account deal history.")
        close_entries = (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY, mt5.DEAL_ENTRY_INOUT)
        closed = [d for d in deals if d.entry in close_entries]
        closed.sort(key=lambda d: d.time, reverse=True)
        return jsonify([{
            "ticket": d.ticket,
            "time": datetime.fromtimestamp(d.time, timezone.utc).isoformat(),
            "symbol": d.symbol,
            "side": "BUY" if d.type == mt5.DEAL_TYPE_BUY else "SELL",
            "volume": d.volume,
            "price": d.price,
            "profit": d.profit + d.commission + d.swap + d.fee,
        } for d in closed[:50]])
    except Exception as e:
        return jsonify({"error": str(e)}), 400


if __name__ == "__main__":
    print("=" * 45, "\nAGNTC GOLD TRADER\nInstrument:", SYMBOL,
          "\nLive execution:", LIVE_TRADING_ENABLED, "\nManual approval: REQUIRED\n" + "=" * 45)
    app.run(host="127.0.0.1", port=5000, debug=False)
