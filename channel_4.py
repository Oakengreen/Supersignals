import logging
import MetaTrader5 as mt5

logger = logging.getLogger("Channel4")

SYMBOL_MAP = {
    "US30": "DJ30",  # Mappa US30 till DJ30
}


def map_symbol(symbol):
    """Mappa symbol till broker-specifik symbol om det behövs."""
    return SYMBOL_MAP.get(symbol, symbol)  # Returnera mappad symbol eller originalet


def close_opposite_positions(symbol, action):
    """Stäng alla motsatta positioner för en given symbol."""
    try:
        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            logger.info(f"No positions to close for {symbol}.")
            return True

        logger.info(f"Checking for opposite positions to close for {symbol}.")
        for position in positions:
            # Kontrollera om positionen är av motsatt typ
            if (action == "BUY" and position.type == mt5.ORDER_TYPE_SELL) or \
                    (action == "SELL" and position.type == mt5.ORDER_TYPE_BUY):
                # Välj rätt pris beroende på ordertypen
                tick = mt5.symbol_info_tick(symbol)
                if not tick:
                    logger.error(f"Failed to retrieve tick data for {symbol} while closing positions.")
                    return False

                if position.type == mt5.ORDER_TYPE_SELL:
                    close_action = mt5.ORDER_TYPE_BUY
                    price = tick.ask  # Använd ask-priset för att köpa tillbaka
                else:
                    close_action = mt5.ORDER_TYPE_SELL
                    price = tick.bid  # Använd bid-priset för att sälja tillbaka

                logger.info(
                    f"Closing position for {symbol}: Ticket={position.ticket}, Volume={position.volume}, Price={price}")

                # Skapa och skicka stängningsordern
                close_order = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": symbol,
                    "volume": position.volume,  # Exakt volym från positionen
                    "type": close_action,
                    "position": position.ticket,  # Använd positionens ticket
                    "price": price,
                    "deviation": 100,
                    "magic": 0,
                    "comment": "Channel4_CloseOpposite",
                    "type_filling": mt5.ORDER_FILLING_IOC,  # Explicit fyllnadsmetod
                }

                close_result = mt5.order_send(close_order)
                if close_result.retcode == mt5.TRADE_RETCODE_DONE:
                    logger.info(f"Closed opposite position for {symbol}: Ticket={position.ticket}")
                else:
                    logger.error(
                        f"Failed to close position for {symbol}: Retcode={close_result.retcode}, Description={mt5.last_error()}")
                    return False
        return True
    except Exception as e:
        logger.error(f"Error while closing opposite positions for {symbol}: {e}")
        return False


async def process_channel_4_signal(message, mt5_path):
    """Processa inkommande signaler från Kanal 4."""
    try:
        # Initiera MetaTrader 5 om det inte redan är gjort
        if not mt5.initialize(mt5_path) and not mt5.terminal_info():
            raise RuntimeError(f"Failed to initialize MT5 at path {mt5_path}")

        # Dela upp meddelandet i rader och trimma bort onödiga mellanslag
        lines = [line.strip() for line in message.strip().split("\n") if line.strip()]
        logger.info(f"Processed lines from Channel 4: {lines}")

        if len(lines) < 2:
            raise ValueError("Invalid signal format: Not enough lines.")

        # Extrahera och mappa symbol
        action_line = lines[0].lower()
        action = "BUY" if "buy" in action_line else "SELL" if "sell" in action_line else None
        raw_symbol = action_line.split()[1].upper().rstrip(":")  # Ta bort ':' från slutet av symbolen
        symbol = map_symbol(raw_symbol)
        if not symbol:
            raise ValueError(f"Invalid signal format: Unrecognized symbol {raw_symbol}.")

        logger.info(f"Parsed signal: Action={action}, Symbol={symbol}")

        # Kontrollera om symbolen är tillgänglig
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info or not symbol_info.visible:
            raise ValueError(f"Symbol {symbol} is not available or not visible in MetaTrader 5.")

        # Stäng motsatta positioner
        if not close_opposite_positions(symbol, action):
            logger.error(f"Failed to close opposite positions for {symbol}. Aborting new order.")
            return

        # Hämta tickdata
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            raise ValueError(f"Failed to retrieve tick data for {symbol}.")
        logger.info(f"Tick data for {symbol}: Ask={tick.ask}, Bid={tick.bid}")
        current_price = tick.ask if action == "BUY" else tick.bid
        if current_price is None:
            raise ValueError(f"Current price for {symbol} is not available.")

        # Skapa ny order
        order = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": 0.01,
            "type": mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL,
            "price": current_price,
            "deviation": 100,  # Öka avvikelsen för att hantera volatilitet
            "magic": 0,
            "comment": "Channel4_Signal",
            "type_filling": mt5.ORDER_FILLING_IOC,  # Explicit fyllnadsmetod
        }

        logger.info(f"Placing order: {order}")
        result = mt5.order_send(order)
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"Order placed successfully for {symbol} ({action}): {result}")
        else:
            logger.error(f"Order failed: Retcode={result.retcode}, Description={mt5.last_error()}")

    except Exception as e:
        logger.error(f"Error processing signal from Channel 4: {e}")
