"""Entry point of the console build (patchwork-cli.exe): the command-line interface only, never the GUI."""
import os
import sys

os.environ.setdefault("PYTHONUTF8", "1")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.cli import run

if __name__ == "__main__":
    run(sys.argv[1:] or ["--help"])
