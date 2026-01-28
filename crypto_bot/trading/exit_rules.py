import time

MAX_HOLD_SECONDS = 2700  # 45 minutes

def time_exit(trade):
    return time.time() - trade["entry_time"] > MAX_HOLD_SECONDS
