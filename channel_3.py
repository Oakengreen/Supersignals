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
    :param symbol: Symbolen (t.ex. BTCUSD).
    :param period: Antalet perioder att beräkna ATR över (default: 14).
    :return: ATR-värdet i pips.
    """
    # Hämta historiska data
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, period + 1)
    if rates is None or len(rates) < period + 1:
        raise ValueError(f"Not enough data to calculate ATR for {symbol}. Ensure sufficient historical data.")

    # Hämta symbolspecifikationer
    symbol_info = mt5.symbol_info(symbol)
    if not symbol_info:
        raise ValueError(f"Failed to retrieve symbol info for {symbol}.")

    point = symbol_info.point  # Punktstorlek

    # Beräkna True Range för varje period
    true_ranges = []
    for i in range(1, len(rates)):
        high = rates[i]["high"]
        low = rates[i]["low"]
        prev_close = rates[i - 1]["close"]

        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)

    # Beräkna ATR som medelvärdet av TR
    atr = sum(true_ranges[-period:]) / period

    # Omvandla ATR från punkter till pips
    atr_in_pips = atr / point
    return atr_in_pips


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
    try:
        # Kontrollera att MT5 är initialiserat
        if not mt5.initialize(mt5_path):
            raise RuntimeError(f"Failed to initialize MT5 at path {mt5_path}")

        # Dela upp meddelandet i rader
        lines = [line.strip() for line in message.strip().split("\n") if line.strip()]
        logger.info(f"Processed lines from Channel 3: {lines}")

        if len(lines) < 2:
            raise ValueError("Invalid signal format: Not enough lines.")

        # Extrahera och mappa symbol
        action_line = lines[0].lower()
        action = "BUY" if "buy" in action_line else "SELL" if "sell" in action_line else None
        raw_symbol = action_line.split()[1].upper()
        symbol = map_symbol(raw_symbol)
        if not symbol:
            raise ValueError(f"Invalid signal format: Unrecognized symbol {raw_symbol}.")

        logger.info(f"Parsed signal: Action={action}, Symbol={symbol}")

        # Kontrollera om det redan finns en aktiv position
        if mt5.positions_total() > 0:
            logger.info("An active position exists. Skipping new order.")
            return

        # Hämta tickdata
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            raise ValueError(f"Failed to retrieve tick data for {symbol}.")
        current_price = tick.ask if action == "BUY" else tick.bid

        # Beräkna ATR-baserad SL och TP
        atr = calculate_atr(symbol)
        sl_distance = atr * 1.5
        sl = current_price - sl_distance if action == "BUY" else current_price + sl_distance
        tp = current_price + (sl_distance * 1.3) if action == "BUY" else current_price - (sl_distance * 1.3)

        # Beräkna lotstorlek
        account_balance = mt5.account_info().balance
        lot_size = calculate_lot_size(account_balance, 24, atr, symbol, sl_distance)
        if lot_size < 0.01:
            raise ValueError("Calculated lot size is too small to trade.")

        # Skapa order
        order = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot_size,
            "type": mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL,
            "price": current_price,
            "sl": sl,
            "tp": tp,
            "deviation": 100,
            "magic": 0,
            "comment": "Channel3_Signal",
        }

        logger.info(f"Placing order: {order}")
        result = mt5.order_send(order)
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"Order placed successfully for {symbol} ({action}): {result}")
        else:
            logger.error(f"Failed to place order: Retcode={result.retcode}, Description={mt5.last_error()}")

    except Exception as e:
        logger.error(f"Error processing signal from Channel 3: {e}")
