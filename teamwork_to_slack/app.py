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
DEFAULT_SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL_ID")
latest_channel_id = DEFAULT_SLACK_CHANNEL

if not SLACK_BOT_TOKEN:
    raise RuntimeError("SLACK_BOT_TOKEN is not set. Please define it in a .env file or environment variable.")

# Fetch the bot's ID dynamically using auth.test
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
            KNOWN_BOT_IDS = {BOT_ID, "B08QQESME15"}  # add known historical webhook bot id
            print(f"✅ Slack Bot ID resolved to: {BOT_ID}")
    except Exception as e:
        print("Failed to fetch bot ID:", e)

fetch_bot_id()

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
        resp = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={
                "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
                "Content-Type": "application/json"
            },
            json={
                "channel": latest_channel_id,
                **test_message
            }
        )
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

    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={
            "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
            "Content-Type": "application/json"
        },
        json={
            "channel": latest_channel_id,
            **slack_message
        }
    )
    print(f"[Slack {timestamp}] Response status:", resp.status_code)
    print(f"[Slack {timestamp}] Response body:", resp.text)

    if resp.status_code != 200:
        return jsonify({"error": "Failed to send to Slack", "details": resp.text}), 500

    return jsonify({"message": "Slack notification sent successfully.", "timestamp": timestamp}), 200

@app.route("/clean-tickets", methods=["POST"])
def clean_tickets():
    global latest_channel_id

    if not SLACK_BOT_TOKEN:
        return jsonify({"error": "Missing SLACK_BOT_TOKEN"}), 403

    channel_id = request.form.get("channel_id")
    user_id = request.form.get("user_id")
    latest_channel_id = channel_id

    headers = {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json"
    }

    history_resp = requests.get("https://slack.com/api/conversations.history", params={
        "channel": channel_id,
        "limit": 20
    }, headers=headers)

    history_data = history_resp.json()
    print("--- Full conversations.history response ---")
    print(history_data)
    print("------------------------------------------------")

    messages = history_data.get("messages", [])
    deleted = 0

    for msg in messages:
        print("--- Message ---")
        print("ts:", msg.get("ts"))
        print("text:", msg.get("text"))
        print("bot_id:", msg.get("bot_id"))
        print("user:", msg.get("user"))
        print("----------------")

        if msg.get("bot_id") in KNOWN_BOT_IDS:
            ts = msg.get("ts")
            delete_resp = requests.post("https://slack.com/api/chat.delete", headers=headers, json={
                "channel": channel_id,
                "ts": ts
            })
            response_json = delete_resp.json()
            print("Delete response:", response_json)
            if delete_resp.ok and response_json.get("ok"):
                deleted += 1
            else:
                print("❌ Delete failed:", response_json.get("error"))

    return jsonify({"message": f"Deleted {deleted} messages from channel."})

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
