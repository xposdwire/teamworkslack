from flask import Flask, request, jsonify
import requests
import os
from dotenv import load_dotenv
from datetime import datetime
from dateutil import tz

load_dotenv()

app = Flask(__name__)

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
DEFAULT_SLACK_CHANNEL = os.environ.get("SLACK_CHANNEL_ID")
latest_channel_id = DEFAULT_SLACK_CHANNEL

if not SLACK_BOT_TOKEN:
    raise RuntimeError("SLACK_BOT_TOKEN is not set. Please define it in a .env file or environment variable.")

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
            KNOWN_BOT_IDS = {BOT_ID}
            print(f"✅ Slack Bot ID resolved to: {BOT_ID}")
    except Exception as e:
        print("Failed to fetch bot ID:", e)

def resolve_slack_mention(email: str) -> str:
    try:
        resp = requests.get(
            "https://slack.com/api/users.lookupByEmail",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
            params={"email": email}
        )
        result = resp.json()
        if result.get("ok"):
            return f"<@{result['user']['id']}>"
    except Exception as e:
        print("Slack user lookup failed:", e)
    return None

fetch_bot_id()

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        return jsonify({"message": "Teamwork tried to POST to root. Use /teamwork-webhook"}), 405
    return "✅ Teamwork-Slack bridge is online."

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
        return jsonify({"status": "ok", "timestamp": timestamp}), resp.status_code
    except Exception as e:
        return jsonify({"status": "error", "exception": str(e)}), 500

@app.route("/teamwork-webhook", methods=["POST"])
def teamwork_webhook():
    timestamp = datetime.utcnow().isoformat()
    data = request.get_json()
    print(f"[Webhook {timestamp}] Received: {data}")

    event_type = data.get("event")
    if event_type != "ticket.created":
        print(f"Ignored event: {event_type}")
        return jsonify({"ignored": event_type}), 204

    ticket = data.get("ticket") or data.get("data", {}).get("ticket", {})
    ticket_id = ticket.get("id")
    subject = ticket.get("subject")
    ticket_url = ticket.get("link")
    status = ticket.get("status", {}).get("name", "Unknown")
    priority = ticket.get("priority", {}).get("name", "Unknown")
    ticket_type = ticket.get("type", {}).get("name", "General")

    created_at = ticket.get("createdAt")
    try:
        created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(tz.tzlocal())
        created_ts = int(created_dt.timestamp())
        slack_ts = f"<!date^{created_ts}^{{date_short_pretty}} at {{time}}|{created_dt.isoformat()}>"
    except Exception:
        slack_ts = created_at or "N/A"

    agent = ticket.get("agent", {})
    agent_name = agent.get("fullName") or agent.get("firstName") or "Unassigned"
    agent_email = agent.get("email")
    mention = resolve_slack_mention(agent_email) or agent_name

    payload = {
        "channel": latest_channel_id,
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": ":admission_tickets: *New Ticket Received*"}},
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*🔗 Link:*\n<{ticket_url}|View Ticket>"},
                    {"type": "mrkdwn", "text": f"*🆔 ID:*\n`{ticket_id}`"},
                    {"type": "mrkdwn", "text": f"*📌 Subject:*\n*{subject}*"},
                    {"type": "mrkdwn", "text": f"*📊 Status:*\n`{status}`"},
                    {"type": "mrkdwn", "text": f"*🏷️ Type:*\n`{ticket_type}`"},
                    {"type": "mrkdwn", "text": f"*🚨 Priority:*\n`{priority}`"},
                    {"type": "mrkdwn", "text": f"*🙋 Assigned To:*\n{mention}"},
                    {"type": "mrkdwn", "text": f"*🕒 Created:*\n{slack_ts}"}
                ]
            }
        ]
    }

    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"},
        json=payload
    )

    print(f"[Slack {timestamp}] Status: {resp.status_code}")
    print(f"[Slack {timestamp}] Body: {resp.text}")

    if resp.status_code != 200:
        return jsonify({"error": "Slack post failed", "details": resp.text}), 500

    return jsonify({"message": "Posted to Slack"}), 200

@app.route("/clean-tickets", methods=["POST"])
def clean_tickets():
    global latest_channel_id
    channel_id = request.form.get("channel_id")
    latest_channel_id = channel_id

    headers = {
        "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
        "Content-Type": "application/json"
    }

    history = requests.get("https://slack.com/api/conversations.history", params={
        "channel": channel_id,
        "limit": 50
    }, headers=headers).json()

    deleted = 0
    for msg in history.get("messages", []):
        if msg.get("bot_id") in KNOWN_BOT_IDS:
            ts = msg.get("ts")
            del_resp = requests.post("https://slack.com/api/chat.delete", headers=headers, json={
                "channel": channel_id, "ts": ts
            }).json()
            if del_resp.get("ok"):
                deleted += 1

    return jsonify({"message": f"Deleted {deleted} messages from channel."})

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

