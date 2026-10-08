"""Vercel entrypoint.

Vercel's Python runtime auto-detects an ASGI app in this file -- it just
needs to find a variable named `app`. Everything else (routing, static
files, the database) is the same FastAPI app used for local/other hosting.
"""
from app.main import app  # noqa: F401
