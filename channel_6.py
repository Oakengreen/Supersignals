from telethon import TelegramClient, events
from settings import TELEGRAM_BOT_TOKEN_CHANNEL_6, GROUP_ID6, TARGET_GROUP_ID6, MT5_PATH
import logging
import MetaTrader5 as mt5

# Logger setup
logger = logging.getLogger("Channel6")

# Skapa Telegram-klient för Kanal 6
client_channel_6 = TelegramClient("channel_6_session", api_id=21741387, api_hash="097295cc4e92cedcf99626ff23d2a010")

async def start_client():
    """Startar Telegram-klient för Kanal 6 med bot-token."""
    await client_channel_6.start(bot_token=TELEGRAM_BOT_TOKEN_CHANNEL_6)
    logger.info("Channel 6 Telegram client started.")

@client_channel_6.on(events.NewMessage(chats=GROUP_ID6))
async def handle_channel_6(event):
    logger.info("[Channel 6] New message received.")
    await process_channel_6_signal(event.raw_text, MT5_PATH, client_channel_6, TARGET_GROUP_ID6)

async def main_channel_6(mt5_path):
    """Startar Telegram-klient och initierar MT5 för Kanal 6."""
    try:
        logger.info("Initializing MetaTrader 5 for Channel 6...")
        if not mt5.initialize(mt5_path):
            logger.error("Failed to initialize MetaTrader 5.")
            return
        logger.info("MetaTrader 5 initialized successfully.")

        logger.info("Starting Telegram client for Channel 6...")
        await start_client()  # Starta klienten med bot-token
        await client_channel_6.run_until_disconnected()
    except Exception as e:
        logger.error(f"Error in Channel 6 main loop: {e}")
    finally:
        mt5.shutdown()

async def process_channel_6_signal(message, mt5_path, client, target_group):
    """Processa signaler från Kanal 6 och skicka orderinformation till en annan Telegram-grupp."""
    try:
        # Kontrollera att MT5 är initierat
        if not mt5.initialize(mt5_path):
            logger.error("MetaTrader 5 is not initialized. Please initialize before running the bot.")
            return

        logger.info(f"Processing message: {message}")
        lines = [line.strip() for line in message.strip().split("\n") if line.strip()]

        if len(lines) < 2:
            logger.error("Signal format is invalid or incomplete.")
            return

        # Identifiera signalens komponenter
        action_line = lines[0].upper()
        if action_line.startswith("BUY"):
            action = "BUY_STOP"
            symbol = action_line.split()[1].strip(":")
        elif action_line.startswith("SELL"):
            action = "SELL_STOP"
            symbol = action_line.split()[1].strip(":")
        else:
            logger.error("No valid action (BUY/SELL) found in the signal.")
            return

        # Kontrollera om symbol hittades
        if not symbol:
            logger.error("No symbol provided in signal.")
            return

        logger.info(f"Action: {action}, Symbol: {symbol}")

        # Kontrollera symbolens information
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info or not symbol_info.visible:
            raise ValueError(f"Symbol {symbol} is not available or not visible in MetaTrader 5.")

        logger.info(f"Symbol info: {symbol_info}")

        # Hämta föregående candle data
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 2)
        if rates is None or len(rates) < 2:
            raise ValueError(f"Not enough data to calculate SL and Entry for {symbol}.")
        previous_high = rates[1][2]  # High från föregående candle
        previous_low = rates[1][3]   # Low från föregående candle

        logger.info(f"Previous Candle High: {previous_high}, Low: {previous_low}")

        # Definiera Entry, SL och TP
        entry_price = previous_high if action == "BUY_STOP" else previous_low
        sl = previous_low if action == "BUY_STOP" else previous_high
        sl = sl - symbol_info.point if action == "SELL_STOP" else sl + symbol_info.point  # Justera för spread
        tp_distance = abs(entry_price - sl) * 1.3
        tp = entry_price + tp_distance if action == "BUY_STOP" else entry_price - tp_distance

        logger.info(f"Entry Price: {entry_price}, SL: {sl}, TP: {tp}")

        # Kontrollera och justera för minimala avstånd
        min_stop_distance = symbol_info.trade_stops_level * symbol_info.point
        if abs(entry_price - sl) < min_stop_distance:
            logger.warning("SL too close to Entry. Adjusting SL.")
            sl = sl - min_stop_distance if action == "SELL_STOP" else sl + min_stop_distance
        if abs(entry_price - tp) < min_stop_distance:
            logger.warning("TP too close to Entry. Adjusting TP.")
            tp = tp + min_stop_distance if action == "BUY_STOP" else tp - min_stop_distance

        logger.info(f"Adjusted SL: {sl}, TP: {tp}")

        # Beräkna lotstorlek
        balance = mt5.account_info().balance
        risk_percentage = 0.01  # Risk 1% av balans
        risk_amount = balance * risk_percentage
        pip_value = symbol_info.trade_tick_value / symbol_info.trade_tick_size
        sl_distance_usd = abs(entry_price - sl) * pip_value
        lot_size = round(risk_amount / sl_distance_usd, 2)

        logger.info(f"Lot Size: {lot_size}")

        # Förbered ordern
        order = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": lot_size,
            "type": mt5.ORDER_TYPE_BUY_STOP if action == "BUY_STOP" else mt5.ORDER_TYPE_SELL_STOP,
            "price": entry_price,
            "sl": round(sl, 4),
            "tp": round(tp, 4),
            "deviation": 10,
            "magic": 6,  # Magic number för Kanal 6
            "comment": "Channel6_Signal",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        logger.info(f"Placing order: {order}")

        # Skicka ordern
        result = mt5.order_send(order)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            raise ValueError(f"Order placement failed: {result}")

        logger.info(f"Order placed successfully: {result}")

        # Skicka orderinformation till en annan Telegram-grupp
        order_message = f"""
{action.split("_")[0]} {symbol}
Entry: {round(entry_price, 4)}
SL: {round(sl, 4)}
TP: {round(tp, 4)}
"""
        await client.send_message(target_group, order_message.strip())
        logger.info("Order details sent to target Telegram group.")

    except Exception as e:
        logger.error(f"Error processing signal: {e}")

