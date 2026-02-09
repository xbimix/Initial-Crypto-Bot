# import time

# MAX_HOLD_SECONDS = 2700  # 45 minutes

# def time_exit(position, now=None):
#     """
#     Time-based exit ONLY if trade is not profitable.
#     """
#     if "entry_time" not in position:
#         return False

#     now = now or time.time()
#     held = now - position["entry_time"]

#     # Only exit on time if still not profitable
#     if held > MAX_HOLD_SECONDS and position.get("unrealized_pnl", 0) <= 0:
#         return True

#     return False


import time

MAX_HOLD_SECONDS = 86500  # 24 HRs

def time_exit(trade):
    return time.time() - trade["entry_time"] > MAX_HOLD_SECONDS
