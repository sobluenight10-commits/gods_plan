"""
Refresh Olympus Dashboard — run the full update and write OLYMPUS_LIVE.html.
Use this when the dashboard shows old data (e.g. laptop was off and 06:45 didn't run).

  python refresh_olympus.py          # Update HTML only
  python refresh_olympus.py --send   # Update + send summary to Telegram
"""
import os
import sys
from pathlib import Path

os.chdir(Path(__file__).resolve().parent)

def main():
    send_telegram = "--send" in sys.argv
    try:
        from olympus_engine import run_olympus_update, get_olympus_telegram_summary
        print("Running Olympus update (~60s)...")
        result = run_olympus_update()
        print(f"Dashboard written: data/OLYMPUS_LIVE.html")

        import shutil
        live = Path("data/OLYMPUS_LIVE.html")
        deploy = Path("OLYMPUS_UNIFIED.html")
        if live.exists():
            shutil.copy2(live, deploy)
            print(f"Copied to {deploy} (ready for git push)")

        if send_telegram:
            from telegram_bot import send_telegram
            msg = get_olympus_telegram_summary(result)
            send_telegram(msg)
            print("Telegram summary sent.")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
