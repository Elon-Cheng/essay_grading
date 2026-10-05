"""Compatibility CLI; all Word generation lives in backend.documents."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.documents import main

if __name__ == '__main__':
    main()
