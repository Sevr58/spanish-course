"""
Встраивает в каждый урок блок с прямыми ссылками на:
  - Language Transfer (нужные эпизоды на YouTube)
  - Dreaming Spanish (плейлист нужного уровня)
  - Polyglot (если у урока есть привязка)

Блок вставляется в раздел Anki + Домашнее задание, перед списком ДЗ.

Запуск:  python embed_videos.py
"""

import re
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent
LESSONS_DIR = ROOT / "lessons"
DATA_JS = ROOT / "data.js"


def parse_meta_from_data_js():
    """Read data.js and extract {lesson_id: {lt: [...], ds: '...', polyglot: ...}}"""
    text = DATA_JS.read_text(encoding="utf-8")
    meta = {}
    # Match each lesson object: { id:"LXX", ..., lt_episodes:[...], ds_level:"...", polyglot:..., ... }
    lesson_blocks = re.finditer(r'\{[^{}]*?id:"(L\d+)"[^{}]*?\}', text, re.DOTALL)
    for block in lesson_blocks:
        content = block.group(0)
        lid = block.group(1)
        m_lt = re.search(r"lt_episodes:\s*\[([^\]]*)\]", content)
        m_ds = re.search(r'ds_level:"([^"]+)"', content)
        m_pg = re.search(r"polyglot:\s*([\d\"\+]+|null)", content)
        eps = []
        if m_lt:
            for x in re.findall(r"\d+", m_lt.group(1)):
                eps.append(int(x))
        ds = m_ds.group(1) if m_ds else "super_beginner"
        polyglot = None
        if m_pg and m_pg.group(1) not in ("null", "None"):
            v = m_pg.group(1).strip('"')
            polyglot = v
        meta[lid] = {"lt": eps, "ds": ds, "polyglot": polyglot}
    return meta


DS_LABEL = {
    "super_beginner": "Super Beginner",
    "beginner": "Beginner",
    "intermediate": "Intermediate",
    "intermediate+": "Intermediate",
    "advanced": "Advanced",
}


def build_video_block(meta):
    """Return HTML for the video/audio sources block."""
    eps = meta.get("lt", [])
    ds = meta.get("ds", "super_beginner")
    polyglot = meta.get("polyglot")
    ds_label = DS_LABEL.get(ds, ds.replace("_", " ").title())

    lt_html = ""
    if eps:
        for ep in eps:
            lt_html += (
                f'<a href="https://www.youtube.com/@LanguageTransfer/search?query=spanish%20{ep}" '
                f'target="_blank" rel="noopener" '
                f'style="display:flex;align-items:center;gap:10px;padding:12px 14px;background:var(--bg3);'
                f"color:var(--gold);text-decoration:none;border-radius:8px;margin:6px 0;"
                f'font-weight:600;border:1px solid rgba(255,214,10,.3);">'
                f'<span style="font-size:1.3rem;">🎧</span>'
                f'<span>Language Transfer — Spanish, эпизод {ep}</span>'
                f'<span style="margin-left:auto;font-size:.8rem;opacity:.6;">YouTube ↗</span>'
                f"</a>"
            )

    ds_html = (
        f'<a href="https://www.youtube.com/@DreamingSpanish/playlists" '
        f'target="_blank" rel="noopener" '
        f'style="display:flex;align-items:center;gap:10px;padding:12px 14px;background:var(--bg3);'
        f"color:var(--blue);text-decoration:none;border-radius:8px;margin:6px 0;"
        f'font-weight:600;border:1px solid rgba(69,123,157,.3);">'
        f'<span style="font-size:1.3rem;">📺</span>'
        f'<span>Dreaming Spanish — плейлист {ds_label} (15 мин)</span>'
        f'<span style="margin-left:auto;font-size:.8rem;opacity:.6;">YouTube ↗</span>'
        f"</a>"
    )

    polyglot_html = ""
    if polyglot:
        pg = polyglot.replace("+", " + урок #")
        polyglot_html = (
            f'<a href="../../lessons/lesson_{pg.split(" + ")[0].zfill(2)}.html" target="_blank" '
            f'style="display:flex;align-items:center;gap:10px;padding:12px 14px;background:var(--bg3);'
            f"color:#9d4edd;text-decoration:none;border-radius:8px;margin:6px 0;"
            f'font-weight:600;border:1px solid rgba(157,78,221,.3);">'
            f'<span style="font-size:1.3rem;">📚</span>'
            f'<span>Polyglot Spanish — урок #{pg}</span>'
            f'<span style="margin-left:auto;font-size:.8rem;opacity:.6;">Локально ↗</span>'
            f"</a>"
        )

    block = (
        f'<div class="video-block" style="background:linear-gradient(135deg,rgba(69,123,157,.06),'
        f"rgba(157,78,221,.04));border:1px solid var(--border);border-radius:var(--r);"
        f'padding:16px 18px;margin:16px 0;">'
        f'<h4 style="font-size:.95rem;font-weight:700;margin-bottom:10px;color:var(--text);">'
        f"🎬 Слушай и смотри сегодня</h4>"
        f"{lt_html}{ds_html}{polyglot_html}"
        f"</div>"
    )
    return block


VIDEO_BLOCK_MARKER = '<div class="video-block"'


def inject_videos(html: str, video_block: str) -> str:
    """Insert video block before homework callout, removing any existing block."""
    # Remove existing video block if any (idempotent)
    html = re.sub(
        r'<div class="video-block".*?</div>\s*</div>',
        "",
        html,
        count=1,
        flags=re.DOTALL,
    )
    # Find homework callout (anchor: '<h4>📅' inside callout.info)
    # Match the callout wrapping the homework h4
    pattern = re.compile(
        r'(<div class="callout info"[^>]*>\s*<h4>📅)',
        re.DOTALL,
    )
    m = pattern.search(html)
    if not m:
        # Alternative: "До LXX" without 📅
        pattern2 = re.compile(r'(<div class="callout info"[^>]*>\s*<h4>До\s+L\d+)', re.DOTALL)
        m = pattern2.search(html)
    if not m:
        # Fallback: insert before any callout containing "Anki" or "Домашнее" or "Homework"
        pattern3 = re.compile(
            r'(<div class="callout[^"]*"[^>]*>\s*<h4>[^<]*(?:Домашнее|Homework|hasta L|Anki|Tarea))',
            re.DOTALL,
        )
        m = pattern3.search(html)
    if not m:
        # Last resort: insert before the .anki block (Anki section)
        pattern4 = re.compile(r'(<div class="anki">)', re.DOTALL)
        m = pattern4.search(html)
    if not m:
        return html  # no homework section found, skip

    insert_pos = m.start()
    return html[:insert_pos] + video_block + "\n" + html[insert_pos:]


def main():
    meta = parse_meta_from_data_js()
    print(f"Parsed {len(meta)} lessons from data.js")
    print()

    updated = 0
    skipped = 0
    for html_path in sorted(LESSONS_DIR.glob("L*.html")):
        lid = html_path.stem
        m = meta.get(lid)
        if not m:
            print(f"  - {lid}: no meta in data.js, skipping")
            skipped += 1
            continue

        html = html_path.read_text(encoding="utf-8", errors="ignore")
        video_block = build_video_block(m)
        new_html = inject_videos(html, video_block)

        if new_html != html:
            html_path.write_text(new_html, encoding="utf-8")
            print(f"  + {lid}: video block injected (LT={m['lt']}, DS={m['ds']})")
            updated += 1
        else:
            print(f"  ? {lid}: no homework section found")
            skipped += 1

    print(f"\nDone. Updated: {updated}, skipped: {skipped}")


if __name__ == "__main__":
    main()
