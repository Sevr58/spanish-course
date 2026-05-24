"""
Генератор Anki-колод (.apkg) для курса испанского.

Парсит каждый урок lessons/LXX.html и извлекает ВСЕ испанские фразы:
- ANKI_DECK_LXX из JavaScript (основные карточки с переводом и примером)
- vocab-table (полный словарь урока)
- phrase-list (фразы из раздела "Испания на практике")
- speak-box (примеры из говорения)
- sound-card .se .w (примеры произношения)

Для каждой испанской фразы:
- Генерирует mp3 через Edge TTS (голос es-ES-ElviraNeural, бесплатно)
- Дедуплицирует
- Упаковывает всё в LXX.apkg

Использование:
    python generate_anki.py            # обработать все уроки
    python generate_anki.py L01 L02    # обработать конкретные

Результат: anki_decks/LXX.apkg — открыть в Anki Desktop одним кликом.
"""

import asyncio
import hashlib
import os
import re
import sys
from pathlib import Path

# Force UTF-8 output on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import edge_tts
import genanki
from bs4 import BeautifulSoup

# Paths
ROOT = Path(__file__).parent
LESSONS_DIR = ROOT / "lessons"
OUTPUT_DIR = ROOT / "anki_decks"
AUDIO_DIR = ROOT / "anki_audio"

OUTPUT_DIR.mkdir(exist_ok=True)
AUDIO_DIR.mkdir(exist_ok=True)

# Edge TTS voice (best free Spanish - Spain accent, female, neural)
VOICE = "es-ES-ElviraNeural"
# Alternative: "es-ES-AlvaroNeural" (male)


def audio_filename(text: str) -> str:
    """Stable filename based on text hash."""
    digest = hashlib.md5(text.encode("utf-8")).hexdigest()[:12]
    safe = re.sub(r"[^a-z0-9]+", "_", text.lower())[:40].strip("_")
    return f"es_{safe}_{digest}.mp3"


async def synthesize_audio(text: str, output_path: Path) -> None:
    """Generate mp3 from Spanish text using Edge TTS."""
    if output_path.exists():
        return
    communicate = edge_tts.Communicate(text, VOICE, rate="-5%")
    await communicate.save(str(output_path))


def extract_anki_deck(html: str):
    """Extract ANKI_DECK_LXX array from JavaScript."""
    pattern = r"const\s+ANKI_DECK(?:_L\d+)?\s*=\s*\[(.*?)\];"
    match = re.search(pattern, html, re.DOTALL)
    if not match:
        return []
    deck_text = match.group(1)
    cards = []
    # Match {front: "...", back: "..."} pairs (handles both double and single quotes)
    card_pattern = r'\{\s*front\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*back\s*:\s*"((?:[^"\\]|\\.)*)"\s*\}'
    for m in re.finditer(card_pattern, deck_text):
        front = m.group(1).encode().decode("unicode_escape")
        back = m.group(2).encode().decode("unicode_escape")
        cards.append({"front": front.strip(), "back": back.strip()})
    return cards


def extract_vocab_table(soup):
    """Extract from <table class="vocab-table">.
    Returns list of (spanish, translation) where translation is best guess."""
    pairs = []
    for table in soup.find_all("table", class_="vocab-table"):
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if not tds:
                continue
            # Find Spanish cell (.es)
            es_cell = None
            for td in tds:
                if "es" in (td.get("class") or []):
                    es_cell = td
                    break
            if not es_cell:
                continue
            spanish = es_cell.get_text(" ", strip=True)
            # Remove emoji-only cells and clean up
            spanish = re.sub(r"🔊", "", spanish).strip()
            if not spanish or len(spanish) > 120:
                continue
            # Translation is usually the last cell (not .es, not .tr)
            translation = ""
            for td in tds:
                cls = td.get("class") or []
                if "es" in cls or "tr" in cls:
                    continue
                txt = td.get_text(" ", strip=True)
                if txt and not re.match(r"^[\[\(].*[\)\]]$", txt) and "🔊" not in txt:
                    translation = txt
            # Also check .tr cell for transcription/translation
            if not translation:
                for td in tds:
                    if "tr" in (td.get("class") or []):
                        translation = td.get_text(" ", strip=True)
                        break
            pairs.append((spanish, translation))
    return pairs


def extract_phrase_list(soup):
    """Extract from .phrase divs (Испания на практике)."""
    pairs = []
    for phrase in soup.select(".phrase"):
        es = phrase.select_one(".es")
        tr = phrase.select_one(".tr")
        if es:
            spanish = es.get_text(" ", strip=True)
            translation = tr.get_text(" ", strip=True) if tr else ""
            if spanish and 2 < len(spanish) < 200:
                pairs.append((spanish, translation))
    return pairs


def extract_sound_cards(soup):
    """Extract from <div class="se"> sound examples."""
    pairs = []
    for se in soup.select(".se"):
        w = se.select_one(".w")
        tr = se.select_one(".tr")
        if w:
            spanish = w.get_text(" ", strip=True)
            translation = tr.get_text(" ", strip=True) if tr else ""
            if spanish:
                pairs.append((spanish, translation))
    return pairs


def extract_speak_boxes(soup):
    """Extract example phrases from .speak-box .es."""
    phrases = []
    for box in soup.select(".speak-box"):
        es_div = box.select_one(".es")
        hint = box.select_one(".hint")
        if es_div:
            spanish = es_div.get_text(" ", strip=True)
            # Remove brackets content (transcription)
            spanish = re.sub(r"\[.*?\]", "", spanish).strip()
            spanish = re.sub(r"\s+", " ", spanish)
            if spanish and 3 < len(spanish) < 200:
                trans = ""
                if hint:
                    hint_text = hint.get_text(" ", strip=True)
                    m = re.search(r"\[(.+?)\]", hint_text)
                    if m:
                        trans = m.group(1)
                phrases.append((spanish, trans))
    return phrases


def deduplicate(pairs):
    """Keep first occurrence by normalized Spanish."""
    seen = set()
    result = []
    for sp, tr in pairs:
        key = re.sub(r"[¿¡!?.,;:]", "", sp.lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append((sp, tr))
    return result


def merge_cards(anki_deck, extra_pairs):
    """Combine ANKI_DECK cards with extra vocab into one list."""
    cards = []
    seen = set()
    for c in anki_deck:
        key = re.sub(r"[¿¡!?.,;:]", "", c["front"].lower()).strip()
        if key not in seen:
            seen.add(key)
            cards.append(
                {
                    "front": c["front"],
                    "back": c["back"],
                    "is_full_card": True,
                }
            )
    for sp, tr in extra_pairs:
        key = re.sub(r"[¿¡!?.,;:]", "", sp.lower()).strip()
        if key in seen or not key:
            continue
        seen.add(key)
        if not tr:
            tr = "(см. урок)"
        cards.append(
            {
                "front": sp,
                "back": tr,
                "is_full_card": False,
            }
        )
    return cards


def parse_lesson(html_path: Path):
    """Return list of card dicts {front, back, is_full_card}."""
    html = html_path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")

    anki_deck = extract_anki_deck(html)
    vocab = extract_vocab_table(soup)
    phrases = extract_phrase_list(soup)
    sounds = extract_sound_cards(soup)
    speaks = extract_speak_boxes(soup)

    extra = deduplicate(vocab + phrases + sounds + speaks)
    return merge_cards(anki_deck, extra)


# Genanki model definition
SPANISH_MODEL = genanki.Model(
    1607393001,
    "Spanish Course Card",
    fields=[
        {"name": "Front"},
        {"name": "Back"},
        {"name": "Audio"},
    ],
    templates=[
        {
            "name": "ES -> RU",
            "qfmt": """
<div style="font-size:28px; font-weight:600; text-align:center; color:#1d2734;">{{Front}}</div>
<div style="text-align:center; margin-top:12px;">{{Audio}}</div>
""",
            "afmt": """
{{FrontSide}}
<hr id="answer">
<div style="font-size:16px; line-height:1.6; color:#333; max-width:500px; margin:0 auto;">{{Back}}</div>
""",
        }
    ],
    css="""
.card { font-family: 'Segoe UI', system-ui, sans-serif; background: #f5f5f5; padding: 20px; }
""",
)


async def process_lesson(html_path: Path):
    """Build .apkg for one lesson."""
    lesson_id = html_path.stem  # L01, L02, ...
    cards = parse_lesson(html_path)
    if not cards:
        print(f"  ⚠ {lesson_id}: no cards extracted, skipping")
        return

    # Stable deck ID derived from lesson_id
    deck_id = 1_000_000_000 + int(hashlib.md5(lesson_id.encode()).hexdigest()[:8], 16) % 100_000_000

    deck = genanki.Deck(deck_id, f"{lesson_id} Spanish")
    media_files = []

    print(f"  📥 {lesson_id}: {len(cards)} cards, generating audio…")

    # Generate audio for all Spanish phrases in parallel
    audio_tasks = []
    for card in cards:
        # Clean the front text for TTS (remove slashes, parens)
        tts_text = re.sub(r"\s*/\s*.+$", "", card["front"])  # "tú / vosotros" -> "tú"
        tts_text = re.sub(r"\(.*?\)", "", tts_text).strip()
        if not tts_text:
            tts_text = card["front"]
        fname = audio_filename(tts_text)
        fpath = AUDIO_DIR / fname
        card["audio_file"] = fname
        card["audio_path"] = fpath
        card["tts_text"] = tts_text
        if not fpath.exists():
            audio_tasks.append(synthesize_audio(tts_text, fpath))

    # Process audio in batches of 8 to avoid rate limits
    BATCH_SIZE = 8
    for i in range(0, len(audio_tasks), BATCH_SIZE):
        batch = audio_tasks[i : i + BATCH_SIZE]
        try:
            await asyncio.gather(*batch, return_exceptions=True)
        except Exception as e:
            print(f"     ⚠ audio batch error: {e}")

    # Build notes
    for card in cards:
        back_html = card["back"].replace("\n", "<br>")
        # Add audio reference
        audio_tag = f"[sound:{card['audio_file']}]"
        note = genanki.Note(
            model=SPANISH_MODEL,
            fields=[card["front"], back_html, audio_tag],
        )
        deck.add_note(note)
        if card["audio_path"].exists():
            media_files.append(str(card["audio_path"]))

    # Write .apkg
    package = genanki.Package(deck)
    package.media_files = media_files
    output_path = OUTPUT_DIR / f"{lesson_id}.apkg"
    package.write_to_file(str(output_path))
    print(f"  ✅ {lesson_id}: saved {output_path.name} ({len(cards)} cards, {len(media_files)} audio)")


async def main():
    if len(sys.argv) > 1:
        targets = [LESSONS_DIR / f"{arg}.html" for arg in sys.argv[1:]]
    else:
        targets = sorted(LESSONS_DIR.glob("L*.html"))

    print(f"🎴 Generating Anki decks for {len(targets)} lessons")
    print(f"   Output: {OUTPUT_DIR}")
    print(f"   Audio:  {AUDIO_DIR}")
    print(f"   Voice:  {VOICE}")
    print()

    for path in targets:
        if not path.exists():
            print(f"  ⚠ {path.name}: not found")
            continue
        try:
            await process_lesson(path)
        except Exception as e:
            print(f"  ❌ {path.stem}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n✅ Done. Decks in {OUTPUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
