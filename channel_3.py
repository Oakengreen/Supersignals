import logging
import MetaTrader5 as mt5
import math

logger = logging.getLogger("Channel3")

SYMBOL_MAP = {
    "US30": "DJ30",  # Mappa US30 till DJ30
}

def map_symbol(symbol):
    """Mappa symbol till broker-specifik symbol om det behövs."""
    return SYMBOL_MAP.get(symbol, symbol)  # Returnera mappad symbol eller originalet


def calculate_atr(symbol, period=14):
    """
    Beräkna ATR (Average True Range) i pips för en given symbol och period.
    """
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, period + 1)
    if rates is None or len(rates) < period + 1:
        raise ValueError(f"Not enough data to calculate ATR for {symbol}. Ensure sufficient historical data.")

    symbol_info = mt5.symbol_info(symbol)
    if not symbol_info:
        raise ValueError(f"Failed to retrieve symbol info for {symbol}.")

    point = symbol_info.point

    true_ranges = []
    for i in range(1, len(rates)):
        high = rates[i]["high"]
        low = rates[i]["low"]
        prev_close = rates[i - 1]["close"]

        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)

    atr = sum(true_ranges[-period:]) / period
    return atr / point  # Konvertera till pips



def calculate_lot_size(balance, risk_percentage, atr, symbol, sl_distance):
    """
    Beräkna lotstorlek baserat på riskprocent, ATR och SL-avstånd.
    :param balance: Konto-balansen.
    :param risk_percentage: Risk i procent av balans (t.ex., 24 för 24%).
    :param atr: ATR-värdet för symbolen.
    :param symbol: Symbolen (t.ex. BTCUSD).
    :param sl_distance: Stop loss-avstånd i samma enhet som ATR.
    :return: Beräknad lotstorlek (avrundad till närmaste 0.01).
    """
    # Risk i dollar
    risk_amount = balance * (risk_percentage / 100)

    # Hämta symbolspecifikationer
    symbol_info = mt5.symbol_info(symbol)
    if not symbol_info:
        raise ValueError(f"Failed to retrieve symbol info for {symbol}.")

    # Pipvärde per kontrakt
    point = symbol_info.point  # Punktstorlek
    contract_size = symbol_info.trade_contract_size  # Kontraktsstorlek (t.ex., 1 för forex, 100 för aktier)
    pip_value_per_contract = (contract_size * point)

    # Kontrollera att pipvärdet är giltigt
    if pip_value_per_contract <= 0:
        raise ValueError(f"Invalid pip value for {symbol}: {pip_value_per_contract}")

    # Lotstorlek baserat på risk och SL-avstånd
    lot_size = risk_amount / (pip_value_per_contract * sl_distance)

    # Avrunda lotstorlek till närmaste tillåtna nivå
    min_lot = symbol_info.volume_min
    step_lot = symbol_info.volume_step
    rounded_lot_size = max(min_lot, round(lot_size / step_lot) * step_lot)

    # Logga mellanresultat för felsökning
    logger.info(f"Calculated lot size for {symbol}:")
    logger.info(f"  Balance: {balance}, Risk Percentage: {risk_percentage}%, Risk Amount: {risk_amount}")
    logger.info(f"  ATR: {atr}, SL Distance: {sl_distance}")
    logger.info(f"  Point: {point}, Contract Size: {contract_size}, Pip Value per Contract: {pip_value_per_contract}")
    logger.info(f"  Lot Size (rounded): {rounded_lot_size}")

    return rounded_lot_size



async def process_channel_3_signal(message, mt5_path):
    """Processa inkommande signaler från Kanal 3."""
    try:  # Korrekt indentering av try-blocket
        if not mt5.initialize(mt5_path):
            raise RuntimeError(f"Failed to initialize MT5 at path {mt5_path}")

        lines = [line.strip() for line in message.strip().split("\n") if line.strip()]
        logger.info(f"Processed lines from Channel 3: {lines}")

        action_line = lines[0].lower()
        action = "BUY" if "buy" in action_line else "SELL" if "sell" in action_line else None
        raw_symbol = action_line.split()[1].upper()
        symbol = map_symbol(raw_symbol)
        if not symbol:
            raise ValueError(f"Unrecognized symbol {raw_symbol}.")

        # Hämta tickdata
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            raise ValueError(f"Failed to retrieve tick data for {symbol}.")
        current_price = tick.ask if action == "BUY" else tick.bid

        # Beräkna ATR
        atr = calculate_atr(symbol)
        logger.info(f"ATR for {symbol}: {atr}")

        # SL och TP
        sl_distance = atr * 1.5
        tp_distance = sl_distance * 1.3

        sl = current_price - sl_distance if action == "BUY" else current_price + sl_distance
        tp = current_price + tp_distance if action == "BUY" else current_price - tp_distance

        # Kontrollera SL/TP
        symbol_info = mt5.symbol_info(symbol)
        min_stop_distance = symbol_info.trade_stops_level * symbol_info.point
        if abs(current_price - sl) < min_stop_distance or abs(current_price - tp) < min_stop_distance:
            raise ValueError(f"SL or TP levels too close for {symbol}. Min distance: {min_stop_distance}")
        sl = max(sl, current_price - min_stop_distance) if action == "BUY" else min(sl, current_price + min_stop_distance)
        tp = max(tp, current_price + min_stop_distance) if action == "BUY" else min(tp, current_price - min_stop_distance)

        # Beräkna lotstorlek
        account_balance = mt5.account_info().balance
        lot_size = calculate_lot_size(account_balance, 24, atr, symbol, sl_distance)
        if not (symbol_info.volume_min <= lot_size <= symbol_info.volume_max):
            raise ValueError(f"Lot size {lot_size} outside allowed range: {symbol_info.volume_min} - {symbol_info.volume_max}")

        # Skapa och skicka order
        order = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot_size,
            "type": mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL,
            "price": current_price,
            "sl": sl,
            "tp": tp,
            "deviation": 500,
            "magic": 0,
            "comment": "Channel3_Signal",
        }
        logger.info(f"Placing order: {order}")
        result = mt5.order_send(order)
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"Order placed successfully for {symbol} ({action}): {result}")
        else:
            logger.error(f"Failed to place order: Retcode={result.retcode}, Description={mt5.last_error()}")

    except ValueError as ve:
        logger.error(f"ValueError: {ve}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")


