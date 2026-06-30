# Agentic Claims-Integrity Reviewer

A proof-of-concept explainable FWA (fraud, waste, and abuse) detection system for healthcare claims, built for the Cotiviti intern assessment (Topic 2: Clinical Decision Making & Pattern Recognition).

## How It Works

A LangGraph agent takes a single insurance claim (structured on the CMS DE-SynPUF Carrier schema) and runs two tools: (1) a **coding-rule checker** modeled on CMS NCCI edits — PTP unbundling pairs, MUE unit caps, mutually-exclusive gender edits, and upcoding detection — and (2) a **statistical outlier scorer** that flags payment amounts beyond 3 standard deviations from code-level norms. The agent synthesizes both tool outputs into a **FLAG / PASS** decision with the triggered rule(s), a plain-English rationale, and a confidence score.

Claims are synthetic and self-generated, but structured on CMS's DE-SynPUF schema — so the same pipeline runs on real claims data.

## Evaluation Results

| Metric    | Value |
|-----------|-------|
| Accuracy  | 97% (29/30) |
| Precision | 92% (12/13) |
| Recall    | 100% (12/12) |
| F1 Score  | 96% |

Evaluated on all 30 labeled claims (12 flagged, 18 clean). All four violation types detected correctly: upcoding, unbundling, mutually-exclusive gender mismatch, and MUE + amount outlier. One false positive (conservative bias — appropriate for FWA detection where missed fraud is costlier than a flagged clean claim).

## Setup

```bash
conda create -n cotiviti python=3.11 -y
conda activate cotiviti
pip install -r requirements.txt
cp .env.example .env   # add your Anthropic API key
```

## Usage

```bash
# Generate synthetic claims and coding rules
python src/generate_data.py

# Review a single claim (CLI)
python run.py CLM001

# Evaluate on the labeled dataset
python src/eval.py

# Launch the Streamlit UI
streamlit run app.py
```

## Project Structure

```
├── app.py                    # Streamlit UI
├── run.py                    # CLI entry point
├── data/
│   ├── claims.json           # 30 synthetic labeled claims
│   └── coding_rules.json     # ~13 NCCI-style edits
├── src/
│   ├── generate_data.py      # Builds claims + rules
│   ├── tools.py              # Agent tools (rule checker + outlier scorer)
│   ├── agent.py              # LangGraph agent + reasoning node
│   └── eval.py               # Evaluation script (precision/recall/F1)
├── report.docx               # Written report
└── deck.pptx                 # Slide deck
```

## Data & Methods

- **Data:** All claims are synthetic and self-generated. No real patient data or PHI. Schema modeled on the [CMS DE-SynPUF](https://www.cms.gov/data-research/statistics-trends-and-reports/medicare-claims-synthetic-public-use-files) Carrier claim structure.
- **Rules:** Curated subset of ~13 edits modeled on the [CMS NCCI](https://www.cms.gov/national-correct-coding-initiative-ncci) structure (PTP pairs, MUE caps, mutually-exclusive edits). Not the full ~3M-row production table.
- **Stack:** Python, LangGraph, Claude (Anthropic), Streamlit.
- **AI disclosure:** Claude Code was used as a development assistant for code scaffolding and iterative debugging. All work was reviewed, tested, and is defended by the author.
