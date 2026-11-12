"""Measure extraction accuracy against labelled ground truth.

    cd backend
    .venv/Scripts/python ../eval/run_eval.py                 # uses samples/ (synthetic)
    .venv/Scripts/python ../eval/run_eval.py --dataset ../eval/dataset --limit 10

A dataset folder holds documents (pdf/png/jpg) in `invoices/` and `<stem>.json` ground truth in
`ground_truth/` - the same layout `scripts/make_samples.py` writes. Uses the extractor configured
in backend/.env (EXTRACTOR=claude needs ANTHROPIC_API_KEY, EXTRACTOR=openai needs OPENAI_API_KEY;
both cost money. EXTRACTOR=mock is free but only meaningful as a smoke test). Override per run
with an env var, e.g. `set EXTRACTOR=openai` before running, to compare providers.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.pipeline.orchestrator import get_extractor, run_extraction  # noqa: E402
from app.pipeline.preprocess import SUPPORTED_EXTENSIONS, prepare, sha256_bytes  # noqa: E402
from app.schemas import InvoiceExtraction  # noqa: E402

KEY_FIELDS = ["vendor_name", "invoice_number", "invoice_date", "due_date", "currency", "subtotal", "tax", "total"]


def norm(v):
    if isinstance(v, str):
        return " ".join(v.lower().replace(",", "").replace(".", "").split())
    if isinstance(v, float):
        return round(v, 2)
    return v


def line_item_f1(pred: InvoiceExtraction, gold: dict) -> float:
    p = [round(li.amount, 2) for li in pred.line_items]
    g = [round(li["amount"], 2) for li in gold["line_items"]]
    if not p and not g:
        return 1.0
    remaining, tp = list(g), 0
    for a in p:
        if a in remaining:
            remaining.remove(a)
            tp += 1
    precision = tp / len(p) if p else 0
    recall = tp / len(g) if g else 0
    return 0.0 if tp == 0 else 2 * precision * recall / (precision + recall)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(ROOT / "samples"))
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    dataset = Path(args.dataset)
    settings = get_settings()

    docs = sorted(p for p in (dataset / "invoices").glob("*") if p.suffix.lower() in SUPPORTED_EXTENSIONS)
    docs = [d for d in docs if (dataset / "ground_truth" / f"{d.stem}.json").exists()]
    if args.limit:
        docs = docs[: args.limit]
    if not docs:
        sys.exit(f"No labelled documents in {dataset}. Run scripts/make_samples.py first.")

    field_hits = {f: 0 for f in KEY_FIELDS}
    f1s, auto, cost, latency, attempts, rows = [], 0, 0.0, 0, 0, []
    for path in docs:
        gold = json.loads((dataset / "ground_truth" / f"{path.stem}.json").read_text())
        outcome = run_extraction(
            prepare(path), get_extractor(sha256_bytes(path.read_bytes())), settings.max_correction_attempts
        )
        pred = outcome.data
        misses = []
        for f in KEY_FIELDS:
            if norm(getattr(pred, f)) == norm(gold.get(f)):
                field_hits[f] += 1
            else:
                misses.append(f"{f}: got {getattr(pred, f)!r}, want {gold.get(f)!r}")
        f1 = line_item_f1(pred, gold)
        f1s.append(f1)
        is_auto = not any(i.severity == "error" for i in outcome.issues) and outcome.confidence >= settings.auto_approve_threshold
        auto += is_auto
        cost += outcome.cost_usd
        latency += outcome.latency_ms
        attempts += outcome.attempts
        rows.append({"file": path.name, "auto_approved": is_auto, "confidence": outcome.confidence,
                     "attempts": outcome.attempts, "line_item_f1": round(f1, 3), "misses": misses,
                     "issues": [i.message for i in outcome.issues]})
        print(f"{path.name:28} conf={outcome.confidence:.2f} passes={outcome.attempts} "
              f"li_f1={f1:.2f} {'AUTO' if is_auto else 'REVIEW'} {'; '.join(misses)[:120]}")

    n = len(docs)
    summary = {
        "documents": n,
        "extractor": settings.extractor,
        "model": settings.active_model,
        "field_accuracy": {f: round(h / n, 3) for f, h in field_hits.items()},
        "line_item_f1": round(sum(f1s) / n, 3),
        "auto_approve_rate": round(auto / n, 3),
        "avg_passes": round(attempts / n, 2),
        "avg_cost_usd": round(cost / n, 5),
        "avg_latency_s": round(latency / n / 1000, 2),
    }
    print("\n| Metric | Value |\n|---|---|")
    for f, v in summary["field_accuracy"].items():
        print(f"| {f} exact match | {v:.1%} |")
    print(f"| Line-item F1 | {summary['line_item_f1']:.1%} |")
    print(f"| Auto-approve rate | {summary['auto_approve_rate']:.1%} |")
    print(f"| Avg passes | {summary['avg_passes']} |")
    print(f"| Avg cost / doc | ${summary['avg_cost_usd']:.4f} |")
    print(f"| Avg time / doc | {summary['avg_latency_s']}s |")

    out = ROOT / "eval" / "results"
    out.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (out / f"eval-{stamp}.json").write_text(json.dumps({"summary": summary, "documents": rows}, indent=2))
    print(f"\nSaved eval/results/eval-{stamp}.json")


if __name__ == "__main__":
    main()
