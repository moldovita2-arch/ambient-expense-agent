import json
import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Ensure project root is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from google.adk.sessions import InMemorySessionService
from google.adk.runners import Runner
from google.adk.events.request_input import RequestInput
from google.genai import types

from expense_agent.agent import root_agent

def main():
    with open('tests/eval/datasets/basic-dataset.json') as f:
        dataset = json.load(f)
    
    out_cases = []
    
    for case in dataset['eval_cases']:
        print(f"Running case: {case['eval_case_id']}")
        session_id = f"eval-{case['eval_case_id']}"
        session_service = InMemorySessionService()
        try:
            session_service.create_session_sync(user_id="eval", app_name="expense_agent", session_id=session_id)
        except Exception:
            pass
        runner = Runner(agent=root_agent, session_service=session_service, app_name="expense_agent")
        
        prompt_text = case['prompt']['parts'][0]['text']
        content = types.Content(role="user", parts=[types.Part.from_text(text=prompt_text)])
        
        events = []
        events.append({
            "author": "user",
            "content": {
                "role": "user",
                "parts": [{"text": prompt_text}]
            }
        })
        
        generator = runner.run(new_message=content, session_id=session_id, user_id="eval")
        
        while True:
            try:
                evt = next(generator)
                
                # In ADK 2.0, check if it's RequestInput
                if isinstance(evt, RequestInput) and evt.interrupt_id == "approval_decision":
                    print(f"  Intercepted human approval for {case['eval_case_id']}")
                    decision = "reject" if ("injection" in case['eval_case_id'] or "threat" in case['eval_case_id']) else "approve"
                    
                    # Log the human input
                    events.append({
                        "author": "user",
                        "content": {
                            "role": "user",
                            "parts": [{"text": decision}]
                        }
                    })
                    
                    generator = runner.run(session_id=session_id, user_id="eval", resume_inputs={"approval_decision": decision})
                    continue
                
                # If evt has content, log it as an agent output turn
                if getattr(evt, "content", None):
                    c = evt.content
                    parts = []
                    for p in c.parts:
                        if p.text:
                            parts.append({"text": p.text})
                        elif p.function_call:
                            # Not strictly used here but good practice
                            parts.append({"function_call": {"name": p.function_call.name, "args": p.function_call.args}})
                    
                    if parts:
                        events.append({
                            "author": "expense_agent",
                            "content": {
                                "role": c.role or "model",
                                "parts": parts
                            }
                        })
            except StopIteration:
                break
        
        # After execution, we also want to extract the final session history for debugging or trace details
        # However, the events array captured above is sufficient for the LLM judge.
        out_case = {
            "eval_case_id": case['eval_case_id'],
            "responses": [{"response": {"role": "model", "parts": [{"text": "done"}]}}],
            "agent_data": {
                "agents": {
                    "expense_agent": {
                        "agent_id": "expense_agent",
                        "instruction": "Expense approval workflow"
                    }
                },
                "turns": [
                    {
                        "turn_index": 0,
                        "events": events
                    }
                ]
            }
        }
        out_cases.append(out_case)

    out_data = {"eval_cases": out_cases}
    os.makedirs('artifacts/traces', exist_ok=True)
    with open('artifacts/traces/generated_traces.json', 'w') as f:
        json.dump(out_data, f, indent=2)
    print("Saved traces to artifacts/traces/generated_traces.json")

if __name__ == "__main__":
    main()
