"""Entry point of the Orizon X PC app (PyInstaller target; in development: .venv\\Scripts\\pythonw.exe orizonx_pc.py)."""
import sys

from app.main import main

if __name__ == "__main__":
    sys.exit(main())
