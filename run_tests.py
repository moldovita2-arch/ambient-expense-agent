import os
import sys
import json
import time
import urllib.request
import base64
import subprocess

def get_id_token():
    try:
        return subprocess.check_output("gcloud auth print-identity-token", shell=True).decode().strip()
    except Exception as e:
        print(f"Error getting ID token: {e}")
        return None

def trigger_and_check(url, token, payload, msg_id):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    
    # 1. Trigger via PubSub endpoint
    b64_data = base64.b64encode(json.dumps(payload).encode()).decode()
    envelope = {
        "message": {
            "data": b64_data,
            "messageId": msg_id,
            "publishTime": "2026-06-20T00:00:00.000Z"
        },
        "subscription": "projects/my-project/subscriptions/test-sub"
    }
    
    req = urllib.request.Request(url, data=json.dumps(envelope).encode(), headers=headers)
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode())
            session_id = result.get("session_id")
            print(f"Triggered successfully. Session ID: {session_id}")
    except Exception as e:
        print(f"Error triggering: {e}")
        return
        
    print("Waiting for agent to process...")
    time.sleep(15) # Wait for LLM risk review
    
    # 2. Fetch session state
    endpoint = f"{url}/apps/expense_agent/users/pubsub/sessions/{session_id}"
    req_get = urllib.request.Request(endpoint, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req_get) as response:
            session_data = json.loads(response.read().decode())
            
            # Print the final events / decisions
            events = session_data.get("events", [])
            print(f"Total events in session: {len(events)}")
            for event in events:
                if event.get("type") == "RequestInput":
                    print(f"--> [HITL PAUSE] Agent requested input: {event.get('message')}")
                elif event.get("type") == "Event" and "output" in event:
                    print(f"--> [AGENT EVENT]: {event.get('output')}")
                
            state = session_data.get("state", {})
            if "decision" in state:
                print(f"--> Final Decision State: {state['decision']}")
            if "risk_review" in state:
                print(f"--> Risk Review Summary: {state['risk_review']}")
                
    except Exception as e:
        print(f"Error fetching session: {e}")

if __name__ == "__main__":
    url = "https://ambient-expense-agent-cvinmrfe6q-nw.a.run.app"
    token = get_id_token()
    
    if not token:
        sys.exit(1)
        
    print("\n=======================================================")
    print("--- Test 1: $50 Meal Expense (Auto-Approve Expected) ---")
    payload1 = {
        "amount": 50.0,
        "submitter": "user@company.com",
        "category": "meal",
        "description": "Standard lunch",
        "date": "2026-06-20"
    }
    trigger_and_check(url, token, payload1, msg_id="test_50_meal_v2")
    
    print("\n=======================================================")
    print("--- Test 2: $150 Client Dinner (HITL Expected) ---")
    payload2 = {
        "amount": 150.0,
        "submitter": "user@company.com",
        "category": "meal",
        "description": "Client dinner with executive team",
        "date": "2026-06-20"
    }
    trigger_and_check(url, token, payload2, msg_id="test_150_dinner_v2")
