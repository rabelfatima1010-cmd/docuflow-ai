"""Render docs/social/upwork.html into Upwork portfolio images (1600x1200 PNG) in
social-media-posts/upwork/, using headless Microsoft Edge (Windows).

    backend\\.venv\\Scripts\\python scripts\\make_upwork.py
"""

import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "social" / "upwork.html"
OUT = ROOT / "social-media-posts" / "upwork"
NAMES = ["1-cover", "2-overview", "3-how-it-works", "4-error-review", "5-inbox", "6-dashboard", "7-results-demo"]
SIZE = (1600, 1200)
EDGE = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
]


def main() -> None:
    edge = next((p for p in EDGE if p.exists()), None)
    if edge is None:
        sys.exit("Microsoft Edge not found.")
    OUT.mkdir(parents=True, exist_ok=True)
    profile = tempfile.mkdtemp(prefix="edge-upwork-")
    for i, name in enumerate(NAMES, start=1):
        out = OUT / f"{name}.png"
        out.unlink(missing_ok=True)
        subprocess.run(
            [str(edge), "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={profile}",
             "--force-device-scale-factor=1", f"--window-size={SIZE[0]},{SIZE[1]}", "--virtual-time-budget=3000",
             f"--screenshot={out}", SOURCE.as_uri() + f"?s={i}"],
            capture_output=True, timeout=90,
        )
        for _ in range(20):
            if out.exists():
                break
            time.sleep(0.5)
        img = Image.open(out).convert("RGB")
        if img.size != SIZE:
            img = img.crop((0, 0, *SIZE))
        img.save(out)
        print(out.name)


if __name__ == "__main__":
    main()
