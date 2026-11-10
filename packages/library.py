"""Presentation library: recently added decks/documents and their extracted text.

Supported sources
  .pptx         PowerPoint          one entry per slide
  .pdf          PDF                 one entry per page
  .docx / .doc  Word documents      one entry per section (split at headings)
  Google Slides a share link        slide text downloaded when the deck is shared
                                    publicly; presenting works either way
"""
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid

from packages.config import DATA_DIR, ssl_context

LIBRARY_DIR = os.path.join(DATA_DIR, "library")
MAX_RECENT = 8
FILE_TYPES = (".pptx", ".pdf", ".docx", ".doc")
DOCUMENT_TYPES = (".docx", ".doc")
SECTION_WORDS = 140          # target size of a section when a document has no headings
GSLIDES_RE = re.compile(r"https://docs\.google\.com/presentation/d/([A-Za-z0-9_-]{20,})")


def kind_of(name):
    """'pptx' | 'pdf' | 'docx' | 'doc' | 'gslides' from a file name or URL."""
    if GSLIDES_RE.match(name or ""):
        return "gslides"
    ext = os.path.splitext(name or "")[1].lower().lstrip(".")
    return ext if f".{ext}" in FILE_TYPES else ""


def is_document(kind):
    return kind in ("docx", "doc")


# ---- text extraction -------------------------------------------------------
def extract_pptx(path):
    from pptx import Presentation

    prs = Presentation(path)
    slides = []
    for i, slide in enumerate(prs.slides):
        title, parts = "", []
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text.strip():
                text = shape.text.strip()
                is_title = getattr(shape, "is_placeholder", False) and \
                    shape.placeholder_format.type is not None and \
                    "TITLE" in str(shape.placeholder_format.type)
                if is_title and not title:
                    title = text.splitlines()[0]
                parts.append(text)
            elif getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    parts.append(" | ".join(cell.text.strip() for cell in row.cells))
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
            parts.append("Notes: " + slide.notes_slide.notes_text_frame.text.strip())
        text = "\n".join(parts)
        slides.append({"slide_number": i + 1, "title": title or _first_line(text), "text": text})
    return slides


def extract_pdf(path):
    from pypdf import PdfReader

    slides = []
    for i, page in enumerate(PdfReader(path).pages):
        text = (page.extract_text() or "").strip()
        slides.append({"slide_number": i + 1, "title": _first_line(text), "text": text})
    return slides


def extract_docx(path):
    """Sections split at headings (Title / Heading 1-3); tables are kept as rows."""
    from docx import Document

    doc = Document(path)
    blocks = []   # (is_heading, text)
    body = doc.element.body
    for child in body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            from docx.text.paragraph import Paragraph
            p = Paragraph(child, doc)
            text = p.text.strip()
            if not text:
                continue
            style = (p.style.name if p.style is not None else "") or ""
            heading = style == "Title" or bool(re.match(r"Heading [1-3]$", style))
            blocks.append((heading, text))
        elif tag == "tbl":
            from docx.table import Table
            for row in Table(child, doc).rows:
                cells = [c.text.strip() for c in row.cells]
                if any(cells):
                    blocks.append((False, " | ".join(cells)))
    if any(h for h, _ in blocks):
        return _sections_from_headings(blocks)
    return _sections_by_length([t for _, t in blocks])


def extract_doc(path):
    """Legacy .doc: macOS textutil, Word on Windows, antiword on Linux."""
    text = None
    try:
        if sys.platform == "darwin":
            text = subprocess.run(["textutil", "-convert", "txt", "-stdout", path],
                                  capture_output=True, text=True, timeout=60, check=True).stdout
        elif sys.platform == "win32":
            text = _doc_text_via_word(path)
        elif shutil.which("antiword"):
            text = subprocess.run(["antiword", path], capture_output=True, text=True,
                                  timeout=60, check=True).stdout
    except (OSError, subprocess.SubprocessError) as e:
        raise ValueError(f"Couldn't read this .doc file ({e}). Try saving it as .docx.") from e
    if text is None:
        raise ValueError("Reading .doc files needs Word (Windows) or antiword (Linux). Save it as .docx instead.")
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\r\n\s*\r\n", text) if p.strip()]
    return _sections_by_length(paragraphs)


def _doc_text_via_word(path):
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return None
    pythoncom.CoInitialize()
    word = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        doc = word.Documents.Open(os.path.abspath(path), ReadOnly=True)
        text = doc.Content.Text
        doc.Close(False)
        return text.replace("\r", "\n\n")
    finally:
        if word is not None:
            word.Quit()
        pythoncom.CoUninitialize()


def _sections_from_headings(blocks):
    sections, title, parts = [], "", []

    def flush():
        if title or parts:
            text = "\n".join(([title] if title else []) + parts)
            sections.append({"slide_number": len(sections) + 1,
                             "title": title or _first_line(text), "text": text})

    for heading, text in blocks:
        if heading:
            flush()
            title, parts = text[:120], []
        else:
            parts.append(text)
    flush()
    return sections


def _sections_by_length(paragraphs, target=SECTION_WORDS):
    sections, chunk, words = [], [], 0
    for p in paragraphs:
        chunk.append(p)
        words += len(p.split())
        if words >= target:
            sections.append(chunk)
            chunk, words = [], 0
    if chunk:
        sections.append(chunk)
    return [{"slide_number": i + 1, "title": _first_line(c[0]), "text": "\n".join(c)}
            for i, c in enumerate(sections)]


def _first_line(text):
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:80]
    return ""


def extract(path):
    kind = kind_of(path)
    if kind == "pptx":
        return extract_pptx(path)
    if kind == "pdf":
        return extract_pdf(path)
    if kind == "docx":
        return extract_docx(path)
    if kind == "doc":
        return extract_doc(path)
    raise ValueError("Please choose a .pptx, .pdf, .docx or .doc file")


# ---- Google Slides -----------------------------------------------------------
def normalize_gslides(url):
    """Return (deck_id, edit_url) for a Google Slides link, or raise ValueError."""
    m = GSLIDES_RE.match((url or "").strip())
    if not m:
        raise ValueError("That doesn't look like a Google Slides link "
                         "(https://docs.google.com/presentation/d/…)")
    deck_id = m.group(1)
    return deck_id, f"https://docs.google.com/presentation/d/{deck_id}/edit"


def present_url(url):
    deck_id, _ = normalize_gslides(url)
    return f"https://docs.google.com/presentation/d/{deck_id}/present"


def download_gslides(deck_id, dest, timeout=20):
    """Download a publicly shared deck as .pptx. Returns (path, title) or (None, None)."""
    req = urllib.request.Request(
        f"https://docs.google.com/presentation/d/{deck_id}/export/pptx",
        headers={"User-Agent": "Airglide"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
            if "presentation" not in resp.headers.get("Content-Type", ""):
                return None, None   # a sign-in page: the deck isn't shared publicly
            title = None
            disp = resp.headers.get("Content-Disposition", "")
            m = re.search(r"filename\*=UTF-8''([^;]+)", disp) or re.search(r'filename="([^"]+)"', disp)
            if m:
                title = urllib.request.unquote(m.group(1))
            with open(dest, "wb") as f:
                shutil.copyfileobj(resp, f)
        return dest, title
    except (urllib.error.URLError, TimeoutError, OSError):
        return None, None


# ---- talk timeline ---------------------------------------------------------
PACE_FACTORS = {"relaxed": 1.25, "normal": 1.0, "fast": 0.8}
MIN_SLIDE_S, MAX_SLIDE_S = 20, 300


def _words(text):
    return len([w for w in text.split() if any(ch.isalnum() for ch in w)])


def estimate_seconds(slide, pace="normal"):
    """Rough speaking time for one slide: a base for introducing it, plus time
    for the words on the slide and (read more slowly) its speaker notes."""
    text = slide.get("text", "")
    notes = ""
    if "Notes: " in text:
        text, notes = text.split("Notes: ", 1)
    seconds = 25 + _words(text) * 1.2 + _words(notes) * 0.45
    seconds *= PACE_FACTORS.get(pace, 1.0)
    return int(min(max(seconds, MIN_SLIDE_S), MAX_SLIDE_S))


def timeline(slides, target_minutes=0, pace="normal"):
    """Planned start time and duration for every slide.

    With a target length the estimates are scaled so the talk fits it."""
    durations = [estimate_seconds(s, pace) for s in slides]
    total = sum(durations)
    if target_minutes and total:
        scale = target_minutes * 60 / total
        durations = [max(5, round(d * scale)) for d in durations]
    plan, t = [], 0
    for s, d in zip(slides, durations):
        plan.append({"slide_number": s["slide_number"], "title": s.get("title", ""),
                     "start": t, "duration": d,
                     "has_notes": "Notes: " in s.get("text", ""),
                     "words": _words(s.get("text", ""))})
        t += d
    return plan


# ---- library -----------------------------------------------------------------
class Library:
    def __init__(self, settings, root=LIBRARY_DIR):
        self._settings = settings
        self._root = root
        self._lock = threading.Lock()

    def _dir(self, entry_id):
        return os.path.join(self._root, entry_id)

    @staticmethod
    def _kind(entry):
        return entry.get("kind") or kind_of(entry.get("file") or entry.get("name", ""))

    def _available(self, e):
        if self._kind(e) == "gslides":
            return bool(e.get("url"))
        return os.path.exists(os.path.join(self._dir(e["id"]), e["file"]))

    def recent(self):
        """Recent entries that are still available, newest first."""
        out = []
        for e in self._settings.get("recent"):
            if self._available(e):
                out.append({**e, "kind": self._kind(e)})
        return out

    def current(self):
        cur = self._settings.get("current")
        for e in self.recent():
            if e["id"] == cur:
                return e
        return None

    def current_path(self):
        """File path of the current entry, or its URL for Google Slides."""
        e = self.current()
        if not e:
            return None
        if e["kind"] == "gslides":
            return e["url"]
        return os.path.join(self._dir(e["id"]), e["file"])

    def slides(self, entry=None):
        entry = entry or self.current()
        if not entry:
            return []
        try:
            with open(os.path.join(self._dir(entry["id"]), "slides.json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return []

    def _store(self, entry, slides, replace_key):
        """Save slides.json and put `entry` first in the recent list."""
        with open(os.path.join(self._dir(entry["id"]), "slides.json"), "w", encoding="utf-8") as f:
            json.dump(slides, f, indent=2, ensure_ascii=False)
        old = self._settings.get("recent")
        recent = [e for e in old if replace_key(e) != replace_key(entry)]
        dropped = [e for e in old if replace_key(e) == replace_key(entry)]
        recent.insert(0, entry)
        dropped += recent[MAX_RECENT:]
        recent = recent[:MAX_RECENT]
        self._settings.update({"recent": recent, "current": entry["id"]})
        for e in dropped:
            shutil.rmtree(self._dir(e["id"]), ignore_errors=True)

    def add(self, source_path):
        kind = kind_of(source_path)
        if not kind or kind == "gslides":
            raise ValueError("Please choose a .pptx, .pdf, .docx or .doc file")
        slides = extract(source_path)  # validates the file before anything is stored
        with self._lock:
            entry_id = uuid.uuid4().hex[:12]
            folder = self._dir(entry_id)
            os.makedirs(folder)
            name = os.path.basename(source_path)
            shutil.copy(source_path, os.path.join(folder, name))
            entry = {"id": entry_id, "name": name, "file": name, "kind": kind,
                     "slides": len(slides), "added": int(time.time())}
            self._store(entry, slides, lambda e: e.get("name"))
        return entry

    def add_link(self, url, download=download_gslides):
        """Add a Google Slides deck by its share link."""
        deck_id, edit_url = normalize_gslides(url)
        with self._lock:
            entry_id = uuid.uuid4().hex[:12]
            folder = self._dir(entry_id)
            os.makedirs(folder)
            path, title = download(deck_id, os.path.join(folder, "deck.pptx"))
            slides = []
            if path:
                try:
                    slides = extract_pptx(path)
                except Exception:
                    slides = []
            name = (title or "").removesuffix(".pptx") or "Google Slides deck"
            entry = {"id": entry_id, "name": name, "file": "deck.pptx" if path else "",
                     "kind": "gslides", "url": edit_url, "deck_id": deck_id,
                     "slides": len(slides), "has_text": bool(slides), "added": int(time.time())}
            self._store(entry, slides, lambda e: e.get("deck_id") or e.get("id"))
        return entry

    def select(self, entry_id):
        for e in self.recent():
            if e["id"] == entry_id:
                recent = [x for x in self._settings.get("recent") if x["id"] != entry_id]
                original = next(x for x in self._settings.get("recent") if x["id"] == entry_id)
                self._settings.update({"recent": [original] + recent, "current": entry_id})
                return e
        raise ValueError("That presentation is no longer available")

    def remove(self, entry_id):
        with self._lock:
            recent = [e for e in self._settings.get("recent") if e["id"] != entry_id]
            changes = {"recent": recent}
            if self._settings.get("current") == entry_id:
                changes["current"] = recent[0]["id"] if recent else None
            self._settings.update(changes)
            shutil.rmtree(self._dir(entry_id), ignore_errors=True)
