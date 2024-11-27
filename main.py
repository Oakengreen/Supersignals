from telethon import TelegramClient, events
import asyncio
import logging
from settings import TELEGRAM_API_ID, TELEGRAM_API_HASH, GROUP_ID1, GROUP_ID2, MT5_PATH
from channel_1 import process_scalping_signal
from channel_2 import process_channel_2_signal

# Logger setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("MultiChannelBot")

# Skapa Telegram-klient
client = TelegramClient("multi_channel_session", TELEGRAM_API_ID, TELEGRAM_API_HASH)

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

# Main-funktion
async def main():
    logger.info("Starting Telegram client...")
    await client.start()
    logger.info("Telegram client started. Listening to both channels.")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
