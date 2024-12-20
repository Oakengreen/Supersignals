# channel_4.py
import MetaTrader5 as mt5
import asyncio
import time  # För tidskontroll i throttling
from settings import EMA_PERIOD, Trendorders
from communication import (
    update_queue,
    hedged_positions,
    original_orders_per_symbol,
    hedge_orders_per_symbol
)
import logging
import os  # För att använda miljövariabeln eller en flagga för testläge

# Skapa logger
logger = logging.getLogger("Channel4")

# Standard loggnivå
log_level = logging.INFO

# Kontrollera om vi är i testläge (kan sättas via en miljövariabel eller en flagga)
if os.getenv('TEST_MODE', 'False') == 'True':
    # Om vi är i testläge, logga till en fil
    handler = logging.FileHandler('test_log.log')  # Loggar till filen test_log.log
else:
    # Annars loggas till standard utmatning (som konsolen)
    handler = logging.StreamHandler()

# Ange loggnivå och formattering
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(log_level)

SYMBOL_MAP = {
    "US30": "DJ30",  # Mappa US30 till DJ30
}

# Global ordbok för att lagra trender per symbol
current_trends = {}
# Variabel för att hålla koll på om monitor_equity är igång
monitoring_equity = False
# Global dictionary för att logga senaste varningstid per symbol
hedge_warning_logged = {}
# En global lista eller dict för att hålla reda på den senaste orginalordern per symbol
last_original_order_per_symbol = {}
# En global dictionary för att koppla hedgeorder till orginalorder
hedge_orders_per_original = {}

def map_symbol(symbol):
    """Mappa symbol till broker-specifik symbol om det behövs."""
    return SYMBOL_MAP.get(symbol, symbol)

def get_trend(symbol):
    """Hämtar aktuell trend för en symbol."""
    mapped_symbol = map_symbol(symbol)  # Mappa symbolen
    trend = current_trends.get(mapped_symbol, "UNKNOWN")
    logger.info(f"Current trend for {mapped_symbol}: {trend}")
    return trend

def calculate_ema(symbol, period=EMA_PERIOD, timeframe=mt5.TIMEFRAME_M1):
    """Beräkna EMA för en given symbol och period."""
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 1)
    if rates is None or len(rates) < period + 1:
        raise ValueError(f"Not enough data to calculate EMA for {symbol}.")

    close_prices = [rate[4] for rate in rates]  # Hämta stängningspriser
    multiplier = 2 / (period + 1)
    ema = close_prices[0]  # Initiera EMA med första stängningspriset

    for price in close_prices[1:]:
        ema = (price - ema) * multiplier + ema

    return ema

def check_price_vs_ema(symbol, timeframe=mt5.TIMEFRAME_M1):
    """
    Kontrollera om aktuellt pris är över eller under EMA och returnera resultatet.

    Returnerar:
        dict: {'position': 'above' eller 'below', 'ema': <ema-värde>, 'price': <aktuellt pris>}
    """
    ema = calculate_ema(symbol, period=EMA_PERIOD, timeframe=timeframe)
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        raise ValueError(f"Failed to retrieve tick data for {symbol}.")
    current_price = (tick.ask + tick.bid) / 2  # Medelpris

    position = "above" if current_price > ema else "below"
    logger.info(f"Current Price: {current_price}, EMA({EMA_PERIOD}): {ema}, Position: {position}")
    return {"position": position, "ema": ema, "price": current_price}

async def process_channel_4_signal(message, mt5_path):
    """Processa inkommande signaler från Kanal 4 med EMA-villkor och equity-övervakning."""
    global monitoring_equity

    try:
        logger.info("Initializing MetaTrader 5...")
        if not mt5.initialize(mt5_path):
            raise RuntimeError(f"Failed to initialize MT5 at path {mt5_path}")

        logger.info(f"Processing message: {message}")

        # Extrahera ordertyp och symbol från meddelandet
        lines = [line.strip() for line in message.strip().split("\n") if line.strip()]
        if not lines:
            logger.error("Received empty message.")
            return

        action_line = lines[0].strip().upper()
        if "BUY" in action_line:
            action = mt5.ORDER_TYPE_BUY
        elif "SELL" in action_line:
            action = mt5.ORDER_TYPE_SELL
        else:
            logger.error(f"Unknown action in message: {action_line}")
            return

        # Hämta symbol från meddelandet
        try:
            symbol = map_symbol(action_line.split()[1].upper().rstrip(":"))
        except IndexError:
            logger.error(f"Failed to parse symbol from message: {action_line}")
            return

        logger.info(f"Parsed symbol: {symbol}")

        # Kontrollera om symbol är synlig
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info or not symbol_info.visible:
            raise ValueError(f"Symbol {symbol} is not available or not visible in MetaTrader 5.")

        # Kontrollera EMA-filter
        ema_check = check_price_vs_ema(symbol)
        current_price = ema_check["price"]

        # Introducera en variabel för att avgöra ordertyp i kommentaren
        is_trend_order = False

        # Ändring start:
        # Om Trendorders = True och symbolen har hedge, skippa vanlig EMA-logik
        # (Trendorder tillåts oavsett EMA-läge)
        if Trendorders and symbol in hedged_positions:
            is_trend_order = True
            logger.info(f"Trend order allowed for {action_line} on {symbol}.")
        else:
            # Ny logik för originalorder:
            # BUY endast om position == "above"
            # SELL endast om position == "below"
            if action == mt5.ORDER_TYPE_BUY and ema_check["position"] != "above":
                logger.warning(f"BUY signal rejected: Price is not above EMA för {symbol}.")
                return
            elif action == mt5.ORDER_TYPE_SELL and ema_check["position"] != "below":
                logger.warning(f"SELL signal rejected: Price is not below EMA för {symbol}.")
                return

            logger.info(f"Signal passed EMA filter: {action_line}. EMA={ema_check['ema']}, Price={current_price}")

            # Kontrollera Trendorders-inställning om vi inte redan är i trend-läget
            if not Trendorders and symbol in hedged_positions:
                logger.info(f"Order rejected due to active hedge on {symbol} and Trendorders=False.")
                return
        # Ändring slut

        # Nu skall ordern läggas. Bestäm kommentaren beroende på ordertyp
        if is_trend_order:
            order_comment = "Trendorder"
        else:
            # Om det inte är en trendorder, är det en original-order
            order_comment = "Original_order"

        # Använd fast lotstorlek
        fixed_lot_size = 0.1
        logger.info(f"Using fixed lot size: {fixed_lot_size}")

        account_info = mt5.account_info()
        if account_info is None:
            logger.error("Failed to fetch account info.")
            return

        free_margin = account_info.margin_free

        while fixed_lot_size >= symbol_info.volume_min:
            required_margin = mt5.order_calc_margin(action, symbol, fixed_lot_size, current_price)
            if free_margin >= required_margin:
                break
            fixed_lot_size = round(fixed_lot_size - symbol_info.volume_step, 2)

        if fixed_lot_size < symbol_info.volume_min:
            raise ValueError(f"Insufficient margin for minimum lot size {symbol_info.volume_min}. Free={free_margin}")

        logger.info(f"Final Lot Size: {fixed_lot_size}")

        order = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": fixed_lot_size,
            "type": action,
            "price": current_price,
            "deviation": 20,
            "magic": 0,
            "comment": order_comment,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(order)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"Failed to place order for {symbol}. Error: {result.retcode}, Comment: {result.comment}")
        else:
            logger.info(f"Successfully placed {'BUY' if action == mt5.ORDER_TYPE_BUY else 'SELL'} order for {symbol}. Ticket: {result.order}")

            # Spara den senaste orginalordern i dictionaryn
            last_original_order_per_symbol[symbol] = result.order
            logger.debug(f"Last original order for {symbol}: {last_original_order_per_symbol[symbol]}")

            # Öka antalet originalorder per symbol
            original_orders_per_symbol[symbol] += 1
            logger.debug(f"Original orders for {symbol}: {original_orders_per_symbol[symbol]}")

            # Kontrollera om monitor_equity är igång, och starta den om den inte är det
            if not monitoring_equity:
                monitoring_equity = True
                asyncio.create_task(supervise_monitor_equity())

    except Exception as e:
        logger.error(f"Error processing channel 4 signal: {e}")


async def supervise_monitor_equity():
    """Supervisorn som säkerställer att monitor_equity alltid körs."""
    while True:
        try:
            await monitor_equity()
        except Exception as e:
            logger.error(f"monitor_equity crashed: {e}. Restarting in 5 seconds.")
            await asyncio.sleep(5)  # Vänta innan du startar om
            continue

def close_position(position):
    """Stänger en specifik position."""
    if not isinstance(position.ticket, int) or position.ticket <= 0:
        logger.error(f"Invalid ticket number for position: {position}")
        return

    order_type = mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
    tick = mt5.symbol_info_tick(position.symbol)
    if not tick:
        logger.error(f"Failed to retrieve tick data for symbol {position.symbol}. Cannot close position {position.ticket}.")
        return

    price = tick.bid if order_type == mt5.ORDER_TYPE_BUY else tick.ask

    if price == 0.0:
        logger.error(f"Failed to retrieve price for symbol {position.symbol}. Cannot close position {position.ticket}.")
        return

    close_order = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": position.symbol,
        "volume": position.volume,
        "type": order_type,
        "position": position.ticket,  # Korrekt position ticket
        "price": price,
        "deviation": 20,  # Minska deviation
        "magic": 0,
        "comment": "Close_Position",
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    # Logga close_order innan skickning
    logger.debug(f"Closing order: {close_order}")

    result = mt5.order_send(close_order)

    # Logga hela resultatet för detaljerad felsökning
    logger.debug(f"OrderSendResult: retcode={result.retcode}, deal={result.deal}, order={result.order}, volume={result.volume}, price={result.price}, comment='{result.comment}'")

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"Failed to close position {position.ticket}. Error: {result.retcode}, Comment: {result.comment}")
    else:
        logger.info(f"Successfully closed position {position.ticket}. Result: {result}")

        # Om det är en originalorder, minska antalet originalorder och hedge-order
        symbol = position.symbol
        if position.ticket in hedged_positions:
            hedge_ticket = hedged_positions.pop(position.ticket)
            hedge_orders_per_symbol[symbol] -= 1
            logger.info(f"Removed hedge ticket {hedge_ticket} for original ticket {position.ticket}.")
            logger.debug(f"Hedge orders for {symbol}: {hedge_orders_per_symbol[symbol]}")
        else:
            original_orders_per_symbol[symbol] -= 1
            logger.debug(f"Original orders for {symbol}: {original_orders_per_symbol[symbol]}")

def close_all_orders():
    """Stänger alla öppna positioner och verifierar att de stängs."""
    open_positions = mt5.positions_get()
    if open_positions is None:
        logger.error("Failed to fetch open positions.")
        return

    if len(open_positions) == 0:
        logger.info("No open positions to close.")
        return

    for position in open_positions:
        # Verifiera att position.ticket är giltigt
        if not isinstance(position.ticket, int) or position.ticket <= 0:
            logger.error(f"Invalid ticket number for position: {position}")
            continue

        order_type = mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(position.symbol)
        if not tick:
            logger.error(f"Failed to retrieve tick data for symbol {position.symbol}. Cannot close position {position.ticket}.")
            continue

        price = tick.bid if order_type == mt5.ORDER_TYPE_BUY else tick.ask

        if price == 0.0:
            logger.error(f"Failed to retrieve price for symbol {position.symbol}. Cannot close position {position.ticket}.")
            continue

        close_order = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "volume": position.volume,
            "type": order_type,
            "position": position.ticket,  # Korrekt position ticket
            "price": price,
            "deviation": 20,  # Minska deviation
            "magic": 0,
            "comment": "Close_Position",
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        # Logga close_order innan skickning
        logger.debug(f"Closing order: {close_order}")

        result = mt5.order_send(close_order)

        # Logga hela resultatet för detaljerad felsökning
        logger.debug(f"OrderSendResult: retcode={result.retcode}, deal={result.deal}, order={result.order}, volume={result.volume}, price={result.price}, comment='{result.comment}'")

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"Failed to close position {position.ticket}. Error: {result.retcode}, Comment: {result.comment}")
        else:
            logger.info(f"Successfully closed position {position.ticket}. Result: {result}")

            # Om det är en originalorder, minska antalet originalorder och hedge-order
            symbol = position.symbol
            if position.ticket in hedged_positions:
                hedge_ticket = hedged_positions.pop(position.ticket)
                hedge_orders_per_symbol[symbol] -= 1
                logger.info(f"Removed hedge ticket {hedge_ticket} for original ticket {position.ticket}.")
                logger.debug(f"Hedge orders for {symbol}: {hedge_orders_per_symbol[symbol]}")
            else:
                original_orders_per_symbol[symbol] -= 1
                logger.debug(f"Original orders for {symbol}: {original_orders_per_symbol[symbol]}")

def initialize_order_tracking():
    """Initialisera orderspårning baserat på befintliga öppna positioner."""
    open_positions = mt5.positions_get()
    if open_positions:
        for position in open_positions:
            symbol = position.symbol
            # Antag att varje befintlig position är en originalorder
            original_orders_per_symbol[symbol] += 1
            logger.info(f"Tracking existing position {position.ticket} for symbol {symbol}.")
            logger.debug(f"Original orders for {symbol}: {original_orders_per_symbol[symbol]}")

async def monitor_equity():
    """Övervaka total equity och profit för alla positioner, och hantera hedge-logik."""
    global monitoring_equity
    logger.info("Starting equity monitoring...")

    profit_threshold = 10.0  # $10 profit gräns
    loss_threshold = -20.0  # $10 förlust gräns
    lot_size = 0.1  # Lotstorlek för hedge-order

    while True:
        try:
            # Hämta öppna positioner
            open_positions = mt5.positions_get()

            # --- Ny kod start ---
            # Nollställ alla räknare innan vi räknar om från verkliga data
            for sym in original_orders_per_symbol.keys():
                original_orders_per_symbol[sym] = 0
            for sym in hedge_orders_per_symbol.keys():
                hedge_orders_per_symbol[sym] = 0

            # Räkna om räknarna baserat på aktuella öppna positioner
            if open_positions:
                for position in open_positions:
                    symbol = position.symbol
                    # Om positionens ticket finns i hedged_positions.values() så är det en hedge-order
                    if position.ticket in hedged_positions.values():
                        hedge_orders_per_symbol[symbol] += 1
                    else:
                        original_orders_per_symbol[symbol] += 1
            # --- Ny kod slut ---

            if not open_positions or len(open_positions) == 0:
                await update_queue.put({'type': 'label', 'text': "No open positions."})  # Uppdatera GUI via kön
                logger.info("No open positions. Monitoring paused.")
                monitoring_equity = False  # Reset flaggan
                await asyncio.sleep(10)  # Vänta innan du kontrollerar igen
                continue  # Fortsätt loopen

            # Initialisera: Lägg till öppna positioner som inte redan är spårade
            # (Denna del är nu mest redundant, då vi redan byggt upp räknarna baserat på öppna positioner
            #  i koden ovan. Men om du vill behålla logiken för att logga befintliga positioner kan den vara kvar.)
            for position in open_positions:
                symbol = position.symbol
                # Om positionen redan räknats som originalorder behöver vi inte sätta om den,
                # men om du vill behålla denna logg för debugging kan du låta den vara.
                if original_orders_per_symbol[symbol] == 0:
                    original_orders_per_symbol[symbol] = 1
                    logger.info(f"Tracking existing position {position.ticket} for symbol {symbol}.")
                    logger.debug(f"Original orders for {symbol}: {original_orders_per_symbol[symbol]}")

            # Hämta total equity och profit
            account_info = mt5.account_info()
            if account_info is None:
                logger.error("Failed to fetch account info.")
                await asyncio.sleep(10)
                continue

            equity = account_info.equity
            balance = account_info.balance
            total_profit = equity - balance  # Totalt P/L

            # Logga total profit för debugging
            logger.debug(f"Monitoring Total Equity: Balance={balance:.2f}, Equity={equity:.2f}, Total Profit={total_profit:.2f}")

            # Hantera vinstgräns
            if total_profit >= profit_threshold:
                logger.info(f"Total profit reached ${total_profit:.2f}. Closing all orders.")
                close_all_orders()

                # Verifiera att alla order är stängda
                remaining_positions = mt5.positions_get()
                if remaining_positions and len(remaining_positions) > 0:
                    logger.error("Some positions could not be closed. Continuing monitoring.")
                else:
                    logger.info("All positions successfully closed. Stopping monitoring.")
                monitoring_equity = False  # Reset flaggan
                await asyncio.sleep(10)  # Vänta innan du kontrollerar igen
                continue  # Fortsätt loopen

            # Iterera över alla öppna positioner och hantera varje symbol
            for position in open_positions:
                # Verifiera att position.ticket är ett positivt heltal
                if not isinstance(position.ticket, int) or position.ticket <= 0:
                    logger.error(f"Invalid ticket number for position: {position}")
                    continue

                symbol = position.symbol

                # Kontrollera om positionen är en hedge-order
                if position.ticket in hedged_positions.values():
                    logger.warning(f"Skipping hedge order {position.ticket} from hedging.")
                    continue  # Hoppa över hedge-order

                position_info = f"Position {position.ticket} ({symbol}) - Profit: {position.profit:.2f}"

                # Hantera förlustgräns för varje position
                if position.profit <= loss_threshold:
                    # Kontrollera om vi har möjlighet att placera en hedge för denna symbol
                    max_allowed_hedges = original_orders_per_symbol[symbol]
                    current_hedges = hedge_orders_per_symbol[symbol]

                    if max_allowed_hedges > 0:
                        if current_hedges < max_allowed_hedges:
                            if position.ticket not in hedged_positions:
                                logger.info(f"Loss threshold reached for position {position.ticket}. Placing hedge.")
                                open_hedge_order(lot_size, position)
                                hedge_orders_per_symbol[symbol] += 1
                                logger.debug(f"Hedge orders for {symbol}: {hedge_orders_per_symbol[symbol]}")
                        else:
                            current_time = time.time()
                            cooldown_period = 60  # 60 sekunder
                            last_logged = hedge_warning_logged.get(symbol, 0)
                            if current_time - last_logged > cooldown_period:
                                logger.info(f"Cannot place hedge for {symbol}. Max hedge orders reached ({current_hedges}/{max_allowed_hedges}).")
                                await update_queue.put({'type': 'label', 'text': f"Cannot place hedge for {symbol}. Max hedge orders reached."})
                                hedge_warning_logged[symbol] = current_time
                    else:
                        logger.debug(f"No original orders for {symbol}. Skipping hedge placement.")

                # Uppdatera GUI med ny position och hedgestatus via kön
                await update_queue.put({'type': 'position_status', 'position': position})

        except Exception as e:
            await update_queue.put({'type': 'label', 'text': f"Error in equity monitoring: {e}"})  # Uppdatera GUI via kön
            logger.error(f"Error in equity monitoring: {e}")

        await asyncio.sleep(10)  # Vänta 10 sekunder innan nästa kontroll

def open_hedge_order(lot_size, position):
    """Lägger en hedge-order för en given position, men endast om det finns en originalorder i samma riktning som positionen."""
    symbol = position.symbol

    open_positions = mt5.positions_get(symbol=symbol)
    if open_positions is None:
        logger.error(f"Failed to fetch positions for {symbol}. Cannot determine hedge eligibility.")
        return

    # Istället för att leta efter motsatt riktning letar vi efter originalorder i samma riktning som den förlustposition vi hedgar.
    # Logik: Om positionen är BUY (förlust), hedge är SELL. Men vi vill försäkra oss om att det finns minst en original-BUY-order.
    # Om positionen är SELL (förlust), hedge är BUY. Då vill vi att det finns minst en original-SELL-order.

    original_needed = position.type  # Om position.type är BUY, behövs en BUY original. Om SELL, behövs en SELL original.

    has_required_original = False
    for pos in open_positions:
        if pos.ticket not in hedged_positions.values():
            # Detta är en originalorder
            if pos.type == original_needed:
                has_required_original = True
                break

    if not has_required_original:
        logger.info(f"Cannot place hedge order for {symbol}. No original order found in the same direction as the losing position.")
        return

    # Nu vet vi att det finns en originalorder i samma riktning, vilket betyder att denna hedge är logiskt giltig.

    symbol_info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if symbol_info is None or tick is None:
        logger.error(f"Failed to retrieve symbol info or tick data for {symbol}.")
        return

    # Bestäm hedge-typ (motsatt riktning mot positionen)
    hedge_type = mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
    hedge_price = tick.ask if hedge_type == mt5.ORDER_TYPE_BUY else tick.bid

    required_margin = mt5.order_calc_margin(hedge_type, symbol, lot_size, hedge_price)
    account_info = mt5.account_info()
    if account_info is None:
        logger.error("Failed to fetch account info.")
        return

    free_margin = account_info.margin_free
    logger.debug(f"Required Margin: {required_margin}, Free Margin: {free_margin}")
    if required_margin > free_margin:
        logger.error("Insufficient margin to place hedge order.")
        return

    # Lägg hedge-ordern
    hedge_order = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot_size,
        "type": hedge_type,
        "price": hedge_price,
        "deviation": 20,
        "magic": 0,
        "comment": "Hedge_order",
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    logger.debug(f"Placing hedge order: {hedge_order}")
    result = mt5.order_send(hedge_order)

    logger.debug(f"OrderSendResult: retcode={result.retcode}, deal={result.deal}, order={result.order}, volume={result.volume}, price={result.price}, comment='{result.comment}'")

    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logger.error(f"Failed to place hedge order for {symbol}. Retcode: {result.retcode}, Comment: {result.comment}")
    else:
        logger.info(f"Successfully placed hedge order for {symbol}. Hedge Ticket: {result.order}")
        hedged_positions[position.ticket] = result.order  # Registrera hedge-order
        hedge_orders_per_symbol[symbol] += 1
        logger.debug(f"Hedge orders for {symbol}: {hedge_orders_per_symbol[symbol]}")

