"""
Agent tools for the claims-integrity reviewer.

Two tools that operate on DE-SynPUF-shaped claim records:
  1. lookup_coding_rules — checks a claim against the curated NCCI-style rule table
  2. score_amount_outlier — z-score check on payment amount and service units
"""

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_rules_cache: dict | None = None


def _load_rules() -> dict:
    global _rules_cache
    if _rules_cache is None:
        with open(DATA_DIR / "coding_rules.json") as f:
            _rules_cache = json.load(f)
    return _rules_cache


def lookup_coding_rules(claim: dict) -> list[dict]:
    """
    Check a claim against the curated NCCI-style coding rules.

    Returns a list of violation dicts, each with:
      - edit_type: "ptp" | "mue" | "mutually_exclusive" | "upcoding"
      - description: human-readable explanation of the violation
      - details: dict with the specific codes/values involved

    Returns an empty list if no violations are found.
    """
    rules = _load_rules()
    violations = []

    hcpcs = claim.get("HCPCS_CD")
    hcpcs_2 = claim.get("HCPCS_CD_2")
    diag = claim.get("ICD9_DGNS_CD_1")
    units = claim.get("LINE_SRVC_CNT", 1)
    sex = claim.get("BENE_SEX_IDENT_CD")

    # --- PTP unbundling check ---
    if hcpcs and hcpcs_2:
        code_pair = {hcpcs, hcpcs_2}
        ptp_edits = rules.get("ptp_edits", [])

        # Direct match: one code is column_1, the other is column_2
        for edit in ptp_edits:
            edit_pair = {edit["column_1"], edit["column_2"]}
            if code_pair == edit_pair:
                violations.append({
                    "edit_type": "ptp",
                    "description": (
                        f"Unbundling: {edit['column_2']} is a component of "
                        f"{edit['column_1']} (comprehensive) — "
                        f"modifier indicator {edit['modifier_indicator']}"
                    ),
                    "details": {
                        "column_1_comprehensive": edit["column_1"],
                        "column_2_component": edit["column_2"],
                        "modifier_indicator": edit["modifier_indicator"],
                        "rule_description": edit["description"],
                    },
                })

        # Cross-component: both billed codes are column_2 components of the
        # same column_1 comprehensive code (e.g. 58260+58720 → should be 58262)
        comp_to_parent: dict[str, list] = {}
        for edit in ptp_edits:
            comp_to_parent.setdefault(edit["column_2"], []).append(edit)
        if hcpcs in comp_to_parent and hcpcs_2 in comp_to_parent:
            parents_1 = {e["column_1"] for e in comp_to_parent[hcpcs]}
            parents_2 = {e["column_1"] for e in comp_to_parent[hcpcs_2]}
            shared = parents_1 & parents_2
            for parent in shared:
                violations.append({
                    "edit_type": "ptp",
                    "description": (
                        f"Unbundling: {hcpcs} and {hcpcs_2} are both "
                        f"components of {parent} (comprehensive) — "
                        f"billing them separately instead of the "
                        f"comprehensive code"
                    ),
                    "details": {
                        "column_1_comprehensive": parent,
                        "billed_components": [hcpcs, hcpcs_2],
                        "rule_description": (
                            f"Both {hcpcs} and {hcpcs_2} are column-2 "
                            f"components of comprehensive code {parent}"
                        ),
                    },
                })

    # --- MUE unit-cap check ---
    for mue in rules.get("mue_edits", []):
        if hcpcs == mue["hcpcs_cd"] and units > mue["max_units"]:
            violations.append({
                "edit_type": "mue",
                "description": (
                    f"MUE violation: {hcpcs} billed with {units} units "
                    f"(cap = {mue['max_units']})"
                ),
                "details": {
                    "hcpcs_cd": hcpcs,
                    "billed_units": units,
                    "max_units": mue["max_units"],
                    "rationale": mue["rationale"],
                },
            })

    # --- Mutually exclusive (gender) check ---
    for mx in rules.get("mutually_exclusive_edits", []):
        target_code = mx["hcpcs_cd"]
        if (hcpcs == target_code or hcpcs_2 == target_code) and sex != mx["requires_sex"]:
            sex_label = "male" if sex == 1 else "female"
            required_label = "female" if mx["requires_sex"] == 2 else "male"
            violations.append({
                "edit_type": "mutually_exclusive",
                "description": (
                    f"Mutually exclusive: {target_code} requires "
                    f"{required_label} patient but beneficiary is {sex_label}"
                ),
                "details": {
                    "hcpcs_cd": target_code,
                    "patient_sex": sex,
                    "required_sex": mx["requires_sex"],
                    "rule_description": mx["description"],
                },
            })

    # --- Upcoding check (E/M level vs diagnosis complexity) ---
    for uc in rules.get("upcoding_rules", []):
        if hcpcs == uc["high_code"] and diag in uc["low_complexity_diagnoses"]:
            violations.append({
                "edit_type": "upcoding",
                "description": (
                    f"Upcoding: {uc['high_code']} (high-complexity) billed "
                    f"with diagnosis {diag} — a low-acuity condition; "
                    f"{uc['appropriate_code']} is the appropriate level"
                ),
                "details": {
                    "billed_code": uc["high_code"],
                    "appropriate_code": uc["appropriate_code"],
                    "diagnosis": diag,
                    "rule_description": uc["description"],
                },
            })

    return violations


def score_amount_outlier(claim: dict) -> dict:
    """
    Score a claim's payment amount and service units against reference norms.

    Returns a dict with:
      - is_outlier: bool
      - payment_z_score: float (how many std devs above the mean)
      - details: dict with the reference values used
    """
    rules = _load_rules()
    ref_dists = rules.get("reference_distributions", {})

    hcpcs = claim.get("HCPCS_CD")
    amount = claim.get("LINE_NCH_PMT_AMT", 0)
    units = claim.get("LINE_SRVC_CNT", 1)

    ref = ref_dists.get(hcpcs)
    if ref is None:
        return {
            "is_outlier": False,
            "payment_z_score": 0.0,
            "details": {"note": f"No reference distribution for code {hcpcs}"},
        }

    mean = ref["mean_payment"]
    std = ref["std_payment"]

    z_score = (amount - mean) / std if std > 0 else 0.0

    # Flag if z-score > 3 (payment more than 3 std devs above mean)
    is_outlier = z_score > 3.0

    return {
        "is_outlier": is_outlier,
        "payment_z_score": round(z_score, 2),
        "details": {
            "hcpcs_cd": hcpcs,
            "billed_amount": amount,
            "reference_mean": mean,
            "reference_std": std,
            "billed_units": units,
            "threshold": "z > 3.0",
        },
    }
