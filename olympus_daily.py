"""olympus_daily.py — single entry point for OLYMPUS pipeline"""
import sys, os
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from fetch_data import get_all_data
from olympus_engine import run_engine
from output_factory import generate_outputs


def main():
    print("=== OLYMPUS DAILY PIPELINE ===")
    data = get_all_data()
    print(f"Data: {len(data['prices'])} prices, {len(data['universe'])} universe")
    state = run_engine(data)
    print(f"Engine: ONE COMMAND = {state['one_command'][:60]}")
    generate_outputs(state)
    print("=== DONE ===")


if __name__ == "__main__":
    main()
