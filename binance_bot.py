"""
Binance Futures Bot — EMA 9/21 + RSI 14 + ATR Stop Loss
Mercado: BTCUSDT Futures | Apalancamiento: 3x | Temporalidad: 15m
Notificaciones: Telegram Bot

SL/TP: órdenes reales STOP_MARKET + TAKE_PROFIT_MARKET en Binance
(endpoint estándar /fapi/v1/order) + monitoreo software como respaldo.
Compatible con todas las cuentas Binance Futures.

Dependencias:
    pip install python-binance pandas pandas-ta requests
"""

import os
import time
import logging
from logging.handlers import RotatingFileHandler
import pathlib
import requests
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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
    "heartbeat_ciclos": 80,   # cada 80 ciclos × 15s = ~20min
}

# ─── LOGGING ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        RotatingFileHandler("logs/bot.log", maxBytes=5*1024*1024, backupCount=3),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ─── ESTADO INTERNO (SL/TP en memoria) ───────────────────────────────────────

state = {
    "sl_price"   : None,
    "tp_price"   : None,
    "signal"     : None,   # "LONG" o "SHORT"
    "entry_price": None,
    "entry_time" : None,   # datetime de apertura
    "sl_order_id": None,   # orderId de la orden SL en Binance
    "tp_order_id": None,   # orderId de la orden TP en Binance
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
                 rsi: float, atr: float, pos_txt: str,
                 balance_available: float, balance_total: float):
    now = datetime.now().strftime("%d/%m %H:%M")
    tg_send(
        f"📊 <b>Resumen 20min</b>  <i>{now}</i>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💵 Precio: <b>${price:,.2f}</b>\n"
        f"📈 EMA9: <code>{ema_f}</code>  EMA21: <code>{ema_s}</code>\n"
        f"📉 RSI: <code>{rsi}</code>  ATR: <code>{atr}</code>\n"
        f"📂 Posición: {pos_txt}\n"
        f"💰 Disponible: <code>${balance_available:,.2f}</code>\n"
        f"💼 Total: <code>${balance_total:,.2f} USDT</code>"
    )


def tg_error(msg: str):
    tg_send(f"⚠️ <b>Error en el bot</b>\n<code>{msg[:300]}</code>")


# ═══════════════════════════════════════════════════════════════════════════════
#  BINANCE
# ═══════════════════════════════════════════════════════════════════════════════

def get_client() -> Client:
    if CONFIG["testnet"]:
        c = Client(API_KEY, API_SECRET, testnet=True,
                   requests_params={"timeout": 30})
        log.info("Conectado a TESTNET Binance Futures")
    else:
        c = Client(API_KEY, API_SECRET,
                   requests_params={"timeout": 30})
        log.info("Conectado a Binance Futures REAL")

    # Reintentos automáticos para errores de red transitorios
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,            # 1s, 2s, 4s entre reintentos
        status_forcelist=[502, 503, 504],
        allowed_methods=["GET", "POST", "DELETE"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    c.session.mount("https://", adapter)

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


def get_total_balance(client: Client) -> float:
    for a in client.futures_account_balance():
        if a["asset"] == "USDT":
            return float(a["balance"])
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
    state["entry_time"]  = None
    state["sl_order_id"] = None
    state["tp_order_id"] = None


def cancel_open_orders(client: Client):
    # Cancelar órdenes estándar
    try:
        client.futures_cancel_all_open_orders(symbol=CONFIG["symbol"])
        log.info("Órdenes estándar canceladas")
    except BinanceAPIException as e:
        log.warning(f"No se pudieron cancelar órdenes estándar: {e}")

    # Cancelar órdenes condicionales (Algo Order API) si se usó ese endpoint
    if _use_conditional_endpoint:
        try:
            client._request_futures_api(
                'delete', 'conditional/allOpenOrders',
                signed=True, data={"symbol": CONFIG["symbol"]}
            )
            log.info("Órdenes condicionales canceladas")
        except BinanceAPIException as e:
            log.warning(f"No se pudieron cancelar órdenes condicionales: {e}")


_use_conditional_endpoint = False   # se activa si la cuenta requiere Algo Order API


def _create_conditional_order(client: Client, **params) -> dict:
    """
    Llama al endpoint /fapi/v1/conditional/order (Algo Order API)
    para cuentas que no soportan STOP_MARKET/TAKE_PROFIT_MARKET
    en el endpoint estándar /fapi/v1/order (error -4120).
    """
    return client._request_futures_api('post', 'conditional/order',
                                       signed=True, data=params)


def _place_single_order(client: Client, order_type: str,
                        close_side: str, stop_price: float) -> dict:
    """
    Intenta colocar una orden condicional.  Si la cuenta no soporta
    el endpoint estándar (error -4120), usa el endpoint condicional
    y lo recuerda para futuras órdenes.
    """
    global _use_conditional_endpoint

    params = dict(
        symbol        = CONFIG["symbol"],
        side          = close_side,
        type          = order_type,
        stopPrice     = str(stop_price),
        closePosition = "true",
        workingType   = "MARK_PRICE",
    )

    if not _use_conditional_endpoint:
        try:
            return client.futures_create_order(**params)
        except BinanceAPIException as e:
            if e.code == -4120:
                log.warning("Endpoint estándar no soportado → cambiando a conditional/order")
                _use_conditional_endpoint = True
            else:
                raise

    # Endpoint condicional (Algo Order API)
    return _create_conditional_order(client, **params)


def place_sl_tp(client: Client, close_side: str,
                sl_price: float, tp_price: float):
    """
    Coloca órdenes reales de SL y TP en Binance usando STOP_MARKET y
    TAKE_PROFIT_MARKET.

    Intenta primero el endpoint estándar /fapi/v1/order.  Si la cuenta
    devuelve -4120, cambia al endpoint /fapi/v1/conditional/order
    (Algo Order API) automáticamente.

    closePosition=True  → Binance cierra toda la posición al dispararse.
    workingType=MARK_PRICE → trigger por Mark Price (evita wick-outs).
    """
    sl_order = _place_single_order(client, "STOP_MARKET", close_side, sl_price)
    log.info(f"SL colocado en Binance — trigger={sl_price} id={sl_order['orderId']}")

    tp_order = _place_single_order(client, "TAKE_PROFIT_MARKET", close_side, tp_price)
    log.info(f"TP colocado en Binance — trigger={tp_price} id={tp_order['orderId']}")

    return sl_order["orderId"], tp_order["orderId"]


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
        # 1. Orden de entrada a mercado
        client.futures_create_order(
            symbol   = symbol,
            side     = side,
            type     = ORDER_TYPE_MARKET,
            quantity = qty
        )

        # Pausa para que Binance registre la posición
        time.sleep(1)
        pos      = get_open_position(client)
        real_qty = abs(float(pos["positionAmt"])) if pos else qty

        # 2. Órdenes reales SL + TP en Binance
        close_side = SIDE_SELL if signal == "LONG" else SIDE_BUY
        sl_id, tp_id = place_sl_tp(client, close_side, sl_price, tp_price)

        # 3. Guardar estado en memoria (monitoreo software de respaldo)
        state["sl_price"]    = sl_price
        state["tp_price"]    = tp_price
        state["signal"]      = signal
        state["entry_price"] = price
        state["entry_time"]  = datetime.now()
        state["sl_order_id"] = sl_id
        state["tp_order_id"] = tp_id

        balance = get_balance(client)
        log.info(f"Posición {signal} abierta | SL={sl_price} TP={tp_price} | SL_id={sl_id} TP_id={tp_id}")
        tg_orden_abierta(signal, price, real_qty, sl_price, tp_price, balance)

    except BinanceAPIException as e:
        log.error(f"Error abriendo posición: {e}")
        tg_error(f"Error abriendo {signal}: {e}")
        # Si la entrada se ejecutó pero los SL/TP fallaron → cerrar por seguridad
        try:
            pos = get_open_position(client)
            if pos:
                log.warning("Entrada ejecutada pero SL/TP fallaron — cerrando por seguridad")
                tg_error("Entrada sin SL/TP — cerrando por seguridad")
                close_position(client, "fallo en SL/TP")
        except Exception as fallback_err:
            log.error(f"Error en fallback de cierre: {fallback_err}")
            tg_error(f"Error crítico cerrando tras fallo SL/TP: {fallback_err}")


def close_position(client: Client, motivo: str = "señal inversa"):
    pos = get_open_position(client)
    if not pos:
        clear_state()
        return
    amt  = float(pos["positionAmt"])
    pnl  = float(pos.get("unrealizedProfit", 0))
    side = SIDE_SELL if amt > 0 else SIDE_BUY

    try:
        # Cancelar órdenes SL/TP de Binance antes de cerrar con market
        cancel_open_orders(client)
        client.futures_create_order(
            symbol     = CONFIG["symbol"],
            side       = side,
            type       = ORDER_TYPE_MARKET,
            quantity   = abs(amt),
            reduceOnly = "true"
        )
        log.info(f"Posición cerrada | motivo={motivo} | PnL={pnl:+.2f}")
        tg_orden_cerrada(motivo, pnl)
        clear_state()
    except BinanceAPIException as e:
        log.error(f"Error cerrando posición: {e}")
        tg_error(f"Error cerrando posición: {e}")


def binance_orders_alive(client: Client) -> bool:
    """
    Verifica si las órdenes SL y TP siguen activas en Binance.
    Si no están (ejecutadas o canceladas externamente), el software
    de monitoreo toma el control.
    """
    if state["sl_order_id"] is None:
        return False
    try:
        # Recopilar IDs de órdenes abiertas (estándar + condicionales)
        open_orders = client.futures_get_open_orders(symbol=CONFIG["symbol"])
        ids = {o["orderId"] for o in open_orders}

        if _use_conditional_endpoint:
            try:
                cond_orders = client._request_futures_api(
                    'get', 'conditional/openOrders',
                    signed=True, data={"symbol": CONFIG["symbol"]}
                )
                ids.update(o["orderId"] for o in cond_orders)
            except BinanceAPIException:
                pass  # si falla, verificar con lo que tenemos

        sl_alive = state["sl_order_id"] in ids
        tp_alive = state["tp_order_id"] in ids
        if not sl_alive or not tp_alive:
            log.warning(f"Órden(es) Binance ya no activas: SL={sl_alive} TP={tp_alive} — modo software activado")
            return False
        return True
    except BinanceAPIException as e:
        log.warning(f"No se pudo verificar órdenes abiertas: {e}")
        return True  # asumir vivas ante duda


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

    ciclo_heartbeat = 0
    # Separar contador de señales del de precio (precio cada 15s, señal cada 60s)
    ciclos_senal = 0
    CICLOS_POR_SENAL = max(1, 60 // CONFIG["loop_seconds"])  # cada 60s revisar señal
    errores_consecutivos = 0
    MAX_ERRORES_RECONEXION = 5

    # Inicializar variables para que heartbeat no falle en primeros ciclos
    price = ema_f = ema_s = rsi = atr_val = 0
    indicadores_listos = False

    while True:
        try:
            # ── Precio actual (cada ciclo, para SL/TP) ──────────────────────
            current_price = get_current_price(client)

            # ── Leer posición una sola vez por ciclo ────────────────────────
            pos = get_open_position(client)

            # Reset contador de errores tras ciclo exitoso
            errores_consecutivos = 0

            # ── Verificar SL/TP si hay posición ─────────────────────────────
            if pos and state["sl_price"] is not None:
                # Si las órdenes Binance ya no están (ejecutadas por el exchange
                # o canceladas externamente), el monitoreo software toma el control
                if not binance_orders_alive(client):
                    check_sl_tp(client, current_price)
                # Re-leer pos: alguna de las dos vías puede haber cerrado
                pos = get_open_position(client)
                # Si Binance ejecutó el SL/TP por su cuenta, limpiar estado
                if not pos:
                    log.info("Posición cerrada por Binance (SL/TP ejecutado)")
                    clear_state()
            elif pos and state["sl_price"] is None:
                # Posición abierta pero sin estado (ej: reinicio) → cerrar
                log.warning("Posición sin SL/TP en memoria — cerrando por seguridad")
                close_position(client, "sin SL/TP en memoria")
                pos = None

            # ── Revisar señal cada CICLOS_POR_SENAL ciclos ──────────────────
            ciclos_senal += 1
            if ciclos_senal >= CICLOS_POR_SENAL:
                ciclos_senal = 0
                df      = get_klines(client)
                price   = float(df.iloc[-1]["close"])
                atr_val = float(df.iloc[-1]["atr"])
                ema_f   = round(float(df.iloc[-1]["ema_fast"]), 2)
                ema_s   = round(float(df.iloc[-1]["ema_slow"]), 2)
                rsi     = round(float(df.iloc[-1]["rsi"]), 1)
                signal  = check_signal(df)
                indicadores_listos = True

                log.info(f"BTC=${price:.2f} | EMA9={ema_f} EMA21={ema_s} | RSI={rsi} | ATR={atr_val:.2f} | {signal}")

                if signal != "NONE" and pos is None:
                    open_position(client, signal, price, atr_val)
                    pos = get_open_position(client)  # actualizar tras apertura

                elif signal != "NONE" and pos is not None:
                    amt = float(pos["positionAmt"])
                    if (signal == "LONG" and amt < 0) or (signal == "SHORT" and amt > 0):
                        log.info("Señal inversa → cerrando y reabriendo")
                        close_position(client, "señal inversa")
                        time.sleep(2)
                        # Usar precio fresco para la nueva entrada
                        fresh_price = get_current_price(client)
                        open_position(client, signal, fresh_price, atr_val)
                        pos = get_open_position(client)

            # ── Heartbeat cada N ciclos reales (80 × 15s = 20min) ────────
            ciclo_heartbeat += 1
            if ciclo_heartbeat >= CONFIG["heartbeat_ciclos"] and indicadores_listos:
                bal_available = get_balance(client)
                bal_total     = get_total_balance(client)
                if pos:
                    amt       = float(pos["positionAmt"])
                    pnl       = float(pos.get("unrealizedProfit", 0))
                    direccion = "LONG 🟢" if amt > 0 else "SHORT 🔴"
                    sl_txt    = f"SL: ${state['sl_price']:,.0f}" if state["sl_price"] else "—"
                    tp_txt    = f"TP: ${state['tp_price']:,.0f}" if state["tp_price"] else "—"
                    # Duración de la posición
                    dur_txt   = ""
                    if state["entry_time"]:
                        delta   = datetime.now() - state["entry_time"]
                        horas   = int(delta.total_seconds() // 3600)
                        minutos = int((delta.total_seconds() % 3600) // 60)
                        dur_txt = f"\n⏱ Duración: {horas}h {minutos}m"
                    pos_txt   = f"{direccion} | PnL: <code>${pnl:+.2f}</code>\n{sl_txt} · {tp_txt}{dur_txt}"
                else:
                    pos_txt = "Sin posición abierta"
                tg_heartbeat(price, ema_f, ema_s, rsi,
                             round(atr_val, 2), pos_txt,
                             bal_available, bal_total)
                ciclo_heartbeat = 0

        except BinanceAPIException as e:
            log.error(f"Binance API error: {e}")
            tg_error(str(e))
            errores_consecutivos += 1
        except Exception as e:
            log.error(f"Error inesperado: {e}")
            tg_error(str(e))
            errores_consecutivos += 1

        # Reconectar si hay muchos errores seguidos
        if errores_consecutivos >= MAX_ERRORES_RECONEXION:
            log.warning(f"{errores_consecutivos} errores consecutivos — reconectando cliente Binance")
            tg_error(f"Reconectando tras {errores_consecutivos} errores consecutivos")
            try:
                client = get_client()
                errores_consecutivos = 0
            except Exception as reconn_err:
                log.error(f"Error reconectando: {reconn_err}")

        time.sleep(CONFIG["loop_seconds"])


if __name__ == "__main__":
    run()