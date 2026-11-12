"""Snapshot a running DocuFlow API into static files for the hosted read-only demo.

    # with the API running on :8000 and documents processed
    python scripts/export_demo.py

Writes frontend/public/demo/: documents.json, documents/<id>.json, stats.json, categories.json,
health.json, export.csv and files/<id>.<ext> (the original uploads). The frontend reads these
when built with NEXT_PUBLIC_DEMO_MODE=1, so the demo needs no backend and no API key.
"""

import argparse
import json
import shutil
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "frontend" / "public" / "demo"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8000")
    args = parser.parse_args()
    api = httpx.Client(base_url=args.api, timeout=30)

    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "documents").mkdir(parents=True)
    (OUT / "files").mkdir()

    def save(name: str, data) -> None:
        (OUT / name).write_text(json.dumps(data, indent=1), encoding="utf-8")

    docs = api.get("/api/documents", params={"limit": 500}).json()
    save("documents.json", docs)
    for d in docs:
        detail = api.get(f"/api/documents/{d['id']}").json()
        save(f"documents/{d['id']}.json", detail)
        ext = ".pdf" if detail["mime_type"] == "application/pdf" else ".png"
        (OUT / "files" / f"{d['id']}{ext}").write_bytes(api.get(f"/api/documents/{d['id']}/file").content)
    save("stats.json", api.get("/api/stats").json())
    save("categories.json", api.get("/api/categories").json())
    health = api.get("/api/health").json()
    save("health.json", {**health, "queue": "demo snapshot"})
    (OUT / "export.csv").write_text(api.get("/api/export.csv").text, encoding="utf-8")
    print(f"Exported {len(docs)} documents to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
