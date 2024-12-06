import tkinter as tk
from tkinter import ttk
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import MetaTrader5 as mt5

# Anta att hedged_positions, etc. är importerade eller tillgängliga
# from communication import hedged_positions
# from channel_4 import hedged_positions, original_orders_per_symbol, hedge_orders_per_symbol
# Justera efter din kodstruktur

# Denna funktion hämtar aktuell data för alla symboler, beräknar P/L för original och hedge
def get_symbol_pl_data():
    open_positions = mt5.positions_get()
    if open_positions is None:
        return {}, {}  # Inga data om något gick fel

    symbol_data_original = {}
    symbol_data_hedge = {}

    # Nollställ data
    # Vi använder dictionaries: {symbol: sum_of_profits}
    # För varje symbol börjar vi på 0
    # Men vi lägger bara till symboler som faktiskt har positioner

    for pos in open_positions:
        symbol = pos.symbol
        # Kolla om hedge eller original
        if pos.ticket in hedged_positions.values():
            # Hedgeorder
            if symbol not in symbol_data_hedge:
                symbol_data_hedge[symbol] = 0.0
            symbol_data_hedge[symbol] += pos.profit
        else:
            # Originalorder
            if symbol not in symbol_data_original:
                symbol_data_original[symbol] = 0.0
            symbol_data_original[symbol] += pos.profit

    # Se till att om en symbol finns i original men inte hedge (eller tvärtom) sätter vi 0 för den andra
    all_symbols = set(symbol_data_original.keys()).union(set(symbol_data_hedge.keys()))
    for sym in all_symbols:
        if sym not in symbol_data_original:
            symbol_data_original[sym] = 0.0
        if sym not in symbol_data_hedge:
            symbol_data_hedge[sym] = 0.0

    return symbol_data_original, symbol_data_hedge


class EquityChartGUI:
    def __init__(self, master):
        self.master = master
        self.master.title("Symbol Equity Visualization")

        # Skapa en matplotlib figure och axes
        self.fig = Figure(figsize=(8,5), dpi=100)
        self.ax = self.fig.add_subplot(111)

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.master)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # Lägg till en knapp för manuella uppdateringar (om du vill)
        update_button = ttk.Button(self.master, text="Uppdatera", command=self.update_equity_chart)
        update_button.pack(pady=5)

        # Uppdatera diagrammet en gång direkt
        self.update_equity_chart()

        # Om du vill ha automatisk uppdatering, t.ex. var 10:e sekund:
        # self.master.after(10000, self.update_equity_chart)

    def update_equity_chart(self):
        # Hämta data
        symbol_data_original, symbol_data_hedge = get_symbol_pl_data()

        # Rensa axel
        self.ax.clear()

        # Om det inte finns några symboler, visa ett meddelande
        if len(symbol_data_original) == 0 and len(symbol_data_hedge) == 0:
            self.ax.text(0.5, 0.5, "No positions", ha='center', va='center', fontsize=12)
            self.canvas.draw()
            return

        # Konvertera dict till listor för plotting
        symbols = sorted(symbol_data_original.keys())
        original_values = [symbol_data_original[sym] for sym in symbols]
        hedge_values = [symbol_data_hedge[sym] for sym in symbols]

        # Antag att vi vill ha en grouped bar chart med två staplar per symbol
        x = range(len(symbols))  # x-lägen för symbolerna
        width = 0.4
        # Originalbar på x, hedgebar på x+width
        # För att centrera staplar, t.ex. x kan vara en numpy array och du kan shift

        import numpy as np
        x = np.arange(len(symbols))
        self.ax.bar(x - width/2, original_values, width, label='Original Orders P/L', color='blue')
        self.ax.bar(x + width/2, hedge_values, width, label='Hedge Orders P/L', color='orange')

        # Sätt xticks
        self.ax.set_xticks(x)
        self.ax.set_xticklabels(symbols, rotation=45, ha='right')

        self.ax.set_ylabel("Profit/Loss")
        self.ax.set_title("Original vs Hedge Equity per Symbol")
        self.ax.legend()

        self.fig.tight_layout()
        self.canvas.draw()


def start_gui():
    root = tk.Tk()
    gui = EquityChartGUI(root)
    root.mainloop()


# Om du vill testa lokalt kan du köra:
# if __name__ == "__main__":
#     mt5.initialize()
#     start_gui()
