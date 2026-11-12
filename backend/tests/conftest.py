import os
import sys
import tempfile
from pathlib import Path

# Isolated DB + storage + offline extractor for every test run (must be set before app imports)
_tmp = Path(tempfile.mkdtemp(prefix="docuflow-test-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["STORAGE_DIR"] = str(_tmp / "uploads")
os.environ["EXTRACTOR"] = "mock"
os.environ["REDIS_URL"] = ""
os.environ["EXPORT_ON_APPROVE"] = "true"
os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"] = ""
os.environ["N8N_EXPORT_WEBHOOK_URL"] = ""
os.environ["WEBHOOK_SECRET"] = "test-secret"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
