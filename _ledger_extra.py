import sys, os
sys.path.insert(0, "/root/gods_plan")
from thesis_ledger import add_decision, add_note

STRAT = ("Top-10 mega-cap dip-buy test: accumulate 1-2 shares every 2-3 days when "
         "price is -15% from ATH. AI capex phobia is dragging prices; thesis is these "
         "are earthmovers worth >=2x in 5y. Year-start buy / year-end trim-and-add test.")

for tk, name in [("AVGO","Broadcom"), ("GOOGL","Alphabet"), ("TSLA","Tesla"), ("NVDA","Nvidia")]:
    add_decision(tk, "ADD", 0, thesis=STRAT, horizon="5Y", conviction=7,
                 thesis_type="top10_dipbuy", feel="afraid", when="2026-06-26",
                 raw_note="Bleeding but not selling in panic. Earthmover conviction.")

add_decision("KTOS", "ADD", 57.97, thesis="Add to KTOS — contracts support thesis, Soros gap big.",
             horizon="1Y", conviction=7, target=89.5, thesis_type="defense", when="2026-04-22")

add_note("UEC", "[LEARN 2026-05-07] Treasury announced +$80B Q2 bond issuance = liquidity "
         "expansion (interim vote / war aftermath). OLYMPUS MISSED this signal. Wire Treasury "
         "QRA / issuance into the liquidity engine so the next expansion is caught early.")

add_note("AVAV", "[LEARN 2026-04-21] Bought on system signal, then sold -10% when system "
         "flagged 'thesis broken' (SCAR cancelled). Reality: SCAR was a fraction of backlog; "
         "stock kept spiking after fear-plunge. Lesson: verify the MAGNITUDE of a thesis break "
         "before acting — a cancelled minor contract is not a broken thesis.")

print("EXTRA_LEDGER_OK")
