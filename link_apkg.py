"""
Заменяет в каждом уроке JS-кнопку «Скачать .txt» на прямую ссылку
на готовый .apkg в anki_decks/.

Все 4 формата кнопок поддерживаются:
  <button ... onclick="exportAnkiL01()">📥 ...</button>
  <button ... onclick="exportAnki()">📥 ...</button>
  <button ... onclick="exportAnkiL01">...</button>
"""

import re
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
LESSONS_DIR = ROOT / "lessons"
DECKS_DIR = ROOT / "anki_decks"


def replace_button(html: str, lesson_id: str) -> tuple[str, bool]:
    """Return (new_html, changed)."""
    apkg_path = DECKS_DIR / f"{lesson_id}.apkg"
    if not apkg_path.exists():
        return html, False

    link_html = (
        f'<a href="../anki_decks/{lesson_id}.apkg" download '
        f'class="anki-export-btn" '
        f'style="display:inline-flex;align-items:center;gap:6px;text-decoration:none;">'
        f'📥 Скачать колоду {lesson_id}.apkg (с произношением)</a>'
    )

    # Pattern: <button ... onclick="exportAnki...">...</button>
    pattern = re.compile(
        r'<button[^>]*?onclick="exportAnki[^"]*?"[^>]*?>[^<]*</button>',
        re.IGNORECASE | re.DOTALL,
    )
    new_html, n = pattern.subn(link_html, html)
    return new_html, n > 0


def main():
    updated = 0
    skipped = 0
    no_deck = 0
    for html_path in sorted(LESSONS_DIR.glob("L*.html")):
        lid = html_path.stem
        html = html_path.read_text(encoding="utf-8", errors="ignore")
        new_html, changed = replace_button(html, lid)
        if not (DECKS_DIR / f"{lid}.apkg").exists():
            no_deck += 1
            continue
        if changed:
            html_path.write_text(new_html, encoding="utf-8")
            print(f"  + {lid}: button replaced")
            updated += 1
        else:
            skipped += 1
    print(f"\nUpdated: {updated}, skipped (no button match): {skipped}, no apkg: {no_deck}")


if __name__ == "__main__":
    main()
