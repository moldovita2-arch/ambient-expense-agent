import urllib.request
import json
import base64

payload = {
    "amount": 150.0,
    "submitter": "pubsub@company.com",
    "category": "software",
    "description": "IDE License PubSub",
    "date": "2026-06-06"
}
b64_data = base64.b64encode(json.dumps(payload).encode()).decode()

envelope = {
    "message": {
        "data": b64_data,
        "messageId": "msg123",
        "publishTime": "2026-06-18T20:45:00.000Z"
    },
    "subscription": "projects/my-project/subscriptions/expense-sub"
}

req = urllib.request.Request(
    "http://127.0.0.1:8080/",
    data=json.dumps(envelope).encode(),
    headers={"Content-Type": "application/json"}
)

try:
    with urllib.request.urlopen(req) as response:
        print(response.read().decode())
except Exception as e:
    print(f"Error: {e}")
