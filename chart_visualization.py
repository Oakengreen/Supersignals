import logging
import matplotlib.pyplot as plt
import pandas as pd
import MetaTrader5 as mt5
import os

# Skapa en logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
ch = logging.StreamHandler()  # Skickar loggar till konsolen
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
logger.addHandler(ch)

def plot_candlestick_chart(final_values):
    """Skapa en graf för att visualisera de senaste candlarna och prisnivåer."""
    symbol = final_values["symbol"]
    sl = final_values["sl"]
    tp = final_values["tp"]
    current_price = final_values["current_price"]
    spread = final_values["spread"]
    action = final_values["action"]

    # Hämta OHLC-data (de senaste 5 candlarna)
    rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 5)
    if rates is None or len(rates) < 5:
        raise ValueError(f"Not enough data to create chart for {symbol}.")

    # Omvandla till DataFrame för enklare hantering och loggning
    ohlc_data = pd.DataFrame(rates, columns=['time', 'open', 'high', 'low', 'close', 'volume'])

    # Konvertera timestamp till datetime för läsbarhet
    ohlc_data['time'] = pd.to_datetime(ohlc_data['time'], unit='s')

    # Skapa graf
    fig, ax = plt.subplots(figsize=(10, 6))

    # Rita candlestick-graf med justerat bredd
    for i, row in ohlc_data.iterrows():
        color = 'green' if row['close'] >= row['open'] else 'red'

        # Wick (linjer)
        ax.plot([row['time'], row['time']], [row['low'], row['high']], color='black')  # Wick

        # Body (rektangel)
        rect_x_start = row['time'] - pd.Timedelta(minutes=0.3)  # Starttid för kroppen
        rect_x_end = row['time'] + pd.Timedelta(minutes=0.3)  # Sluttid för kroppen
        rect_x = [rect_x_start, rect_x_start, rect_x_end, rect_x_end, rect_x_start]
        rect_y = [row['open'], row['close'], row['close'], row['open'], row['open']]
        ax.fill(rect_x, rect_y, color=color)

    # Rita SL, TP och nuvarande pris
    ax.axhline(sl, color='red', linestyle='--', label=f'Stop Loss (SL): {sl:.4f}')
    ax.axhline(tp, color='blue', linestyle='--', label=f'Take Profit (TP): {tp:.4f}')
    ax.axhline(current_price, color='black', linestyle='-', label=f'Current Price: {current_price:.4f}')

    # Lägg till text för SL och TP
    ax.text(ohlc_data['time'].iloc[-1], sl, f"SL: {sl:.4f}", color='red', fontsize=10, ha='right')
    ax.text(ohlc_data['time'].iloc[-1], tp, f"TP: {tp:.4f}", color='blue', fontsize=10, ha='right')
    ax.text(ohlc_data['time'].iloc[-1], current_price, f"Current Price: {current_price:.4f}", color='black',
            fontsize=10, ha='right')

    # Lägg till text om vi använder fasta eller beräknade SL/TP
    ax.text(ohlc_data['time'].iloc[-1], sl, "Calculated SL/TP", color='black', fontsize=10, ha='right')

    # Anpassa axlar och etiketter
    ax.set_title(f"{symbol} - {action} Signal")
    ax.set_xlabel("Time")
    ax.set_ylabel("Price")
    plt.xticks(rotation=45)
    plt.tight_layout()
    ax.legend()

    # Spara grafen som bild och skriv över varje gång
    file_path = "latest_chart.png"
    plt.savefig(file_path)
    plt.close()

    # Öppna bilden direkt (Windows använder 'start')
    os.system(f"start {file_path}")  # För Windows
    # För macOS använd: os.system(f"open {file_path}")
    # För Linux: os.system(f"xdg-open {file_path}")

    return file_path
