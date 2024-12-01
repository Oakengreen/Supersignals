import logging
import MetaTrader5 as mt5
import math

logger = logging.getLogger("Channel4")

SYMBOL_MAP = {
    "US30": "DJ30",  # Mappa US30 till DJ30
}

last_trend = {}


def calculate_atr(symbol, period=14):
    """Beräkna ATR (Average True Range) för en given symbol."""
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, period + 1)
    if rates is None or len(rates) < period + 1:
        raise ValueError(f"Not enough data to calculate ATR for {symbol}.")

    tr_values = []
    for i in range(1, len(rates)):
        high = rates[i][2]  # Justera index för 'high'
        low = rates[i][3]  # Justera index för 'low'
        prev_close = rates[i - 1][4]  # Justera index för 'close'
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_values.append(tr)

    atr = sum(tr_values) / period
    return atr


def calculate_pip_value(symbol_info):
    """Beräkna pipvärdet per kontrakt baserat på symbolinfo."""
    if symbol_info.trade_tick_size > 0:
        pip_value = symbol_info.trade_tick_value / symbol_info.trade_tick_size
        logger.info(f"Pip Value calculated: {pip_value}")
        return pip_value
    else:
        raise ValueError(f"Invalid tick size for {symbol_info.name}. Cannot calculate pip value.")


def map_symbol(symbol):
    """Mappa symbol till broker-specifik symbol om det behövs."""
    return SYMBOL_MAP.get(symbol, symbol)


def position_size(balance, symbol, sl_distance_usd):
    """Beräkna en fast lotstorlek för att säkerställa korrekt riskhantering."""
    leverage = mt5.account_info().leverage
    price = (mt5.symbol_info(symbol).ask + mt5.symbol_info(symbol).bid) / 2
    trade_size = mt5.symbol_info(symbol).trade_contract_size
    lot_size = (balance * leverage) / (sl_distance_usd * price * trade_size)

    # Anpassa till symbolens gränser
    min_lot = mt5.symbol_info(symbol).volume_min
    max_lot = mt5.symbol_info(symbol).volume_max
    lot_size = max(min(round(lot_size, 2), max_lot), min_lot)

    logger.info(f"Lot Size calculated: {lot_size}")
    return lot_size


async def process_channel_4_signal(message, mt5_path):
    """Processa inkommande signaler från Kanal 4."""
    try:
        logger.info("Initializing MetaTrader 5...")
        if not mt5.initialize(mt5_path):
            raise RuntimeError(f"Failed to initialize MT5 at path {mt5_path}")

        logger.info(f"Processing message: {message}")
        lines = [line.strip() for line in message.strip().split("\n") if line.strip()]
        logger.info(f"Processed lines: {lines}")

        action_line = lines[0].strip().upper()
        if "BUY" in action_line:
            action = mt5.ORDER_TYPE_BUY
        elif "SELL" in action_line:
            action = mt5.ORDER_TYPE_SELL
        else:
            raise ValueError("Invalid action in message. Expected 'BUY' or 'SELL'.")
        logger.info(f"Action parsed: {'BUY' if action == mt5.ORDER_TYPE_BUY else 'SELL'}")

        symbol = map_symbol(action_line.split()[1].upper().rstrip(":"))
        logger.info(f"Symbol parsed: {symbol}")
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info or not symbol_info.visible:
            raise ValueError(f"Symbol {symbol} is not available or not visible in MetaTrader 5.")
        logger.info(f"Symbol info: {symbol_info}")

        logger.info("Fetching account balance...")
        balance = mt5.account_info().balance
        risk_amount = round(balance * 0.01, 4)  # 1% av balans
        logger.info(f"Account Balance: {balance}, Risk Amount (1%): {risk_amount}")

        logger.info("Calculating ATR...")
        atr = calculate_atr(symbol)
        sl_distance = round(atr * 2, 4)  # ATR x 2
        logger.info(f"ATR: {atr}, SL Distance (ATR x 2): {sl_distance}")

        pip_value = calculate_pip_value(symbol_info)
        sl_distance_usd = round(sl_distance * pip_value, 4)
        logger.info(f"SL Distance USD: {sl_distance_usd}")

        # Simulera med 1 lot
        simulated_fixed_lot_size = 1.0
        simulated_risk = round(simulated_fixed_lot_size * sl_distance_usd, 4)
        logger.info(f"Simulated Fixed Lot Size: {simulated_fixed_lot_size}, Simulated Risk: {simulated_risk}, Expected Risk: {risk_amount}")

        # Dynamisk lotstorlek baserat på risk
        calculated_lot_size = round(risk_amount / sl_distance_usd, 2)
        logger.info(f"Dynamically Calculated Lot Size: {calculated_lot_size}")

        # Kontrollera marginal och justera lotstorlek
        adjusted_lot_size = calculated_lot_size
        while adjusted_lot_size >= 0.01:  # Minsta lotstorlek
            required_margin = mt5.order_calc_margin(action, symbol, adjusted_lot_size, mt5.symbol_info_tick(symbol).ask)
            free_margin = mt5.account_info().margin_free
            if required_margin is not None and free_margin >= required_margin:
                break  # Om marginalen räcker, använd denna storlek
            adjusted_lot_size = round(adjusted_lot_size - 0.01, 2)  # Minska lotstorleken
        if adjusted_lot_size < 0.01:
            raise ValueError(f"Insufficient margin for any lot size. Free={free_margin}, Required={required_margin}")
        logger.info(f"Adjusted Lot Size: {adjusted_lot_size}")

        logger.info("Preparing order...")
        current_price = mt5.symbol_info_tick(symbol).ask if action == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(
            symbol).bid
        sl = current_price - sl_distance if action == mt5.ORDER_TYPE_BUY else current_price + sl_distance
        tp = current_price + sl_distance * 1.5 if action == mt5.ORDER_TYPE_BUY else current_price - sl_distance * 1.5
        order = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": adjusted_lot_size,
            "type": action,
            "price": current_price,
            "sl": round(sl, 4),
            "tp": round(tp, 4),
            "deviation": 500,
            "magic": 0,
            "comment": "Channel4_Signal",
            "type_filling": mt5.ORDER_FILLING_FOK,
        }
        logger.info(f"Order prepared: {order}")

        logger.info("Sending order...")
        result = mt5.order_send(order)
        logger.info(f"Order result: {result}")
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"Order placed successfully for {symbol}: {result}")
        else:
            raise ValueError(f"Order failed: Retcode={result.retcode}, Description={mt5.last_error()}")

    except Exception as e:
        logger.error(f"Error processing signal from Channel 4: {e}")




