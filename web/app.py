"""
FastAPI web server for the School Water Control app.

The Bluetooth control happens entirely in the browser via the Web Bluetooth API
(JavaScript). This server's responsibilities are:
  - Serve the single-page HTML/JS frontend over HTTPS
  - Expose a /health endpoint for Docker health-checks and load-balancers
  - (Optional) Proxy API endpoints for future server-side features

Run locally (development):
    uvicorn web.app:app --reload --port 8080

In production (Docker + nginx) TLS termination is handled by nginx.
"""

import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="School Water Control", version="1.0.0")

# Mount static files (CSS, JS, images)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
