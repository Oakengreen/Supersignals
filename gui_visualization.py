# gui_visualization.py
import tkinter as tk
import logging
import queue  # Importera queue
from communication import update_queue, hedged_positions  # Importera hedged_positions

logger = logging.getLogger("GUI")

class GUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("MetaTrader 5 Position Monitoring")

        self.label = tk.Label(self.root, text="Waiting for data...", font=("Helvetica", 14))
        self.label.pack(pady=20)

        self.position_list_frame = tk.Frame(self.root)
        self.position_list_frame.pack(fill="both", expand=True)

        self.title_label = tk.Label(self.position_list_frame, text="Positioner och Hedge-status", font=("Helvetica", 12, "bold"))
        self.title_label.pack()

        self.position_widgets = {}

        # Starta uppdateringskön
        self.root.after(100, self.process_queue)

    def start(self):
        self.root.mainloop()

    def process_queue(self):
        try:
            while True:
                task = update_queue.get_nowait()
                if task['type'] == 'label':
                    self.label.config(text=task['text'])
                elif task['type'] == 'position_status':
                    self.update_position_status(task['position'])
        except queue.Empty:
            pass
        except Exception as e:
            logger.error(f"Error processing queue: {e}")
        # Schemalägg nästa kontroll
        self.root.after(100, self.process_queue)

    def update_position_status(self, position):
        """Uppdatera status för en position i GUI."""
        ticket = position.ticket
        is_hedge = ticket in hedged_positions.values()
        is_original = ticket not in hedged_positions

        # Bestäm om denna position har en hedge
        has_hedge = False
        hedge_ticket = None
        for orig_ticket, hedge_tkt in hedged_positions.items():
            if orig_ticket == ticket:
                has_hedge = True
                hedge_ticket = hedge_tkt
                break

        # Uppdatera eller lägg till positionens information
        position_info = f"{position.symbol} (Ticket {ticket}) - Profit: {position.profit:.2f}"
        position_type = "Hedge" if is_hedge else "Original"

        # Lagra information om ordertypen och hedge-status
        self.position_widgets[ticket] = {
            'position_info': position_info,
            'type': position_type,
            'has_hedge': has_hedge,
            'hedge_ticket': hedge_ticket
        }

        # Uppdatera UI med senaste status
        self.update_position_list_ui()

    def update_position_list_ui(self):
        """Uppdatera UI:t med alla positioner och checkboxar."""
        # Först rensa befintliga widgets, men behåll rubriket
        children = self.position_list_frame.winfo_children()
        if children:
            title_label = children[0]  # Förutsätter att första widgeten är rubriket
            for widget in children[1:]:
                widget.destroy()

        # Lägg till varje position som en rad med en checkbox
        for ticket, data in self.position_widgets.items():
            position_info = data["position_info"]
            order_type = data["type"]
            has_hedge = data["has_hedge"]
            hedge_ticket = data["hedge_ticket"]

            # Skapa en etikett med information om ordertypen och hedge-statusen
            if order_type == "Original":
                hedge_status = "Hedged" if has_hedge else "Not Hedged"
            else:
                hedge_status = f"Hedge for Ticket {hedge_ticket}"

            display_text = f"{position_info} | Type: {order_type} | Status: {hedge_status}"

            # Skapa en Checkbutton som visar hedge-statusen
            var = tk.BooleanVar(value=has_hedge)
            checkbox = tk.Checkbutton(self.position_list_frame, text=display_text, state=tk.DISABLED, variable=var)
            checkbox.pack(anchor="w", padx=10)

    def update_label(self, text):
        self.label.config(text=text)

def start_gui():
    gui = GUI()
    gui.start()
