"""
Binance Futures Bot — EMA 9/21 + RSI 14 + ATR Stop Loss
Mercado: BTCUSDT Futures | Apalancamiento: 3x | Temporalidad: 15m
Notificaciones: Telegram Bot

SL y TP manejados por el bot (sin órdenes condicionales de Binance).
Compatible con todas las cuentas Binance Futures.

Dependencias:
    pip install python-binance pandas pandas-ta requests
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

API_KEY    = os.getenv("BINANCE_API_KEY",    "TU_API_KEY_AQUI")
API_SECRET = os.getenv("BINANCE_API_SECRET", "TU_API_SECRET_AQUI")
TG_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID",   "")

# ─── PARÁMETROS ──────────────────────────────────────────────────────────────

CONFIG = {
    "symbol"          : "BTCUSDT",
    "interval"        : Client.KLINE_INTERVAL_15MINUTE,
    "leverage"        : 3,
    "ema_fast"        : 9,
    "ema_slow"        : 21,
    "rsi_period"      : 14,
    "rsi_overbought"  : 70,
    "rsi_oversold"    : 30,
    "atr_period"      : 14,
    "sl_atr_mult"     : 1.5,
    "tp_atr_mult"     : 3.0,
    "risk_pct"        : 0.02,
    "testnet"         : False,
    "loop_seconds"    : 15,   # más frecuente para monitorear SL/TP
    "heartbeat_ciclos": 240,  # cada 240 ciclos × 15s = ~1h
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

# ─── ESTADO INTERNO (SL/TP en memoria) ───────────────────────────────────────

state = {
    "sl_price"  : None,
    "tp_price"  : None,
    "signal"    : None,   # "LONG" o "SHORT"
    "entry_price": None,
}


# ═══════════════════════════════════════════════════════════════════════════════
#  TELEGRAM
# ═══════════════════════════════════════════════════════════════════════════════

def tg_send(text: str):
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
    emoji      = "🟢" if signal == "LONG" else "🔴"
    direccion  = "LONG  ▲" if signal == "LONG" else "SHORT ▼"
    riesgo_pct = round(abs(price - sl) / price * 100 * CONFIG["leverage"], 2)
    tp_pct     = round(abs(tp - price) / price * 100 * CONFIG["leverage"], 2)
    now        = datetime.now().strftime("%H:%M:%S")
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
    pnl_txt = ""
    if pnl is not None:
        emoji_pnl = "🟢" if pnl >= 0 else "🔴"
        pnl_txt   = f"\n{emoji_pnl} PnL: <code>${pnl:+.2f} USDT</code>"
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
    for col in ["close", "high", "low"]:
        df[col] = df[col].astype(float)
    df["ema_fast"] = ta.ema(df["close"], length=CONFIG["ema_fast"])
    df["ema_slow"] = ta.ema(df["close"], length=CONFIG["ema_slow"])
    df["rsi"]      = ta.rsi(df["close"], length=CONFIG["rsi_period"])
    df["atr"]      = ta.atr(df["high"], df["low"], df["close"], length=CONFIG["atr_period"])
    return df.dropna()


def get_current_price(client: Client) -> float:
    ticker = client.futures_symbol_ticker(symbol=CONFIG["symbol"])
    return float(ticker["price"])


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


def calc_qty(client: Client, atr: float, price: float) -> float:
    balance   = get_balance(client)
    risk_usdt = balance * CONFIG["risk_pct"]
    stop_dist = atr * CONFIG["sl_atr_mult"]
    qty_risk  = risk_usdt / stop_dist
    qty_max   = (balance * CONFIG["leverage"] * 0.95) / price
    return round(min(qty_risk, qty_max), 3)


def set_leverage(client: Client):
    try:
        client.futures_change_leverage(
            symbol=CONFIG["symbol"], leverage=CONFIG["leverage"]
        )
        log.info(f"Leverage {CONFIG['leverage']}x configurado")
    except BinanceAPIException:
        pass


def clear_state():
    state["sl_price"]    = None
    state["tp_price"]    = None
    state["signal"]      = None
    state["entry_price"] = None


def open_position(client: Client, signal: str, price: float, atr: float):
    symbol = CONFIG["symbol"]
    qty    = calc_qty(client, atr, price)

    if qty <= 0:
        msg = f"Cantidad inválida (qty={qty}), posición no abierta"
        log.warning(msg)
        tg_error(msg)
        return

    sl_dist = atr * CONFIG["sl_atr_mult"]
    tp_dist = atr * CONFIG["tp_atr_mult"]

    if signal == "LONG":
        side     = SIDE_BUY
        sl_price = round(price - sl_dist, 2)
        tp_price = round(price + tp_dist, 2)
    else:
        side     = SIDE_SELL
        sl_price = round(price + sl_dist, 2)
        tp_price = round(price - tp_dist, 2)

    log.info(f"Abriendo {signal} qty={qty} entry={price:.2f} SL={sl_price:.2f} TP={tp_price:.2f}")

    try:
        # Única orden necesaria: entrada a mercado
        client.futures_create_order(
            symbol   = symbol,
            side     = side,
            type     = ORDER_TYPE_MARKET,
            quantity = qty
        )

        time.sleep(1)
        pos      = get_open_position(client)
        real_qty = abs(float(pos["positionAmt"])) if pos else qty

        # Guardar SL/TP en estado interno — el bot los monitorea cada ciclo
        state["sl_price"]    = sl_price
        state["tp_price"]    = tp_price
        state["signal"]      = signal
        state["entry_price"] = price

        balance = get_balance(client)
        log.info(f"Posición {signal} abierta | SL={sl_price} TP={tp_price} (monitoreados por el bot)")
        tg_orden_abierta(signal, price, real_qty, sl_price, tp_price, balance)

    except BinanceAPIException as e:
        log.error(f"Error abriendo posición: {e}")
        tg_error(f"Error abriendo {signal}: {e}")


def close_position(client: Client, motivo: str = "señal inversa"):
    pos = get_open_position(client)
    if not pos:
        clear_state()
        return
    amt  = float(pos["positionAmt"])
    pnl  = float(pos.get("unrealizedProfit", 0))
    side = SIDE_SELL if amt > 0 else SIDE_BUY

    try:
        client.futures_create_order(
            symbol     = CONFIG["symbol"],
            side       = side,
            type       = ORDER_TYPE_MARKET,
            quantity   = abs(amt),
            reduceOnly = True
        )
        log.info(f"Posición cerrada | motivo={motivo} | PnL={pnl:+.2f}")
        tg_orden_cerrada(motivo, pnl)
        clear_state()
    except BinanceAPIException as e:
        log.error(f"Error cerrando posición: {e}")
        tg_error(f"Error cerrando posición: {e}")


def check_sl_tp(client: Client, current_price: float):
    """
    Monitorea SL y TP en cada ciclo.
    Si el precio toca alguno, cierra la posición con orden de mercado.
    """
    if state["sl_price"] is None or state["tp_price"] is None:
        return

    signal   = state["signal"]
    sl_price = state["sl_price"]
    tp_price = state["tp_price"]

    if signal == "LONG":
        if current_price <= sl_price:
            log.info(f"SL tocado | precio={current_price} SL={sl_price}")
            close_position(client, f"🛑 Stop Loss (${current_price:,.2f})")
        elif current_price >= tp_price:
            log.info(f"TP tocado | precio={current_price} TP={tp_price}")
            close_position(client, f"🎯 Take Profit (${current_price:,.2f})")

    elif signal == "SHORT":
        if current_price >= sl_price:
            log.info(f"SL tocado | precio={current_price} SL={sl_price}")
            close_position(client, f"🛑 Stop Loss (${current_price:,.2f})")
        elif current_price <= tp_price:
            log.info(f"TP tocado | precio={current_price} TP={tp_price}")
            close_position(client, f"🎯 Take Profit (${current_price:,.2f})")


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

    # Si el bot se reinicia con una posición abierta, recuperar estado de Binance
    pos = get_open_position(client)
    if pos:
        log.warning("Posición abierta detectada al iniciar — no hay SL/TP en memoria.")
        log.warning("Cerrando posición previa para empezar limpio.")
        close_position(client, "reinicio del bot")

    ciclo = 0
    # Separar contador de señales del de precio (precio cada 15s, señal cada 60s)
    ciclos_senal = 0
    CICLOS_POR_SENAL = max(1, 60 // CONFIG["loop_seconds"])  # cada 60s revisar señal

    while True:
        try:
            # ── Precio actual (cada ciclo, para SL/TP) ──────────────────────
            current_price = get_current_price(client)

            # ── Verificar SL/TP si hay posición ─────────────────────────────
            pos = get_open_position(client)
            if pos and state["sl_price"] is not None:
                check_sl_tp(client, current_price)
            elif pos and state["sl_price"] is None:
                # Posición abierta pero sin estado (ej: reinicio) → cerrar
                log.warning("Posición sin SL/TP en memoria — cerrando por seguridad")
                close_position(client, "sin SL/TP en memoria")

            # ── Revisar señal cada CICLOS_POR_SENAL ciclos ──────────────────
            ciclos_senal += 1
            if ciclos_senal >= CICLOS_POR_SENAL:
                ciclos_senal = 0
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
                        sl_txt    = f"SL: ${state['sl_price']:,.0f}" if state['sl_price'] else "—"
                        tp_txt    = f"TP: ${state['tp_price']:,.0f}" if state['tp_price'] else "—"
                        pos_txt   = f"{direccion} | PnL: <code>${pnl:+.2f}</code>\n{sl_txt} · {tp_txt}"
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