from pathlib import Path

root = Path(__file__).resolve().parents[1]
html = (root / "OLYMPUS_UNIFIED.html").read_text(encoding="utf-8")
snippet = (root / "tools" / "_matrix_v3_rows.html").read_text(encoding="utf-8").strip()
needle = 'data-ticker="000660.KS"'
i = html.index(needle)
start = html.rfind("<tr", 0, i)
end = html.index("</tbody></table></div>", start)
out = html[:start] + snippet + "\n" + html[end:]
(root / "OLYMPUS_UNIFIED.html").write_text(out, encoding="utf-8")
print("OK splice", len(snippet))
