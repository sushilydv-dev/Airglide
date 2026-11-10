"""On-device language model (llama.cpp) for the slide assistant.

* The model file is downloaded once into the data folder (resumable).
* It is loaded on first use and unloaded after a while without questions,
  so it only uses memory when you need it.
* Everything runs locally: no API key, no internet once downloaded.
"""
import atexit
import os
import sys
import threading
import time
import urllib.error
import urllib.request

from packages.config import DATA_DIR, ssl_context
from packages.logs import log

MODELS_DIR = os.path.join(DATA_DIR, "models")

MODELS = {
    "tiny": {
        "label": "Qwen3 0.6B",
        "summary": "Very small · 0.4 GB · under 1 GB memory. Runs on almost any computer",
        "file": "Qwen3-0.6B-Q4_K_M.gguf",
        "url": "https://huggingface.co/unsloth/Qwen3-0.6B-GGUF/resolve/main/Qwen3-0.6B-Q4_K_M.gguf",
        "size": 396705472,
        "ctx": 4096,
        "temperature": 0.15,
        "outline": False,    # small models copy an outline instead of answering
        "no_think": True,    # Qwen3: answer directly, skip the <think> reasoning block
    },
}
LICENSE_NOTE = "Qwen3 and Qwen2.5 models by Alibaba Cloud, Apache 2.0 licence."
CONTEXT_TOKENS = 8192
IDLE_UNLOAD_S = 15 * 60


def runtime_available():
    """Is llama-cpp-python installed? (Doesn't import it: that compiles GPU shaders.)"""
    import importlib.util
    try:
        return importlib.util.find_spec("llama_cpp") is not None
    except (ImportError, ValueError):
        return False


def total_memory_gb():
    """Physical memory in GB (0 if unknown)."""
    try:
        if sys.platform == "win32":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return stat.ullTotalPhys / 1024 ** 3
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3
    except (ValueError, OSError, AttributeError):
        return 0


def recommended_model():
    """The very small model is the default everywhere: it's accurate on slide
    questions and runs on almost any computer. Bigger models are optional."""
    return "tiny"


def active_model_id(setting):
    """Resolve the 'local_model' setting ('auto' picks by available memory)."""
    return recommended_model() if setting not in MODELS else setting


def model_path(model_id):
    return os.path.join(MODELS_DIR, MODELS[model_id]["file"])


# ---- downloads -------------------------------------------------------------
class Downloader:
    def __init__(self, on_progress=lambda status: None):
        self._on_progress = on_progress
        self._lock = threading.Lock()
        self._thread = None
        self._cancel = threading.Event()
        self.model_id = None
        self.done = 0
        self.total = 0
        self.error = None

    @property
    def active(self):
        return self._thread is not None and self._thread.is_alive()

    def status(self, model_id):
        info = MODELS[model_id]
        path = model_path(model_id)
        if self.active and self.model_id == model_id:
            return {"id": model_id, "state": "downloading", "done": self.done,
                    "total": self.total or info["size"],
                    "progress": self.done / (self.total or info["size"])}
        if os.path.exists(path):
            return {"id": model_id, "state": "ready", "done": info["size"], "total": info["size"], "progress": 1.0}
        part = path + ".part"
        done = os.path.getsize(part) if os.path.exists(part) else 0
        state = "error" if (self.error and self.model_id == model_id) else ("paused" if done else "missing")
        return {"id": model_id, "state": state, "done": done, "total": info["size"],
                "progress": done / info["size"], "error": self.error if state == "error" else None}

    def start(self, model_id):
        with self._lock:
            if self.active:
                return self.model_id == model_id
            self.model_id, self.error = model_id, None
            self.done, self.total = 0, MODELS[model_id]["size"]
            self._cancel.clear()
            self._thread = threading.Thread(target=self._run, args=(model_id,), name="model-download", daemon=True)
            self._thread.start()
            return True

    def cancel(self):
        self._cancel.set()

    def _run(self, model_id):
        info = MODELS[model_id]
        path = model_path(model_id)
        part = path + ".part"
        os.makedirs(MODELS_DIR, exist_ok=True)
        start = os.path.getsize(part) if os.path.exists(part) else 0
        headers = {"User-Agent": "Airglide"}
        if start:
            headers["Range"] = f"bytes={start}-"
        last_emit = 0.0
        try:
            req = urllib.request.Request(info["url"], headers=headers)
            with urllib.request.urlopen(req, timeout=30, context=ssl_context()) as resp:
                if start and resp.status != 206:   # server ignored the range: start over
                    start = 0
                total = start + int(resp.headers.get("Content-Length") or (info["size"] - start))
                self.done, self.total = start, total
                with open(part, "ab" if start else "wb") as f:
                    while not self._cancel.is_set():
                        chunk = resp.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                        self.done += len(chunk)
                        if time.time() - last_emit > 0.4:
                            self._on_progress(self.status(model_id))
                            last_emit = time.time()
            if self._cancel.is_set():
                log.info("Model download paused at %d bytes", self.done)
            elif os.path.getsize(part) < info["size"] * 0.98:
                raise OSError("the download ended early. Try again to resume")
            else:
                os.replace(part, path)
                log.info("Model %s downloaded", model_id)
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            self.error = f"Download failed: {getattr(e, 'reason', e)}"
            log.warning(self.error)
        finally:
            threading.Thread(target=lambda: self._on_progress(self.status(model_id)), daemon=True).start()

    @staticmethod
    def delete(model_id):
        for p in (model_path(model_id), model_path(model_id) + ".part"):
            if os.path.exists(p):
                os.remove(p)


# ---- inference -------------------------------------------------------------
class ThinkFilter:
    """Removes a leading <think>…</think> block from a token stream."""

    def __init__(self):
        self.buffer = ""
        self.passing = False

    def feed(self, text):
        if self.passing:
            return text
        self.buffer += text
        stripped = self.buffer.lstrip()
        if not stripped:
            return ""
        if not "<think>".startswith(stripped[:7]) and not stripped.startswith("<think>"):
            self.passing = True          # no think block at all
            out, self.buffer = self.buffer, ""
            return out
        end = self.buffer.find("</think>")
        if end == -1:
            return ""                    # still inside the think block
        self.passing = True
        out = self.buffer[end + len("</think>"):].lstrip()
        self.buffer = ""
        return out

    def flush(self):
        out = "" if not self.passing and "<think>" in self.buffer else self.buffer
        self.buffer = ""
        return out



class LocalModel:
    def __init__(self):
        self._lock = threading.Lock()
        self._llm = None
        self._loaded_id = None
        self._last_used = 0.0
        threading.Thread(target=self._idle_watch, name="llm-idle", daemon=True).start()

    @property
    def loaded(self):
        return self._loaded_id

    def _load(self, model_id):
        if self._llm is not None and self._loaded_id == model_id:
            return
        self._unload_locked()
        from llama_cpp import Llama

        t = time.time()
        self._llm = Llama(
            model_path=model_path(model_id),
            n_ctx=MODELS[model_id].get("ctx", CONTEXT_TOKENS),
            n_gpu_layers=-1,          # use Metal / GPU when available, CPU otherwise
            n_threads=max(2, (os.cpu_count() or 4) - 2),
            verbose=False,
        )
        self._loaded_id = model_id
        log.info("Loaded local model %s in %.1fs", model_id, time.time() - t)

    def _unload_locked(self):
        if self._llm is not None:
            try:
                self._llm.close()
            except Exception:
                pass
        self._llm, self._loaded_id = None, None

    def unload(self, timeout=10):
        if self._lock.acquire(timeout=timeout):
            try:
                self._unload_locked()
            finally:
                self._lock.release()

    def _idle_watch(self):
        while True:
            time.sleep(60)
            if self._llm is not None and time.time() - self._last_used > IDLE_UNLOAD_S:
                with self._lock:
                    if self._llm is not None and time.time() - self._last_used > IDLE_UNLOAD_S:
                        log.info("Unloading idle local model")
                        self._unload_locked()

    def chat(self, model_id, messages, on_token=lambda t: None, max_tokens=420, stop_event=None):
        """Stream a reply for OpenAI-style `messages`. Returns the full text."""
        spec = MODELS[model_id]
        if spec.get("no_think") and messages and messages[-1]["role"] == "user":
            messages = messages[:-1] + [{**messages[-1], "content": messages[-1]["content"] + " /no_think"}]
        think = ThinkFilter() if spec.get("no_think") else None
        with self._lock:
            self._load(model_id)
            self._last_used = time.time()
            reply = []
            stream = self._llm.create_chat_completion(
                messages=messages, stream=True, max_tokens=max_tokens,
                temperature=MODELS[model_id].get("temperature", 0.3), top_p=0.9, repeat_penalty=1.1,
            )
            for part in stream:
                if stop_event is not None and stop_event.is_set():
                    break
                delta = part["choices"][0].get("delta", {}).get("content")
                if delta and think:
                    delta = think.feed(delta)
                if delta:
                    reply.append(delta)
                    on_token(delta)
            if think:
                tail = think.flush()
                if tail:
                    reply.append(tail)
                    on_token(tail)
            self._last_used = time.time()
            return "".join(reply).strip()

    def count_tokens(self, text):
        with self._lock:
            if self._llm is None:
                return len(text) // 4
            return len(self._llm.tokenize(text.encode("utf-8"), add_bos=False))


local_model = LocalModel()
# Free the model before the interpreter exits: llama.cpp's Metal backend aborts
# if GPU buffers are still alive when its device is torn down.
atexit.register(local_model.unload)
