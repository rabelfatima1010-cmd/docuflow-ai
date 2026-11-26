"""Record a captioned walkthrough video of DocuFlow AI (MP4, 1920x1080).

Drives the real app in Microsoft Edge with Playwright, adds on-screen captions and a
visible cursor, speeds up the parts where the AI is working, and exports with ffmpeg.

Needs a running app with real AI (uploads cost ~1-3 cents each) and its access code:

    pip install playwright imageio-ffmpeg        # one time, in backend/.venv
    set VIDEO_BASE_URL=http://localhost:8200
    set VIDEO_ACCESS_CODE=...
    backend\\.venv\\Scripts\\python scripts\\make_video.py

Output: social-media-posts/upwork/docuflow-walkthrough.mp4
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BASE = os.environ.get("VIDEO_BASE_URL", "http://localhost:8200").rstrip("/")
CODE = os.environ.get("VIDEO_ACCESS_CODE", "")
TEST = ROOT / "test-invoices"
OUT = ROOT / "social-media-posts" / "upwork" / "docuflow-walkthrough.mp4"
W, H = 1600, 900
FAST = 6  # speed-up factor while the AI is working

THEME = "linear-gradient(135deg, #010000 0%, #3a0021 50%, #730041 100%)"
FONT = '<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;800&display=swap" rel="stylesheet">'

OVERLAY_JS = """
(() => {
  const ready = (fn) => document.readyState !== 'loading' ? fn() : document.addEventListener('DOMContentLoaded', fn);
  ready(() => {
    if (document.getElementById('__cursor')) return;
    const c = document.createElement('div');
    c.id = '__cursor';
    c.innerHTML = '<svg width="28" height="28" viewBox="0 0 24 24"><path d="M4 2l16 10-7 1.5L10 21z" fill="#fff" stroke="#111" stroke-width="1.5" stroke-linejoin="round"/></svg>';
    Object.assign(c.style, {position:'fixed', left:'-50px', top:'-50px', zIndex:2147483647, pointerEvents:'none',
      transform:'translate(-4px,-2px)', filter:'drop-shadow(0 2px 4px rgba(0,0,0,.6))'});
    document.body.appendChild(c);
    document.addEventListener('mousemove', (e) => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
    const cap = document.createElement('div');
    cap.id = '__caption';
    Object.assign(cap.style, {position:'fixed', left:'50%', bottom:'36px', transform:'translateX(-50%)', zIndex:2147483646,
      pointerEvents:'none', background:'linear-gradient(135deg,#3a0021,#730041)', color:'#fff',
      font:'700 26px/1.35 "Segoe UI", system-ui, sans-serif', padding:'16px 30px', borderRadius:'16px',
      boxShadow:'0 12px 40px rgba(0,0,0,.55)', border:'2px solid rgba(255,255,255,.18)', maxWidth:'1300px',
      textAlign:'center', opacity:'0', transition:'opacity .35s'});
    document.body.appendChild(cap);
    window.__cap = (t) => { cap.textContent = t || ''; cap.style.opacity = t ? '1' : '0'; };
    if (window.__pendingCap) window.__cap(window.__pendingCap);
  });
})();
"""

CARD = """<!doctype html><html><head><meta charset="utf-8">{font}<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{width:{w}px;height:{h}px;background:{bg};color:#fff;font-family:Poppins,"Segoe UI",sans-serif;
display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;overflow:hidden}}
</style></head><body>{body}</body></html>"""

INTRO = """<div style="font-size:30px;font-weight:600;letter-spacing:.14em;text-transform:uppercase;color:#ff7aa8">DocuFlow AI · Walkthrough</div>
<div style="font-size:104px;font-weight:800;line-height:1.08;margin-top:26px">AI Invoice<br>Processing Agent</div>
<div style="font-size:30px;color:#f0d9e3;margin-top:30px">Reads invoices · checks the math · fixes its own mistakes</div>"""

OUTRO = """<div style="font-size:30px;font-weight:600;letter-spacing:.14em;text-transform:uppercase;color:#ff7aa8">Benchmark on 20 invoices</div>
<div style="display:flex;gap:26px;margin-top:34px">{tiles}</div>
<div style="margin-top:46px;background:#fff;color:#730041;border-radius:22px;padding:28px 48px">
<div style="font-size:44px;font-weight:800">Live demo available</div>
<div style="font-size:26px;color:#3a0021;margin-top:6px">Python · FastAPI · OpenAI vision · Next.js · n8n</div></div>"""
TILE = ('<div style="background:rgba(255,255,255,.08);border:2px solid rgba(255,255,255,.18);border-radius:22px;'
        'padding:30px 34px;min-width:250px"><div style="font-size:78px;font-weight:800;line-height:1">{v}</div>'
        '<div style="font-size:22px;color:#f0d9e3;margin-top:10px">{l}</div></div>')


class Recorder:
    def __init__(self, page):
        self.page = page
        self.t0 = time.monotonic()
        self.fast: list[tuple[float, float]] = []
        self._fast_start = None

    def now(self) -> float:
        return time.monotonic() - self.t0

    def wait(self, s: float):
        self.page.wait_for_timeout(int(s * 1000))

    def caption(self, text: str, hold: float = 0):
        self.page.evaluate("(t) => { window.__pendingCap = t; if (window.__cap) window.__cap(t); }", text)
        if hold:
            self.wait(hold)

    def move_to(self, locator, steps: int = 28):
        locator.scroll_into_view_if_needed()
        box = locator.bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        self.page.mouse.move(x, y, steps=steps)
        self.wait(0.25)
        return x, y

    def click(self, locator):
        self.move_to(locator)
        self.page.mouse.down()
        self.wait(0.08)
        self.page.mouse.up()

    def scroll(self, total: int, step: int = 60, pause: float = 0.03):
        for _ in range(abs(total) // step):
            self.page.mouse.wheel(0, step if total > 0 else -step)
            self.wait(pause)

    def start_fast(self):
        self._fast_start = self.now()

    def end_fast(self):
        self.fast.append((self._fast_start, self.now()))
        self._fast_start = None

    def card(self, body: str, hold: float):
        self.page.set_content(CARD.format(font=FONT, w=W, h=H, bg=THEME, body=body))
        self.page.wait_for_load_state("networkidle")
        self.caption("")
        self.wait(hold)


def api(path: str):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read())


def wait_processed(rec: Recorder, filenames: list[str], timeout: float = 180) -> dict[str, dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        docs = {d["filename"]: d for d in api("/api/documents?limit=200") if d["filename"] in filenames}
        if len(docs) == len(filenames) and all(d["status"] not in ("queued", "processing") for d in docs.values()):
            return docs
        rec.wait(1.5)
    sys.exit(f"Timed out waiting for {filenames}")


def record() -> Path:
    raw_dir = Path(tempfile.mkdtemp(prefix="docuflow-video-"))
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        ctx = browser.new_context(viewport={"width": W, "height": H}, color_scheme="dark", record_video_dir=str(raw_dir),
                                  record_video_size={"width": W, "height": H})
        ctx.add_init_script(f"try {{ localStorage.setItem('docuflow.accessCode', {json.dumps(CODE)}); }} catch (e) {{}}")
        ctx.add_init_script(OVERLAY_JS)
        page = ctx.new_page()
        rec = Recorder(page)

        # 1. Intro
        rec.card(INTRO, 4.0)

        # 2. Inbox with the sample run
        page.goto(BASE + "/")
        page.get_by_text("Drop invoices here").wait_for()
        page.locator("tbody tr").first.wait_for()
        rec.wait(1.0)
        rec.caption("20 sample invoices already read by the AI", 3.0)
        rec.move_to(page.locator("tbody tr").nth(1))
        rec.scroll(420)
        rec.wait(1.2)
        rec.scroll(-420)

        # 3. Upload four new invoices
        rec.caption("Drop in new invoices: PDFs or phone photos")
        rec.move_to(page.get_by_text("Drop invoices here"))
        rec.wait(1.2)
        batch = ["test-invoice-1.png", "test-invoice-2.png", "test-invoice-4.png", "test-invoice-5.pdf"]
        page.locator('input[type="file"]').set_input_files([str(TEST / f) for f in batch])
        rec.caption("The AI reads every field and checks the math  (sped up)")
        rec.start_fast()
        wait_processed(rec, batch)
        rec.wait(3.5)  # the inbox refreshes every 3 s
        rec.end_fast()
        rec.caption("Clean invoices are approved automatically", 3.0)

        # 4. Look at one result
        link = page.get_by_role("link", name="test-invoice-1.png")
        rec.click(link)
        page.get_by_text("Extracted data").wait_for()
        rec.wait(1.0)
        rec.caption("The invoice on the left, the extracted data on the right", 1.5)
        rec.move_to(page.get_by_text("Vendor", exact=True))
        rec.wait(1.2)
        rec.move_to(page.get_by_text("Line items", exact=True))
        rec.scroll(360)
        rec.caption("Line items, tax and total all add up", 3.0)

        # 5. An invoice with a wrong total
        rec.click(page.get_by_role("link", name="← Inbox"))
        page.get_by_text("Drop invoices here").wait_for()
        rec.caption("Now an invoice whose printed total is wrong", 1.5)
        rec.move_to(page.get_by_text("Drop invoices here"))
        bad = "test-invoice-3.png"
        page.locator('input[type="file"]').set_input_files(str(TEST / bad))
        rec.caption("The AI re-reads it to double-check  (sped up)")
        rec.start_fast()
        docs = wait_processed(rec, [bad])
        rec.wait(3.5)
        rec.end_fast()
        rec.caption("Flagged for review instead of approved", 2.0)
        rec.click(page.get_by_role("link", name=bad))
        page.get_by_text("Checks that need attention").wait_for()
        rec.wait(0.8)
        rec.caption("It caught that subtotal + tax doesn't equal the total", 1.0)
        rec.move_to(page.get_by_text("Checks that need attention"))
        rec.wait(2.0)

        detail = api(f"/api/documents/{docs[bad]['id']}")
        data = (detail.get("extraction") or {}).get("data") or {}
        expected = round((data.get("subtotal") or 0) + (data.get("tax") or 0), 2)
        total_input = page.locator("input.font-semibold").first
        rec.move_to(total_input)
        rec.caption("A person fixes it in one click…", 0.8)
        total_input.click(click_count=3)
        page.keyboard.type(f"{expected:.2f}", delay=90)
        rec.wait(1.2)
        rec.move_to(page.get_by_text(re.compile(r"Line items .* expected total")))
        rec.caption("…the math check turns green…", 2.0)
        rec.caption("…and approves. The next invoice opens automatically.")
        rec.click(page.get_by_role("button", name=re.compile("Approve")))
        rec.wait(3.0)

        # 6. Dashboard
        rec.click(page.get_by_role("link", name="Dashboard"))
        page.locator(".recharts-wrapper").first.wait_for()
        rec.wait(1.0)
        rec.caption("Dashboard: spend by month, category and vendor", 2.5)
        rec.scroll(480, pause=0.04)
        rec.wait(2.5)

        # 7. Outro
        tiles = "".join(TILE.format(v=v, l=l) for v, l in
                        [("100%", "fields read correctly"), ("85%", "no human needed"), ("~1¢", "AI cost per invoice"), ("7s", "per invoice")])
        rec.card(OUTRO.format(tiles=tiles), 5.0)

        fast = rec.fast
        video_path = Path(page.video.path())
        ctx.close()
        browser.close()
    return video_path, fast


def export(raw: Path, fast: list[tuple[float, float]]) -> None:
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    # Split the recording into normal and sped-up parts, then join them.
    cuts, t = [], 0.0
    for s, e in fast:
        cuts.append((t, s, 1))
        cuts.append((s, e, FAST))
        t = e
    cuts.append((t, None, 1))
    parts, labels = [], []
    for i, (s, e, speed) in enumerate(cuts):
        end = f":end={e:.3f}" if e is not None else ""
        parts.append(f"[0:v]trim=start={s:.3f}{end},setpts=(PTS-STARTPTS)/{speed}[v{i}]")
        labels.append(f"[v{i}]")
    graph = ";".join(parts) + f";{''.join(labels)}concat=n={len(labels)}:v=1:a=0,scale=1920:1080:flags=lanczos,fps=30[out]"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ffmpeg, "-y", "-i", str(raw), "-filter_complex", graph, "-map", "[out]",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart", str(OUT)], check=True, capture_output=True)


def main() -> None:
    if not CODE:
        sys.exit("Set VIDEO_ACCESS_CODE to the app's access code.")
    if not (TEST / "test-invoice-3.png").exists():
        sys.exit("test-invoices/ is missing; generate it first.")
    raw, fast = record()
    export(raw, fast)
    print(f"Saved {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
