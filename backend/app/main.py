import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import router
from app.config import get_settings
from app.db import SessionLocal, init_db
from app.seed import seed_demo_documents

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    db = SessionLocal()
    try:
        seed_demo_documents(db)
    except Exception:  # a broken sample set must never stop the app from starting
        log.exception("Seeding sample documents failed")
    finally:
        db.close()
    yield


app = FastAPI(title="DocuFlow AI", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)

# Serve the web UI from the same server (one link to share). Must be mounted last:
# it catches every path the API routes above didn't match.
_frontend = Path(get_settings().frontend_dir)
if (_frontend / "index.html").exists():
    app.mount("/", StaticFiles(directory=_frontend, html=True), name="frontend")
else:
    log.info("No built frontend at %s - API only (run `npm run build` in frontend/ to serve the UI)", _frontend)
