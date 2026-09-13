"""
Email Classifier + Auto-Draft Assistant
-----------------------------------------
Connects to a Gmail inbox via IMAP (read-only, using an App Password),
classifies each unread email with Claude, drafts a suggested reply,
and logs everything to a CSV. It never sends anything automatically --
it only reads and logs, which is safer for a live client demo.

Setup:
    pip install -r requirements.txt

    1. Turn on 2-Step Verification on the Gmail account you're testing with:
       https://myaccount.google.com/security
    2. Create an "App Password":
       https://myaccount.google.com/apppasswords
    3. Create a .env file in this folder containing:
        GMAIL_ADDRESS="youraddress@gmail.com"
        GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"
        ANTHROPIC_API_KEY="sk-ant-..."

Usage:
    python email_classifier.py
"""

import os
import csv
import json
import imaplib
import email
from email.header import decode_header
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
import anthropic

load_dotenv()

OUTPUT_CSV = Path("email_log.csv")
MAX_EMAILS_TO_CHECK = 10  # keep small for a live demo

FIELDS = [
    "received_at", "from", "subject", "category", "urgency",
    "one_line_summary", "suggested_reply", "processed_at"
]

CLASSIFY_PROMPT_TEMPLATE = """You are a customer-inbox triage assistant for a small business.
Read the email below and respond with ONLY a JSON object (no markdown, no preamble)
with these exact keys:

- category: one of ["sales_lead", "support_request", "complaint", "spam", "other"]
- urgency: one of ["low", "medium", "high"]
- one_line_summary: a single sentence summarizing what the sender wants
- suggested_reply: a short, polite, professional draft reply (2-4 sentences) a human can send as-is or edit

Email:
From: {sender}
Subject: {subject}
Body:
{body}
"""


def decode_mime_words(s):
    if not s:
        return ""
    decoded_parts = decode_header(s)
    return "".join(
        part.decode(enc or "utf-8") if isinstance(part, bytes) else part
        for part, enc in decoded_parts
    )


def get_email_body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition") or "")
            if content_type == "text/plain" and "attachment" not in disposition:
                charset = part.get_content_charset() or "utf-8"
                try:
                    return part.get_payload(decode=True).decode(charset, errors="replace")
                except Exception:
                    return part.get_payload(decode=True).decode("utf-8", errors="replace")
        return "(no plain-text body found)"
    else:
        charset = msg.get_content_charset() or "utf-8"
        return msg.get_payload(decode=True).decode(charset, errors="replace")


def fetch_recent_emails(address: str, app_password: str, limit: int):
    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    imap.login(address, app_password)
    imap.select("INBOX")

    status, message_ids = imap.search(None, "UNSEEN")
    ids = message_ids[0].split()
    ids = ids[-limit:]  # most recent N unread

    emails = []
    for msg_id in ids:
        # peek = don't mark as read, keeps this safe to re-run during a demo
        status, msg_data = imap.fetch(msg_id, "(BODY.PEEK[])")
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        emails.append({
            "from": decode_mime_words(msg.get("From")),
            "subject": decode_mime_words(msg.get("Subject")),
            "date": msg.get("Date"),
            "body": get_email_body(msg)[:3000],  # cap body length
        })

    imap.logout()
    return emails


def classify_email(client: anthropic.Anthropic, mail: dict) -> dict:
    prompt = CLASSIFY_PROMPT_TEMPLATE.format(
        sender=mail["from"], subject=mail["subject"], body=mail["body"]
    )

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
    )

    raw_text = "".join(
        block.text for block in message.content if block.type == "text"
    ).strip()
    raw_text = raw_text.replace("```json", "").replace("```", "").strip()

    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        return {
            "category": "other",
            "urgency": "low",
            "one_line_summary": "PARSE_ERROR",
            "suggested_reply": raw_text[:300],
        }


def ensure_csv_header():
    if not OUTPUT_CSV.exists():
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()


def append_row(row: dict):
    with open(OUTPUT_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writerow({k: row.get(k, "") for k in FIELDS})


def main():
    address = os.environ.get("GMAIL_ADDRESS")
    app_password = os.environ.get("GMAIL_APP_PASSWORD")
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    missing = [
        name for name, val in [
            ("GMAIL_ADDRESS", address),
            ("GMAIL_APP_PASSWORD", app_password),
            ("ANTHROPIC_API_KEY", api_key),
        ] if not val
    ]
    if missing:
        raise SystemExit(f"Missing environment variables: {', '.join(missing)}")

    client = anthropic.Anthropic(api_key=api_key)
    ensure_csv_header()

    print("Fetching recent unread emails...")
    emails = fetch_recent_emails(address, app_password, MAX_EMAILS_TO_CHECK)

    if not emails:
        print("No unread emails found. Send a test email to the inbox and re-run.")
        return

    print(f"Found {len(emails)} unread email(s). Classifying...\n")

    for mail in emails:
        result = classify_email(client, mail)
        row = {
            "received_at": mail["date"],
            "from": mail["from"],
            "subject": mail["subject"],
            "category": result.get("category", ""),
            "urgency": result.get("urgency", ""),
            "one_line_summary": result.get("one_line_summary", ""),
            "suggested_reply": result.get("suggested_reply", ""),
            "processed_at": datetime.now().isoformat(timespec="seconds"),
        }
        append_row(row)
        print(f"  [{row['category'].upper()} / {row['urgency']}] {row['subject']} <- {row['from']}")

    print(f"\nDone. Results appended to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()