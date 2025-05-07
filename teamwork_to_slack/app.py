from flask import Flask, request, jsonify
import requests
import os
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
load_dotenv()

app = Flask(__name__)

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
DEFAULT_SLACK_CHANNEL = os.getenv("SLACK_CHANNEL_ID")

if not SLACK_BOT_TOKEN or not DEFAULT_SLACK_CHANNEL:
    raise RuntimeError("Missing SLACK_BOT_TOKEN or SLACK_CHANNEL_ID in environment variables")

# Globals
latest_channel_id = DEFAULT_SLACK_CHANNEL
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
            KNOWN_BOT_IDS.update([BOT_ID])
            print(f"✅ Slack Bot ID resolved to: {BOT_ID}")
    except Exception as e:
        print("Failed to fetch bot ID:", e)

fetch_bot_id()

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        return jsonify({"message": "Use /teamwork-webhook"}), 405
    return "✅ Teamwork-Slack webhook bridge is online."

@app.route("/health", methods=["GET"])
def health():
    timestamp = datetime.utcnow().isoformat()
    msg = f":white_check_mark: Health check at {timestamp}"
    response = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={
            "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
            "Content-Type": "application/json"
        },
        json={
            "channel": DEFAULT_SLACK_CHANNEL,
            "text": msg
        }
    )
    return jsonify({"status": "ok" if response.ok else "fail", "timestamp": timestamp}), response.status_code

@app.route("/teamwork-webhook", methods=["POST"])
def teamwork_webhook():
    timestamp = datetime.utcnow().isoformat()
    data = request.get_json()
    print(f"[Webhook {timestamp}] Received:", data)

    # Validate it's a new ticket event (no eventType present in payload)
    ticket = data.get("ticket") or data.get("data", {}).get("ticket", {})
    threads = ticket.get("threads", [])

    is_ticket_created = (
        ticket and threads and
        threads[0].get("threadType", {}).get("name") == "message" and
        "customer" in threads[0]
    )

    if not is_ticket_created:
        print("Ignored event: not a new ticket")
        return "", 204

    # Extract ticket info
    ticket_id = ticket.get("id")
    subject = ticket.get("subject") or "No subject"
    status = ticket.get("status", {}).get("name", "Unknown")
    assignee = ticket.get("agent", {}) or {}
    assigned_to = assignee.get("firstName", "Unassigned")

    # Ticket link
    ticket_link = ticket.get("link", f"https://yourteamworkdomain/teamwork/desk/tickets/{ticket_id}")

    # Compose Slack message
    slack_msg = {
        "text": (
            f":admission_tickets: *New Ticket Received*\n"
            f"ID: `{ticket_id}`\n"
            f"Subject: *{subject}*\n"
            f"Status: `{status}`\n"
            f"Assigned To: {assigned_to}\n"
            f"<{ticket_link}|View Ticket>"
        )
    }

    slack_resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={
            "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
            "Content-Type": "application/json"
        },
        json={
            "channel": DEFAULT_SLACK_CHANNEL,
            **slack_msg
        }
    )
    print(f"[Slack {timestamp}] Response status: {slack_resp.status_code}")
    print(f"[Slack {timestamp}] Response body: {slack_resp.text}")
    return jsonify({"ok": slack_resp.ok}), slack_resp.status_code

@app.route("/clean-tickets", methods=["POST"])
def clean_tickets():
    global latest_channel_id

    channel_id = request.form.get("channel_id")
    user_id = request.form.get("user_id")
    latest_channel_id = channel_id or DEFAULT_SLACK_CHANNEL

    headers = {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json"
    }

    history = requests.get("https://slack.com/api/conversations.history", params={
        "channel": latest_channel_id,
        "limit": 50
    }, headers=headers).json()

    print("--- Full conversations.history response ---")
    print(history)
    print("------------------------------------------------")

    deleted = 0
    for msg in history.get("messages", []):
        if msg.get("bot_id") in KNOWN_BOT_IDS:
            ts = msg.get("ts")
            delete_resp = requests.post("https://slack.com/api/chat.delete", headers=headers, json={
                "channel": latest_channel_id,
                "ts": ts
            }).json()
            if delete_resp.get("ok"):
                deleted += 1
            else:
                print("❌ Failed to delete:", delete_resp.get("error"))

    return jsonify({"message": f"Deleted {deleted} messages from channel."})

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
