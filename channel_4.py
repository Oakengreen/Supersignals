import logging
import MetaTrader5 as mt5
from chart_visualization import plot_candlestick_chart

logger = logging.getLogger("Channel4")

SYMBOL_MAP = {
    "US30": "DJ30",  # Mappa US30 till DJ30
}

#last_order = {}

# Global ordbok för att lagra trender per symbol
current_trends = {}

def calculate_atr(symbol, period=14):
    """Beräkna ATR (Average True Range) för en given symbol."""
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, period + 1)
    if rates is None or len(rates) < period + 1:
        raise ValueError(f"Not enough data to calculate ATR for {symbol}.")

    tr_values = []
    for i in range(1, len(rates)):
        high = rates[i][2]  # Justera index för 'high'
        low = rates[i][3]  # Justera index för 'low'
        prev_close = rates[i - 1][4]  # Justera index för 'close'
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        tr_values.append(tr)

    atr = sum(tr_values) / period
    return atr

def calculate_pip_value(symbol_info):
    """Beräkna pipvärdet per kontrakt baserat på symbolinfo."""
    if symbol_info.trade_tick_size > 0:
        pip_value = symbol_info.trade_tick_value / symbol_info.trade_tick_size
        logger.info(f"Pip Value calculated: {pip_value}")
        return pip_value
    else:
        raise ValueError(f"Invalid tick size for {symbol_info.name}. Cannot calculate pip value.")

def map_symbol(symbol):
    """Mappa symbol till broker-specifik symbol om det behövs."""
    return SYMBOL_MAP.get(symbol, symbol)

def position_size(balance, symbol, sl_distance_usd):
    """Beräkna en fast lotstorlek för att säkerställa korrekt riskhantering."""
    leverage = mt5.account_info().leverage
    price = (mt5.symbol_info(symbol).ask + mt5.symbol_info(symbol).bid) / 2
    trade_size = mt5.symbol_info(symbol).trade_contract_size
    lot_size = (balance * leverage) / (sl_distance_usd * price * trade_size)

    # Anpassa till symbolens gränser
    min_lot = mt5.symbol_info(symbol).volume_min
    max_lot = mt5.symbol_info(symbol).volume_max
    lot_size = max(min(round(lot_size, 2), max_lot), min_lot)

    logger.info(f"Lot Size calculated: {lot_size}")

    return lot_size

def update_trend(message):
    """Uppdaterar trenden baserat på inkommande meddelande."""
    global current_trends

    # Dela upp meddelandet i rader och rensa tomma rader
    lines = [line.strip() for line in message.strip().split("\n") if line.strip()]

    # Initialisera variabler för trend och symbol
    trend = None
    symbol = None

    # Extrahera trenden och symbolen från respektive rader
    for line in lines:
        if line.startswith("TREND:"):
            trend = line.split("TREND:")[1].strip().upper()
            logger.info(f"Extracted trend: {trend}")
        elif line.startswith("SYMBOL:"):
            raw_symbol = line.split("SYMBOL:")[1].strip().upper()
            symbol = map_symbol(raw_symbol)  # Mappa symbolen här
            logger.info(f"Extracted and mapped symbol: {symbol}")

    # Kontrollera att både trend och symbol är tillgängliga
    if trend and symbol:
        if trend in ["UP", "DN", "DOWN"]:  # Hantera DN som DOWN
            current_trends[symbol] = "UP" if trend == "UP" else "DOWN"
            logger.info(f"Trend updated: {symbol} is now in {current_trends[symbol]} trend.")
        else:
            logger.warning(f"Unrecognized trend direction: {trend}")
    else:
        logger.warning(f"Invalid trend or symbol format: {message}")

    # Logga aktuella trender
    logger.info(f"Current Trends: {current_trends}")

def get_trend(symbol):
    """Hämtar aktuell trend för en symbol."""
    mapped_symbol = map_symbol(symbol)  # Mappa symbolen
    trend = current_trends.get(mapped_symbol, "UNKNOWN")
    logger.info(f"Current trend for {mapped_symbol}: {trend}")
    return trend

async def process_channel_4_signal(message, mt5_path):
    """Processa inkommande signaler från Kanal 4."""
    try:
        logger.info("Initializing MetaTrader 5...")
        if not mt5.initialize(mt5_path):
            raise RuntimeError(f"Failed to initialize MT5 at path {mt5_path}")

        logger.info(f"Processing message: {message}")
        lines = [line.strip() for line in message.strip().split("\n") if line.strip()]
        logger.info(f"Processed lines: {lines}")

        # Kontrollera om meddelandet innehåller en trenduppdatering
        if any(line.startswith("TREND:") for line in lines):
            logger.info("Detected trend update message. Triggering update_trend().")
            update_trend(message)
            return  # Avsluta processen här eftersom det är en trenduppdatering

        action_line = lines[0].strip().upper()
        action = mt5.ORDER_TYPE_BUY if "BUY" in action_line else mt5.ORDER_TYPE_SELL

        symbol = map_symbol(action_line.split()[1].upper().rstrip(":"))
        logger.info(f"Symbol parsed: {symbol}")
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info or not symbol_info.visible:
            raise ValueError(f"Symbol {symbol} is not available or not visible in MetaTrader 5.")
        logger.info(f"Symbol info: {symbol_info}")

        # Kontrollera trenden innan vi fortsätter
        trend = get_trend(symbol)
        if action == mt5.ORDER_TYPE_BUY and trend != "UP":
            logger.error(f"Cannot place BUY order for {symbol} as trend is {trend}.")
            return
        elif action == mt5.ORDER_TYPE_SELL and trend != "DOWN":
            logger.error(f"Cannot place SELL order for {symbol} as trend is {trend}.")
            return

        # Hämta aktuellt pris, spread och andra symbolparametrar
        tick = mt5.symbol_info_tick(symbol)
        current_price = tick.ask if action == mt5.ORDER_TYPE_BUY else tick.bid
        spread = abs(tick.ask - tick.bid)
        min_stop_distance = symbol_info.trade_stops_level * symbol_info.point
        one_pip = symbol_info.point

        logger.info(f"Current Price: {current_price}")
        logger.info(f"Spread: {spread}")
        logger.info(f"Minimum Stop Distance: {min_stop_distance}")
        logger.info(f"One Pip Value: {one_pip}")

        if min_stop_distance <= 0 or one_pip <= 0:
            raise ValueError(f"Invalid stop level or pip value for {symbol}. Check broker configuration.")

        # Hämta de senaste två candlarna
        rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 5)
        if rates is None or len(rates) < 5:
            raise ValueError(f"Not enough data to calculate SL for {symbol}.")

        # Extract OHLC data för de senaste candlarna
        previous_high = rates[3][2]  # High för föregående candle (rates[3])
        previous_low = rates[3][3]  # Low för föregående candle (rates[3])

        logger.info(f"Previous Candle OHLC: High={previous_high}, Low={previous_low}")

        # Beräkna SL och TP baserat på föregående candle
        if action == mt5.ORDER_TYPE_SELL:
            # För en säljorder: Stop Loss ska vara föregående högsta pris + spread
            sl = previous_high + spread
            tp = sl - (sl - previous_high) * 1.3  # TP som är 1.3 gånger SL-avståndet
        else:
            # För en köporder: Stop Loss ska vara föregående lägsta pris - spread
            sl = previous_low - spread
            tp = sl + (previous_low - sl) * 1.3  # TP som är 1.3 gånger SL-avståndet

        logger.info(f"Calculated SL: {sl}, Calculated TP: {tp}")

        # Förbered de slutliga värdena som ska skickas till grafen
        final_values = {
            "sl": round(sl, 4),
            "tp": round(tp, 4),
            "current_price": current_price,
            "spread": spread,
            "symbol": symbol,
            "action": action
        }

        # Skicka dessa värden till grafen
        try:
            # Skapa graf för visualisering
            logger.info(f"Creating chart for visualization...")
            try:
                chart_path = plot_candlestick_chart(final_values)
                logger.info(f"Chart saved at: {chart_path}")
            except Exception as e:
                logger.error(f"Failed to create chart: {e}")

        except Exception as e:
            logger.error(f"Error processing signal from Channel 4: {e}")

        # Beräkna lotstorlek och kontrollera margin
        balance = mt5.account_info().balance
        risk_amount = round(balance * 0.01, 4)  # 1% av balans
        logger.info(f"Account Balance: {balance}, Risk Amount (1%): {risk_amount}")

        pip_value = calculate_pip_value(symbol_info)
        sl_distance_usd = abs(sl - current_price) * pip_value
        lot_size = round(risk_amount / sl_distance_usd, 2)

        while lot_size >= symbol_info.volume_min:
            required_margin = mt5.order_calc_margin(action, symbol, lot_size, current_price)
            free_margin = mt5.account_info().margin_free
            if free_margin >= required_margin:
                break
            lot_size = round(lot_size - symbol_info.volume_step, 2)

        if lot_size < symbol_info.volume_min:
            raise ValueError(f"Insufficient margin for minimum lot size {symbol_info.volume_min}. Free={free_margin}")

        logger.info(f"Final Lot Size: {lot_size}")

        # Förbered och skicka order
        try:
            # Förbered och skicka order med beräknade SL och TP
            order = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": lot_size,  # Använd beräknad lotstorlek
                "type": action,
                "price": current_price,
                "sl": round(sl, 4),
                "tp": round(tp, 4),
                "deviation": 500,
                "magic": 0,
                "comment": "Channel4_Signal",
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            logger.info(f"Order prepared: {order}")

            # Skicka ordern till MT5
            result = mt5.order_send(order)
            logger.info(f"Order result: {result}")

            # Hantera resultatet
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                # Hantera Invalid Stops-fel
                if result.comment == "Invalid stops":
                    logger.warning("Invalid stops detected. Retrying with fixed SL and TP distances.")

                    # Fasta SL och TP avstånd
                    fixed_sl_distance = 100 * symbol_info.point
                    fixed_tp_distance = 130 * symbol_info.point

                    # Uppdatera SL och TP baserat på action
                    sl = current_price + fixed_sl_distance if action == mt5.ORDER_TYPE_SELL else current_price - fixed_sl_distance
                    tp = current_price - fixed_tp_distance if action == mt5.ORDER_TYPE_SELL else current_price + fixed_tp_distance

                    logger.info(f"Retrying order with Fixed SL={sl}, Fixed TP={tp}")

                    # Skapa graf med de fasta värdena
                    logger.info(f"Creating chart for visualization...FIXED")
                    try:
                        chart_path = plot_candlestick_chart(final_values)
                        logger.info(f"Chart saved at: {chart_path}")
                    except Exception as e:
                        logger.error(f"Failed to create chart: {e}")

                    # Uppdatera ordern och skicka om
                    order["sl"] = round(sl, 4)
                    order["tp"] = round(tp, 4)
                    retry_result = mt5.order_send(order)

                    if retry_result.retcode != mt5.TRADE_RETCODE_DONE:
                        logger.error(f"Retry failed. Error: {retry_result}")
                        raise ValueError(f"Retry failed: {retry_result}")
                    else:
                        logger.info(f"Retry successful: {retry_result}")
                else:
                    raise ValueError(f"Order failed: {result}")
            else:
                logger.info(f"Order placed successfully for {symbol}: {result}")

        except Exception as e:
            logger.error(f"Error processing signal from Channel 4: {e}")

    except Exception as e:
        logger.error(f"Error processing signal from Channel 4: {e}")
