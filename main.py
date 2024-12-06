# main.py
from telethon import TelegramClient, events
import asyncio
import logging
#import threading
from settings import (
    TELEGRAM_API_ID,
    TELEGRAM_API_HASH,
    GROUP_ID4,
    MT5_PATH, MT5_PATH_ALT
)
from channel_4 import process_channel_4_signal, supervise_monitor_equity
import MetaTrader5 as mt5
#import gui_visualization  # Se till att den är i samma mapp eller ange rätt sökväg

# Konfigurera loggning till konsolen med INFO-nivå
logging.basicConfig(
    level=logging.INFO,  # Ändra till INFO för mindre detaljerad loggning
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("MultiChannelBot")

# Telegram-klient
client = TelegramClient("multi_channel_session", TELEGRAM_API_ID, TELEGRAM_API_HASH)

def ensure_mt5_initialized(mt5_path, alias="default"):
    """Initialisera MetaTrader 5."""
    if not mt5.initialize(mt5_path):
        logger.error(f"Failed to initialize MT5 ({alias}) at path {mt5_path}.")
        raise Exception(f"MT5 initialization failed for {alias}.")
    logger.info(f"MetaTrader 5 ({alias}) initialized successfully.")

@client.on(events.NewMessage(chats=GROUP_ID4))
async def handle_channel_4(event):
    logger.info("[Channel 4] New message received.")
    await process_channel_4_signal(event.raw_text, MT5_PATH_ALT)

async def main():
    logger.info("Initializing MetaTrader 5 terminals...")
    try:
        ensure_mt5_initialized(MT5_PATH, alias="Primary")
        ensure_mt5_initialized(MT5_PATH_ALT, alias="Secondary")
    except Exception as e:
        logger.error(f"Failed to initialize one or more MT5 terminals: {e}")
        return

    logger.info("MetaTrader 5 terminals initialized. Starting Telegram client...")
    try:
        # Starta GUI i en separat tråd för att inte blockera main loop
        #gui_thread = threading.Thread(target=gui_visualization.start_gui)
        #gui_thread.daemon = True
        #gui_thread.start()

        await client.start()  # Startar huvudklienten
        logger.info("Telegram client started. Listening for messages...")

        # Starta supervisorn för equity-övervakning
        asyncio.create_task(supervise_monitor_equity())

        # Håll Telegram-klienten aktiv
        await client.run_until_disconnected()
    except Exception as e:
        logger.error(f"An error occurred while running the Telegram client: {e}")

if __name__ == "__main__":
    asyncio.run(main())
