from flask import Flask, request, jsonify
import os
import requests
from dotenv import load_dotenv
from datetime import datetime

# Load environment variables
load_dotenv()

app = Flask(__name__)

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID")
SLACK_USER_MAPPING = os.getenv("SLACK_USER_MAPPING")  # Format: 374561:U08QQESNQ2K,374645:U08QQESABC1

# Parse Slack user ID mapping
user_map = dict(item.split(":") for item in SLACK_USER_MAPPING.split(",")) if SLACK_USER_MAPPING else {}

def get_slack_user_mention(agent_id, agent_fallback=None):
    """Resolve agent ID to Slack mention or fallback to name."""
    if not agent_id:
        return agent_fallback or "Unassigned"
    slack_id = user_map.get(str(agent_id))
    if slack_id:
        return f"<@{slack_id}>"
    return agent_fallback or "Unassigned"

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        return jsonify({"message": "Teamwork tried to POST to root. Use /teamwork-webhook"}), 405
    return "✅ Teamwork-Slack bridge online."

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
                "channel": SLACK_CHANNEL_ID,
                **test_message
            }
        )
        if resp.status_code == 200:
            return jsonify({"status": "ok", "timestamp": timestamp}), 200
        return jsonify({"status": "error", "details": resp.text, "timestamp": timestamp}), 500
    except Exception as e:
        return jsonify({"status": "error", "exception": str(e), "timestamp": timestamp}), 500

@app.route("/teamwork-webhook", methods=["POST"])
def teamwork_webhook():
    timestamp = datetime.utcnow().isoformat()
    payload = request.get_json()
    print(f"[Webhook {timestamp}] Received:", payload)

    if not payload or payload.get("event") != "ticket.created":
        print(f"Ignored event: {payload.get('event')}")
        return "", 204

    ticket = payload.get("ticket", {})
    ticket_id = ticket.get("id")
    subject = ticket.get("subject")
    status = ticket.get("status", {}).get("name")
    link = ticket.get("link")
    agent = ticket.get("agent", {})

    assigned_to = get_slack_user_mention(
        agent.get("id"),
        f"{agent.get('firstName', '')} {agent.get('lastName', '')}".strip()
    )

    slack_blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":admission_tickets: *New Ticket Received*\n"
                    f"*ID:* `{ticket_id}`\n"
                    f"*Subject:* *{subject}*\n"
                    f"*Status:* `{status}`\n"
                    f"*Assigned To:* {assigned_to}\n"
                    f":link: <{link}|View Ticket>"
                )
            }
        }
    ]

    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={
            "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
            "Content-Type": "application/json"
        },
        json={
            "channel": SLACK_CHANNEL_ID,
            "blocks": slack_blocks
        }
    )

    print(f"[Slack {timestamp}] Response:", resp.status_code, resp.text)
    return "", 200

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)

