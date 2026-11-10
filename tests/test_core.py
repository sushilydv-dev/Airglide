import json

import pytest

from packages import profiles
from packages.chatbot import ChatSession, parse_sse_lines
from packages.library import Library
from packages.settings import DEFAULT_GESTURE_MAP, DEFAULTS, Settings
from packages.system import parse_version


# ---- settings ---------------------------------------------------------------
@pytest.fixture
def store(tmp_path):
    return Settings(str(tmp_path / "settings.json"))


def test_settings_defaults_and_persistence(store, tmp_path):
    assert store.get("hold_frames") == DEFAULTS["hold_frames"]
    assert store.update({"hold_frames": 6, "sounds": False}) == ["hold_frames", "sounds"]
    reloaded = Settings(str(tmp_path / "settings.json"))
    assert reloaded.get("hold_frames") == 6 and reloaded.get("sounds") is False


def test_settings_validation(store):
    store.update({"hold_frames": 999, "cooldown_s": -4, "unknown": 1, "text_scale": "abc"})
    assert store.get("hold_frames") == 30          # clamped
    assert store.get("cooldown_s") == 0.0          # clamped
    assert store.get("text_scale") == DEFAULTS["text_scale"]   # invalid ignored
    assert "unknown" not in store.all()


def test_gesture_map_merges_with_defaults(store):
    store.update({"gesture_map": {"fist": "next", "bogus": "next", "palm": "not-an-action"}})
    m = store.get("gesture_map")
    assert m["fist"] == "next"
    assert m["palm"] == DEFAULT_GESTURE_MAP["palm"]
    assert "bogus" not in m


def test_corrupt_settings_file_falls_back(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{not json")
    assert Settings(str(p)).get("hold_frames") == DEFAULTS["hold_frames"]


def test_listeners_get_changed_keys(store):
    seen = []
    store.subscribe(seen.append)
    store.update({"sounds": False})
    store.update({"sounds": False})               # no change -> no event
    assert seen == [["sounds"]]


# ---- library ----------------------------------------------------------------
def _make_pptx(path, slides):
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    for title, body in slides:
        s = prs.slides.add_slide(prs.slide_layouts[1])
        s.shapes.title.text = title
        s.placeholders[1].text = body
        s.notes_slide.notes_text_frame.text = f"note for {title}"
    s = prs.slides.add_slide(prs.slide_layouts[5])
    s.shapes.title.text = "Table"
    table = s.shapes.add_table(2, 2, Inches(1), Inches(2), Inches(4), Inches(1)).table
    table.cell(0, 0).text, table.cell(0, 1).text = "Year", "Price"
    table.cell(1, 0).text, table.cell(1, 1).text = "2010", "$4"
    prs.save(path)


@pytest.fixture
def lib(tmp_path, store):
    return Library(store, root=str(tmp_path / "library"))


def test_library_add_extracts_text_titles_tables_notes(lib, tmp_path):
    deck = tmp_path / "talk.pptx"
    _make_pptx(str(deck), [("Solar", "Panels make power"), ("Costs", "Fell 90%")])
    entry = lib.add(str(deck))
    assert entry["slides"] == 3
    slides = lib.slides()
    assert slides[0]["title"] == "Solar"
    assert "Panels make power" in slides[0]["text"]
    assert "Notes: note for Solar" in slides[0]["text"]
    assert "2010 | $4" in slides[2]["text"]
    assert lib.current()["id"] == entry["id"]
    assert lib.current_path().endswith("talk.pptx")


def test_library_recent_select_remove(lib, tmp_path):
    ids = []
    for name in ("a", "b", "c"):
        p = tmp_path / f"{name}.pptx"
        _make_pptx(str(p), [(name, "x")])
        ids.append(lib.add(str(p))["id"])
    assert [e["name"] for e in lib.recent()] == ["c.pptx", "b.pptx", "a.pptx"]
    lib.select(ids[0])
    assert lib.current()["name"] == "a.pptx"
    lib.remove(ids[0])
    assert lib.current()["name"] == "c.pptx"
    assert len(lib.recent()) == 2


def test_library_readding_same_name_replaces(lib, tmp_path):
    p = tmp_path / "deck.pptx"
    _make_pptx(str(p), [("one", "x")])
    lib.add(str(p))
    _make_pptx(str(p), [("one", "x"), ("two", "y")])
    lib.add(str(p))
    assert len(lib.recent()) == 1 and lib.current()["slides"] == 3


def test_library_rejects_bad_files(lib, tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("hi")
    with pytest.raises(ValueError):
        lib.add(str(bad))
    broken = tmp_path / "broken.pptx"
    broken.write_text("not a real pptx")
    with pytest.raises(Exception):
        lib.add(str(broken))
    assert lib.recent() == []


def test_library_pdf(lib, tmp_path):
    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(200, 200)
    w.add_blank_page(200, 200)
    p = tmp_path / "doc.pdf"
    with open(p, "wb") as f:
        w.write(f)
    entry = lib.add(str(p))
    assert entry["slides"] == 2


# ---- chatbot ----------------------------------------------------------------
def test_parse_sse_stream():
    def event(text):
        return "data: " + json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}}]})
    lines = [b": keep-alive", event("Hello").encode(), b"", event(" world").encode(), b"data: [DONE]"]
    assert "".join(parse_sse_lines(lines)) == "Hello world"


def test_parse_sse_error():
    with pytest.raises(RuntimeError, match="quota"):
        list(parse_sse_lines(['data: {"error": {"message": "quota exceeded"}}']))


class FakeModel:
    def __init__(self, reply="Here is the answer."):
        self.reply, self.calls = reply, []

    def chat(self, model_id, messages, on_token=lambda t: None, **kw):
        self.calls.append(messages)
        for word in self.reply.split(" "):
            on_token(word + " ")
        return self.reply


DECK = [{"slide_number": 1, "title": "Solar", "text": "Solar panels convert sunlight into power"},
        {"slide_number": 2, "title": "Costs", "text": "Panel prices fell 90% since 2010"},
        {"slide_number": 3, "title": "Storage", "text": "Batteries store energy for the night"}]


def _local_session(monkeypatch, model, current=None):
    from packages import chatbot

    monkeypatch.setattr(chatbot.ChatSession, "_local_ready", lambda self: (True, ""))
    monkeypatch.setattr(chatbot.settings, "get", lambda k: {"assistant_engine": "local", "local_model": "small",
                                                          "offline_mode": False}.get(k))
    return ChatSession("talk.pptx", DECK, current_slide=lambda: current, model=model)


def test_local_chat_streams_and_keeps_history(monkeypatch):
    model = FakeModel("Prices fell by 90%.")
    s = _local_session(monkeypatch, model, current=(2, "Costs"))
    chunks = []
    r = s.send("How much did panel prices fall?", chunks.append)
    assert r["ok"] and r["reply"] == "Prices fell by 90%." and "".join(chunks).strip() == r["reply"]
    system = model.calls[0][0]["content"]
    assert "currently showing slide 2 (Costs)" in system
    assert "[Slide 2] Panel prices fell 90%" in system
    s.send("And batteries?", chunks.append)
    roles = [m["role"] for m in model.calls[1]]
    assert roles == ["system", "user", "assistant", "user"]


def test_local_chat_refuses_off_topic_without_calling_model(monkeypatch):
    model = FakeModel()
    s = _local_session(monkeypatch, model)
    r = s.send("Who won the football world cup in 1998?")
    assert r["ok"] and "relevant questions" in r["reply"] and model.calls == []
    assert s.send("Summarise the deck")["ok"] and len(model.calls) == 1


def test_status_uses_the_builtin_chatbot(monkeypatch):
    from packages import chatbot

    s = ChatSession("x", DECK)
    # Even an old "gemini" setting uses the built-in on-device chatbot now.
    monkeypatch.setattr(chatbot.settings, "get", lambda k: {"assistant_engine": "gemini", "local_model": "auto", "offline_mode": True}.get(k))
    assert s.engine() == "local"
    monkeypatch.setattr(chatbot.ChatSession, "_local_ready", lambda self: (True, ""))
    assert s.status()["ok"]          # on-device keeps working in offline mode
    monkeypatch.setattr(chatbot.ChatSession, "_local_ready", lambda self: (False, "Download the model"))
    assert s.status()["code"] == "no_model"


# ---- retrieval -------------------------------------------------------------------
from packages.retrieval import bm25_scores, build_context, is_relevant  # noqa: E402


def test_bm25_ranks_matching_slide_first():
    docs = [s["text"] for s in DECK]
    scores = bm25_scores("battery storage at night", docs)
    assert scores.index(max(scores)) == 2


def test_relevance_gate():
    assert is_relevant("summarise the deck", DECK)
    assert is_relevant("what about solar panels?", DECK)
    assert is_relevant("give me talking points", DECK)
    assert not is_relevant("best pizza recipe in naples", DECK)


def test_context_fits_budget_and_includes_current():
    big = [{"slide_number": i + 1, "title": f"T{i}", "text": ("filler words here " * 80) + (" rocket" if i == 30 else "")}
           for i in range(60)]
    ctx = build_context("tell me about the rocket", big, current=5, budget_chars=4000)
    assert len(ctx) < 5200
    assert "[Slide 5]" in ctx and "[Slide 31]" in ctx
    assert "Outline:" in ctx and "60. T59" in ctx


# ---- profiles & versions -------------------------------------------------------
def test_profiles_resolve():
    assert profiles.resolve("keynote") == "keynote"
    assert profiles.resolve("auto", "/x/deck.pdf") == "pdf"
    assert profiles.resolve("auto", "/x/deck.pptx") in profiles.PROFILES


def test_profiles_complete():
    required = {"start", "next", "prev", "first", "last", "exit", "blank", "laser", "pen", "arrow",
                "zoom_in", "zoom_out"}
    for pid, p in profiles.PROFILES.items():
        assert required <= set(p["keys"]), pid
        assert profiles.pointer_modes(pid)[-1] == "off"


def test_parse_version():
    assert parse_version("v2.1.0") > parse_version("2.0.9")
    assert parse_version("2.0") == (2, 0, 0)
    assert parse_version("v3.0.0-beta") == (3, 0, 0)


# ---- talk timeline -------------------------------------------------------------
from packages.library import estimate_seconds, timeline  # noqa: E402


def _slides(n, words=10, notes=False):
    body = " ".join(["word"] * words) + ("\nNotes: " + " ".join(["note"] * 40) if notes else "")
    return [{"slide_number": i + 1, "title": f"S{i + 1}", "text": body} for i in range(n)]


def test_timeline_is_contiguous_and_bounded():
    plan = timeline(_slides(5, words=30))
    assert [p["slide_number"] for p in plan] == [1, 2, 3, 4, 5]
    for a, b in zip(plan, plan[1:]):
        assert b["start"] == a["start"] + a["duration"]
    assert all(20 <= p["duration"] <= 300 for p in plan)


def test_timeline_scales_to_target_length():
    plan = timeline(_slides(10, words=50), target_minutes=15)
    assert abs(sum(p["duration"] for p in plan) - 900) <= 10


def test_notes_and_pace_change_estimates():
    plain, noted = _slides(1)[0], _slides(1, notes=True)[0]
    assert estimate_seconds(noted) > estimate_seconds(plain)
    assert estimate_seconds(plain, "relaxed") > estimate_seconds(plain) > estimate_seconds(plain, "fast")
    assert timeline(_slides(1, notes=True))[0]["has_notes"]


def test_theme_and_pace_settings_are_validated(store):
    store.update({"theme": "dark", "speaking_pace": "fast"})
    assert store.get("theme") == "dark" and store.get("speaking_pace") == "fast"
    store.update({"theme": "purple", "speaking_pace": "warp"})
    assert store.get("theme") == "dark" and store.get("speaking_pace") == "fast"


# ---- presenter schedule ----------------------------------------------------------
def test_presenter_schedule_and_goto(monkeypatch):
    import time as _time

    from packages import gesture

    typed = []
    monkeypatch.setattr(gesture.pyautogui, "write", lambda s, **k: typed.append(s))
    monkeypatch.setattr(gesture.pyautogui, "press", lambda k, **kw: typed.append(k))
    p = gesture.Presenter(notify=lambda m: None)
    p.plan = [{"start": 0, "duration": 60}, {"start": 60, "duration": 60}, {"start": 120, "duration": 60}]
    p.total, p.titles, p.profile_id = 3, ["a", "b", "c"], "powerpoint_win"
    p.started_at = _time.time() - 90
    p.slide = 1
    assert p._schedule(90) == -30          # 30 s behind: slide 1 should have ended at 60 s
    p.slide = 2
    assert p._schedule(90) == 0            # on track
    p.slide = 3
    assert p._schedule(90) == 30           # 30 s ahead
    # goto needs a running presenter
    assert not p.goto_slide(2)["ok"]
    monkeypatch.setattr(gesture.Presenter, "running", property(lambda self: True))
    assert p.goto_slide(2)["ok"] and typed == ["2", "enter"] and p.slide == 2
    assert not p.goto_slide(9)["ok"]
    p.profile_id = "pdf"
    assert not p.goto_slide(1)["ok"]


# ---- more formats ---------------------------------------------------------------
import shutil as _shutil  # noqa: E402
import subprocess as _subprocess  # noqa: E402
import sys as _sys  # noqa: E402

from packages import library as libmod  # noqa: E402


def _make_docx(path, headings=True):
    from docx import Document

    d = Document()
    if headings:
        d.add_heading("Project Plan", 0)
        d.add_paragraph("This plan covers the next quarter.")
        d.add_heading("Goals", 1)
        d.add_paragraph("Ship the mobile app.")
        d.add_paragraph("Grow revenue by 20%.")
        d.add_heading("Budget", 1)
        t = d.add_table(rows=2, cols=2)
        t.cell(0, 0).text, t.cell(0, 1).text = "Item", "Cost"
        t.cell(1, 0).text, t.cell(1, 1).text = "Design", "$10k"
    else:
        for i in range(12):
            d.add_paragraph(f"Paragraph {i} " + "word " * 40)
    d.save(path)


def test_docx_sections_follow_headings(lib, tmp_path):
    p = tmp_path / "plan.docx"
    _make_docx(str(p))
    entry = lib.add(str(p))
    assert entry["kind"] == "docx" and entry["slides"] == 3
    secs = lib.slides()
    assert [s["title"] for s in secs] == ["Project Plan", "Goals", "Budget"]
    assert "Grow revenue by 20%." in secs[1]["text"]
    assert "Design | $10k" in secs[2]["text"]


def test_docx_without_headings_is_chunked(tmp_path):
    p = tmp_path / "essay.docx"
    _make_docx(str(p), headings=False)
    secs = libmod.extract(str(p))
    assert 2 <= len(secs) <= 6
    assert all(len(s["text"].split()) >= 40 for s in secs)


@pytest.mark.skipif(_sys.platform != "darwin" or not _shutil.which("textutil"), reason="needs macOS textutil")
def test_legacy_doc_on_mac(lib, tmp_path):
    txt = tmp_path / "old.txt"
    txt.write_text("Old report\n\nFirst paragraph about sales.\n\nSecond paragraph about costs.\n")
    _subprocess.run(["textutil", "-convert", "doc", str(txt), "-output", str(tmp_path / "old.doc")], check=True)
    entry = lib.add(str(tmp_path / "old.doc"))
    assert entry["kind"] == "doc"
    assert "Second paragraph about costs." in lib.slides()[0]["text"]


def test_google_slides_link(lib, tmp_path):
    url = "https://docs.google.com/presentation/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789/edit#slide=id.p"
    deck_id, edit = libmod.normalize_gslides(url)
    assert edit.endswith(f"/d/{deck_id}/edit")
    assert libmod.present_url(url).endswith(f"/d/{deck_id}/present")

    def fake_download(did, dest):
        _make_pptx(dest, [("Intro", "Hello"), ("Plan", "Steps")])
        return dest, "Team Offsite.pptx"

    entry = lib.add_link(url, download=fake_download)
    assert entry["kind"] == "gslides" and entry["name"] == "Team Offsite" and entry["has_text"]
    assert lib.current_path() == edit
    assert lib.slides()[0]["title"] == "Intro"
    # re-adding the same deck replaces it instead of duplicating
    lib.add_link(url, download=lambda did, dest: (None, None))
    assert len(lib.recent()) == 1 and lib.current()["has_text"] is False


def test_google_slides_rejects_other_links(lib):
    with pytest.raises(ValueError):
        lib.add_link("https://example.com/deck")


def test_profiles_for_new_formats():
    assert profiles.resolve("keynote", "/x/report.docx") == "document"
    assert profiles.resolve("keynote", "/x/old.doc") == "document"
    assert profiles.resolve("keynote", "/x/file.pdf") == "pdf"
    assert profiles.resolve("auto", "https://docs.google.com/presentation/d/abc/edit") == "google_slides"
    assert profiles.PROFILES["document"]["keys"]["next"] == ("pagedown",)
    assert all(c["id"] not in ("document", "pdf") for c in profiles.choices())


def test_presenter_document_mode_has_no_slide_counter(monkeypatch):
    from packages import gesture

    monkeypatch.setattr(gesture.threading.Thread, "start", lambda self: None)
    p = gesture.Presenter(notify=lambda m: None)
    p.start("/x/report.docx", [{"slide_number": 1, "title": "A", "text": "x"}], plan=[{"start": 0, "duration": 30}])
    st = p.state()
    assert st["document"] and st["total"] == 0 and st["schedule"] is None
    assert p._action_label("next") == "Page down"


def test_current_slide_questions_only_see_that_slide():
    ctx = build_context("Give me talking points for the current slide", DECK, current=2)
    assert "[Slide 2]" in ctx and "[Slide 1]" not in ctx and "[Slide 3]" not in ctx


# ---- model choice ---------------------------------------------------------------
def test_very_small_model_is_the_default():
    from packages import local_llm

    assert local_llm.active_model_id("auto") == "tiny"
    assert local_llm.active_model_id("large") == "tiny"       # old settings fall back to the built-in model
    assert list(local_llm.MODELS) == ["tiny"]                 # a single built-in chatbot model
    assert local_llm.MODELS["tiny"]["size"] < 450_000_000


def test_think_filter_strips_reasoning_block():
    from packages.local_llm import ThinkFilter

    f = ThinkFilter()
    out = "".join(f.feed(t) for t in ["<thi", "nk>\n", "\n</thi", "nk>\n\n", "APAC was ", "flat."]) + f.flush()
    assert out == "APAC was flat."
    g = ThinkFilter()
    assert "".join(g.feed(t) for t in ["Hello", " there"]) + g.flush() == "Hello there"


def test_tiny_model_gets_lean_context():
    ctx = build_context("summarise", DECK, current=1, outline=False, budget_chars=3500)
    assert "Outline:" not in ctx and "[Slide 1]" in ctx


# ---- Windows code paths (simulated, so they're covered on any OS) ----------------
def test_windows_camera_uses_directshow(monkeypatch):
    from packages import camera as cam

    opened = []

    class FakeCap:
        def __init__(self, src, backend=None):
            opened.append((src, backend))
            self.ok = backend is not None

        def isOpened(self):
            return self.ok

        def release(self):
            pass

    monkeypatch.setattr(cam.sys, "platform", "win32")
    monkeypatch.setattr(cam.cv2, "VideoCapture", FakeCap)
    assert cam.open_capture(0).isOpened()
    assert opened[-1] == (0, cam.cv2.CAP_DSHOW)
    cam.open_capture("http://phone/video")               # URLs keep the default backend
    assert opened[-1] == ("http://phone/video", None)
    monkeypatch.setattr(cam.sys, "platform", "darwin")
    cam.open_capture(1)
    assert opened[-1] == (1, None)


def test_windows_profile_resolution(monkeypatch):
    monkeypatch.setattr(profiles.sys, "platform", "win32")
    assert profiles.resolve("auto", r"C:\\Users\\José\\deck.pptx") == "powerpoint_win"
    assert profiles.PROFILES["powerpoint_win"]["keys"]["start"] == ("f5",)
    assert profiles.PROFILES["powerpoint_win"]["keys"]["laser"] == ("ctrl", "l")


def test_presenter_opens_files_with_startfile_on_windows(monkeypatch):
    from packages import gesture

    started = []
    monkeypatch.setattr(gesture.sys, "platform", "win32")
    monkeypatch.setattr(gesture.os, "startfile", lambda p: started.append(p), raising=False)
    gesture.open_file(r"C:\\decks\\talk.pptx")
    assert started == [r"C:\\decks\\talk.pptx"]
