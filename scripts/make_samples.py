"""Generate synthetic invoice/receipt images + ground-truth JSON for demos and evaluation.

    python scripts/make_samples.py --count 20

Writes samples/invoices/*.png and samples/ground_truth/*.json. Some samples are rotated,
noisy or low-contrast to mimic phone photos; a few contain deliberate math errors so the
validation + review path can be demonstrated.
"""

import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT_IMG = ROOT / "samples" / "invoices"
OUT_GT = ROOT / "samples" / "ground_truth"

VENDORS = [
    ("CloudNest Hosting LLC", "Software & SaaS", ["Cloud server (monthly)", "Managed database", "Backup storage 500GB", "SSL certificate"]),
    ("PaperTrail Office Supplies", "Office Supplies", ["A4 paper (box)", "Toner cartridge", "Ballpoint pens (50)", "Sticky notes"]),
    ("SkyLink Airways", "Travel", ["Flight ISB-DXB economy", "Seat selection", "Extra baggage 10kg"]),
    ("Bean & Byte Cafe", "Meals & Entertainment", ["Cappuccino", "Club sandwich", "Team lunch platter", "Mineral water"]),
    ("BrightGrid Electric", "Utilities", ["Electricity usage", "Meter service fee"]),
    ("Northwind Legal Partners", "Professional Services", ["Contract review (hours)", "Consultation call", "Filing fees"]),
    ("Adwave Marketing Studio", "Marketing & Advertising", ["Social ads campaign", "SEO audit", "Landing page design"]),
    ("SwiftShip Couriers", "Shipping & Logistics", ["Express parcel", "Freight pallet", "Insurance cover"]),
    ("Pixel Hardware Co", "Hardware & Equipment", ["27in monitor", "Mechanical keyboard", "USB-C dock", "Laptop stand"]),
]
CURRENCIES = [("USD", "$"), ("EUR", "EUR "), ("PKR", "Rs "), ("GBP", "GBP ")]


def font(size: int):
    for name in ("arial.ttf", "DejaVuSans.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def make_one(i: int, rng: random.Random) -> tuple[Image.Image, dict]:
    vendor, category, products = rng.choice(VENDORS)
    currency, symbol = rng.choice(CURRENCIES)
    is_receipt = vendor == "Bean & Byte Cafe" or rng.random() < 0.15
    issued = date(2026, 1, 1) + timedelta(days=rng.randint(0, 300))
    due = None if is_receipt else issued + timedelta(days=rng.choice([14, 30, 45]))
    inv_no = None if is_receipt else f"INV-{issued.year}-{rng.randint(1000, 9999)}"

    items = []
    for desc in rng.sample(products, k=rng.randint(1, len(products))):
        qty = rng.randint(1, 5)
        unit = round(rng.uniform(3, 400) * (50 if currency == "PKR" else 1), 2)
        items.append({"description": desc, "quantity": float(qty), "unit_price": unit, "amount": round(qty * unit, 2)})
    subtotal = round(sum(x["amount"] for x in items), 2)
    tax_rate = rng.choice([0, 0.05, 0.1, 0.17])
    tax = round(subtotal * tax_rate, 2)
    total = round(subtotal + tax, 2)

    printed_total = total
    if i % 9 == 4:  # deliberate inconsistency printed on the document
        printed_total = round(total + rng.choice([10, 25.5, 100]), 2)

    W, H = 1240, 1754 if not is_receipt else 1400
    if is_receipt:
        W = 900  # wide enough that long totals (e.g. "GBP 12,345.67") are never clipped
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    big, mid, small = font(44 if not is_receipt else 30), font(26), font(22)
    y = 60
    d.text((60, y), vendor, fill="black", font=big); y += 70
    d.text((60, y), f"{rng.randint(10, 999)} Market Street, Suite {rng.randint(1, 40)}", fill="#333", font=small); y += 32
    tax_id = f"TAX-{rng.randint(100000, 999999)}" if rng.random() < 0.6 else None
    if tax_id:
        d.text((60, y), f"Tax ID: {tax_id}", fill="#333", font=small); y += 32
    y += 30
    d.text((60, y), "RECEIPT" if is_receipt else "INVOICE", fill="black", font=big); y += 70
    if inv_no:
        d.text((60, y), f"Invoice #: {inv_no}", fill="black", font=mid); y += 38
    date_fmt = rng.choice(["%Y-%m-%d", "%d %b %Y", "%B %d, %Y"])
    d.text((60, y), f"Date: {issued.strftime(date_fmt)}", fill="black", font=mid); y += 38
    if due:
        d.text((60, y), f"Due: {due.strftime(date_fmt)}", fill="black", font=mid); y += 38
    y += 30

    col_q, col_u, col_a = (W * 0.55, W * 0.68, W * 0.84) if not is_receipt else (W * 0.5, W * 0.62, W * 0.78)
    d.line((50, y, W - 50, y), fill="black", width=2); y += 12
    for label, x in (("Description", 60), ("Qty", col_q), ("Unit", col_u), ("Amount", col_a)):
        d.text((x, y), label, fill="black", font=mid)
    y += 40
    d.line((50, y, W - 50, y), fill="black", width=1); y += 14
    fmt = lambda v: f"{symbol}{v:,.2f}"  # noqa: E731
    for it in items:
        d.text((60, y), it["description"], fill="black", font=small)
        d.text((col_q, y), f"{int(it['quantity'])}", fill="black", font=small)
        d.text((col_u, y), f"{it['unit_price']:,.2f}", fill="black", font=small)
        d.text((col_a, y), fmt(it["amount"]), fill="black", font=small)
        y += 36
    y += 10
    d.line((W * 0.5, y, W - 50, y), fill="black", width=1); y += 16
    for label, v in (("Subtotal", subtotal), (f"Tax ({int(tax_rate * 100)}%)", tax), ("TOTAL", printed_total)):
        d.text((W * 0.55, y), label, fill="black", font=mid)
        d.text((col_a, y), fmt(v), fill="black", font=mid)
        y += 42
    y += 40
    d.text((60, y), "Thank you for your business!", fill="#555", font=small)

    # Photo-like degradation for some samples
    if i % 3 == 1:
        img = img.rotate(rng.uniform(-4, 4), expand=True, fillcolor="white")
    if i % 4 == 2:
        img = img.filter(ImageFilter.GaussianBlur(1.1))
    if i % 5 == 3:
        img = Image.blend(img, Image.new("RGB", img.size, (225, 215, 195)), 0.35)

    gt = {
        "doc_type": "receipt" if is_receipt else "invoice",
        "vendor_name": vendor,
        "vendor_tax_id": tax_id,
        "invoice_number": inv_no,
        "invoice_date": issued.isoformat(),
        "due_date": due.isoformat() if due else None,
        "currency": currency,
        "subtotal": subtotal,
        "tax": tax,
        "total": printed_total,
        "line_items": items,
        "category": category,
        "field_confidence": {"vendor_name": 0.98, "invoice_number": 0.97 if inv_no else 0.9,
                             "invoice_date": 0.96, "total": 0.98, "line_items": 0.95},
    }
    return img, gt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    rng = random.Random(args.seed)
    OUT_IMG.mkdir(parents=True, exist_ok=True)
    OUT_GT.mkdir(parents=True, exist_ok=True)
    for i in range(args.count):
        img, gt = make_one(i, rng)
        name = f"sample_{i + 1:03d}"
        img.save(OUT_IMG / f"{name}.png")
        (OUT_GT / f"{name}.json").write_text(json.dumps(gt, indent=2))
    print(f"Wrote {args.count} samples to {OUT_IMG.relative_to(ROOT)} and {OUT_GT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
