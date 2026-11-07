
import os
import time
import requests
from datetime import datetime, timezone

# ===== SOZLAMALAR =====
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
API_KEY = os.getenv("TWELVE_DATA_API_KEY")

SYMBOL = "XAU/USD"
TIMEFRAMES = {
    "M1": "1min",
    "M5": "5min",
    "M15": "15min"
}

CHECK_INTERVAL = 60
SIGNAL_EXPIRY = 10
MIN_SCORE = 3

last_signals = {}
last_signal_time = {}

# ===== INDIKATORLAR =====

def ema(values, period):
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    result = sum(values[:period]) / period
    for value in values[period:]:
        result = value * k + result * (1 - k)
    return result


def rsi(values, period=14):
    if len(values) < period + 1:
        return 50

    changes = [
        values[i] - values[i - 1]
        for i in range(1, len(values))
    ]

    gains = [max(x, 0) for x in changes[-period:]]
    losses = [max(-x, 0) for x in changes[-period:]]

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    if avg_loss == 0:
        return 100

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def atr(candles, period=14):
    if len(candles) < period + 1:
        return None

    trs = []
    for i in range(1, len(candles)):
        high = candles[i]["high"]
        low = candles[i]["low"]
        previous = candles[i - 1]["close"]

        trs.append(max(
            high - low,
            abs(high - previous),
            abs(low - previous)
        ))

    return sum(trs[-period:]) / period


def macd(values):
    fast = ema(values, 12)
    slow = ema(values, 26)

    if fast is None or slow is None:
        return 0, 0

    line = fast - slow
    return line, 0


# ===== NARX MA'LUMOTI =====

def get_candles(interval):
    url = "https://api.twelvedata.com/time_series"

    params = {
        "symbol": SYMBOL,
        "interval": interval,
        "outputsize": 120,
        "apikey": API_KEY
    }

    response = requests.get(
        url, params=params, timeout=20
    )
    data = response.json()

    if "values" not in data:
        print("API xatosi:", data)
        return None

    candles = []

    for item in reversed(data["values"]):
        candles.append({
            "open": float(item["open"]),
            "high": float(item["high"]),
            "low": float(item["low"]),
            "close": float(item["close"]),
            "time": item["datetime"]
        })

    return candles


# ===== STRATEGIYA =====

def analyze(candles):
    if not candles or len(candles) < 40:
        return None

    closes = [c["close"] for c in candles]
    current = closes[-1]

    ema9 = ema(closes, 9)
    ema21 = ema(closes, 21)
    ema50 = ema(closes, 50)
    current_rsi = rsi(closes)
    current_atr = atr(candles)

    if None in (ema9, ema21, ema50, current_atr):
        return None

    macd_line, _ = macd(closes)

    previous = candles[-2]
    last = candles[-1]

    recent_high = max(c["high"] for c in candles[-21:-1])
    recent_low = min(c["low"] for c in candles[-21:-1])

    buy_score = 0
    sell_score = 0

    # EMA trend
    if ema9 > ema21:
        buy_score += 1
    if ema9 < ema21:
        sell_score += 1

    if current > ema50:
        buy_score += 1
    if current < ema50:
        sell_score += 1

    # RSI
    if 52 <= current_rsi <= 70:
        buy_score += 1
    if 30 <= current_rsi <= 48:
        sell_score += 1

    # MACD
    if macd_line > 0:
        buy_score += 1
    if macd_line < 0:
        sell_score += 1

    # Breakout
    if current > recent_high:
        buy_score += 1
    if current < recent_low:
        sell_score += 1

    # Sham tasdig'i
    bullish = (
        last["close"] > last["open"]
        and previous["close"] < previous["open"]
        and last["close"] > previous["open"]
    )

    bearish = (
        last["close"] < last["open"]
        and previous["close"] > previous["open"]
        and last["close"] < previous["open"]
    )

    if bullish:
        buy_score += 1
    if bearish:
        sell_score += 1

    # Juda uzoq ketgan narx ortidan quvmaslik
    if abs(current - ema9) > current_atr * 0.8:
        return None

    if buy_score >= MIN_SCORE and buy_score > sell_score:
        direction = "BUY"
        score = buy_score
    elif sell_score >= MIN_SCORE and sell_score > buy_score:
        direction = "SELL"
        score = sell_score
    else:
        return None

    return {
        "direction": direction,
        "score": score,
        "price": current,
        "atr": current_atr,
        "rsi": current_rsi,
        "candle_time": last["time"]
    }


# ===== SIGNAL FORMAT =====

def create_signal(result, timeframe):
    price = result["price"]
    volatility = result["atr"]
    direction = result["direction"]

    risk = volatility * 1.2

    if direction == "BUY":
        sl = price - risk
        tp1 = price + risk
        tp2 = price + risk * 1.8
        tp3 = price + risk * 2.5
    else:
        sl = price + risk
        tp1 = price - risk
        tp2 = price - risk * 1.8
        tp3 = price - risk * 2.5

    return (
        f"🥇 XAUUSD {direction}\n\n"
        f"⏱ Timeframe: {timeframe}\n"
        f"💰 Entry: {price:.2f}\n"
        f"🛑 SL: {sl:.2f}\n"
        f"🎯 TP1: {tp1:.2f}\n"
        f"🎯 TP2: {tp2:.2f}\n"
        f"🎯 TP3: {tp3:.2f}\n\n"
        f"📊 RSI: {result['rsi']:.1f}\n"
        f"✅ Tasdiqlar: {result['score']}/6\n"
        f"⌛ Amal qilish muddati: {SIGNAL_EXPIRY} daqiqa\n"
        f"🕒 Sham vaqti: {result['candle_time']}\n\n"
        f"⚠️ Signal kafolat emas. Riskni nazorat qil."
    )


# ===== TELEGRAM =====

def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    response = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": message
        },
        timeout=20
    )

    print("Telegram:", response.status_code, response.text)


# ===== ASOSIY ISH =====

def check_signals():
    results = {}

    for name, interval in TIMEFRAMES.items():
        try:
            candles = get_candles(interval)

            if candles:
                result = analyze(candles)
                results[name] = result

        except Exception as error:
            print(name, "xato:", error)

    # M5 va M15 yo'nalishlarini tekshirish
    for timeframe in ("M1", "M5", "M15"):
        result = results.get(timeframe)

        if not result:
            continue

        direction = result["direction"]

        if timeframe == "M1":
            m5 = results.get("M5")
            m15 = results.get("M15")

            if m5 and m5["direction"] != direction:
                continue

            if m15 and m15["direction"] != direction:
                continue

        signal_key = (
            timeframe,
            direction,
            result["candle_time"]
        )

        now = time.time()

        if signal_key in last_signals:
            continue

        previous_time = last_signal_time.get(timeframe, 0)

        if now - previous_time < 180:
            continue

        message = create_signal(result, timeframe)
        send_telegram(message)

        last_signals[signal_key] = True
        last_signal_time[timeframe] = now

        print("SIGNAL:", timeframe, direction)


def main():
    if not BOT_TOKEN or not CHAT_ID or not API_KEY:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN, CHAT_ID va "
            "TWELVE_DATA_API_KEY kerak!"
        )

    send_telegram("🥇 GOLD AI SIGNAL BOT ISHGA TUSHDI!")

    while True:
        try:
            check_signals()
        except Exception as error:
            print("Asosiy xato:", error)

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
