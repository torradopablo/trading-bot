"""
Binance Futures Bot — EMA 9/21 + RSI 14 + ATR Stop Loss
Mercado: BTCUSDT Futures | Apalancamiento: 3x | Temporalidad: 15m
Notificaciones: Telegram Bot

Dependencias:
    pip install python-binance pandas pandas-ta requests

Cómo crear el bot de Telegram:
    1. Abrí Telegram y buscá @BotFather
    2. Enviá /newbot → seguí los pasos → copiá el TOKEN
    3. Buscá @userinfobot o @RawDataBot → te da tu CHAT_ID
    4. Pegá ambos en el .env (ver .env.example)
"""

import os
import time
import logging
import pathlib
import requests
from datetime import datetime

import pandas as pd
import pandas_ta as ta
from binance.client import Client
from binance.enums import *
from binance.exceptions import BinanceAPIException

pathlib.Path("logs").mkdir(exist_ok=True)

# ─── CREDENCIALES ────────────────────────────────────────────────────────────

API_KEY       = os.getenv("BINANCE_API_KEY",    "TU_API_KEY_AQUI")
API_SECRET    = os.getenv("BINANCE_API_SECRET", "TU_API_SECRET_AQUI")
TG_TOKEN      = os.getenv("TELEGRAM_BOT_TOKEN", "")   # 7123456789:AAFxxx...
TG_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID",   "")   # 123456789

# ─── PARÁMETROS ──────────────────────────────────────────────────────────────

CONFIG = {
    "symbol"         : "BTCUSDT",
    "interval"       : Client.KLINE_INTERVAL_15MINUTE,
    "leverage"       : 3,
    "ema_fast"       : 9,
    "ema_slow"       : 21,
    "rsi_period"     : 14,
    "rsi_overbought" : 70,
    "rsi_oversold"   : 30,
    "atr_period"     : 14,
    "sl_atr_mult"    : 1.5,
    "tp_atr_mult"    : 3.0,
    "risk_pct"       : 0.02,
    "testnet"        : True,
    "loop_seconds"   : 60,
    "heartbeat_ciclos": 60,   # cada 60 ciclos (~1h) manda resumen
}

# ─── LOGGING ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
#  TELEGRAM
# ═══════════════════════════════════════════════════════════════════════════════

def tg_send(text: str):
    """Envía mensaje de Telegram. Silencioso si no hay token configurado."""
    if not TG_TOKEN or not TG_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        resp = requests.post(url, json={
            "chat_id"   : TG_CHAT_ID,
            "text"      : text,
            "parse_mode": "HTML"
        }, timeout=10)
        if not resp.ok:
            log.warning(f"Telegram HTTP {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        log.warning(f"Telegram error: {e}")


def tg_bot_iniciado():
    modo = "🧪 <b>TESTNET</b>" if CONFIG["testnet"] else "🔴 <b>DINERO REAL</b>"
    tg_send(
        f"🤖 <b>Bot Binance iniciado</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📌 Par: <code>{CONFIG['symbol']}</code>\n"
        f"⚡ Apalancamiento: <b>{CONFIG['leverage']}x</b>\n"
        f"⏱ Temporalidad: <b>15m</b>\n"
        f"📐 Estrategia: EMA 9/21 · RSI 14 · ATR SL\n"
        f"🌐 Modo: {modo}"
    )


def tg_orden_abierta(signal: str, price: float, qty: float,
                     sl: float, tp: float, balance: float):
    if signal == "LONG":
        emoji     = "🟢"
        direccion = "LONG  ▲"
        riesgo_pct = round(abs(price - sl) / price * 100 * CONFIG["leverage"], 2)
    else:
        emoji     = "🔴"
        direccion = "SHORT ▼"
        riesgo_pct = round(abs(sl - price) / price * 100 * CONFIG["leverage"], 2)

    tp_pct = round(abs(tp - price) / price * 100 * CONFIG["leverage"], 2)
    now    = datetime.now().strftime("%H:%M:%S")

    tg_send(
        f"{emoji} <b>ORDEN ABIERTA — {direccion}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🕐 Hora: <code>{now}</code>\n"
        f"📌 Par: <code>{CONFIG['symbol']}</code>\n"
        f"💵 Entrada: <b>${price:,.2f}</b>\n"
        f"📦 Cantidad: <code>{qty} BTC</code>\n"
        f"🛑 Stop Loss: <code>${sl:,.2f}</code>  (-{riesgo_pct}%)\n"
        f"🎯 Take Profit: <code>${tp:,.2f}</code>  (+{tp_pct}%)\n"
        f"💰 Balance: <code>${balance:,.2f} USDT</code>"
    )


def tg_orden_cerrada(motivo: str, pnl: float | None = None):
    emoji_pnl = ""
    pnl_txt   = ""
    if pnl is not None:
        emoji_pnl = "🟢" if pnl >= 0 else "🔴"
        pnl_txt   = f"\n{emoji_pnl} PnL no realizado: <code>${pnl:+.2f} USDT</code>"
    now = datetime.now().strftime("%H:%M:%S")
    tg_send(
        f"⚪ <b>POSICIÓN CERRADA</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🕐 Hora: <code>{now}</code>\n"
        f"📌 Par: <code>{CONFIG['symbol']}</code>\n"
        f"📋 Motivo: {motivo}"
        f"{pnl_txt}"
    )


def tg_heartbeat(price: float, ema_f: float, ema_s: float,
                 rsi: float, pos_txt: str, balance: float):
    now = datetime.now().strftime("%d/%m %H:%M")
    tg_send(
        f"📊 <b>Resumen horario</b>  <i>{now}</i>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💵 Precio: <b>${price:,.2f}</b>\n"
        f"📈 EMA9: <code>{ema_f}</code>  EMA21: <code>{ema_s}</code>\n"
        f"📉 RSI: <code>{rsi}</code>\n"
        f"📂 Posición: {pos_txt}\n"
        f"💰 Balance: <code>${balance:,.2f} USDT</code>"
    )


def tg_error(msg: str):
    tg_send(f"⚠️ <b>Error en el bot</b>\n<code>{msg[:300]}</code>")


# ═══════════════════════════════════════════════════════════════════════════════
#  BINANCE
# ═══════════════════════════════════════════════════════════════════════════════

def get_client() -> Client:
    if CONFIG["testnet"]:
        c = Client(API_KEY, API_SECRET, testnet=True)
        log.info("Conectado a TESTNET Binance Futures")
    else:
        c = Client(API_KEY, API_SECRET)
        log.info("Conectado a Binance Futures REAL")
    return c


def get_klines(client: Client) -> pd.DataFrame:
    raw = client.futures_klines(
        symbol=CONFIG["symbol"],
        interval=CONFIG["interval"],
        limit=100
    )
    df = pd.DataFrame(raw, columns=[
        "open_time","open","high","low","close","volume",
        "close_time","qav","trades","tbbav","tbqav","ignore"
    ])
    for col in ["close","high","low"]:
        df[col] = df[col].astype(float)

    df["ema_fast"] = ta.ema(df["close"], length=CONFIG["ema_fast"])
    df["ema_slow"] = ta.ema(df["close"], length=CONFIG["ema_slow"])
    df["rsi"]      = ta.rsi(df["close"], length=CONFIG["rsi_period"])
    df["atr"]      = ta.atr(df["high"], df["low"], df["close"], length=CONFIG["atr_period"])
    return df.dropna()


def check_signal(df: pd.DataFrame) -> str:
    prev, curr = df.iloc[-2], df.iloc[-1]
    cross_up   = prev["ema_fast"] <= prev["ema_slow"] and curr["ema_fast"] > curr["ema_slow"]
    cross_down = prev["ema_fast"] >= prev["ema_slow"] and curr["ema_fast"] < curr["ema_slow"]
    if cross_up   and curr["rsi"] < CONFIG["rsi_overbought"]: return "LONG"
    if cross_down and curr["rsi"] > CONFIG["rsi_oversold"]:   return "SHORT"
    return "NONE"


def get_balance(client: Client) -> float:
    for a in client.futures_account_balance():
        if a["asset"] == "USDT":
            return float(a["availableBalance"])
    return 0.0


def get_open_position(client: Client) -> dict | None:
    for p in client.futures_position_information(symbol=CONFIG["symbol"]):
        if float(p["positionAmt"]) != 0:
            return p
    return None


def calc_qty(client: Client, atr: float) -> float:
    balance   = get_balance(client)
    risk_usdt = balance * CONFIG["risk_pct"]
    stop_dist = atr * CONFIG["sl_atr_mult"]
    return round((risk_usdt * CONFIG["leverage"]) / stop_dist, 3)


def set_leverage(client: Client):
    try:
        client.futures_change_leverage(
            symbol=CONFIG["symbol"], leverage=CONFIG["leverage"]
        )
    except BinanceAPIException:
        pass


def open_position(client: Client, signal: str, price: float, atr: float):
    symbol  = CONFIG["symbol"]
    qty     = calc_qty(client, atr)
    sl_dist = atr * CONFIG["sl_atr_mult"]
    tp_dist = atr * CONFIG["tp_atr_mult"]

    if signal == "LONG":
        side, close_side = SIDE_BUY,  SIDE_SELL
        sl_price = round(price - sl_dist, 2)
        tp_price = round(price + tp_dist, 2)
    else:
        side, close_side = SIDE_SELL, SIDE_BUY
        sl_price = round(price + sl_dist, 2)
        tp_price = round(price - tp_dist, 2)

    log.info(f"Abriendo {signal} qty={qty} entry={price:.2f} SL={sl_price:.2f} TP={tp_price:.2f}")

    try:
        client.futures_create_order(
            symbol=symbol, side=side, type=ORDER_TYPE_MARKET, quantity=qty
        )
        client.futures_create_order(
            symbol=symbol, side=close_side,
            type=FUTURE_ORDER_TYPE_STOP_MARKET,
            stopPrice=str(sl_price), closePosition=True
        )
        client.futures_create_order(
            symbol=symbol, side=close_side,
            type=FUTURE_ORDER_TYPE_TAKE_PROFIT_MARKET,
            stopPrice=str(tp_price), closePosition=True
        )
        balance = get_balance(client)
        log.info(f"Posición {signal} abierta OK")
        tg_orden_abierta(signal, price, qty, sl_price, tp_price, balance)

    except BinanceAPIException as e:
        log.error(f"Error abriendo posición: {e}")
        tg_error(f"Error abriendo {signal}: {e}")


def close_position(client: Client, motivo: str = "señal inversa"):
    pos = get_open_position(client)
    if not pos:
        return
    amt  = float(pos["positionAmt"])
    pnl  = float(pos.get("unrealizedProfit", 0))
    side = SIDE_SELL if amt > 0 else SIDE_BUY
    try:
        client.futures_create_order(
            symbol=CONFIG["symbol"], side=side,
            type=ORDER_TYPE_MARKET,
            quantity=abs(amt), reduceOnly=True
        )
        log.info(f"Posición cerrada | motivo={motivo} | PnL={pnl:+.2f}")
        tg_orden_cerrada(motivo, pnl)
    except BinanceAPIException as e:
        log.error(f"Error cerrando posición: {e}")
        tg_error(f"Error cerrando posición: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
#  LOOP PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

def run():
    client = get_client()
    set_leverage(client)

    log.info("=" * 50)
    log.info(f"BOT INICIADO | {CONFIG['symbol']} | {CONFIG['leverage']}x | testnet={CONFIG['testnet']}")
    log.info("=" * 50)

    tg_bot_iniciado()

    ciclo = 0
    while True:
        try:
            df     = get_klines(client)
            price  = float(df.iloc[-1]["close"])
            atr    = float(df.iloc[-1]["atr"])
            ema_f  = round(float(df.iloc[-1]["ema_fast"]), 2)
            ema_s  = round(float(df.iloc[-1]["ema_slow"]), 2)
            rsi    = round(float(df.iloc[-1]["rsi"]), 1)
            signal = check_signal(df)

            log.info(f"BTC=${price:.2f} | EMA9={ema_f} EMA21={ema_s} | RSI={rsi} | ATR={atr:.2f} | {signal}")

            pos = get_open_position(client)

            if signal != "NONE" and pos is None:
                open_position(client, signal, price, atr)

            elif signal != "NONE" and pos is not None:
                amt = float(pos["positionAmt"])
                if (signal == "LONG" and amt < 0) or (signal == "SHORT" and amt > 0):
                    log.info("Señal inversa → cerrando y reabriendo")
                    close_position(client, "señal inversa")
                    time.sleep(2)
                    open_position(client, signal, price, atr)

            # Heartbeat horario
            ciclo += 1
            if ciclo >= CONFIG["heartbeat_ciclos"]:
                balance = get_balance(client)
                if pos:
                    amt       = float(pos["positionAmt"])
                    pnl       = float(pos.get("unrealizedProfit", 0))
                    direccion = "LONG 🟢" if amt > 0 else "SHORT 🔴"
                    pos_txt   = f"{direccion} | PnL: <code>${pnl:+.2f}</code>"
                else:
                    pos_txt = "Sin posición abierta"
                tg_heartbeat(price, ema_f, ema_s, rsi, pos_txt, balance)
                ciclo = 0

        except BinanceAPIException as e:
            log.error(f"Binance API error: {e}")
            tg_error(str(e))
        except Exception as e:
            log.error(f"Error inesperado: {e}")
            tg_error(str(e))

        time.sleep(CONFIG["loop_seconds"])


if __name__ == "__main__":
    run()
