from telethon import TelegramClient, events
import asyncio
import logging
from settings import TELEGRAM_API_ID, TELEGRAM_API_HASH, GROUP_ID1, GROUP_ID2, GROUP_ID3, GROUP_ID4, MT5_PATH, MT5_PATH_ALT
from channel_1 import process_scalping_signal
from channel_2 import process_channel_2_signal
from channel_3 import process_channel_3_signal
from channel_4 import process_channel_4_signal
import MetaTrader5 as mt5  # Importera MT5-modulen

# Logger setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MultiChannelBot")

# Skapa Telegram-klient
client = TelegramClient("multi_channel_session", TELEGRAM_API_ID, TELEGRAM_API_HASH)

def ensure_mt5_initialized(mt5_path, alias="default"):
    """Initialisera MetaTrader 5."""
    if not mt5.initialize(mt5_path):
        logger.error(f"Failed to initialize MT5 ({alias}) at path {mt5_path}.")
        raise Exception(f"MT5 initialization failed for {alias}.")
    logger.info(f"MetaTrader 5 ({alias}) initialized successfully.")

# Hantera signaler från Kanal 1 (Sammy)
@client.on(events.NewMessage(chats=GROUP_ID1))
async def handle_sammy_channel(event):
    logger.info("[Channel 1] New message received.")
    await process_scalping_signal(event.raw_text, MT5_PATH)

# Hantera signaler från Kanal 2
@client.on(events.NewMessage(chats=GROUP_ID2))
async def handle_channel_2(event):
    logger.info("[Channel 2] New message received.")
    await process_channel_2_signal(event.raw_text, MT5_PATH)

# Hantera signaler från Kanal 3
@client.on(events.NewMessage(chats=GROUP_ID3))
async def handle_channel_3(event):
    logger.info("[Channel 3] New message received.")
    await process_channel_3_signal(event.raw_text, MT5_PATH)

# Hantera signaler från Kanal 4
@client.on(events.NewMessage(chats=GROUP_ID4))
async def handle_channel_4(event):
    logger.info("------------------------------------------------------------------")
    logger.info("[Channel 4] New message received.")
    await process_channel_4_signal(event.raw_text, MT5_PATH)  # Skicka till alternativ MT5-path

# Main-funktion
async def main():
    logger.info("Initializing MetaTrader 5 terminals...")
    try:
        # Initiera första MT5-terminalen
        ensure_mt5_initialized(MT5_PATH, alias="Primary")
        # Initiera andra MT5-terminalen
        ensure_mt5_initialized(MT5_PATH_ALT, alias="Secondary")
    except Exception as e:
        logger.error(f"Failed to initialize one or more MT5 terminals: {e}")
        return

    logger.info("MetaTrader 5 terminals initialized. Starting Telegram client...")
    await client.start()
    logger.info("Telegram client started. Listening to all channels.")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
