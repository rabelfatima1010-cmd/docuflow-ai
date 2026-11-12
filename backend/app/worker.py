"""Job queue. With REDIS_URL set, jobs go to Redis and run in `rq worker` processes
(see docker-compose). Without it (local dev), they run in a background thread."""

import logging
import threading

from app.config import get_settings
from app.db import SessionLocal

log = logging.getLogger(__name__)
QUEUE_NAME = "documents"


def process_job(doc_id: int) -> None:
    from app.pipeline.orchestrator import process_document

    db = SessionLocal()
    try:
        process_document(db, doc_id)
    finally:
        db.close()


def enqueue(doc_id: int) -> None:
    settings = get_settings()
    if settings.redis_url:
        from redis import Redis
        from rq import Queue

        Queue(QUEUE_NAME, connection=Redis.from_url(settings.redis_url)).enqueue(
            process_job, doc_id, job_timeout=600
        )
    else:
        threading.Thread(target=process_job, args=(doc_id,), daemon=True).start()


if __name__ == "__main__":  # python -m app.worker
    from redis import Redis
    from rq import Queue, Worker

    from app.db import init_db

    logging.basicConfig(level=logging.INFO)
    init_db()
    conn = Redis.from_url(get_settings().redis_url or "redis://localhost:6379/0")
    Worker([Queue(QUEUE_NAME, connection=conn)], connection=conn).work()
