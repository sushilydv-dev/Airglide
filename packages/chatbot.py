"""Slide assistant.

Two engines:
  local   (default) a small language model running on this computer
          (packages/local_llm.py): no key, no internet, nothing leaves the device
  gemini  Google Gemini over the internet, if the user prefers it and adds a key

Replies stream in chunk by chunk through `on_chunk`.
"""
import json
import urllib.error
import urllib.request

from packages.config import CONFIG, ssl_context
from packages.settings import settings
from packages.retrieval import build_context, is_relevant

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse"
OFF_TOPIC = "Please ask relevant questions only. I can help with \"{name}\"."
HISTORY_TURNS = 3       # previous question/answer pairs the local model sees

GEMINI_PROMPT = (
    "You are Airglide's presentation assistant, helping a presenter with their "
    "slides. Answer using the presentation below, or general knowledge closely "
    "related to its topic. Keep answers short, clear and easy to say out loud. "
    "If a question is unrelated to the presentation, reply exactly: "
    "\"Please ask relevant questions only.\"\n\n"
    "Presentation: {name}\n{slides}"
)

LOCAL_PROMPT = (
    "You are Airglide, a helpful assistant for a presenter. You help with their {what} "
    "\"{name}\".\n"
    "Rules:\n"
    "- Use the {what} content below as your main source. If something isn't covered, say so briefly "
    "and only add widely known facts that relate to the topic.\n"
    "- Be concise: at most 5 short bullet points or 3 sentences. No preamble.\n"
    "- Never invent numbers, dates or facts that are not in the content.\n"
    "- Write your own sentences; don't just list titles.\n"
    "- Refer to {units} by number when useful (e.g. \"{unit} 3\").\n"
    "- If the question has nothing to do with the {what}, reply exactly: "
    "\"Please ask relevant questions only.\"\n"
    "{current}\n\n"
    "{context}"
)

QUICK_PROMPTS = {
    "summary": "Summarise this presentation in 5 short bullet points.",
    "talking_points": "Give me 3-4 talking points for the current slide.",
    "questions": "What questions might the audience ask about this presentation? "
                 "Give 4 likely questions with a one-line answer each.",
    "explain": "Explain the current slide in simple words.",
}


def parse_sse_lines(lines):
    """Yield text chunks from Gemini's server-sent-events stream."""
    for raw in lines:
        line = raw.decode("utf-8", "replace").strip() if isinstance(raw, bytes) else raw.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            data = json.loads(payload)
        except ValueError:
            continue
        if "error" in data:
            raise RuntimeError(data["error"].get("message", "Unknown Gemini error"))
        for cand in data.get("candidates") or []:
            for part in (cand.get("content") or {}).get("parts", []):
                if part.get("text"):
                    yield part["text"]


class ChatSession:
    def __init__(self, presentation_name, slides, current_slide=lambda: None, unit="slides",
                 model=None, downloader=None):
        self.name = presentation_name or "(none)"
        self.slides = slides
        self.current_slide = current_slide  # callable -> (number, title) or None
        self.unit = unit                     # slides / pages / sections
        self.history = []                    # [{"role": "user"|"assistant", "content": str}]
        self._model = model
        self._downloader = downloader

    # ---- engine selection ----------------------------------------------------
    @staticmethod
    def engine():
        return "local"   # the built-in on-device chatbot is the only engine offered

    @staticmethod
    def api_key():
        return CONFIG.get("gemini_api_key", "")

    def _local_ready(self):
        from packages.local_llm import active_model_id, model_path, runtime_available
        import os

        model_id = active_model_id(settings.get("local_model"))
        if not runtime_available():
            return False, "The chatbot engine isn't installed (llama-cpp-python is missing)."
        if not os.path.exists(model_path(model_id)):
            if self._downloader and self._downloader.active:
                return False, "The chatbot is still being added…"
            return False, "Add the chatbot to start asking questions."
        return True, ""

    def status(self):
        if self.engine() == "gemini":
            if settings.get("offline_mode"):
                return {"ok": False, "code": "offline",
                        "error": "Gemini is off because Offline mode is on. Switch to the on-device assistant in Settings → Assistant."}
            if not self.api_key():
                return {"ok": False, "code": "no_key", "error": "No Gemini API key set. Add one in Settings → Assistant."}
        else:
            ok, message = self._local_ready()
            if not ok:
                return {"ok": False, "code": "no_model", "error": message}
        if not any(s.get("text") for s in self.slides):
            return {"ok": True, "message": "No text to work with yet. Add a presentation first."}
        return {"ok": True, "message": f"Ask me anything about \"{self.name}\"."}

    def clear(self):
        self.history = []

    # ---- prompts -------------------------------------------------------------
    def _unit_one(self):
        return {"pages": "Page", "sections": "Section"}.get(self.unit, "Slide")

    def _current_line(self):
        cur = self.current_slide()
        unit = self._unit_one().lower()
        if cur:
            num, title = cur
            return f"The presenter is currently showing {unit} {num}" + (f" ({title})." if title else ".")
        return f"The presenter is not presenting right now; treat \"current {unit}\" as {unit} 1."

    def _local_messages(self, text):
        cur = self.current_slide()
        what = {"pages": "PDF", "sections": "document"}.get(self.unit, "presentation")
        from packages.local_llm import MODELS, active_model_id

        spec = MODELS.get(active_model_id(settings.get("local_model")), {})
        budget = 3500 if spec.get("ctx", 8192) <= 4096 else 7000
        context = build_context(text, self.slides, current=cur[0] if cur else 1, unit=self._unit_one(),
                                budget_chars=budget, outline=spec.get("outline", True))
        system = LOCAL_PROMPT.format(what=what, name=self.name, units=self.unit, unit=self._unit_one(),
                                     current=self._current_line(), context=context)
        history = self.history[-HISTORY_TURNS * 2:]
        return [{"role": "system", "content": system}, *history, {"role": "user", "content": text}]

    # ---- sending -------------------------------------------------------------
    def send(self, text, on_chunk=lambda chunk: None):
        st = self.status()
        if not st["ok"]:
            return st
        if self.slides and not is_relevant(text, self.slides):
            reply = OFF_TOPIC.format(name=self.name)
            on_chunk(reply)
            self._remember(text, reply)
            return {"ok": True, "reply": reply}
        if self.engine() == "gemini":
            return self._send_gemini(text, on_chunk)
        return self._send_local(text, on_chunk)

    def _remember(self, question, reply):
        self.history += [{"role": "user", "content": question}, {"role": "assistant", "content": reply}]

    def _send_local(self, text, on_chunk):
        from packages.local_llm import active_model_id, local_model

        model = self._model or local_model
        try:
            reply = model.chat(active_model_id(settings.get("local_model")), self._local_messages(text), on_chunk)
        except Exception as e:
            return {"ok": False, "error": f"The on-device model couldn't answer: {e}"}
        if not reply:
            return {"ok": False, "error": "The on-device model returned an empty answer. Try rephrasing."}
        self._remember(text, reply)
        return {"ok": True, "reply": reply}

    def _send_gemini(self, text, on_chunk):
        slide_text = "\n\n".join(f"{self._unit_one()} {s['slide_number']}: {s['text']}" for s in self.slides)
        system = GEMINI_PROMPT.format(name=self.name, slides=slide_text or "(no slides uploaded)") \
            + "\n\n" + self._current_line()
        contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
                    for m in self.history] + [{"role": "user", "parts": [{"text": text}]}]
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents}
        req = urllib.request.Request(
            API_URL.format(model=CONFIG.get("gemini_model") or "gemini-flash-latest"),
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key()},
            method="POST",
        )
        reply = ""
        try:
            with urllib.request.urlopen(req, timeout=90, context=ssl_context()) as resp:
                for chunk in parse_sse_lines(resp):
                    reply += chunk
                    on_chunk(chunk)
        except urllib.error.HTTPError as e:
            try:
                message = json.load(e).get("error", {}).get("message", str(e))
            except ValueError:
                message = str(e)
            return {"ok": False, "error": f"Gemini error: {message}"}
        except (urllib.error.URLError, TimeoutError) as e:
            return {"ok": False, "error": f"Network error: {getattr(e, 'reason', e)}"}
        except RuntimeError as e:
            return {"ok": False, "error": f"Gemini error: {e}"}
        reply = reply.strip()
        if not reply:
            return {"ok": False, "error": "Gemini returned an empty answer (it may have been blocked)."}
        self._remember(text, reply)
        return {"ok": True, "reply": reply}
