# teamwork_to_slack/app.py

from flask import Flask, request, jsonify
import requests
import os
from dotenv import load_dotenv
from datetime import datetime

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
            KNOWN_BOT_IDS = {BOT_ID, "B08QQESME15"}
            print(f"✅ Slack Bot ID resolved to: {BOT_ID}")
    except Exception as e:
        print("Failed to fetch bot ID:", e)

fetch_bot_id()

 @app.route("/teamwork-webhook", methods=["POST"])
def teamwork_webhook():
    from dateutil import tz

    timestamp = datetime.utcnow().isoformat()
    print(f"[Webhook {timestamp}] Received POST request")
    data = request.get_json()
    print(f"[Webhook {timestamp}] Payload:", data)

    if not data:
        return jsonify({"error": "Invalid payload"}), 400

    ticket = data.get("ticket") or data.get("data", {}).get("ticket", {})
    ticket_id = ticket.get("id")
    subject = ticket.get("subject")
    ticket_url = ticket.get("link")

    status = ticket.get("status")
    if isinstance(status, dict):
        status = status.get("name")

    priority = ticket.get("priority", {}).get("name", "Unknown")
    ticket_type = ticket.get("type", {}).get("name", "General")

    created_at = ticket.get("createdAt")
    try:
        # Convert to local time for better readability in Slack
        created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00")).astimezone(tz.tzlocal())
        created_ts = int(created_dt.timestamp())
        slack_ts = f"<!date^{created_ts}^{{date_short_pretty}} at {{time}}|{created_dt.isoformat()}>"
    except Exception:
        slack_ts = created_at or "N/A"

    assignee = (
        ticket.get("agent") or
        ticket.get("assignee") or
        ticket.get("assigned_to") or
        ticket.get("assigneeId") or
        {}
    )

    if isinstance(assignee, dict):
        assigned_name = assignee.get("fullName") or assignee.get("name") or assignee.get("firstName")
        slack_mention = f"*🙋 Assigned To:*\n{assigned_name}"
    elif isinstance(assignee, str):
        slack_mention = f"*🙋 Assigned To:*\n{assignee}"
    else:
        slack_mention = "*🙋 Assigned To:*\nUnassigned"

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
                    {"type": "mrkdwn", "text": slack_mention},
                    {"type": "mrkdwn", "text": f"*🕒 Created:*\n{slack_ts}"}
                ]
            }
        ]
    }

    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={
            "Authorization": f"Bearer {SLACK_BOT_TOKEN}",
            "Content-Type": "application/json"
        },
        json=payload
    )

    print(f"[Slack {timestamp}] Response status:", resp.status_code)
    print(f"[Slack {timestamp}] Response body:", resp.text)

    if resp.status_code != 200:
        return jsonify({"error": "Failed to send to Slack", "details": resp.text}), 500

    return jsonify({"message": "Slack notification sent successfully.", "timestamp": timestamp}), 200




# Fix: Support "agent" field from Teamwork as assignee



    assignee = (
        ticket.get("agent") or
        ticket.get("assignee") or
        ticket.get("assigned_to") or
        ticket.get("assigneeId") or
        {}
    )

    print("Assignee field from ticket:", assignee)

    if isinstance(assignee, dict):
        assigned_to = assignee.get("fullName") or assignee.get("name") or assignee.get("firstName")
    elif isinstance(assignee, str):
        assigned_to = assignee
    else:
        assigned_to = "Unassigned"

    slack_message = {
        "text": f":admission_tickets: *New Ticket Received*\n"
                f"ID: `{ticket_id}`\n"
                f"Subject: *{subject}*\n"
                f"Status: `{status}`\n"
                f"Assigned To: {assigned_to}"
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

