"""
Generate synthetic claims and coding rules for the claims-integrity agent.

Claims are structured on the CMS DE-SynPUF Carrier schema. All data is
synthetic and self-generated — no real patient data or PHI.

Rule table is modeled on the CMS NCCI edit structure (PTP pairs, MUE caps,
mutually-exclusive edits) with a curated subset of ~12 representative edits.
"""

import json
import os
import random
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# ---------------------------------------------------------------------------
# Code vocabularies — every code here must be explainable on camera
# ---------------------------------------------------------------------------

# CPT/HCPCS procedure codes
PROCEDURE_CODES = {
    "99213": "Office visit, established patient, low complexity",
    "99214": "Office visit, established patient, moderate complexity",
    "99215": "Office visit, established patient, high complexity",
    "80053": "Comprehensive metabolic panel (CMP)",
    "80048": "Basic metabolic panel (BMP)",
    "36415": "Venipuncture (routine blood draw)",
    "71046": "Chest X-ray, 2 views",
    "93000": "Electrocardiogram (ECG), complete",
    "93005": "Electrocardiogram (ECG), tracing only",
    "58262": "Vaginal hysterectomy with removal of tube(s)/ovary(ies)",
    "58260": "Vaginal hysterectomy (component)",
    "58720": "Salpingo-oophorectomy (removal of fallopian tubes and ovaries)",
    "59400": "Routine obstetric care (prenatal + delivery + postpartum)",
    "59025": "Fetal non-stress test",
    "99283": "Emergency department visit, moderate severity",
}

# ICD-10-CM diagnosis codes (field named ICD9_DGNS_CD_1 per DE-SynPUF convention)
DIAGNOSIS_CODES = {
    "I10":    "Essential hypertension",
    "E11.9":  "Type 2 diabetes mellitus without complications",
    "R07.9":  "Chest pain, unspecified",
    "Z34.90": "Supervision of normal pregnancy, unspecified trimester",
    "M54.5":  "Low back pain",
    "J20.9":  "Acute bronchitis, unspecified",
    "J02.9":  "Acute pharyngitis, unspecified",
    "R50.9":  "Fever, unspecified",
    "N95.1":  "Menopausal and female climacteric states",
    "K21.0":  "Gastroesophageal reflux disease with esophagitis",
}

# Diagnoses too simple to justify a high-complexity visit (99215)
LOW_COMPLEXITY_DIAGNOSES = {"J02.9", "J20.9", "R50.9", "M54.5", "K21.0"}

# ---------------------------------------------------------------------------
# Build the coding-rules table (~12 edits, modeled on NCCI structure)
# ---------------------------------------------------------------------------


def build_coding_rules() -> dict:
    """Return a dict of curated NCCI-style edits for the rule engine."""

    rules = {
        "_meta": {
            "description": (
                "Curated subset of ~12 NCCI-style edits for the POC. "
                "Modeled on the CMS National Correct Coding Initiative "
                "structure; not the full ~3M-row production table."
            ),
            "code_vocabulary": PROCEDURE_CODES,
            "diagnosis_vocabulary": DIAGNOSIS_CODES,
        },

        # --- PTP (Procedure-to-Procedure) unbundling edits ---
        # Column 1 = comprehensive (payable), Column 2 = component (denied)
        # Modifier indicator: 0 = never unbundle, 1 = allowed with modifier, 9 = deleted
        "ptp_edits": [
            {
                "column_1": "58262",
                "column_2": "58260",
                "modifier_indicator": 0,
                "description": (
                    "Vaginal hysterectomy with tube/ovary removal (58262) "
                    "is comprehensive; vaginal hysterectomy alone (58260) "
                    "is a component — cannot be billed separately"
                ),
            },
            {
                "column_1": "58262",
                "column_2": "58720",
                "modifier_indicator": 0,
                "description": (
                    "Vaginal hysterectomy with tube/ovary removal (58262) "
                    "includes salpingo-oophorectomy (58720) — cannot unbundle"
                ),
            },
            {
                "column_1": "80053",
                "column_2": "80048",
                "modifier_indicator": 0,
                "description": (
                    "Comprehensive metabolic panel (80053) includes all "
                    "components of basic metabolic panel (80048)"
                ),
            },
            {
                "column_1": "93000",
                "column_2": "93005",
                "modifier_indicator": 1,
                "description": (
                    "Complete ECG (93000) includes tracing (93005); "
                    "may unbundle with documented modifier"
                ),
            },
        ],

        # --- MUE (Medically Unlikely Edits) — max units per line per day ---
        "mue_edits": [
            {"hcpcs_cd": "99213", "max_units": 1,
             "rationale": "One E/M office visit per beneficiary per day"},
            {"hcpcs_cd": "99214", "max_units": 1,
             "rationale": "One E/M office visit per beneficiary per day"},
            {"hcpcs_cd": "99215", "max_units": 1,
             "rationale": "One E/M office visit per beneficiary per day"},
            {"hcpcs_cd": "80053", "max_units": 1,
             "rationale": "One comprehensive metabolic panel per encounter"},
            {"hcpcs_cd": "36415", "max_units": 3,
             "rationale": "Venipuncture; up to 3 sites plausible per encounter"},
        ],

        # --- Mutually exclusive edits (gender / age) ---
        "mutually_exclusive_edits": [
            {"hcpcs_cd": "59400", "requires_sex": 2,
             "description": "Obstetric care — female patients only"},
            {"hcpcs_cd": "59025", "requires_sex": 2,
             "description": "Fetal non-stress test — female patients only"},
            {"hcpcs_cd": "58262", "requires_sex": 2,
             "description": "Hysterectomy — female patients only"},
        ],

        # --- Upcoding rules (E/M level vs diagnosis complexity) ---
        "upcoding_rules": [
            {
                "high_code": "99215",
                "appropriate_code": "99213",
                "low_complexity_diagnoses": sorted(LOW_COMPLEXITY_DIAGNOSES),
                "description": (
                    "High-complexity E/M visit (99215) not supported by "
                    "a low-acuity diagnosis; 99213 is the appropriate level"
                ),
            },
        ],

        # --- Reference distributions for amount/unit outlier scoring ---
        # mean and std of LINE_NCH_PMT_AMT per HCPCS code (synthetic norms)
        "reference_distributions": {
            "99213": {"mean_payment": 85.0,  "std_payment": 20.0},
            "99214": {"mean_payment": 125.0, "std_payment": 25.0},
            "99215": {"mean_payment": 175.0, "std_payment": 35.0},
            "80053": {"mean_payment": 22.0,  "std_payment": 6.0},
            "80048": {"mean_payment": 18.0,  "std_payment": 5.0},
            "36415": {"mean_payment": 8.0,   "std_payment": 3.0},
            "71046": {"mean_payment": 45.0,  "std_payment": 12.0},
            "93000": {"mean_payment": 35.0,  "std_payment": 10.0},
            "93005": {"mean_payment": 20.0,  "std_payment": 6.0},
            "58262": {"mean_payment": 850.0, "std_payment": 150.0},
            "58260": {"mean_payment": 650.0, "std_payment": 120.0},
            "58720": {"mean_payment": 450.0, "std_payment": 100.0},
            "59400": {"mean_payment": 3200.0, "std_payment": 600.0},
            "59025": {"mean_payment": 120.0, "std_payment": 30.0},
            "99283": {"mean_payment": 250.0, "std_payment": 60.0},
        },
    }
    return rules


# ---------------------------------------------------------------------------
# Build the synthetic claims (~30 total, ~40% flagged)
# ---------------------------------------------------------------------------

def _claim(
    clm_id: str,
    ben_id: str,
    from_dt: str,
    thru_dt: str,
    hcpcs: str,
    hcpcs_2: str | None,
    diag: str,
    amount: float,
    units: int,
    sex: int,
    birth_dt: str,
    label: str,
    violation: str | None,
    violation_type: str | None,
) -> dict:
    """Construct a single DE-SynPUF-shaped claim record."""
    return {
        "CLM_ID": clm_id,
        "DESYNPUF_ID": ben_id,
        "CLM_FROM_DT": from_dt,
        "CLM_THRU_DT": thru_dt,
        "HCPCS_CD": hcpcs,
        "HCPCS_CD_2": hcpcs_2,
        "ICD9_DGNS_CD_1": diag,
        "LINE_NCH_PMT_AMT": amount,
        "LINE_SRVC_CNT": units,
        "BENE_SEX_IDENT_CD": sex,
        "BENE_BIRTH_DT": birth_dt,
        "ground_truth_label": label,
        "planted_violation": violation,
        "planted_violation_type": violation_type,
    }


def build_claims() -> list[dict]:
    """Generate ~30 synthetic claims with planted FWA violations."""
    claims = []

    # ===== FLAGGED CLAIMS (12) =====

    # --- Upcoding (3 claims) ---
    claims.append(_claim(
        "CLM001", "BEN10001", "2024-03-15", "2024-03-15",
        "99215", None, "J02.9", 170.00, 1, 1, "1978-06-12",
        "FLAG", "Upcoding: 99215 billed for pharyngitis (low-acuity); 99213 appropriate",
        "upcoding",
    ))
    claims.append(_claim(
        "CLM002", "BEN10002", "2024-04-22", "2024-04-22",
        "99215", None, "J20.9", 180.00, 1, 2, "1985-11-03",
        "FLAG", "Upcoding: 99215 billed for acute bronchitis (low-acuity); 99213 appropriate",
        "upcoding",
    ))
    claims.append(_claim(
        "CLM003", "BEN10003", "2024-05-10", "2024-05-10",
        "99215", None, "M54.5", 165.00, 1, 1, "1960-02-28",
        "FLAG", "Upcoding: 99215 billed for low back pain (low-acuity); 99213 appropriate",
        "upcoding",
    ))

    # --- Unbundling / PTP violations (3 claims) ---
    claims.append(_claim(
        "CLM004", "BEN10004", "2024-06-18", "2024-06-18",
        "58260", "58720", "N95.1", 1100.00, 1, 2, "1962-09-14",
        "FLAG",
        "Unbundling (PTP): 58260 + 58720 billed separately; "
        "should be comprehensive 58262 (modifier indicator 0 — cannot unbundle)",
        "unbundling",
    ))
    claims.append(_claim(
        "CLM005", "BEN10005", "2024-07-02", "2024-07-02",
        "80053", "80048", "E11.9", 40.00, 1, 2, "1970-04-19",
        "FLAG",
        "Unbundling (PTP): 80053 + 80048 billed together; "
        "BMP (80048) is a component of CMP (80053) — cannot bill both",
        "unbundling",
    ))
    claims.append(_claim(
        "CLM006", "BEN10006", "2024-08-11", "2024-08-11",
        "93000", "93005", "R07.9", 55.00, 1, 1, "1955-12-01",
        "FLAG",
        "Unbundling (PTP): 93000 + 93005 billed together; "
        "complete ECG (93000) includes tracing (93005) — modifier indicator 1, "
        "but no modifier documented",
        "unbundling",
    ))

    # --- Mutually exclusive / gender mismatch (2 claims) ---
    claims.append(_claim(
        "CLM007", "BEN10007", "2024-03-28", "2024-03-28",
        "59400", None, "Z34.90", 3100.00, 1, 1, "1990-07-22",
        "FLAG",
        "Mutually exclusive: obstetric care (59400) billed for male patient "
        "(BENE_SEX_IDENT_CD=1)",
        "mutually_exclusive",
    ))
    claims.append(_claim(
        "CLM008", "BEN10008", "2024-09-05", "2024-09-05",
        "58262", None, "N95.1", 820.00, 1, 1, "1965-03-10",
        "FLAG",
        "Mutually exclusive: hysterectomy (58262) billed for male patient "
        "(BENE_SEX_IDENT_CD=1)",
        "mutually_exclusive",
    ))

    # --- MUE violations (2 claims) ---
    claims.append(_claim(
        "CLM009", "BEN10009", "2024-04-14", "2024-04-14",
        "99213", None, "I10", 340.00, 4, 2, "1972-08-30",
        "FLAG",
        "MUE violation: 99213 billed with 4 units (MUE cap = 1 per day); "
        "amount also elevated ($340 vs mean $85)",
        "mue",
    ))
    claims.append(_claim(
        "CLM010", "BEN10010", "2024-10-20", "2024-10-20",
        "80053", None, "E11.9", 110.00, 5, 1, "1968-01-15",
        "FLAG",
        "MUE violation: 80053 billed with 5 units (MUE cap = 1 per encounter)",
        "mue",
    ))

    # --- Amount outlier (2 claims) ---
    claims.append(_claim(
        "CLM011", "BEN10011", "2024-05-30", "2024-05-30",
        "99213", None, "K21.0", 450.00, 1, 1, "1980-10-05",
        "FLAG",
        "Amount outlier: $450 for 99213 office visit (mean $85, >18 std devs)",
        "amount_outlier",
    ))
    claims.append(_claim(
        "CLM012", "BEN10012", "2024-11-12", "2024-11-12",
        "36415", None, "E11.9", 120.00, 8, 2, "1975-06-28",
        "FLAG",
        "MUE + amount outlier: 36415 with 8 units (MUE cap = 3) and $120 "
        "(mean $8); combined violation",
        "mue",
    ))

    # ===== CLEAN CLAIMS (18) =====

    # Routine office visits with appropriate diagnoses
    claims.append(_claim(
        "CLM013", "BEN10013", "2024-03-20", "2024-03-20",
        "99213", None, "I10", 82.00, 1, 1, "1958-04-11",
        "PASS", None, None,
    ))
    claims.append(_claim(
        "CLM014", "BEN10014", "2024-04-05", "2024-04-05",
        "99213", None, "J02.9", 90.00, 1, 2, "1992-12-18",
        "PASS", None, None,
    ))
    claims.append(_claim(
        "CLM015", "BEN10015", "2024-05-12", "2024-05-12",
        "99214", None, "E11.9", 130.00, 1, 1, "1965-09-25",
        "PASS", None, None,
    ))
    claims.append(_claim(
        "CLM016", "BEN10016", "2024-06-01", "2024-06-01",
        "99214", None, "I10", 118.00, 1, 2, "1970-03-07",
        "PASS", None, None,
    ))
    claims.append(_claim(
        "CLM017", "BEN10017", "2024-07-15", "2024-07-15",
        "99215", None, "R07.9", 185.00, 1, 1, "1948-11-20",
        "PASS", None, None,
    ))
    claims.append(_claim(
        "CLM018", "BEN10018", "2024-08-22", "2024-08-22",
        "99215", None, "E11.9", 170.00, 1, 2, "1955-07-14",
        "PASS", None, None,
    ))

    # Lab work — appropriate units and amounts
    claims.append(_claim(
        "CLM019", "BEN10019", "2024-03-10", "2024-03-10",
        "80053", None, "E11.9", 24.00, 1, 1, "1963-05-02",
        "PASS", None, None,
    ))
    claims.append(_claim(
        "CLM020", "BEN10020", "2024-04-18", "2024-04-18",
        "80048", None, "I10", 16.00, 1, 2, "1978-08-30",
        "PASS", None, None,
    ))
    claims.append(_claim(
        "CLM021", "BEN10021", "2024-09-25", "2024-09-25",
        "36415", None, "E11.9", 9.00, 1, 1, "1960-01-19",
        "PASS", None, None,
    ))
    claims.append(_claim(
        "CLM022", "BEN10022", "2024-10-08", "2024-10-08",
        "36415", None, "I10", 7.50, 2, 2, "1982-11-27",
        "PASS", None, None,
    ))

    # Imaging and cardiac
    claims.append(_claim(
        "CLM023", "BEN10023", "2024-05-20", "2024-05-20",
        "71046", None, "R07.9", 48.00, 1, 1, "1950-06-15",
        "PASS", None, None,
    ))
    claims.append(_claim(
        "CLM024", "BEN10024", "2024-06-30", "2024-06-30",
        "93000", None, "R07.9", 38.00, 1, 2, "1967-02-09",
        "PASS", None, None,
    ))

    # Gender-appropriate gynecologic / obstetric codes on female patients
    claims.append(_claim(
        "CLM025", "BEN10025", "2024-07-22", "2024-07-22",
        "58262", None, "N95.1", 880.00, 1, 2, "1960-04-03",
        "PASS", None, None,
    ))
    claims.append(_claim(
        "CLM026", "BEN10026", "2024-08-15", "2024-08-15",
        "59400", None, "Z34.90", 3300.00, 1, 2, "1995-10-12",
        "PASS", None, None,
    ))
    claims.append(_claim(
        "CLM027", "BEN10027", "2024-09-10", "2024-09-10",
        "59025", None, "Z34.90", 115.00, 1, 2, "1993-03-28",
        "PASS", None, None,
    ))

    # Emergency department visit
    claims.append(_claim(
        "CLM028", "BEN10028", "2024-11-02", "2024-11-02",
        "99283", None, "R07.9", 260.00, 1, 1, "1945-12-05",
        "PASS", None, None,
    ))

    # Additional routine visits
    claims.append(_claim(
        "CLM029", "BEN10029", "2024-11-18", "2024-11-18",
        "99213", None, "M54.5", 78.00, 1, 2, "1988-09-14",
        "PASS", None, None,
    ))
    claims.append(_claim(
        "CLM030", "BEN10030", "2024-12-03", "2024-12-03",
        "99214", None, "K21.0", 122.00, 1, 1, "1973-07-21",
        "PASS", None, None,
    ))

    return claims


# ---------------------------------------------------------------------------
# Main — write both JSON files
# ---------------------------------------------------------------------------

def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    rules = build_coding_rules()
    claims = build_claims()

    rules_path = DATA_DIR / "coding_rules.json"
    claims_path = DATA_DIR / "claims.json"

    with open(rules_path, "w") as f:
        json.dump(rules, f, indent=2)

    with open(claims_path, "w") as f:
        json.dump(claims, f, indent=2)

    # Summary
    flagged = sum(1 for c in claims if c["ground_truth_label"] == "FLAG")
    clean = len(claims) - flagged
    violation_types = {}
    for c in claims:
        vt = c.get("planted_violation_type")
        if vt:
            violation_types[vt] = violation_types.get(vt, 0) + 1

    print(f"Generated {len(claims)} claims: {flagged} flagged, {clean} clean")
    print(f"Violation breakdown: {violation_types}")
    print(f"Rule table: {len(rules['ptp_edits'])} PTP edits, "
          f"{len(rules['mue_edits'])} MUE edits, "
          f"{len(rules['mutually_exclusive_edits'])} mutually-exclusive edits, "
          f"{len(rules['upcoding_rules'])} upcoding rules")
    print(f"\nWritten to:\n  {rules_path}\n  {claims_path}")


if __name__ == "__main__":
    main()
