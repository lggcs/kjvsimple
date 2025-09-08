#!/usr/bin/env python3
import sys
import re
import curses
import textwrap
import re
import json
import os
import sys
import time
from collections import defaultdict, OrderedDict

CP_BORDER = 1
CP_TITLE = 2
CP_FOCUS = 3
CP_DIM = 4
CP_HL = 5
CP_CURSOR = 6

ALLOWED_COLORS = [
    ("Yellow", curses.COLOR_YELLOW),
    ("Cyan", curses.COLOR_CYAN),
    ("Green", curses.COLOR_GREEN),
    ("Magenta", curses.COLOR_MAGENTA),
    ("Red", curses.COLOR_RED),
    ("Blue", curses.COLOR_BLUE),
    ("White", curses.COLOR_WHITE),
]

FAV_FILE = os.path.expanduser(".kjv_favorites.json")

def init_colors():
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(CP_BORDER, curses.COLOR_CYAN, -1)
    curses.init_pair(CP_TITLE, curses.COLOR_YELLOW, -1)
    curses.init_pair(CP_FOCUS, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(CP_DIM, curses.COLOR_BLUE, -1)
    curses.init_pair(CP_HL, curses.COLOR_YELLOW, -1)
    curses.init_pair(CP_CURSOR, curses.COLOR_BLACK, curses.COLOR_WHITE)

def load_chapter_lines(bible, book_key, chapter_num, width):
    chapter = bible[book_key].get(chapter_num, [])
    lines, line_to_verse = format_chapter_lines_with_map(chapter, width)
    return chapter, lines, line_to_verse

def load_favorites():
    if not os.path.exists(FAV_FILE):
        return {}
    try:
        with open(FAV_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
            return {
                parse_verse_key(k): v
                for k, v in raw.items()
            }
    except Exception as e:
        print(f"Failed to load favorites: {e}")
        return {}

def save_favorites(favorites):
    try:
        # Convert tuple keys to strings
        serializable = {
            verse_key(b, ch, v): data
            for (b, ch, v), data in favorites.items()
        }
        with open(FAV_FILE, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2)
    except Exception as e:
        print(f"Failed to save favorites: {e}")

def verse_key(book, chapter, verse):
    return f"{book}:{chapter}:{verse}"

def parse_verse_key(key):
    b, ch, v = key.split(":")
    return b, int(ch), int(v)


def move_cursor_to_verse_line(line_to_verse, current_line, direction):
    current_verse = line_to_verse[current_line]
    i = current_line
    if direction > 0:
        while i < len(line_to_verse) and (line_to_verse[i] == current_verse or line_to_verse[i] is None):
            i += 1
    else:
        while i > 0 and (line_to_verse[i] == current_verse or line_to_verse[i] is None):
            i -= 1
        while i > 0 and line_to_verse[i-1] == line_to_verse[i]:
            i -= 1
    return max(0, min(i, len(line_to_verse)-1))


def show_favorites_menu(stdscr, bible, favorites):
    keys = list(favorites.keys())
    if not keys:
        msgbox(stdscr, "No favorites", "You haven't saved any favorite verses yet.")
        return None

    items = []
    for b, ch, v in keys:
        bk = BOOK_NAMES.get(b, b)
        text = next((t for vn, t in bible[b][ch] if vn == v), "")
        snippet = text[:60].replace("\n", " ")
        items.append(f"{bk} {ch}:{v} — {snippet}")

    idx, _ = menu(stdscr, "Favorites", "Select a favorite to jump to or delete:", items, width=80, height=20)
    if idx is None:
        return None

    selected_key = keys[idx]
    b, ch, v = selected_key
    verse_text = next((t for vn, t in bible[b][ch] if vn == v), "")

    choice = menu(
        stdscr,
        "Favorite Options",
        f"{BOOK_NAMES.get(b, b)} {ch}:{v}\n\n{verse_text[:80]}",
        ["Jump to this verse", "Delete this favorite", "Cancel"],
        width=70,
        height=12
    )[0]

    if choice == 0:  # Jump
        return b, ch, {v}
    elif choice == 1:  # Delete
        del favorites[selected_key]
        save_favorites(favorites)
        msgbox(stdscr, "Deleted", f"Removed {BOOK_NAMES.get(b)} {ch}:{v} from favorites.")
        return None
    else:
        return None

def verse_context_menu(stdscr, verse_text):
    items = [
        "Favorite this verse",
        "Copy this verse text",
        "Cancel"
    ]
    idx, _ = menu(stdscr, "Verse options", verse_text[:80], items, width=60, height=10)
    return idx

def choose_highlight_color(stdscr):
    items = [name for name, _ in ALLOWED_COLORS]
    idx, _ = menu(stdscr, "Highlight color", "Choose a highlight color:", items, width=40, height=12)
    if idx is None:
        return None
    return ALLOWED_COLORS[idx][1]

def center_dims(maxy, maxx, h, w):
    y = max(0, (maxy - h) // 2)
    x = max(0, (maxx - w) // 2)
    return y, x, h, w

def draw_box(win, title=None):
    maxy, maxx = win.getmaxyx()
    try:
        win.attron(curses.color_pair(CP_BORDER))
        win.box()
        win.attroff(curses.color_pair(CP_BORDER))
        if title:
            t = f" {title} "
            x = max(2, (maxx - len(t)) // 2)
            win.attron(curses.color_pair(CP_TITLE))
            win.addnstr(0, x, t, max(0, maxx - x - 1), curses.A_BOLD)
            win.attroff(curses.color_pair(CP_TITLE))
    except curses.error:
        pass

def clear_interior_line(win, y, x, width):
    # Clear exactly 'width' cols starting at (y, x) to preserve right border
    try:
        win.addnstr(y, x, " " * width, width)
    except curses.error:
        pass

def wrap_paragraphs(text, width):
    lines = []
    for para in text.splitlines():
        if not para.strip():
            lines.append("")
            continue
        lines.extend(textwrap.wrap(
            para, width=width, break_long_words=False, replace_whitespace=False
        ) or [""])
    return lines

# ---------- Simple dialogs ----------
def button_row(win, buttons, focus_idx, y, x, maxlen=None):
    cx = x
    maxy, maxx = win.getmaxyx()
    limit = maxlen if maxlen is not None else (maxx - x - 1)
    for i, label in enumerate(buttons):
        text = f"< {label} >"
        if cx >= x + limit:
            break
        try:
            if i == focus_idx:
                win.attron(curses.color_pair(CP_FOCUS) | curses.A_BOLD)
                win.addnstr(y, cx, text, max(0, x + limit - cx))
                win.attroff(curses.color_pair(CP_FOCUS) | curses.A_BOLD)
            else:
                win.addnstr(y, cx, text, max(0, x + limit - cx))
        except curses.error:
            pass
        cx += len(text) + 2

def msgbox(stdscr, title, message, width=64, height=12):
    stdscr.clear()
    maxy, maxx = stdscr.getmaxyx()
    height = min(height, maxy - 2) if maxy >= 4 else height
    width = min(width, maxx - 2) if maxx >= 4 else width
    y, x, h, w = center_dims(maxy, maxx, max(4, height), max(10, width))
    win = curses.newwin(h, w, y, x)
    win.keypad(True)
    draw_box(win, title)
    inner_w = w - 4
    text_lines = wrap_paragraphs(message, max(1, inner_w))
    text_lines = text_lines[: max(0, h - 6)]
    for i, line in enumerate(text_lines):
        try:
            win.addnstr(2 + i, 2, line, inner_w)
        except curses.error:
            pass
    buttons = ("OK",)
    button_y = h - 3
    btns_width = sum(len(f"< {b} >") + 2 for b in buttons) - 2
    button_x = max(2, (w - btns_width) // 2)
    button_row(win, buttons, 0, button_y, button_x)
    win.refresh()
    while True:
        ch = win.getch()
        if ch in (10, 13, 27):
            return

def menu(stdscr, title, message, items, width=60, height=None, start_index=0):
    # Returns (index, item) or (None, None) on cancel
    stdscr.clear()
    maxy, maxx = stdscr.getmaxyx()
    height = height or min(24, 8 + len(items))
    height = max(8, min(height, maxy - 2)) if maxy >= 10 else max(6, min(height, maxy))
    width = max(20, min(width, maxx - 2)) if maxx >= 22 else max(20, maxx)
    y, x, h, w = center_dims(maxy, maxx, height, width)
    win = curses.newwin(h, w, y, x)
    win.keypad(True)
    draw_box(win, title)

    inner_w = w - 4
    msg_lines = wrap_paragraphs(message, max(1, inner_w))
    msg_lines = msg_lines[: max(0, h - 10)]
    for i, line in enumerate(msg_lines):
        try:
            win.addnstr(2 + i, 2, line, inner_w)
        except curses.error:
            pass

    start_y = 2 + len(msg_lines) + 1
    view_h = max(1, h - start_y - 4)

    idx = max(0, min(start_index, len(items) - 1)) if items else 0
    top = max(0, idx - view_h // 2)

    while True:
        if idx < top:
            top = idx
        elif idx >= top + view_h:
            top = idx - view_h + 1

        for row in range(view_h):
            i = top + row
            yline = start_y + row
            clear_interior_line(win, yline, 2, inner_w)
            if i >= len(items):
                continue
            s = str(items[i]).replace("\n", " ")
            try:
                if i == idx:
                    win.attron(curses.color_pair(CP_FOCUS))
                    win.addnstr(yline, 2, s, inner_w)
                    win.attroff(curses.color_pair(CP_FOCUS))
                else:
                    win.addnstr(yline, 2, s, inner_w)
            except curses.error:
                pass

        buttons = ("OK", "Cancel")
        button_y = h - 3
        btns_width = sum(len(f"< {b} >") + 2 for b in buttons) - 2
        button_x = max(2, (w - btns_width) // 2)
        button_row(win, buttons, 0, button_y, button_x)

        try:
            win.refresh()
        except curses.error:
            pass

        ch = win.getch()
        if ch in (curses.KEY_UP, ord('k')):
            idx = (idx - 1) % len(items) if items else 0
        elif ch in (curses.KEY_DOWN, ord('j')):
            idx = (idx + 1) % len(items) if items else 0
        elif ch == curses.KEY_PPAGE:
            idx = max(0, idx - view_h)
        elif ch == curses.KEY_NPAGE:
            idx = min(max(0, len(items) - 1), idx + view_h)
        elif ch == curses.KEY_HOME:
            idx = 0
        elif ch == curses.KEY_END:
            idx = max(0, len(items) - 1)
        elif ch in (10, 13):
            if not items:
                return (None, None)
            return idx, items[idx]
        elif ch == 27:
            return None, None
        elif ch == curses.KEY_RESIZE:
            return menu(stdscr, title, message, items, width=width, height=height, start_index=idx)

def inputbox(stdscr, title, prompt, initial=""):
    stdscr.clear()
    maxy, maxx = stdscr.getmaxyx()
    width = min(80, max(30, len(prompt) + 10, maxx - 2))
    height = 10
    y, x, h, w = center_dims(maxy, maxx, height, width)
    win = curses.newwin(h, w, y, x)
    win.keypad(True)
    draw_box(win, title)

    inner_w = w - 4
    lines = wrap_paragraphs(prompt, inner_w)
    lines = lines[: max(0, h - 7)]
    for i, line in enumerate(lines):
        try:
            win.addnstr(2 + i, 2, line, inner_w)
        except curses.error:
            pass

    buf = list(initial)
    cursor = len(buf)
    focus_buttons = False
    buttons = ("OK", "Cancel")
    btn_focus = 0

    while True:
        input_y = h - 6
        try:
            win.attron(curses.color_pair(CP_DIM))
            clear_interior_line(win, input_y - 1, 2, inner_w)
            win.addnstr(input_y - 1, 2, " Input: ", inner_w)
            win.attroff(curses.color_pair(CP_DIM))
            text = "".join(buf)
            shown = text[:inner_w]
            clear_interior_line(win, input_y, 2, inner_w)
            win.addnstr(input_y, 2, shown, inner_w)
        except curses.error:
            pass

        button_y = h - 3
        btns_width = sum(len(f"< {b} >") + 2 for b in buttons) - 2
        button_x = max(2, (w - btns_width) // 2)
        button_row(win, buttons, btn_focus if focus_buttons else -1, button_y, button_x)
        try:
            if not focus_buttons:
                cx = min(cursor, inner_w - 1)
                win.move(input_y, 2 + cx)
            win.refresh()
        except curses.error:
            pass

        ch = win.getch()
        if not focus_buttons:
            if ch == curses.KEY_LEFT:
                cursor = max(0, cursor - 1)
            elif ch == curses.KEY_RIGHT:
                cursor = min(len(buf), cursor + 1)
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                if cursor > 0:
                    del buf[cursor - 1]
                    cursor -= 1
            elif ch == curses.KEY_DC:
                if cursor < len(buf):
                    del buf[cursor]
            elif ch in (10, 13):
                return "".join(buf), True
            elif ch == 27:
                return "".join(buf), False
            elif ch == 9:
                focus_buttons = True
                btn_focus = 0
            elif ch == curses.KEY_HOME:
                cursor = 0
            elif ch == curses.KEY_END:
                cursor = len(buf)
            elif ch == curses.KEY_RESIZE:
                return inputbox(stdscr, title, prompt, initial="".join(buf))
            elif 32 <= ch <= 126:
                buf.insert(cursor, chr(ch))
                cursor += 1
        else:
            if ch == curses.KEY_LEFT:
                btn_focus = max(0, btn_focus - 1)
            elif ch == curses.KEY_RIGHT:
                btn_focus = min(len(buttons) - 1, btn_focus + 1)
            elif ch == 9:
                focus_buttons = False
            elif ch in (10, 13):
                return ("".join(buf), True) if btn_focus == 0 else ("".join(buf), False)
            elif ch == 27:
                return "".join(buf), False
            elif ch == curses.KEY_RESIZE:
                return inputbox(stdscr, title, prompt, initial="".join(buf))

# ---------- KJV parsing ----------
BOOK_NAMES = {
    "Ge": "Genesis", "Ex": "Exodus", "Le": "Leviticus", "Nu": "Numbers", "De": "Deuteronomy",
    "Jos": "Joshua", "Jdg": "Judges", "Ru": "Ruth",
    "1Sa": "1 Samuel", "2Sa": "2 Samuel", "1Ki": "1 Kings", "2Ki": "2 Kings",
    "1Ch": "1 Chronicles", "2Ch": "2 Chronicles", "Ezr": "Ezra", "Ne": "Nehemiah",
    "Es": "Esther", "Job": "Job", "Ps": "Psalms", "Pr": "Proverbs", "Ec": "Ecclesiastes",
    "So": "Song of Solomon", "Isa": "Isaiah", "Jer": "Jeremiah", "La": "Lamentations",
    "Eze": "Ezekiel", "Da": "Daniel", "Ho": "Hosea", "Joe": "Joel", "Am": "Amos",
    "Ob": "Obadiah", "Jon": "Jonah", "Mic": "Micah", "Na": "Nahum", "Hab": "Habakkuk",
    "Zep": "Zephaniah", "Hag": "Haggai", "Zec": "Zechariah", "Mal": "Malachi",
    "Mt": "Matthew", "Mr": "Mark", "Lu": "Luke", "Joh": "John", "Ac": "Acts",
    "Ro": "Romans", "1Co": "1 Corinthians", "2Co": "2 Corinthians", "Ga": "Galatians",
    "Eph": "Ephesians", "Php": "Philippians", "Col": "Colossians", "1Th": "1 Thessalonians",
    "2Th": "2 Thessalonians", "1Ti": "1 Timothy", "2Ti": "2 Timothy", "Tit": "Titus",
    "Phm": "Philemon", "Heb": "Hebrews", "Jas": "James", "1Pe": "1 Peter", "2Pe": "2 Peter",
    "1Jo": "1 John", "2Jo": "2 John", "3Jo": "3 John", "Jude": "Jude", "Re": "Revelation",
}
# name -> code maps for fuzzy matching
NAME_TO_CODE = {}
for code, name in BOOK_NAMES.items():
    NAME_TO_CODE[name.lower()] = code
    NAME_TO_CODE[re.sub(r"\s+", "", name.lower())] = code

HEADER_RE = re.compile(r"^\$\$\s+([A-Za-z0-9]+)\s+(\d+):(\d+)\s*$")

def parse_kjv(path):
    books = OrderedDict()
    order = []
    cur = {"book": None, "ch": None, "v": None, "buf": []}

    def flush():
        if cur["book"] is None:
            return
        book = cur["book"]; ch = int(cur["ch"]); v = int(cur["v"])
        text = " ".join([ln.strip() for ln in cur["buf"]]).strip()
        if book not in books:
            books[book] = defaultdict(list)
            order.append(book)
        books[book][ch].append((v, text))
        cur["buf"].clear()

    with open(path, "r", encoding="utf-8", errors="replace") as f:
      for raw in f:
          line = raw.rstrip("\n").lstrip("\ufeff")
          m = HEADER_RE.match(line)
          if m:
              flush()
              cur["book"], cur["ch"], cur["v"] = m.group(1), int(m.group(2)), int(m.group(3))
              continue
          if cur["book"] is not None:
              cur["buf"].append(line)
    flush()

    for b in order:
        chapters = books[b]
        for ch in list(chapters.keys()):
            verses = sorted(chapters[ch], key=lambda t: t[0])
            chapters[ch] = verses
        books[b] = OrderedDict(sorted(chapters.items(), key=lambda kv: kv[0]))

    ordered_books = OrderedDict((b, books[b]) for b in order)
    return ordered_books

# ---------- Formatting chapter with verse-line mapping ----------
def format_chapter_lines_with_map(chapter_verses, width):
    """
    Returns (lines, line_to_verse):
      - lines: list[str]
      - line_to_verse: list[int or None], verse number for each line
    """
    lines = []
    line_to_verse = []
    for vnum, text in chapter_verses:
        prefix = f"{vnum} "
        wrap_width = max(1, width - len(prefix))
        wrapped = textwrap.wrap(text, width=wrap_width, break_long_words=False, replace_whitespace=False)
        if not wrapped:
            lines.append(prefix)
            line_to_verse.append(vnum)
        else:
            lines.append(prefix + wrapped[0])
            line_to_verse.append(vnum)
            indent = " " * len(prefix)
            for cont in wrapped[1:]:
                lines.append(indent + cont)
                line_to_verse.append(vnum)
        # blank line between verses for readability
        lines.append("")
        line_to_verse.append(None)
    if lines and lines[-1] == "":
        lines.pop()
        line_to_verse.pop()
    return lines, line_to_verse

def line_index_for_verse(chapter_verses, width, verse_num):
    lines, mapping = format_chapter_lines_with_map(chapter_verses, width)
    for i, v in enumerate(mapping):
        if v == verse_num:
            return i
    return 0

# ---------- Navigation helpers ----------
def next_chapter(bible, book_key, chapter_num):
    book_keys = list(bible.keys())
    chapters = list(bible[book_key].keys())
    i = chapters.index(chapter_num)
    if i + 1 < len(chapters):
        return (book_key, chapters[i + 1])
    bi = book_keys.index(book_key)
    if bi + 1 < len(book_keys):
        nb = book_keys[bi + 1]
        nch = list(bible[nb].keys())[0]
        return (nb, nch)
    return None

def prev_chapter(bible, book_key, chapter_num):
    book_keys = list(bible.keys())
    chapters = list(bible[book_key].keys())
    i = chapters.index(chapter_num)
    if i - 1 >= 0:
        return (book_key, chapters[i - 1])
    bi = book_keys.index(book_key)
    if bi - 1 >= 0:
        pb = book_keys[bi - 1]
        pch = list(bible[pb].keys())[-1]
        return (pb, pch)
    return None

# ---------- Parsing references (fixed) ----------
# Try in order to avoid swallowing chapter/verse into book token.
RE_BOOK_CH_VRANGE = re.compile(
    r"^\s*([0-9]{0,2}\s*[A-Za-z][A-Za-z ]+?)\s+(\d+)(?::(\d+)(?:[-–—](\d+))?)?\s*$"
)
RE_REL_CH_VRANGE = re.compile(r"^\s*(\d+)\s*:\s*(\d+)(?:[-–—]\s*(\d+))?\s*$")
RE_REL_CH_ONLY = re.compile(r"^\s*(\d+)\s*$")
RE_BOOK_ONLY = re.compile(r"^\s*([0-9]{0,2}\s*[A-Za-z][A-Za-z ]+?)\s*$")


def normalize_book_token(tok):
    if tok is None:
        return None
    t = tok.strip().lower()
    t = re.sub(r"\s+", " ", t)
    t_no_space = t.replace(" ", "")
    # direct code
    for code in BOOK_NAMES:
        if code.lower() == t or code.lower() == t_no_space:
            return code
    # exact full-name keys
    if t in NAME_TO_CODE: return NAME_TO_CODE[t]
    if t_no_space in NAME_TO_CODE: return NAME_TO_CODE[t_no_space]
    # prefix fuzzy on full names (with and without spaces)
    candidates = set()
    for name_key, code in NAME_TO_CODE.items():
        if name_key.startswith(t) or name_key.startswith(t_no_space):
            candidates.add(code)
    if candidates:
        for code in BOOK_NAMES.keys():
            if code in candidates:
                return code
        return sorted(candidates)[0]
    return None

def parse_reference_range(ref, current_book=None):
    s = ref.strip()
    # 1) Book + chapter [+ verse/range]
    m = RE_BOOK_CH_VRANGE.match(s)
    if m:
        braw, ch, v1, v2 = m.group(1), int(m.group(2)), m.group(3), m.group(4)
        code = normalize_book_token(braw)
        if not code:
            return None
        vs = int(v1) if v1 else None
        ve = int(v2) if v2 else vs
        return (code, ch, vs, ve)
    # 2) Relative chap:verse[–end]
    m = RE_REL_CH_VRANGE.match(s)
    if m and current_book:
        ch, v1, v2 = int(m.group(1)), int(m.group(2)), m.group(3)
        ve = int(v2) if v2 else v1
        return (current_book, ch, v1, ve)
    # 3) Relative chapter only
    m = RE_REL_CH_ONLY.match(s)
    if m and current_book:
        return (current_book, int(m.group(1)), None, None)
    # 4) Book only
    m = RE_BOOK_ONLY.match(s)
    if m:
        code = normalize_book_token(m.group(1))
        if not code:
            return None
        return (code, None, None, None)
    return None

# ---------- Search ----------
def parse_query(q):
    phrases = re.findall(r'"([^"]+)"', q)
    remainder = re.sub(r'"[^"]+"', ' ', q)
    terms = [w for w in re.split(r"\s+", remainder.strip()) if w]
    return terms, phrases

def match_verse(text, terms, phrases, mode="all"):
    s = text.lower()
    t = [w.lower() for w in terms]
    p = [ph.lower() for ph in phrases]
    if mode == "exact":
        if p:
            return any(ph in s for ph in p)
        mode = "all"
    if mode == "any":
        return any((w in s) for w in t) or any((ph in s) for ph in p)
    return all((w in s) for w in t) and all((ph in s) for ph in p)

def make_snippet(text, terms, phrases, width=80):
    s = text
    keys = [w.lower() for w in terms] + [ph.lower() for ph in phrases]
    idx = -1
    ls = s.lower()
    for k in keys:
        pos = ls.find(k)
        if pos != -1 and (idx == -1 or pos < idx):
            idx = pos
    if idx == -1:
        idx = 0
    start = max(0, idx - 30)
    end = min(len(s), start + width)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(s) else ""
    return (prefix + s[start:end] + suffix).replace("\n", " ")

def search_bible(bible, query, mode="all"):
    terms, phrases = parse_query(query)
    results = []
    for bkey, chapters in bible.items():
        for ch, verses in chapters.items():
            for vnum, vtext in verses:
                if match_verse(vtext, terms, phrases, mode=mode):
                    results.append((bkey, ch, vnum, vtext))
    return results, terms, phrases

# ---------- UI helpers ----------
def choose_book_chapter(stdscr, bible, current=None):
    book_keys = list(bible.keys())
    items = [f"{BOOK_NAMES.get(k, k)} ({k})" for k in book_keys]
    start_idx = book_keys.index(current[0]) if current and current[0] in book_keys else 0
    idx, _ = menu(stdscr, "Select book", "Choose a book:", items, width=48, start_index=start_idx)
    if idx is None:
        return (None, None)
    book_key = book_keys[idx]
    ch = choose_chapter(stdscr, bible, book_key, current=current[1] if current and current[0]==book_key else None)
    if ch is None:
        return (None, None)
    return (book_key, ch)

def choose_chapter(stdscr, bible, book_key, current=None):
    chapters = list(bible[book_key].keys())
    items = [f"Chapter {n}" for n in chapters]
    start_idx = chapters.index(current) if current in chapters else 0
    idx, _ = menu(stdscr, f"{BOOK_NAMES.get(book_key, book_key)}", "Choose a chapter:", items,
                  width=40, height=min(24, 8+len(items)), start_index=start_idx)
    if idx is None:
        return None
    return chapters[idx]

def choose_search_mode(stdscr):
    items = [
        "All terms and phrases (AND)",
        "Any term or phrase (OR)",
        'Exact phrase match (use "quotes")'
    ]
    idx, _ = menu(stdscr, "Search mode", "Select how to match your query:", items, width=56, height=12)
    if idx is None:
        return None
    return ["all", "any", "exact"][idx]

def show_search_results(stdscr, results, terms, phrases):
    items = []
    for bkey, ch, v, text in results:
        bk = BOOK_NAMES.get(bkey, bkey)
        snippet = make_snippet(text, terms, phrases, width=80)
        items.append(f"{bk} {ch}:{v} — {snippet}")
    idx, _ = menu(stdscr, "Search results", f"{len(results)} matches. Select a verse:", items,
                  width=90, height=min(28, 10 + len(items)))
    if idx is None:
        return None
    return results[idx]

def jump_to_reference_prompt(stdscr, bible, current_book, current_chapter):
    ref, ok = inputbox(
        stdscr,
        "Jump to",
        'Enter reference (e.g. "John 3:16", "Joh 3:16-18", "John 3", "Genesis", "3:16", "3"):'
    )
    if not ok or not ref.strip():
        return None
    parsed = parse_reference_range(ref, current_book=current_book)
    if not parsed:
        msgbox(stdscr, "Not found", "Could not parse that reference.")
        return None
    bkey, ch, v1, v2 = parsed
    if bkey not in bible:
        msgbox(stdscr, "Not found", f"Book '{bkey}' not in text.")
        return None

    chapters = bible[bkey]
    if ch is None:
        ch = list(chapters.keys())[0]
        verses = [vn for vn, _ in chapters[ch]]
        hl = set(verses)
        return (bkey, ch, hl)
    if ch not in chapters:
        chs = list(chapters.keys())
        ch = min(chs, key=lambda n: abs(n - ch))
    verses = [vn for vn, _ in chapters[ch]]
    if v1 is None:
        hl = set(verses)
        return (bkey, ch, hl)
    if v2 is None:
        v2 = v1
    v1c = min(verses, key=lambda n: abs(n - v1))
    v2c = min(verses, key=lambda n: abs(n - v2))
    lo, hi = sorted((v1c, v2c))
    hl = {vn for vn in verses if lo <= vn <= hi}
    return (bkey, ch, hl)

# ---------- Reader ----------
def reader(stdscr, bible, book_key, chapter_num):
    curses.curs_set(0)
    init_colors()
    favorites = load_favorites()

    highlight_enabled = True
    highlight_set = set()
    cursor_line = 0

    while True:
        stdscr.clear()
        maxy, maxx = stdscr.getmaxyx()
        if maxy < 8 or maxx < 20:
            msgbox(stdscr, "Terminal too small", "Please enlarge the terminal window.")
            return

        win = curses.newwin(maxy, maxx, 0, 0)
        win.keypad(True)
        title = f"{BOOK_NAMES.get(book_key, book_key)} {chapter_num}"
        draw_box(win, title)

        inner_h = max(1, maxy - 6)
        inner_w = max(1, maxx - 4)
        chapter, content_lines, line_to_verse = load_chapter_lines(bible, book_key, chapter_num, inner_w)
        top = max(0, min(cursor_line, len(content_lines) - inner_h))

        help_line = "Arrows: scroll  PgUp/PgDn  Home/End  ←/→: ch  B: book  c: chapter  v: jump  /: search  h: highlight  f: favorite  d: delete  b: bookmarks  q: quit"

        for row in range(inner_h):
            y = 2 + row
            clear_interior_line(win, y, 2, inner_w)
            i = top + row
            if 0 <= i < len(content_lines):
                line = content_lines[i]
                vnum = line_to_verse[i]
                attr = curses.A_NORMAL
                if highlight_enabled and vnum is not None and vnum in highlight_set:
                    attr = curses.color_pair(CP_HL) | curses.A_BOLD
                if vnum is not None and (book_key, chapter_num, vnum) in favorites:
                    color_id = favorites[(book_key, chapter_num, vnum)]["color"]
                    curses.init_pair(100 + color_id, curses.COLOR_BLACK, color_id)
                    attr = curses.color_pair(100 + color_id)
                if i == cursor_line:
                    attr = curses.color_pair(CP_CURSOR)
                try:
                    win.addnstr(y, 2, line, inner_w, attr)
                except curses.error:
                    pass

        status = f"{BOOK_NAMES.get(book_key, book_key)} {chapter_num}  ({len(content_lines)} lines)"
        hl_status = "HL ON" if highlight_enabled and highlight_set else "HL OFF"
        try:
            clear_interior_line(win, maxy - 3, 2, inner_w)
            clear_interior_line(win, maxy - 2, 2, inner_w)
            win.attron(curses.color_pair(CP_DIM))
            win.addnstr(maxy - 3, 2, f"{status}   {hl_status}", inner_w)
            win.addnstr(maxy - 2, 2, help_line[:inner_w], inner_w)
            win.attroff(curses.color_pair(CP_DIM))
        except curses.error:
            pass

        try:
            win.refresh()
        except curses.error:
            pass

        ch = win.getch()
        page = max(1, inner_h - 1)

        if ch in (curses.KEY_UP, ord('k')):
            cursor_line = move_cursor_to_verse_line(line_to_verse, cursor_line, -1)
        elif ch in (curses.KEY_DOWN, ord('j')):
            cursor_line = move_cursor_to_verse_line(line_to_verse, cursor_line, 1)
        elif ch == curses.KEY_PPAGE:
            cursor_line = max(0, cursor_line - page)
        elif ch == curses.KEY_NPAGE:
            cursor_line = min(len(content_lines) - 1, cursor_line + page)
        elif ch == curses.KEY_HOME:
            cursor_line = 0
        elif ch == curses.KEY_END:
            cursor_line = len(content_lines) - 1
        elif ch in (ord('q'), 27):
            return
        elif ch == curses.KEY_LEFT:
            prev = prev_chapter(bible, book_key, chapter_num)
            if prev:
                book_key, chapter_num = prev
                highlight_set = set()
                cursor_line = 0
        elif ch == curses.KEY_RIGHT:
            nxt = next_chapter(bible, book_key, chapter_num)
            if nxt:
                book_key, chapter_num = nxt
                highlight_set = set()
                cursor_line = 0
        elif ch == ord('B'):
            bk, chnum = choose_book_chapter(stdscr, bible, current=(book_key, chapter_num))
            if bk is not None:
                book_key, chapter_num = bk, chnum
                highlight_set = set()
                cursor_line = 0
        elif ch == ord('c'):
            chnum = choose_chapter(stdscr, bible, book_key, current=chapter_num)
            if chnum is not None:
                chapter_num = chnum
                highlight_set = set()
                cursor_line = 0
        elif ch == ord('h'):
            highlight_enabled = not highlight_enabled
        elif ch == ord('v'):
            jump = jump_to_reference_prompt(stdscr, bible, book_key, chapter_num)
            if jump:
                book_key, chapter_num, highlight_set = jump
                chapter, content_lines, line_to_verse = load_chapter_lines(bible, book_key, chapter_num, inner_w)
                first_v = min(highlight_set)
                cursor_line = line_index_for_verse(chapter, inner_w, first_v)
        elif ch == ord('/'):
            q, ok = inputbox(stdscr, "Search", 'Enter query. Use quotes for phrases, e.g. "in the beginning" faith:')
            if not ok or not q.strip():
                continue
            mode = choose_search_mode(stdscr)
            if mode is None:
                continue
            results, terms, phrases = search_bible(bible, q, mode=mode)
            if not results:
                msgbox(stdscr, "No results", "No verses matched your query.")
                continue
            pick = show_search_results(stdscr, results, terms, phrases)
            if pick:
                book_key, chapter_num, verse_num, _ = pick
                highlight_set = {verse_num}
                chapter, content_lines, line_to_verse = load_chapter_lines(bible, book_key, chapter_num, inner_w)
                cursor_line = line_index_for_verse(chapter, inner_w, verse_num)
        elif ch == ord('f'):
            verse_num = line_to_verse[cursor_line]
            if verse_num is not None:
                verse_text = next((t for v, t in chapter if v == verse_num), "")
                choice = verse_context_menu(stdscr, verse_text)
                if choice == 0:
                    color = choose_highlight_color(stdscr)
                    if color is not None:
                        favorites[(book_key, chapter_num, verse_num)] = {"color": color}
                        save_favorites(favorites)
                elif choice == 1:
                    try:
                        import pyperclip
                        pyperclip.copy(verse_text)
                        msgbox(stdscr, "Copied", "Verse text copied to clipboard.")
                    except ImportError:
                        msgbox(stdscr, "Error", "pyperclip not installed.")
        elif ch == ord('d'):
            verse_num = line_to_verse[cursor_line]
            key = (book_key, chapter_num, verse_num)
            if verse_num is not None and key in favorites:
                del favorites[key]
                save_favorites(favorites)
                msgbox(stdscr, "Deleted", f"Removed {BOOK_NAMES.get(book_key)} {chapter_num}:{verse_num} from favorites.")
        elif ch == ord('b'):
            result = show_favorites_menu(stdscr, bible, favorites)
            if result:
                book_key, chapter_num, highlight_set = result
                chapter, content_lines, line_to_verse = load_chapter_lines(bible, book_key, chapter_num, inner_w)
                first_v = min(highlight_set)
                cursor_line = line_index_for_verse(chapter, inner_w, first_v)
        elif ch == curses.KEY_RESIZE:
            continue

# ---------- App entry ----------
def main(stdscr, path):
    curses.curs_set(0)
    init_colors()
    try:
        bible = parse_kjv(path)
    except Exception as e:
        msgbox(stdscr, "Error", f"Failed to parse file:\n{e}")
        return
    start = choose_book_chapter(stdscr, bible, current=None)
    if start == (None, None):
        return
    book_key, chapter_num = start
    reader(stdscr, bible, book_key, chapter_num)

if __name__ == "__main__":
    # Set the default path to KJV.txt in the current directory
    default_path = os.path.join(os.path.dirname(__file__), 'KJV.txt')

    # Use the provided path or the default path
    path = sys.argv[1] if len(sys.argv) > 1 else default_path

    # Check if the file exists
    if not os.path.isfile(path):
        print(f"Error: The file '{path}' does not exist.")
        sys.exit(1)

    curses.wrapper(lambda stdscr: main(stdscr, path))
