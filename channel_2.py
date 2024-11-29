import logging
import MetaTrader5 as mt5
import asyncio

logger = logging.getLogger("Channel2")

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

async def process_channel_2_signal(message, mt5_path):
    """Processa inkommande signaler från Telegram och hantera orderläggning."""
    try:
        lines = [line.strip().lower() for line in message.strip().split("\n") if line.strip()]
        logger.info(f"Processed lines: {lines}")

        # Kontrollera att signalen har minst 5 rader
        if len(lines) < 5:
            raise ValueError(f"Signal format invalid: Not enough lines in the message ({len(lines)} lines).")

        # Kontrollera action (Buy/Sell)
        action = "SELL" if "sell" in lines[1] else "BUY" if "buy" in lines[1] else None
        if not action:
            raise ValueError("Invalid signal format: Missing 'Sell' or 'Buy'.")

        # Kontrollera symbol (Gold)
        symbol = "XAUUSD" if "gold" in lines[1] else None
        if not symbol:
            raise ValueError("Invalid signal format: Missing symbol 'Gold'.")

        # Extrahera zon
        try:
            zone_line = lines[1].split("zone")[1].strip()
            zone = list(map(float, zone_line.replace(" ", "").strip("<>").split("-")))
            if len(zone) != 2:
                raise ValueError(f"Zone parsing failed: {zone}")
        except Exception as e:
            raise ValueError(f"Error parsing zone: {e}")

        # Extrahera SL och TP
        try:
            sl_price = float(lines[2].split(":")[1].strip())
        except IndexError:
            raise ValueError(f"Stop Loss line missing or invalid: {lines[2]}")
        except ValueError:
            raise ValueError(f"Stop Loss format invalid: {lines[2]}")

        tp_prices = []
        for tp_line in lines[3:]:
            if "take profit" in tp_line or "tp" in tp_line:
                try:
                    # Extrahera värdet efter ":", ta bort eventuella mellanslag
                    tp_value = tp_line.split(":")[1].strip()
                    tp_prices.append(float(tp_value))
                except Exception as e:
                    logger.warning(f"Skipping invalid TP line: {tp_line} ({e})")

        if not tp_prices:
            raise ValueError("No valid Take Profit levels found.")

        # Initialize MT5
        ensure_mt5_initialized(mt5_path)

        # Placera pending orders inom zonen
        orders = await asyncio.to_thread(
            place_orders_within_zone, action, symbol, zone, sl_price, tp_prices, logger, total_orders=5
        )
        logger.info(f"Pending orders placed: {orders}")

        # Starta övervakning för TP1
        asyncio.create_task(monitor_positions_for_tp1(symbol, tp_prices[0], logger, offset_pips=1))

    except Exception as e:
        logger.error(f"Error processing signal: {e}")

def place_scalping_orders(action, symbol, zone, sl_price, tp1_price, tp2_price, logger):
    """Placera ordrar baserat på signalens parametrar."""
    current_price = mt5.symbol_info_tick(symbol).ask if action == "BUY" else mt5.symbol_info_tick(symbol).bid
    lot_size = calculate_lot_size(2, mt5.account_info().balance, sl_price, zone[0], total_orders=1)
    orders = []

    for i, tp_price in enumerate([tp1_price, tp2_price]):
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

async def monitor_positions_for_tp1(symbol, tp1_price, logger, offset_pips=1):
    """Övervakar priset och uppdaterar SL till BE + 1 pip vid TP1."""
    logger.info(f"Starting TP1 monitoring for {symbol} at {tp1_price}.")
    point = mt5.symbol_info(symbol).point
    offset_points = offset_pips * point

    while True:
        await asyncio.sleep(5)  # Kontrollera var 5:e sekund

        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            logger.info(f"No active positions to monitor for {symbol}.")
            return

        for position in positions:
            # Beräkna den nya SL-nivån
            new_sl = (
                position.price_open + offset_points
                if position.type == mt5.ORDER_TYPE_BUY
                else position.price_open - offset_points
            )
            condition_met = False

            # Kontrollera om TP1 har nåtts
            if position.type == mt5.ORDER_TYPE_BUY and mt5.symbol_info_tick(symbol).bid >= tp1_price:
                condition_met = True
            elif position.type == mt5.ORDER_TYPE_SELL and mt5.symbol_info_tick(symbol).ask <= tp1_price:
                condition_met = True

            if condition_met and position.profit > 0:
                # Kontrollera om SL redan är korrekt inställd
                if abs(position.sl - new_sl) < point:  # Om SL är inom 1 punkt av det nya värdet
                    logger.info(f"SL already set to the correct value for position {position.ticket}.")
                    continue

                # Uppdatera SL om det behövs
                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "symbol": symbol,
                    "position": position.ticket,
                    "sl": new_sl,
                    "tp": position.tp,
                    "magic": position.magic,
                }
                result = mt5.order_send(request)
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    logger.info(f"Updated SL for position {position.ticket} to {new_sl}.")
                else:
                    logger.error(f"Failed to update SL for position {position.ticket}: {result.retcode}")

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
