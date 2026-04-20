"""
Self-test: simulate the Apr 16 quantum-communication post and ensure the
upgraded pre-alert returns concrete US pure-play tickers instead of NONE.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from blog_monitor import classify_blog_theme, THEME_PUREPLAY_MAP

CASES = [
    {
        "name": "Quantum communication (Korean)",
        "title": "양자컴퓨터가 아니라 양자암호통신? A/S (feat 엔트로픽 미토스)",
        "content": "양자암호통신과 양자통신의 발전. 중국과 미국의 quantum communication 경쟁.",
        "expected_any": {"IONQ", "ARQQ", "LAES", "QUBT"},
    },
    {
        "name": "Fusion",
        "title": "핵융합 원전 시대",
        "content": "핵융합 발전 상용화 가능성.",
        "expected_any": {"BWXT", "FLUX", "GEV"},
    },
    {
        "name": "CRISPR",
        "title": "유전자 치료 혁신",
        "content": "CRISPR 기반 유전자 편집 치료제.",
        "expected_any": {"CRSP", "NTLA", "BEAM", "EDIT"},
    },
]


def run() -> int:
    failed = 0
    for c in CASES:
        bt = classify_blog_theme(c["content"] + "\n" + c["title"], [])
        pp = set(bt.get("theme_pureplay", []))
        ok = bool(pp & c["expected_any"])
        print(
            f"[{'OK' if ok else 'FAIL'}] {c['name']:30s} themes={bt.get('themes')} "
            f"pureplay={list(pp)[:6]}"
        )
        if not ok:
            failed += 1
    print("---")
    print(
        f"Themes registered: {len(THEME_PUREPLAY_MAP)} | "
        f"pure-play universe: {sum(len(v) for v in THEME_PUREPLAY_MAP.values())}"
    )
    return failed


if __name__ == "__main__":
    raise SystemExit(run())
