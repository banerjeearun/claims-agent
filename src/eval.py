"""Evaluate the claims-integrity agent over the full labeled dataset."""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.agent import review_claim


def load_claims() -> list[dict]:
    with open(Path(__file__).resolve().parent.parent / "data" / "claims.json") as f:
        return json.load(f)


def main():
    claims = load_claims()
    print(f"Evaluating agent on {len(claims)} claims...\n")

    results = []
    for i, claim in enumerate(claims):
        clm_id = claim["CLM_ID"]
        truth = claim["ground_truth_label"]
        sys.stdout.write(f"  [{i+1}/{len(claims)}] {clm_id} (truth={truth})...")
        sys.stdout.flush()

        try:
            t0 = time.time()
            result = review_claim(claim)
            elapsed = time.time() - t0
            predicted = result.get("verdict", {}).get("decision", "UNKNOWN")
            match = "✓" if predicted == truth else "✗"
            print(f" predicted={predicted} {match} ({elapsed:.1f}s)")
            results.append({
                "CLM_ID": clm_id,
                "truth": truth,
                "predicted": predicted,
                "verdict": result.get("verdict"),
                "correct": predicted == truth,
            })
        except Exception as e:
            print(f" ERROR: {e}")
            results.append({
                "CLM_ID": clm_id,
                "truth": truth,
                "predicted": "ERROR",
                "verdict": None,
                "correct": False,
            })

    # --- Compute metrics ---
    tp = sum(1 for r in results if r["truth"] == "FLAG" and r["predicted"] == "FLAG")
    tn = sum(1 for r in results if r["truth"] == "PASS" and r["predicted"] == "PASS")
    fp = sum(1 for r in results if r["truth"] == "PASS" and r["predicted"] == "FLAG")
    fn = sum(1 for r in results if r["truth"] == "FLAG" and r["predicted"] != "FLAG")

    total = len(results)
    accuracy = (tp + tn) / total if total else 0
    precision = tp / (tp + fp) if (tp + fp) else 0
    recall = tp / (tp + fn) if (tp + fn) else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0

    print("\n" + "=" * 50)
    print("EVALUATION RESULTS")
    print("=" * 50)
    print(f"\nConfusion Matrix:")
    print(f"                Predicted FLAG   Predicted PASS")
    print(f"  Actual FLAG       {tp:3d} (TP)         {fn:3d} (FN)")
    print(f"  Actual PASS       {fp:3d} (FP)         {tn:3d} (TN)")
    print(f"\nMetrics:")
    print(f"  Accuracy:  {accuracy:.1%}  ({tp+tn}/{total})")
    print(f"  Precision: {precision:.1%}  ({tp}/{tp+fp})")
    print(f"  Recall:    {recall:.1%}  ({tp}/{tp+fn})")
    print(f"  F1 Score:  {f1:.1%}")

    # Breakdown by violation type
    print(f"\nPer-violation-type recall:")
    type_counts: dict[str, dict] = {}
    for r in results:
        claim = next(c for c in claims if c["CLM_ID"] == r["CLM_ID"])
        vtype = claim.get("planted_violation_type")
        if vtype:
            if vtype not in type_counts:
                type_counts[vtype] = {"correct": 0, "total": 0}
            type_counts[vtype]["total"] += 1
            if r["correct"]:
                type_counts[vtype]["correct"] += 1
    for vtype, counts in sorted(type_counts.items()):
        pct = counts["correct"] / counts["total"] if counts["total"] else 0
        print(f"  {vtype:25s} {counts['correct']}/{counts['total']} ({pct:.0%})")

    # Misses detail
    misses = [r for r in results if not r["correct"]]
    if misses:
        print(f"\nMisclassified claims ({len(misses)}):")
        for r in misses:
            claim = next(c for c in claims if c["CLM_ID"] == r["CLM_ID"])
            print(f"  {r['CLM_ID']}: truth={r['truth']}, predicted={r['predicted']}")
            if r["verdict"]:
                print(f"    rationale: {r['verdict'].get('rationale', 'N/A')[:120]}")
    else:
        print(f"\nNo misclassifications — perfect score.")


if __name__ == "__main__":
    main()
