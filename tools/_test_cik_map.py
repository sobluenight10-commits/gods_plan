"""Quick test for the CIK allow-list logic in price_alert.check_sec_filings."""
from price_alert import _build_cik_to_ticker_map

m = _build_cik_to_ticker_map(["PL", "PLTR", "TSM", "OKLO", "VRT", "COHR"])
print("CIK allow-list size:", len(m))
print("CIK 0001836833 (Planet Labs PBC) ->", m.get("0001836833"))
print("CIK 0000770460 (Peoples Financial) ->",
      m.get("0000770460", "BLOCKED (not in allow-list)"))
print("CIK 0001321655 (Palantir) ->", m.get("0001321655"))


def _simulate(title: str, cik_to_ticker: dict) -> str:
    import re
    for match in re.finditer(r"\((\d{6,10})\)", title):
        cik_pad = match.group(1).zfill(10)
        if cik_pad in cik_to_ticker:
            return cik_to_ticker[cik_pad]
    return "no_match"


print()
print("Simulated 8-K title parsing:")
for title in (
    "8-K - PEOPLES FINANCIAL CORP /MS/ (0000770460) (Filer)",
    "8-K - PLANET LABS PBC (0001836833) (Filer)",
    "8-K - PALANTIR TECHNOLOGIES INC (0001321655) (Filer)",
    "8-K - SOME RANDOM PLZ INC (0009999999) (Filer)",
):
    print(f"  {title!r:75s} -> {_simulate(title, m)}")
