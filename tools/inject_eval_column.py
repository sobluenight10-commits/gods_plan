"""Insert EVAL column after GOD column in _matrix_v3_rows.html (one-shot)."""
from pathlib import Path

EVAL = {
    "000660.KS": ("A", "4/7 gates"),
    "TSM": ("A", "5/7 gates"),
    "PLTR": ("B", "P1+P2+P3"),
    "1810.HK": ("B", "P1+P2+P3"),
    "NVDA": ("A", "5/7 gates"),
    "Anthropic": ("B", "P1+P2+P3+P4"),
    "UEC": ("B", "P1+P2+P3"),
    "URNM": ("B", "P1+P2"),
    "CWEN": ("A", "3/7 gates"),
    "UUUU": ("A", "4/7 gates"),
    "CCJ": ("A", "5/7 gates"),
    "OKLO": ("B", "P1+P2+P3"),
    "PL": ("B", "P1+P2"),
    "RKLB": ("B", "P1+P2"),
    "ASTS": ("B", "P1+P2"),
    "xAI": ("B", "P1+P2+P3"),
    "TMO": ("A", "5/7 gates"),
    "BEAM": ("B", "P1+P2"),
    "NTLA": ("B", "P1+P2"),
    "CRSP": ("A", "2/7 gates"),
    "272210.KS": ("B", "P1+P2+P3"),
    "KTOS": ("A", "4/7 gates"),
    "ARKQ": ("B", "P1+P2"),
    "BOTZ": ("B", "P1+P2"),
    "Figure AI": ("B", "P1+P2+P3"),
    "ASML": ("A", "6/7 gates"),
    "VRT": ("A", "5/7 gates"),
    "COHR": ("A", "4/7 gates"),
    "AMAT": ("A", "5/7 gates"),
    "NTR": ("A", "4/7 gates"),
    "FCX": ("A", "3/7 gates"),
    "POSCO": ("A", "manual review"),
    "IAU": ("A", "tactical"),
    "MC.PA": ("A", "locked"),
}


def eval_td(track: str, gates: str) -> str:
    pill = "eval-track-a" if track == "A" else "eval-track-b"
    lab = track
    return (
        f'<td class="mx-eval"><span class="{pill}">{lab}</span>'
        f'<div class="eval-gates">{gates}</div></td>'
    )


def main():
    p = Path(__file__).resolve().parent / "_matrix_v3_rows.html"
    text = p.read_text(encoding="utf-8")
    text = text.replace('colspan="14"', 'colspan="15"')
    lines = text.splitlines()
    out = []
    for line in lines:
        if 'class="mx-row' not in line or "</tr>" not in line:
            out.append(line)
            continue
        key = None
        if 'data-ticker="' in line:
            import re

            m = re.search(r'data-ticker="([^"]*)"', line)
            tk = m.group(1) if m else ""
            if tk and tk in EVAL:
                key = tk
            elif tk == "" and "Anthropic" in line:
                key = "Anthropic"
            elif tk == "" and "Figure AI" in line:
                key = "Figure AI"
        if not key or key not in EVAL:
            out.append(line)
            continue
        tr, gates = EVAL[key]
        cell = eval_td(tr, gates)
        needle = "</span></div></td><td class=\"r mx-entry\">"
        if needle not in line:
            needle = "</span></div></td><td class=\"r mx-entry\">"
        if needle in line:
            line = line.replace(needle, "</span></div></td>" + cell + "<td class=\"r mx-entry\">", 1)
        out.append(line)
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("OK inject_eval", p)


if __name__ == "__main__":
    main()
