import logging
import MetaTrader5 as mt5

logger = logging.getLogger("Channel1")

# Funktion för att säkerställa att MT5 är initierad
def ensure_mt5_initialized(mt5_path):
    if not mt5.initialize(mt5_path):
        logger.error("Failed to initialize MT5.")
        raise Exception("MT5 initialization failed.")

# Funktion för att beräkna lotstorlek
def calculate_lot_size(risk_percent, balance, sl_price, entry_price, total_orders):
    """Calculate lot size based on risk percentage, SL distance, and total allowed orders."""
    total_risk_amount = balance * (risk_percent / 100)
    risk_per_order = total_risk_amount / total_orders
    sl_distance_points = abs(entry_price - sl_price)
    tick_value = mt5.symbol_info("XAUUSD").trade_tick_value
    pip_size = mt5.symbol_info("XAUUSD").point * 10
    sl_distance_pips = sl_distance_points / pip_size
    lot_size = risk_per_order / (sl_distance_pips * tick_value * 10)
    info = mt5.symbol_info("XAUUSD")
    lot_size = max(info.volume_min, min(lot_size, info.volume_max))
    step = info.volume_step
    lot_size = round(lot_size / step) * step
    return round(lot_size, 2)

# Funktion för att hantera inkommande signaler
async def process_scalping_signal(message, mt5_path):
    """Processa signaler från Telegram och placera ordrar."""
    try:
        lines = [line.strip() for line in message.strip().split("\n") if line.strip()]
        if len(lines) < 2:
            raise ValueError("Signal format invalid: Not enough lines in the message.")

        action = "SELL" if "Sell" in lines[0] else "BUY" if "Buy" in lines[0] else None
        if not action:
            raise ValueError("Invalid signal format: Missing 'Sell' or 'Buy'.")

        symbol = "XAUUSD" if "Gold" in lines[0] else None
        if not symbol:
            raise ValueError("Invalid signal format: Symbol not recognized.")

        entry_zone_raw = " ".join(lines[0].split(" ")[2:])
        entry_prices = list(map(float, entry_zone_raw.replace(" ", "").split("-")))

        sl_price = float(lines[1].split(" ")[-1])
        tp_prices = []
        for line in lines[2:]:
            if line.startswith("TP"):
                tp_value = line.split(" ")[-1]
                try:
                    # Rensa parenteser och hantera flera värden (ex: "2636/2634")
                    tp_value_clean = tp_value.strip("()")
                    if "/" in tp_value_clean:
                        tp_value_clean = tp_value_clean.split("/")[0]  # Ta det första värdet före '/'
                    tp_prices.append(float(tp_value_clean))
                except ValueError:
                    logger.warning(f"Skipping invalid TP format: {line}")
                    continue

        if not tp_prices:
            raise ValueError("No valid Take Profit levels found.")

        ensure_mt5_initialized(mt5_path)

        orders = place_scalping_orders(
            action=action,
            symbol=symbol,
            zone=entry_prices,
            sl_price=sl_price,
            tp_prices=tp_prices,
        )

        logger.info(f"Orders placed: {orders}")

    except Exception as e:
        logger.error(f"Error processing signal: {e}")

async def process_channel_1_signal(message, mt5_path):
    """Process incoming signals from Telegram and handle order placement."""
    try:
        lines = [line.strip().lower() for line in message.strip().split("\n") if line.strip()]
        logger.info(f"Processed lines: {lines}")

        if len(lines) < 5:
            raise ValueError(f"Signal format invalid: Not enough lines in the message ({len(lines)} lines).")

        # Kontrollera Buy/Sell
        action = "SELL" if "sell" in lines[0] else "BUY" if "buy" in lines[0] else None
        if not action:
            raise ValueError("Invalid signal format: Missing 'Sell' or 'Buy'.")

        # Kontrollera symbol (Gold)
        symbol = "XAUUSD" if "gold" in lines[0] else None
        if not symbol:
            raise ValueError("Invalid signal format: Missing symbol 'Gold'.")

        # Extrahera zon
        zone_line = lines[1].split("zone")[1].strip()
        zone = list(map(float, zone_line.replace(" ", "").strip("<>").split("-")))
        if len(zone) != 2:
            raise ValueError(f"Zone parsing failed: {zone}")

        # Extrahera SL och TP
        sl_price = float(lines[2].split(":")[1].strip())
        tp_prices = [float(tp.split(":")[1].strip()) for tp in lines[3:] if "tp" in tp]

        if not tp_prices:
            raise ValueError("No valid Take Profit levels found.")

        # Initialize MT5
        ensure_mt5_initialized(mt5_path)

        # Placera gränsordrar inom zonen
        orders = await asyncio.to_thread(
            place_orders_within_zone, action, symbol, zone, sl_price, tp_prices, logger, total_orders=5
        )
        logger.info(f"Limit orders placed: {orders}")

    except Exception as e:
        logger.error(f"Error processing signal: {e}")

# Funktion för att placera ordrar
def place_scalping_orders(action, symbol, zone, sl_price, tp_prices):
    """Placera ordrar inom zonen baserat på signalens parametrar."""
    current_price = mt5.symbol_info_tick(symbol).ask if action == "BUY" else mt5.symbol_info_tick(symbol).bid
    lot_size = calculate_lot_size(2, mt5.account_info().balance, sl_price, zone[0], total_orders=1)
    orders = []

    for i, tp_price in enumerate(tp_prices):
        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": lot_size,
            "type": mt5.ORDER_TYPE_BUY_LIMIT if action == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT,
            "price": current_price,
            "sl": sl_price,
            "tp": tp_price,
            "deviation": 10,
            "magic": 0,
            "comment": f"Order_TP{i+1}",
        }
        result = mt5.order_send(request)
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"Order {request['comment']} placed.")
            orders.append(request)
        else:
            logger.error(f"Failed to place order {request['comment']}: {result.retcode}")
    return orders

def place_orders_within_zone(action, symbol, zone, sl_price, tp_prices, logger, total_orders=4):
    """Place limit orders evenly within the zone with improved validation for stops."""
    try:
        point = mt5.symbol_info(symbol).point
        stops_level = mt5.symbol_info(symbol).trade_stops_level * point
        orders = []

        if zone[1] < zone[0]:
            logger.error("Invalid zone: Upper bound is less than lower bound.")
            return orders

        if total_orders > 1:
            order_distance = (zone[1] - zone[0]) / (total_orders - 1)
        else:
            order_distance = 0

        lot_size = calculate_lot_size(2, mt5.account_info().balance, sl_price, zone[0], total_orders)

        for i in range(total_orders):
            entry_price = zone[0] + i * order_distance
            if i >= len(tp_prices):
                logger.warning(f"Skipping TP for order {i+1}: No valid TP provided.")
                continue
            tp_price = tp_prices[i]

            if abs(entry_price - sl_price) < stops_level:
                logger.error(f"Limit order not placed: SL too close to entry price {entry_price}. Required: {stops_level}")
                continue
            if abs(tp_price - entry_price) < stops_level:
                logger.error(f"Limit order not placed: TP too close to entry price {entry_price}. Required: {stops_level}")
                continue

            request = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": symbol,
                "volume": lot_size,
                "type": mt5.ORDER_TYPE_SELL_LIMIT if action == "SELL" else mt5.ORDER_TYPE_BUY_LIMIT,
                "price": entry_price,
                "sl": sl_price,
                "tp": tp_price,
                "deviation": 10,
                "magic": 0,
                "comment": f"Order_TP{i+1}",
            }
            result = mt5.order_send(request)
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(f"Order {request['comment']} placed successfully.")
                orders.append({"price": entry_price, "volume": lot_size, "tp": tp_price, "comment": f"Order_TP{i+1}"})
            else:
                logger.error(f"Failed to place order {request['comment']}: {result.retcode}")

        return orders

    except Exception as e:
        logger.error(f"Error in placing orders within zone: {e}")
        return []
