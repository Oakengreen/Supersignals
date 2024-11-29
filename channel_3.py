import logging
import MetaTrader5 as mt5
import asyncio

logger = logging.getLogger("Channel3")

SYMBOL_MAP = {
    "US30": "DJ30",  # Mappa US30 till DJ30
}


def map_symbol(symbol):
    """Mappa symbol till broker-specifik symbol om det behövs."""
    return SYMBOL_MAP.get(symbol, symbol)  # Returnera mappad symbol eller originalet

def calculate_sl_tp(symbol, action, current_price):
    """Beräkna SL och TP baserat på fast avstånd i points och dynamisk symbol."""
    symbol_info = mt5.symbol_info(symbol)
    if not symbol_info:
        raise ValueError(f"Symbol {symbol} is not available in MetaTrader 5.")

    # Hantera specifika symbolers punktavstånd
    if symbol == "DJ30":  # US30 mappas till DJ30
        points = 1000
    elif symbol == "XAUUSD":
        points = 100
    elif symbol == "BTCUSD":
        points = 10000
    else:
        points = 100  # Standard (kan justeras för andra symboler)

    point = symbol_info.point
    sl = current_price - points * point if action == "BUY" else current_price + points * point
    tp = current_price + points * point if action == "BUY" else current_price - points * point
    return round(sl, symbol_info.digits), round(tp, symbol_info.digits)

async def process_channel_3_signal(message, mt5_path):
    """Processa inkommande signaler från Kanal 3."""
    try:
        # Dela upp meddelandet i rader och trimma bort onödiga mellanslag
        lines = [line.strip() for line in message.strip().split("\n") if line.strip()]
        logger.info(f"Processed lines from Channel 3: {lines}")

        if len(lines) < 2:
            raise ValueError("Invalid signal format: Not enough lines.")

        # Extrahera och mappa symbol
        action_line = lines[0].lower()
        action = "BUY" if "buy" in action_line else "SELL" if "sell" in action_line else None
        symbol = map_symbol(action_line.split()[1].upper())
        if not symbol:
            raise ValueError("Invalid signal format: Missing or unrecognized symbol.")

        logger.info(f"Parsed signal: Action={action}, Symbol={symbol}")

        # Initialisera MetaTrader 5
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            raise ValueError(f"Symbol {symbol} is not available or inactive.")
        current_price = tick.ask if action == "BUY" else tick.bid

        # Beräkna SL och TP
        sl, tp = calculate_sl_tp(symbol, action, current_price)
        logger.info(f"Calculated SL={sl}, TP={tp} for {symbol} ({action}) at {current_price}")

        # Skapa order
        order = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": 0.01,
            "type": mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL,
            "price": current_price,
            "sl": sl,
            "tp": tp,
            "deviation": 10,
            "magic": 0,
            "comment": "Channel3_Signal",
        }

        # Skicka ordern
        result = mt5.order_send(order)
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"Order placed successfully: {result}")

            # Starta trailing SL monitor om ordern lyckades
            #asyncio.create_task(monitor_trailing_sl(
            #    symbol=symbol,
            #    action=action,
            #    entry_price=current_price,
            #    tp=tp,
            #    profit_threshold=5,
            #    offset_pips=1
            #))
            logger.info("Started trailing SL monitor for position.")
        else:
            logger.error(f"Failed to place order: {result.retcode}")

    except Exception as e:
        logger.error(f"Error processing signal from Channel 3: {e}")

def trail_stop_to_be(symbol, action, entry_price, sl, tp, profit_threshold, offset_pips):
    """
    Flytta SL till BE +/− 1 pip om profit når en viss nivå.

    symbol: Symbolen (t.ex. XAUUSD)
    action: "BUY" eller "SELL"
    entry_price: Inträdespris för positionen
    sl: Nuvarande SL
    tp: TP för positionen
    profit_threshold: Nivå i pips där SL flyttas
    offset_pips: Offset i pips för BE (t.ex. +1 för BUY, -1 för SELL)
    """
    try:
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            raise ValueError(f"Symbol {symbol} is not available.")

        point = symbol_info.point
        offset_points = offset_pips * point
        threshold_points = profit_threshold * point

        # Hämta aktuell prisinformation
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            raise ValueError(f"No tick data for {symbol}.")

        current_price = tick.bid if action == "SELL" else tick.ask

        # Kontrollera om profitnivån nåtts
        profit_reached = (
            (current_price >= entry_price + threshold_points if action == "BUY" else
             current_price <= entry_price - threshold_points)
        )

        if profit_reached:
            new_sl = entry_price + offset_points if action == "BUY" else entry_price - offset_points
            if action == "BUY" and sl < new_sl:
                result = mt5.order_send({
                    "action": mt5.TRADE_ACTION_SLTP,
                    "symbol": symbol,
                    "position": mt5.positions_get(symbol=symbol)[0].ticket,
                    "sl": new_sl,
                    "tp": tp
                })
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    logger.info(f"SL moved to BE +1 pip for BUY position on {symbol}. New SL: {new_sl}")
            elif action == "SELL" and sl > new_sl:
                result = mt5.order_send({
                    "action": mt5.TRADE_ACTION_SLTP,
                    "symbol": symbol,
                    "position": mt5.positions_get(symbol=symbol)[0].ticket,
                    "sl": new_sl,
                    "tp": tp
                })
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    logger.info(f"SL moved to BE -1 pip for SELL position on {symbol}. New SL: {new_sl}")

    except Exception as e:
        logger.error(f"Error in trail_stop_to_be for {symbol}: {e}")

async def monitor_trailing_sl(symbol, action, entry_price, tp, profit_threshold, offset_pips):
    """Övervaka position och justera SL om trailing-nivån nås."""
    logger.info(f"Monitoring trailing SL for {symbol} ({action}).")
    while True:
        try:
            positions = mt5.positions_get(symbol=symbol)
            if not positions:
                logger.info(f"No active positions for {symbol}. Exiting trailing SL monitor.")
                break

            for position in positions:
                trail_stop_to_be(
                    symbol=symbol,
                    action=action,
                    entry_price=entry_price,
                    sl=position.sl,
                    tp=tp,
                    profit_threshold=profit_threshold,
                    offset_pips=offset_pips
                )
        except Exception as e:
            logger.error(f"Error in monitor_trailing_sl: {e}")
        await asyncio.sleep(1)  # Kontrollera varje sekund
