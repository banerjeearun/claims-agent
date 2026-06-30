"""Streamlit UI for the claims-integrity reviewer."""

import json
from pathlib import Path

import streamlit as st

from src.agent import review_claim

DATA_DIR = Path(__file__).parent / "data"


@st.cache_data
def load_claims() -> list[dict]:
    with open(DATA_DIR / "claims.json") as f:
        return json.load(f)


st.set_page_config(page_title="Claims Integrity Reviewer", layout="wide")
st.title("Agentic Claims-Integrity Reviewer")
st.caption(
    "Explainable FWA flagging powered by a LangGraph agent with "
    "NCCI-style coding rules. All data is synthetic (CMS DE-SynPUF schema)."
)

claims = load_claims()
claim_ids = [c["CLM_ID"] for c in claims]

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Select a Claim")
    selected_id = st.selectbox("Claim ID", claim_ids)
    claim = next(c for c in claims if c["CLM_ID"] == selected_id)

    st.markdown("**Claim Details**")
    st.markdown(f"- **HCPCS Code:** `{claim['HCPCS_CD']}`"
                + (f" + `{claim['HCPCS_CD_2']}`" if claim.get("HCPCS_CD_2") else ""))
    st.markdown(f"- **Diagnosis:** `{claim['ICD9_DGNS_CD_1']}`")
    st.markdown(f"- **Amount:** ${claim['LINE_NCH_PMT_AMT']:.2f}")
    st.markdown(f"- **Units:** {claim['LINE_SRVC_CNT']}")
    st.markdown(f"- **Patient Sex:** {'Male' if claim['BENE_SEX_IDENT_CD'] == 1 else 'Female'}")
    st.markdown(f"- **DOB:** {claim['BENE_BIRTH_DT']}")

    if claim.get("ground_truth_label"):
        label = claim["ground_truth_label"]
        color = "red" if label == "FLAG" else "green"
        st.markdown(f"- **Ground Truth:** :{color}[{label}]")

    run_btn = st.button("Review Claim", type="primary", use_container_width=True)

with col2:
    if run_btn:
        with st.spinner("Agent is reviewing the claim..."):
            result = review_claim(claim)

        verdict = result.get("verdict", {})
        decision = verdict.get("decision", "UNKNOWN")

        # Verdict banner
        if decision == "FLAG":
            st.error(f"Decision: **{decision}** — Confidence: {verdict.get('confidence', 'N/A')}")
        else:
            st.success(f"Decision: **{decision}** — Confidence: {verdict.get('confidence', 'N/A')}")

        # Rationale
        st.subheader("Rationale")
        st.write(verdict.get("rationale", "No rationale provided."))

        # Triggered rules
        triggered = verdict.get("triggered_rules", [])
        if triggered:
            st.subheader("Triggered Rules")
            for rule in triggered:
                st.markdown(f"- {rule}")

        # Reasoning trace
        with st.expander("Full Reasoning Trace", expanded=False):
            for msg in result["messages"]:
                role = msg.__class__.__name__.replace("Message", "")
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    st.markdown(f"**{role}** — calling tools:")
                    for tc in msg.tool_calls:
                        st.code(tc["name"], language=None)
                elif hasattr(msg, "name") and msg.name:
                    st.markdown(f"**Tool: {msg.name}**")
                    st.code(msg.content[:600] if len(msg.content) > 600 else msg.content,
                            language="json")
                else:
                    content = msg.content if isinstance(msg.content, str) else str(msg.content)
                    st.markdown(f"**{role}**")
                    st.write(content[:800] if len(content) > 800 else content)

        # Raw verdict JSON
        with st.expander("Raw Verdict JSON"):
            st.json(verdict)
    else:
        st.info("Select a claim and click **Review Claim** to run the agent.")
