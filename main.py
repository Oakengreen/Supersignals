# main.py
import asyncio
import logging
from channel_4 import (
    supervise_monitor_equity,
    initialize_order_tracking
)
from communication import update_queue

# Importera andra nödvändiga moduler och funktioner

# Konfigurera loggning om det inte redan är gjort
logging.basicConfig(
    level=logging.INFO,  # Justera nivå som behövs
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    handlers=[
        logging.FileHandler("supersignals.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("Main")


async def main():
    """Huvudfunktion som startar alla asynkrona uppgifter och hanterar kommunikation."""

    # Initialisera orderspårning
    initialize_order_tracking()

    # Starta equity monitoring som en uppgift
    monitor_task = asyncio.create_task(supervise_monitor_equity())

    # Starta andra asynkrona uppgifter här
    # Exempel: kommunikationskanaler, signalmottagare, etc.
    # async for message in signal_receiver():
    #     await process_channel_4_signal(message, mt5_path)

    # För demonstration, låt oss köra en loop som kontrollerar update_queue
    while True:
        try:
            # Hantera uppdateringar från update_queue
            update = await update_queue.get()
            if update:
                if update['type'] == 'label':
                    # Uppdatera GUI etikett
                    logger.info(f"Label Update: {update['text']}")
                    # Implementera GUI-uppdatering här
                elif update['type'] == 'position_status':
                    # Uppdatera GUI med positionstatus
                    position = update['position']
                    logger.info(f"Position Status Update: {position}")
                    # Implementera GUI-uppdatering här
            await asyncio.sleep(1)  # Justera efter behov
        except Exception as e:
            logger.error(f"Error in main loop: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Program terminated by user.")
