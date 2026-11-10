import os
import sys

# A windowed app (PyInstaller --noconsole on Windows, or a macOS .app) has no
# console, so sys.stdout / sys.stderr can be None. Some libraries (llama.cpp's
# output suppression, logging) write to them and would crash; give them a sink.
for _name in ("stdout", "stderr"):
    if getattr(sys, _name) is None:
        setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))

from packages.frontend import main  # noqa: E402

if __name__ == "__main__":
    main()
