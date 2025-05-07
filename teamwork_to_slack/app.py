from flask import Flask, request, jsonify
from flask import Flask, request, jsonify
import requests
import os
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
app = Flask(__name__)

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
DEFAULT_SLACK_CHANNEL = os.getenv("SLACK_CHANNEL_ID")

if not SLACK_BOT_TOKEN:
    raise RuntimeError("SLACK_BOT_TOKEN is not set")

# Track the Slack bot ID
BOT_ID = None
KNOWN_BOT_IDS = set()


def fetch_bot_id():
    global BOT_ID, KNOWN_BOT_IDS
    try:
        resp = requests.post("https://slack.com/api/auth.test", headers={
            "Authorization": f"Bearer {SLACK_BOT_TOKEN}"
        })
        result = resp.json()
        BOT_ID = result.get("bot_id")
        if BOT_ID:
            KNOWN_BOT_IDS = {BOT_ID, "B08QQESME15"}
            print(f"✅ Slack Bot ID resolved to: {BOT_ID}")
    except Exception as e:
        print("❌ Failed to fetch bot ID:", e)


fetch_bot_id()


@app.route("/", methods=["GET"])
def index():
    return "✅ Teamwork-Slack webhook bridge is online."


@app.route("/health", methods=["GET"])
def health_check():
    timestamp = datetime.utcnow().isoformat()
    try:
        resp = requests.post("https://slack.com/api/chat.postMessage", headers={
            "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
            "Content-Type": "application/json"
        }, json={
            "channel": DEFAULT_SLACK_CHANNEL,
            "text": f"✅ Health check at {timestamp}"
        })
        if resp.status_code == 200:
            return jsonify({"status": "ok", "timestamp": timestamp}), 200
        return jsonify({"status": "error", "details": resp.text}), 500
    except Exception as e:
        return jsonify({"status": "error", "exception": str(e)}), 500


@app.route("/teamwork-webhook", methods=["POST"])
def teamwork_webhook():
    timestamp = datetime.utcnow().isoformat()
    payload = request.get_json()
    print(f"[Webhook {timestamp}] Received:", payload)

    if not payload:
        return jsonify({"error": "Invalid payload"}), 400

    event_type = payload.get("event", {}).get("eventType")
    if event_type != "ticket.created":
        print("Ignored event:", event_type)
        return "", 204

    ticket = payload.get("ticket") or payload.get("data", {}).get("ticket", {})
    if not ticket:
        return jsonify({"error": "No ticket data"}), 400

    ticket_id = ticket.get("id")
    subject = ticket.get("subject")
    status = ticket.get("status", {}).get("name", "Unknown")
    assignee = ticket.get("agent")

    assigned_to = (
        f"{assignee.get('firstName')} {assignee.get('lastName')}".strip()
        if assignee else "Unassigned"
    )

    message = {
        "text": (
            f":admission_tickets: *New Ticket Received*\n"
            f"ID: `{ticket_id}`\n"
            f"Subject: *{subject}*\n"
            f"Status: `{status}`\n"
            f"Assigned To: {assigned_to}"
        )
    }

    slack_resp = requests.post("https://slack.com/api/chat.postMessage", headers={
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json"
    }, json={
        "channel": DEFAULT_SLACK_CHANNEL,
        **message
    })

    print(f"[Slack {timestamp}] Response status: {slack_resp.status_code}")
    print(f"[Slack {timestamp}] Response body:", slack_resp.text)
    return jsonify({"ok": True}), 200


@app.route("/clean-tickets", methods=["POST"])
def clean_tickets():
    channel_id = request.form.get("channel_id") or DEFAULT_SLACK_CHANNEL
    headers = {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json"
    }

    resp = requests.get("https://slack.com/api/conversations.history", headers=headers, params={
        "channel": channel_id,
        "limit": 100
    })
    messages = resp.json().get("messages", [])
    deleted = 0

    for msg in messages:
        if msg.get("bot_id") in KNOWN_BOT_IDS:
            delete_resp = requests.post("https://slack.com/api/chat.delete", headers=headers, json={
                "channel": channel_id,
                "ts": msg["ts"]
            })
            if delete_resp.ok and delete_resp.json().get("ok"):
                deleted += 1

    return jsonify({"message": f"Deleted {deleted} messages from channel."})


if __name__ == "__main__":
    app.run(debug=True, port=5000, host="0.0.0.0")


