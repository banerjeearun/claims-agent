"""
LangGraph agent for claims-integrity review.

Architecture:
  1. Agent node — LLM with tool-calling decides which checks to run
  2. Tool node — executes lookup_coding_rules / score_amount_outlier
  3. Reasoning node — LLM consumes tool results, emits structured verdict

The agent returns: {decision, triggered_rules, rationale, confidence}
"""

import json
import os
import time
from pathlib import Path
from typing import Annotated, TypedDict

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from src.tools import lookup_coding_rules, score_amount_outlier

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Spacing between LLM calls to stay under 5 req/min rate limit
_last_call_time = 0.0
_MIN_INTERVAL = 13.0


def _paced_invoke(llm, messages):
    """Space out LLM calls to respect rate limits. The anthropic client
    handles 429 retries internally via max_retries."""
    global _last_call_time
    elapsed = time.time() - _last_call_time
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _last_call_time = time.time()
    return llm.invoke(messages)

# ---------------------------------------------------------------------------
# Wrap the tool functions so LangGraph can bind them to the LLM
# ---------------------------------------------------------------------------

@tool
def check_coding_rules(claim_json: str) -> str:
    """Check a claim against NCCI-style coding rules (PTP unbundling, MUE
    unit caps, mutually-exclusive edits, upcoding). Pass the full claim
    as a JSON string."""
    claim = json.loads(claim_json)
    violations = lookup_coding_rules(claim)
    if not violations:
        return "No coding-rule violations found."
    return json.dumps(violations, indent=2)


@tool
def check_amount_outlier(claim_json: str) -> str:
    """Score a claim's payment amount against reference norms for the
    procedure code. Pass the full claim as a JSON string."""
    claim = json.loads(claim_json)
    result = score_amount_outlier(claim)
    return json.dumps(result, indent=2)


TOOLS = [check_coding_rules, check_amount_outlier]

# ---------------------------------------------------------------------------
# Graph state
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    claim: dict
    verdict: dict | None


# ---------------------------------------------------------------------------
# Node functions
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a claims-integrity reviewer for a healthcare payer.
Your job is to analyze an insurance claim and determine whether it should be
FLAGGED for potential fraud, waste, or abuse (FWA), or PASSED as clean.

You have two tools:
1. check_coding_rules — checks the claim against NCCI-style edits (PTP
   unbundling, MUE unit caps, mutually-exclusive gender/age edits, upcoding)
2. check_amount_outlier — checks if the payment amount is a statistical
   outlier for the procedure code

ALWAYS call BOTH tools on every claim before making your decision. Pass the
full claim JSON to each tool.

After receiving tool results, provide your final verdict as a JSON object with
exactly these fields:
{
  "decision": "FLAG" or "PASS",
  "triggered_rules": ["list of specific rule violations found, empty if PASS"],
  "rationale": "plain-English explanation of why the claim is flagged or passed",
  "confidence": "HIGH" or "MEDIUM" or "LOW"
}

Be precise. Cite the specific edit type and codes involved. If no violations
are found and the amount is within norms, PASS the claim with confidence HIGH."""


def agent_node(state: AgentState) -> dict:
    """LLM decides which tools to call."""
    llm = ChatAnthropic(
        model="claude-sonnet-4-6",
        temperature=0,
        max_tokens=1024,
        max_retries=5,
    )
    llm_with_tools = llm.bind_tools(TOOLS)

    claim = state["claim"]
    claim_json = json.dumps(claim, indent=2)

    messages = state.get("messages", [])
    if not messages:
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=(
                f"Analyze this claim for potential FWA issues. "
                f"Call both tools, then give your verdict.\n\n"
                f"Claim:\n```json\n{claim_json}\n```"
            )),
        ]

    response = _paced_invoke(llm_with_tools, messages)
    return {"messages": [response]}


VERDICT_PROMPT = """Based on the claim analysis above, output ONLY a JSON object
(no markdown, no explanation, no code fences) with exactly these fields:

{
  "decision": "FLAG" or "PASS",
  "triggered_rules": ["list each specific violation found — empty list if PASS"],
  "rationale": "2-3 sentence plain-English explanation",
  "confidence": "HIGH" or "MEDIUM" or "LOW"
}"""


def reasoning_node(state: AgentState) -> dict:
    """Make a dedicated LLM call to extract a structured verdict."""
    messages = state["messages"]
    last_msg = messages[-1]
    analysis = last_msg.content if isinstance(last_msg.content, str) else str(last_msg.content)

    llm = ChatAnthropic(model="claude-sonnet-4-6", temperature=0, max_tokens=512, max_retries=5)
    response = _paced_invoke(llm, [
        SystemMessage(content="You output only valid JSON. No markdown, no commentary."),
        HumanMessage(content=f"Claim analysis:\n{analysis}\n\n{VERDICT_PROMPT}"),
    ])

    content = response.content if isinstance(response.content, str) else str(response.content)

    try:
        start = content.index("{")
        end = content.rindex("}") + 1
        verdict = json.loads(content[start:end])
    except (ValueError, json.JSONDecodeError):
        verdict = {
            "decision": "FLAG" if "flag" in content.lower() else "PASS",
            "triggered_rules": [],
            "rationale": analysis[:500],
            "confidence": "LOW",
        }

    return {"verdict": verdict}


def should_continue(state: AgentState) -> str:
    """Route: if the LLM wants to call tools, go to tools; otherwise reason."""
    last_msg = state["messages"][-1]
    if isinstance(last_msg, AIMessage) and last_msg.tool_calls:
        return "tools"
    return "reasoning"


# ---------------------------------------------------------------------------
# Build the graph
# ---------------------------------------------------------------------------

def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("agent", agent_node)
    graph.add_node("tools", ToolNode(TOOLS))
    graph.add_node("reasoning", reasoning_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", "reasoning": "reasoning"})
    graph.add_edge("tools", "agent")
    graph.add_edge("reasoning", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def review_claim(claim: dict) -> dict:
    """Run the agent on a single claim. Returns the full state including
    the verdict and message trace."""
    graph = build_graph()

    # Strip ground-truth fields so the agent doesn't see the answer
    agent_claim = {
        k: v for k, v in claim.items()
        if k not in ("ground_truth_label", "planted_violation", "planted_violation_type")
    }

    result = graph.invoke({
        "messages": [],
        "claim": agent_claim,
        "verdict": None,
    })
    return result
