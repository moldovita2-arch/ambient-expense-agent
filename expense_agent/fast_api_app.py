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
import os
import json
import logging

from fastapi import FastAPI, Request
from google.adk.cli.fast_api import get_fast_api_app
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from expense_agent.app_utils.telemetry import setup_telemetry
from expense_agent.app_utils.typing import Feedback
from expense_agent.agent import root_agent

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

setup_telemetry()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

allow_origins = (
    os.getenv("ALLOW_ORIGINS", "").split(",") if os.getenv("ALLOW_ORIGINS") else None
)

# Artifact bucket for ADK (created by Terraform, passed via env var)
logs_bucket_name = os.environ.get("LOGS_BUCKET_NAME")

AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Use sqlite for persistent shared storage between pubsub endpoint and dev-ui
os.makedirs(".google-agents-cli", exist_ok=True)
session_service_uri = "sqlite+aiosqlite:///.google-agents-cli/sessions.db"

artifact_service_uri = f"gs://{logs_bucket_name}" if logs_bucket_name else None
otel_to_cloud = False

app: FastAPI = get_fast_api_app(
    agents_dir=AGENT_DIR,
    web=True,
    artifact_service_uri=artifact_service_uri,
    allow_origins=allow_origins,
    session_service_uri=session_service_uri,
    otel_to_cloud=otel_to_cloud,
)
app.title = "ambient-expense-agent"
app.description = "API for interacting with the Agent ambient-expense-agent"

# Keep the session service persistent for background processing
session_service = InMemorySessionService()

@app.post("/")
async def pubsub_trigger(request: Request):
    """Handles Pub/Sub messages."""
    try:
        envelope = await request.json()
    except Exception as e:
        logger.error(f"Failed to parse JSON envelope: {e}")
        return {"status": "Bad Request: no payload"}

    subscription = envelope.get("subscription", "default_subscription")
    short_name = subscription.split("/")[-1]

    pubsub_message = envelope.get("message")
    if not pubsub_message:
        logger.error("No message in envelope")
        return {"status": "Bad Request: invalid Pub/Sub format"}

    msg_id = pubsub_message.get("messageId", "unknown")
    session_id = f"{short_name}-{msg_id}"
    
    logger.info(f"Received pubsub message: {msg_id} for subscription {short_name}")

    # Re-initialize the same session service (from URI) for the Runner
    from google.adk.sessions import DatabaseSessionService
    session_service = DatabaseSessionService(db_url=session_service_uri)
    runner = Runner(agent=root_agent, session_service=session_service, app_name="expense_agent")
    try:
        await session_service.create_session(app_name="expense_agent", user_id="pubsub", session_id=session_id)
    except Exception:
        pass # Already exists

    content = types.Content(role="user", parts=[types.Part.from_text(text=json.dumps(pubsub_message))])
    
    # Run the generator to exhaustion to ensure the graph executes completely
    list(runner.run(new_message=content, session_id=session_id, user_id="pubsub"))
    
    return {"status": "ok", "session_id": session_id}


@app.post("/feedback")
def collect_feedback(feedback: Feedback) -> dict[str, str]:
    """Collect and log feedback.

    Args:
        feedback: The feedback data to log

    Returns:
        Success message
    """
    logger.info(f"Feedback: {feedback.model_dump()}")
    return {"status": "success"}


# Main execution
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
