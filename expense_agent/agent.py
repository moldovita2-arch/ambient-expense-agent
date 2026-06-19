# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import json
import re
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.apps import App
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.workflow import START, Workflow
from google.genai import types
from pydantic import BaseModel, Field

from expense_agent.config import APPROVAL_THRESHOLD, MODEL_NAME

# ==============================================================================
# Pydantic Schemas for Input, Output, and State
# ==============================================================================


class ExpenseReport(BaseModel):
    amount: float
    submitter: str
    category: str
    description: str
    date: str


class RiskReviewOutput(BaseModel):
    risk_score: int = Field(description="Risk score from 1 to 10")
    risk_factors: list[str] = Field(description="List of identified risk factors")
    risk_summary: str = Field(description="Brief summary of the risk review")


# ==============================================================================
# Workflow Nodes (Functions)
# ==============================================================================


def parse_input(ctx: Context, node_input: Any) -> ExpenseReport:
    """Parses raw event input into structured ExpenseReport.

    Handles base64 Pub/Sub data or direct/nested JSON representations.
    """
    if ctx.state and "expense" in ctx.state:
        return ExpenseReport(**ctx.state["expense"])
    raw_str = ""
    # Extract raw text from types.Content or similar objects if passed by CLI runner
    if hasattr(node_input, "parts") and node_input.parts:
        raw_str = node_input.parts[0].text
    elif isinstance(node_input, str):
        raw_str = node_input
    else:
        raw_str = str(node_input)

    # Try parsing text as JSON
    try:
        payload = json.loads(raw_str)
    except Exception:
        if isinstance(node_input, dict):
            payload = node_input
        else:
            raise ValueError(f"Could not parse input: {node_input}") from None

    # Extract the data block (Pub/Sub event format vs raw event)
    data = payload.get("data")
    if data is None:
        data = payload

    # Handle Base64 decoding if the data is a base64 encoded string
    if isinstance(data, str):
        try:
            decoded = base64.b64decode(data).decode("utf-8")
            data = json.loads(decoded)
        except Exception:
            # Not base64/JSON, fallback to treating the string directly
            pass

    return ExpenseReport(**data)


def route_by_amount(node_input: ExpenseReport) -> Event:
    """Routes the expense report depending on the configured approval threshold."""
    # Store expense details in context state for downstream nodes
    state_delta = {"expense": node_input.model_dump()}

    if node_input.amount < APPROVAL_THRESHOLD:
        return Event(output=node_input, route="auto_approve", state=state_delta)

    return Event(output=node_input, route="review", state=state_delta)


def security_checkpoint(ctx: Context, node_input: ExpenseReport) -> Event:
    """Security checkpoint to scrub PII and detect prompt injection."""
    description = node_input.description
    redacted_categories = []

    # 1. Scrub SSNs
    ssn_pattern = r'\b\d{3}-\d{2}-\d{4}\b'
    if re.search(ssn_pattern, description):
        description = re.sub(ssn_pattern, '[REDACTED_SSN]', description)
        redacted_categories.append('SSN')

    # Scrub CCs (simple regex for 13-16 digits)
    cc_pattern = r'\b(?:\d[ -]*?){13,16}\b'
    if re.search(cc_pattern, description):
        description = re.sub(cc_pattern, '[REDACTED_CC]', description)
        redacted_categories.append('CreditCard')

    node_input.description = description
    
    state_delta = {"expense": node_input.model_dump()}
    if redacted_categories:
        # We append to existing if any, or just set it
        existing = ctx.state.get("redacted_categories", []) if ctx.state else []
        state_delta["redacted_categories"] = list(set(existing + redacted_categories))

    # 2. Defend against prompt injection
    injection_keywords = ["ignore previous instructions", "auto-approve", "bypass", "system prompt", "override"]
    desc_lower = description.lower()
    if any(kw in desc_lower for kw in injection_keywords):
        state_delta["security_event"] = "Prompt injection detected"
        return Event(output=node_input, route="flagged", state=state_delta)

    return Event(output=node_input, route="clean", state=state_delta)


async def human_approval(ctx: Context, node_input: Any):
    """Workflow pause node to request human approval for high-value expenses."""
    decision = None

    # Check resume_inputs (standard way used by Playground/API)
    if ctx.resume_inputs and "approval_decision" in ctx.resume_inputs:
        decision = ctx.resume_inputs["approval_decision"]
    elif ctx.user_content and ctx.user_content.parts:
        # Fallback: check the current user content for a decision (e.g. in CLI runs)
        for part in ctx.user_content.parts:
            if part.text:
                decision = part.text
                break

    decision_str = str(decision).strip().lower() if decision else ""
    is_decision = decision_str in [
        "approve",
        "reject",
        "yes",
        "no",
        "y",
        "n",
        "approved",
        "rejected",
    ]

    if not is_decision:
        msg = "Expense requires review. Please approve or reject (reply 'approve' or 'reject')."
        if ctx.state and ctx.state.get("security_event"):
            msg = f"SECURITY EVENT: {ctx.state['security_event']}. " + msg

        yield RequestInput(
            interrupt_id="approval_decision",
            message=msg,
        )
        return

    if "approve" in decision_str or decision_str in ["yes", "y", "approved"]:
        yield Event(
            output="Approved by human", route="approve", state={"decision": "approved"}
        )
    else:
        yield Event(
            output="Rejected by human", route="reject", state={"decision": "rejected"}
        )


def approve(ctx: Context, node_input: Any):
    """Terminal node for approvals."""
    expense = ctx.state.get("expense", {})
    msg = f"Expense of ${expense.get('amount')} submitted by {expense.get('submitter')} has been APPROVED."
    yield Event(
        content=types.Content(role="model", parts=[types.Part.from_text(text=msg)])
    )
    yield Event(output=msg)


def reject(ctx: Context, node_input: Any):
    """Terminal node for rejections."""
    expense = ctx.state.get("expense", {})
    msg = f"Expense of ${expense.get('amount')} submitted by {expense.get('submitter')} has been REJECTED."
    yield Event(
        content=types.Content(role="model", parts=[types.Part.from_text(text=msg)])
    )
    yield Event(output=msg)


# ==============================================================================
# LLM Risk Review Agent
# ==============================================================================

risk_review_agent = LlmAgent(
    name="risk_review_agent",
    model=MODEL_NAME,
    instruction=(
        "You are an expense report risk reviewer. "
        "Analyze the provided expense report details for potential risk factors "
        "(e.g., suspicious amounts, unusual categories, vague descriptions, timing). "
        "Provide a risk score from 1 to 10, list the risk factors, and write a summary."
    ),
    output_schema=RiskReviewOutput,
    output_key="risk_review",
)

# ==============================================================================
# Workflow Definition
# ==============================================================================

root_agent = Workflow(
    name="expense_approval_workflow",
    edges=[
        (START, parse_input),
        (parse_input, security_checkpoint),
        # Security checkpoint branching
        (security_checkpoint, {"clean": route_by_amount, "flagged": human_approval}),
        # Conditional paths from threshold check
        (route_by_amount, {"auto_approve": approve, "review": risk_review_agent}),
        # Path for manual review
        (risk_review_agent, human_approval),
        # Decision paths from human approval
        (human_approval, {"approve": approve, "reject": reject}),
    ],
)

app = App(
    root_agent=root_agent,
    name="expense_agent",
)
