# communication.py
import queue
from collections import defaultdict

# Skapa en global kö för trådkommunikation
update_queue = queue.Queue()

# Skapa en global dictionary för hedged positions
# Struktur: { original_ticket: hedge_ticket }
hedged_positions = {}

# Skapa en global dictionary för att spåra antalet originalorder per symbol
original_orders_per_symbol = defaultdict(int)

# Skapa en global dictionary för att spåra antalet hedge-order per symbol
hedge_orders_per_symbol = defaultdict(int)
