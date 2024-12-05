import pytest
import asyncio
from channel_4 import process_channel_4_signal


# Märk denna testfunktion som asynkron för att kunna använda await
@pytest.mark.asyncio
async def test_process_signal():
    signal_data = """
    SELL XAUUSD
    ENTRY: 2632.59
    BULL
    """

    # Hämta den aktuella event-loopen
    loop = asyncio.get_running_loop()

    # Sökväg till MetaTrader 5 (från settings.py)
    mt5_path = r"C:\\Program Files\\MetaTrader 5 IC Markets (SC)_OPTIMIZER\\terminal64.exe"

    # Vänta på att den asynkrona funktionen ska exekveras
    await process_channel_4_signal(signal_data, mt5_path)
