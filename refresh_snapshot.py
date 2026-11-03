"""Saves the screener data the app falls back on when Yahoo blocks it. Run with: python refresh_snapshot.py"""

import sys

from data import MIN_LIVE_ROWS, SNAPSHOT_PATH, UNIVERSE, load_data, save_snapshot

df = load_data(UNIVERSE)
if len(df) < MIN_LIVE_ROWS:
    sys.exit(f"Only {len(df)} rows came back, so the saved snapshot was left as is. Try again later.")
save_snapshot(df)
print(f"Saved {len(df)} companies to {SNAPSHOT_PATH}. Commit it to update the app.")
