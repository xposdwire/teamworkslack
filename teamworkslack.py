# teamwork_to_slack/app.py
from flask import Flask, request, jsonify
import requests
import os
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")

if not SLACK_WEBHOOK_URL:
    raise RuntimeError("SLACK_WEBHOOK_URL is not set. Please define it in a .env file or environment variable.")

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        return jsonify({"message": "Teamwork tried to POST to root. Please use /teamwork-webhook"}), 405
    return "✅ Teamwork-Slack webhook bridge is online."

@app.route("/health", methods=["GET"])
def health_check():
    timestamp = datetime.utcnow().isoformat()
    try:
        test_message = {"text": f"✅ Health check at {timestamp}"}
        resp = requests.post(SLACK_WEBHOOK_URL, json=test_message)
        if resp.status_code == 200:
            return jsonify({"status": "ok", "timestamp": timestamp}), 200
        else:
            return jsonify({"status": "error", "details": resp.text, "timestamp": timestamp}), 500
    except Exception as e:
        return jsonify({"status": "error", "exception": str(e), "timestamp": timestamp}), 500

@app.route("/teamwork-webhook", methods=["POST"])
def teamwork_webhook():
    timestamp = datetime.utcnow().isoformat()
    print(f"[Webhook {timestamp}] Received POST request")
    data = request.get_json()
    print(f"[Webhook {timestamp}] Payload:", data)

    if not data:
        return jsonify({"error": "Invalid payload"}), 400

    ticket = data.get("ticket") or data.get("data", {}).get("ticket", {})
    ticket_id = ticket.get("id")
    subject = ticket.get("subject")

    status = ticket.get("status")
    if isinstance(status, dict):
        status = status.get("name")

    assignee = ticket.get("assignee") or ticket.get("assigned_to")
    assigned_to = assignee.get("fullName") if isinstance(assignee, dict) else "Unassigned"

    slack_message = {
        "text": f"🎟️ *New Ticket Received*\nID: `{ticket_id}`\nSubject: *{subject}*\nStatus: `{status}`\nAssigned To: {assigned_to}"
    }

    resp = requests.post(SLACK_WEBHOOK_URL, json=slack_message)
    print(f"[Slack {timestamp}] Response status:", resp.status_code)
    print(f"[Slack {timestamp}] Response body:", resp.text)

    if resp.status_code != 200:
        return jsonify({"error": "Failed to send to Slack", "details": resp.text}), 500

    return jsonify({"message": "Slack notification sent successfully.", "timestamp": timestamp}), 200

@app.route("/clean-tickets", methods=["POST"])
def clean_tickets():
    if not SLACK_BOT_TOKEN:
        return jsonify({"error": "Missing SLACK_BOT_TOKEN"}), 403

    channel_id = request.form.get("channel_id")
    user_id = request.form.get("user_id")

    headers = {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json"
    }

    # Fetch last 20 messages
    history_resp = requests.get("https://slack.com/api/conversations.history", params={
        "channel": channel_id,
        "limit": 20
    }, headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"})

    messages = history_resp.json().get("messages", [])
    deleted = 0

    for msg in messages:
        if msg.get("bot_id") or (msg.get("user") == user_id):  # allow user-triggered deletion for testing
            ts = msg.get("ts")
            delete_resp = requests.post("https://slack.com/api/chat.delete", headers=headers, json={
                "channel": channel_id,
                "ts": ts
            })
            if delete_resp.ok:
                deleted += 1

    return jsonify({"message": f"Deleted {deleted} messages from channel."})

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
