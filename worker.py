"""Compatible queue entry point: python worker.py."""
import sys
from backend import worker

if __name__ == "__main__":
    worker.main()
else:
    sys.modules[__name__] = worker
