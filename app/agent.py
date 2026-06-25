import os
import re
import sys
import json
import datetime
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.apps import App, ResumabilityConfig
from google.adk.models import Gemini
from google.adk.workflow import Workflow, Edge, FunctionNode, START
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.agents.context import Context
from google.adk.tools import AgentTool
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters
from google.genai import types

from app.config import config

# Disable Vertex AI
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "False"

# LLM model
model_instance = Gemini(
    model=config.model,
    retry_options=types.HttpRetryOptions(attempts=config.max_iterations),
)

# MCP Toolset
mcp_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=["-m", "app.mcp_server"],
        ),
    ),
)

# ---------------------------
# SUB AGENTS
# ---------------------------

ticket_classifier = LlmAgent(
    name="ticket_classifier",
    model=model_instance,
    instruction="""
You are a ticket classification assistant.

Classify the support ticket:
1. Category: Billing, Technical, or General
2. Priority: High, Medium, Low

Output format:
Category: <category>
Priority: <priority>
Reason: <short reason>
""",
)

resolution_drafter = LlmAgent(
    name="resolution_drafter",
    model=model_instance,
    instruction="""
You are a resolution drafter assistant.

Write a professional support response.

Use MCP tools if needed.

Output format:
Dear Customer,
<response>
Best regards,
Support Team
""",
    tools=[mcp_toolset],
)

# ---------------------------
# ORCHESTRATOR
# ---------------------------

orchestrator_agent = LlmAgent(
    name="orchestrator",
    model=model_instance,
    instruction="""
You are a support ticket orchestrator.

Steps:
1. Classify ticket (ticket_classifier)
2. Check system status (MCP tool: get_system_status)
3. Draft resolution (resolution_drafter)

FINAL OUTPUT FORMAT (STRICT):
CATEGORY: <category>
PRIORITY: <priority>
RESOLUTION: <resolution>
""",
    tools=[AgentTool(ticket_classifier), AgentTool(resolution_drafter), mcp_toolset],
)

# ---------------------------
# WORKFLOW NODES
# ---------------------------

def security_checkpoint(ctx: Context, node_input: types.Content):
    text = ""

    if node_input and hasattr(node_input, "parts"):
        text = "".join(p.text for p in node_input.parts if p.text)
    else:
        text = str(node_input)

    # PII detection
    ssn_pattern = r"\b\d{3}-\d{2}-\d{4}\b"
    cc_pattern = r"\b(?:\d[ -]*?){13,16}\b"

    scrubbed_text = text
    pii_found = False

    if re.search(ssn_pattern, text):
        scrubbed_text = re.sub(ssn_pattern, "[REDACTED-SSN]", scrubbed_text)
        pii_found = True

    if re.search(cc_pattern, text):
        scrubbed_text = re.sub(cc_pattern, "[REDACTED-CARD]", scrubbed_text)
        pii_found = True

    if pii_found:
        print(json.dumps({
            "event": "PII_REDACTION",
            "severity": "WARNING",
            "time": str(datetime.datetime.now())
        }))
        ctx.state["scrubbed_input"] = scrubbed_text
    else:
        ctx.state["scrubbed_input"] = text

    # Prompt injection detection
    injection_keywords = [
        "ignore previous instructions",
        "system prompt",
        "bypass security",
        "override role"
    ]

    for kw in injection_keywords:
        if kw in text.lower():
            ctx.state["security_violation"] = f"Injection detected: {kw}"
            return Event(output=text, route="security_event")

    # Credential detection
    if re.search(r"(password|api_key|secret_key)", text, re.IGNORECASE):
        ctx.state["security_violation"] = "Credentials detected"
        return Event(output=text, route="security_event")

    return Event(output=scrubbed_text, route="clean")


def review_decision(ctx: Context, node_input: Any):
    text = ""

    # handle both Content and string safely
    if hasattr(node_input, "parts"):
        text = "".join(p.text for p in node_input.parts if p.text)
    else:
        text = str(node_input)

    ctx.state["orchestrator_output"] = text

    priority_match = re.search(r"PRIORITY:\s*(\w+)", text, re.IGNORECASE)
    priority = priority_match.group(1).capitalize() if priority_match else "Low"

    category_match = re.search(r"CATEGORY:\s*(\w+)", text, re.IGNORECASE)
    category = category_match.group(1).capitalize() if category_match else "General"

    resolution_match = re.search(r"RESOLUTION:\s*(.*)", text, re.DOTALL | re.IGNORECASE)
    resolution = resolution_match.group(1).strip() if resolution_match else text

    ctx.state["priority"] = priority
    ctx.state["category"] = category
    ctx.state["resolution"] = resolution

    print(json.dumps({
        "event": "REVIEW_DECISION",
        "category": category,
        "priority": priority
    }))

    if priority == "High":
        return Event(output=resolution, route="needs_review")

    return Event(output=resolution, route="auto_approved")


async def human_review(ctx: Context, node_input: str):
    if not ctx.resume_inputs:
        yield RequestInput(
            interrupt_id="approve_resolution",
            message=f"🚨 HUMAN REVIEW REQUIRED\n\n{node_input}\n\nApprove? (yes/no)"
        )
        return

    approval = ctx.resume_inputs.get("approve_resolution", "").lower()

    if "yes" in approval or "approve" in approval:
        ctx.state["review_status"] = "Approved"
        yield Event(output=node_input, state={"review_status": "Approved"})
    else:
        ctx.state["review_status"] = "Rejected"
        yield Event(output="Rejected by human reviewer", state={"review_status": "Rejected"})


def final_output(ctx: Context, node_input: Any):
    if ctx.state.get("security_violation"):
        msg = ctx.state["security_violation"]
        text = f"⚠️ BLOCKED\nReason: {msg}"

        yield Event(
            content=types.Content(
                role="model",
                parts=[types.Part.from_text(text=text)]
            )
        )
        yield Event(output=text)
        return

    response = f"""
### Support Ticket Summary
- Category: {ctx.state.get('category', 'General')}
- Priority: {ctx.state.get('priority', 'Low')}
- Status: {ctx.state.get('review_status', 'Auto-Approved')}

### Resolution:
{node_input}
"""

    yield Event(
        content=types.Content(
            role="model",
            parts=[types.Part.from_text(text=response)]
        )
    )
    yield Event(output=response)


# ---------------------------
# FUNCTION NODES
# ---------------------------

_security_checkpoint_node = FunctionNode(func=security_checkpoint)
_review_decision_node = FunctionNode(func=review_decision)
_human_review_node = FunctionNode(func=human_review, rerun_on_resume=True)
_final_output_node = FunctionNode(func=final_output)

# ---------------------------
# WORKFLOW
# ---------------------------

root_agent = Workflow(
    name="support_triage_workflow",
    edges=[
        Edge(from_node=START, to_node=_security_checkpoint_node),
        Edge(from_node=_security_checkpoint_node, to_node=orchestrator_agent, route="clean"),
        Edge(from_node=_security_checkpoint_node, to_node=_final_output_node, route="security_event"),

        Edge(from_node=orchestrator_agent, to_node=_review_decision_node),
        Edge(from_node=_review_decision_node, to_node=_human_review_node, route="needs_review"),
        Edge(from_node=_review_decision_node, to_node=_final_output_node, route="auto_approved"),

        Edge(from_node=_human_review_node, to_node=_final_output_node),
    ],
)

app = App(
    root_agent=root_agent,
    name="app",
    resumability_config=ResumabilityConfig(is_resumable=True)
)