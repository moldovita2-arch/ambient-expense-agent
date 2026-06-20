import urllib.request
import json
import sys
import subprocess

def get_id_token():
    return subprocess.check_output("gcloud auth print-identity-token", shell=True).decode().strip()

url = "https://ambient-expense-agent-cvinmrfe6q-nw.a.run.app"
token = get_id_token()

for session_id in ["test-sub-test_50_meal_v2", "test-sub-test_150_dinner_v2"]:
    print(f"\n--- SESSION: {session_id} ---")
    req = urllib.request.Request(f"{url}/apps/expense_agent/users/pubsub/sessions/{session_id}", headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req) as res:
            data = json.loads(res.read().decode())
            print(json.dumps(data, indent=2))
    except Exception as e:
        print(f"Error: {e}")
