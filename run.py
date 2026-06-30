"""CLI entry point — review a single claim and print the reasoning trace."""

import json
import sys
from pathlib import Path

from src.agent import review_claim


def load_claims() -> list[dict]:
    with open(Path(__file__).parent / "data" / "claims.json") as f:
        return json.load(f)


def print_trace(result: dict) -> None:
    """Print the agent's message trace and final verdict."""
    print("\n" + "=" * 60)
    print("REASONING TRACE")
    print("=" * 60)

    for msg in result["messages"]:
        role = msg.__class__.__name__.replace("Message", "")
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            print(f"\n[{role}] Calling tools:")
            for tc in msg.tool_calls:
                print(f"  → {tc['name']}")
        elif hasattr(msg, "name") and msg.name:
            content = msg.content if len(msg.content) < 300 else msg.content[:300] + "..."
            print(f"\n[Tool: {msg.name}]\n  {content}")
        else:
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
            if len(content) > 500:
                content = content[:500] + "..."
            print(f"\n[{role}]\n  {content}")

    print("\n" + "=" * 60)
    print("VERDICT")
    print("=" * 60)
    verdict = result.get("verdict", {})
    print(json.dumps(verdict, indent=2))


def main():
    claims = load_claims()

    if len(sys.argv) > 1:
        clm_id = sys.argv[1].upper()
        claim = next((c for c in claims if c["CLM_ID"] == clm_id), None)
        if not claim:
            print(f"Claim {clm_id} not found. Available: {[c['CLM_ID'] for c in claims]}")
            sys.exit(1)
    else:
        claim = claims[0]
        print(f"No claim ID specified — using {claim['CLM_ID']}. "
              f"Usage: python run.py CLM001")

    print(f"\nReviewing claim {claim['CLM_ID']}...")
    print(f"  HCPCS: {claim['HCPCS_CD']}"
          + (f" + {claim['HCPCS_CD_2']}" if claim.get("HCPCS_CD_2") else ""))
    print(f"  Diagnosis: {claim['ICD9_DGNS_CD_1']}")
    print(f"  Amount: ${claim['LINE_NCH_PMT_AMT']:.2f}")
    print(f"  Units: {claim['LINE_SRVC_CNT']}")
    print(f"  Sex: {'Male' if claim['BENE_SEX_IDENT_CD'] == 1 else 'Female'}")

    result = review_claim(claim)
    print_trace(result)

    if "ground_truth_label" in claim:
        truth = claim["ground_truth_label"]
        predicted = result.get("verdict", {}).get("decision", "?")
        match = "CORRECT" if predicted == truth else "INCORRECT"
        print(f"\nGround truth: {truth} | Predicted: {predicted} | {match}")


if __name__ == "__main__":
    main()
