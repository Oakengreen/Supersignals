from pybit.unified_trading import HTTP
import logging

logger = logging.getLogger("Channel5")

# Initiera PyBit-klient
client = HTTP(
    testnet=True,  # Aktivera testnet
    api_key="DIN_API_KEY",
    api_secret="DIN_API_SECRET",
)

async def process_channel_5_signal(message):
    """Processa inkommande signaler från Channel 5 och lägg order på Bybit."""
    try:
        logger.info(f"Processing message: {message}")
        action_line = message.strip().upper()

        if "BUY" in action_line:
            side = "Buy"
        elif "SELL" in action_line:
            side = "Sell"
        else:
            raise ValueError("Invalid action in message. Expected 'BUY' or 'SELL'.")

        # Exempel: Extrahera symbol och annan info
        symbol = "BTCUSDT"  # Ändra efter behov
        order_qty = 0.01  # Justera efter ditt behov

        # Skicka order
        logger.info(f"Placing {side} order for {symbol}")
        response = client.place_order(
            symbol=symbol,
            side=side,
            qty=order_qty,
            orderType="Market",
            timeInForce="GTC",
        )
        logger.info(f"Order response: {response}")
    except Exception as e:
        logger.error(f"Error processing signal from Channel 5: {e}")
