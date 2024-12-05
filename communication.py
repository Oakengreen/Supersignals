# communication.py
import asyncio
from collections import defaultdict

# Skapa en global kö för asynkron kommunikation
update_queue = asyncio.Queue()

# Skapa en global dictionary för hedged positions
# Struktur: { original_ticket: hedge_ticket }
hedged_positions = {}

# Skapa en global dictionary för att spåra antalet originalorder per symbol
original_orders_per_symbol = defaultdict(int)

# Skapa en global dictionary för att spåra antalet hedge-order per symbol
hedge_orders_per_symbol = defaultdict(int)
