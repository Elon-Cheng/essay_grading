"""Compatible ASGI entry point: python -m uvicorn app:app."""
import sys
from backend import app as application

sys.modules[__name__] = application
