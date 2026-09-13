import os
import csv
import json
import imaplib
import email
import re

from email.header import decode_header
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
from google import genai
from google.genai import types


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")


if not GMAIL_ADDRESS:
    raise RuntimeError("GMAIL_ADDRESS is missing in .env")

if not GMAIL_APP_PASSWORD:
    raise RuntimeError("GMAIL_APP_PASSWORD is missing in .env")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is missing in .env")


# ============================================================
# CONFIGURATION
# ============================================================

INBOX_DIR = Path("inbox")

STATE_DIR = Path("state")
STATE_FILE = STATE_DIR / "processed_emails.json"

EMAIL_LOG = Path("email_log.csv")

MAX_EMAILS_TO_CHECK = 10

GEMINI_MODEL = "gemini-3.6-flash"


SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}


EMAIL_FIELDS = [
    "message_id",
    "received_at",
    "from",
    "subject",
    "category",
    "urgency",
    "has_attachment",
    "attachments_downloaded",
    "one_line_summary",
    "suggested_reply",
    "processed_at",
]


# ============================================================
# GEMINI CLIENT
# ============================================================

gemini_client = genai.Client(
    api_key=GEMINI_API_KEY
)


# ============================================================
# EMAIL CLASSIFICATION PROMPT
# ============================================================

CLASSIFY_PROMPT = """
You are an email triage assistant for a small business.

Analyze the email below.

Return the classification as structured JSON.

CATEGORY OPTIONS:

- invoice
- sales_lead
- support_request
- complaint
- spam
- other

Use "invoice" when the email is clearly sending or requesting
processing of an invoice, bill, receipt, payment document, or
similar financial document.

IMPORTANT:

Do not classify an email as "invoice" merely because it mentions
money.

Examples:

"Please find attached our invoice for September."
=> invoice

"Please process the attached bill."
=> invoice

"Can you tell me the price of your service?"
=> sales_lead

"My product is broken."
=> support_request

"I am unhappy with your service."
=> complaint


URGENCY:

- low
- medium
- high


has_invoice_attachment:

Return true only when the email itself clearly indicates that
an invoice/receipt/bill/document is attached.

Return false otherwise.


one_line_summary:

One sentence explaining what the sender wants.


suggested_reply:

Write a short professional reply of 2-4 sentences.

Email:

From:
{sender}

Subject:
{subject}

Body:
{body}
"""


# ============================================================
# MIME DECODER
# ============================================================

def decode_mime_words(value):

    if not value:
        return ""

    decoded_parts = decode_header(value)

    result = []

    for part, encoding in decoded_parts:

        if isinstance(part, bytes):

            result.append(
                part.decode(
                    encoding or "utf-8",
                    errors="replace"
                )
            )

        else:

            result.append(part)

    return "".join(result)


# ============================================================
# EMAIL BODY
# ============================================================

def get_email_body(msg):

    if msg.is_multipart():

        # Prefer plain text
        for part in msg.walk():

            content_type = part.get_content_type()

            disposition = str(
                part.get("Content-Disposition") or ""
            ).lower()

            if (
                content_type == "text/plain"
                and "attachment" not in disposition
            ):

                payload = part.get_payload(
                    decode=True
                )

                if not payload:
                    continue

                charset = (
                    part.get_content_charset()
                    or "utf-8"
                )

                return payload.decode(
                    charset,
                    errors="replace"
                )

        # Fallback to HTML
        for part in msg.walk():

            if part.get_content_type() == "text/html":

                payload = part.get_payload(
                    decode=True
                )

                if not payload:
                    continue

                charset = (
                    part.get_content_charset()
                    or "utf-8"
                )

                return payload.decode(
                    charset,
                    errors="replace"
                )

        return "(no readable email body found)"

    payload = msg.get_payload(
        decode=True
    )

    if not payload:
        return ""

    charset = (
        msg.get_content_charset()
        or "utf-8"
    )

    return payload.decode(
        charset,
        errors="replace"
    )


# ============================================================
# STATE MANAGEMENT
# ============================================================

def load_processed_ids():

    STATE_DIR.mkdir(
        exist_ok=True
    )

    if not STATE_FILE.exists():

        return set()

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        return set(data)

    except Exception:

        return set()


def save_processed_id(message_id):

    processed_ids = load_processed_ids()

    processed_ids.add(
        message_id
    )

    STATE_DIR.mkdir(
        exist_ok=True
    )

    with open(
        STATE_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            sorted(processed_ids),
            f,
            indent=2
        )


# ============================================================
# SAFE FILE NAME
# ============================================================

def safe_filename(filename):

    filename = Path(filename).name

    # Remove characters that are problematic on Windows/Linux
    filename = re.sub(
        r'[<>:"/\\|?*]',
        "_",
        filename
    )

    filename = filename.strip()

    if not filename:
        filename = "attachment"

    return filename


# ============================================================
# CLASSIFY EMAIL USING GEMINI
# ============================================================

def classify_email(mail):

    prompt = CLASSIFY_PROMPT.format(
        sender=mail["from"],
        subject=mail["subject"],
        body=mail["body"]
    )

    response = gemini_client.models.generate_content(

        model=GEMINI_MODEL,

        contents=prompt,

        config=types.GenerateContentConfig(

            temperature=0,

            response_mime_type="application/json",

            response_schema={

                "type": "object",

                "properties": {

                    "category": {
                        "type": "string",
                        "enum": [
                            "invoice",
                            "sales_lead",
                            "support_request",
                            "complaint",
                            "spam",
                            "other"
                        ]
                    },

                    "urgency": {
                        "type": "string",
                        "enum": [
                            "low",
                            "medium",
                            "high"
                        ]
                    },

                    "has_invoice_attachment": {
                        "type": "boolean"
                    },

                    "one_line_summary": {
                        "type": "string"
                    },

                    "suggested_reply": {
                        "type": "string"
                    }
                },

                "required": [
                    "category",
                    "urgency",
                    "has_invoice_attachment",
                    "one_line_summary",
                    "suggested_reply"
                ]
            }
        )
    )

    try:

        return json.loads(
            response.text
        )

    except json.JSONDecodeError:

        return {
            "category": "other",
            "urgency": "low",
            "has_invoice_attachment": False,
            "one_line_summary": "Unable to parse AI response.",
            "suggested_reply": ""
        }


# ============================================================
# DOWNLOAD INVOICE ATTACHMENTS
# ============================================================

def download_invoice_attachments(
    msg,
    message_id
):

    INBOX_DIR.mkdir(
        exist_ok=True
    )

    downloaded_files = []

    for part in msg.walk():

        filename = part.get_filename()

        if not filename:
            continue

        filename = decode_mime_words(
            filename
        )

        filename = safe_filename(
            filename
        )

        extension = Path(
            filename
        ).suffix.lower()

        if extension not in SUPPORTED_EXTENSIONS:
            continue

        payload = part.get_payload(
            decode=True
        )

        if not payload:
            continue

        # Prefix with Gmail message ID so that
        # two emails containing "invoice.pdf"
        # do not overwrite each other.

        output_filename = (
            f"{message_id}_{filename}"
        )

        output_path = (
            INBOX_DIR / output_filename
        )

        # Avoid overwriting an existing file
        counter = 1

        while output_path.exists():

            output_filename = (
                f"{message_id}_"
                f"{counter}_"
                f"{filename}"
            )

            output_path = (
                INBOX_DIR / output_filename
            )

            counter += 1

        with open(
            output_path,
            "wb"
        ) as f:

            f.write(payload)

        downloaded_files.append(
            output_path
        )

    return downloaded_files


# ============================================================
# EMAIL CSV
# ============================================================

def ensure_email_log():

    if EMAIL_LOG.exists():
        return

    with open(
        EMAIL_LOG,
        "w",
        newline="",
        encoding="utf-8"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=EMAIL_FIELDS
        )

        writer.writeheader()


def append_email_log(row):

    with open(
        EMAIL_LOG,
        "a",
        newline="",
        encoding="utf-8"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=EMAIL_FIELDS
        )

        writer.writerow(
            {
                field: row.get(
                    field,
                    ""
                )
                for field in EMAIL_FIELDS
            }
        )


# ============================================================
# PROCESS ONE EMAIL
# ============================================================

def process_email(
    msg,
    message_id
):

    sender = decode_mime_words(
        msg.get("From")
    )

    subject = decode_mime_words(
        msg.get("Subject")
    )

    received_at = msg.get(
        "Date"
    )

    body = get_email_body(
        msg
    )

    mail = {

        "from": sender,

        "subject": subject,

        "date": received_at,

        "body": body[:5000]
    }

    print()
    print(
        "=" * 60
    )

    print(
        f"[EMAIL] {subject}"
    )

    print(
        f"[FROM]  {sender}"
    )

    # --------------------------------------------------------
    # Gemini classification
    # --------------------------------------------------------

    result = classify_email(
        mail
    )

    category = result.get(
        "category",
        "other"
    )

    urgency = result.get(
        "urgency",
        "low"
    )

    print(
        f"[AI]    {category.upper()} / {urgency.upper()}"
    )

    # --------------------------------------------------------
    # Download attachments
    # --------------------------------------------------------

    downloaded_files = []

    # We only download supported documents from emails
    # that Gemini identifies as invoices.
    #
    # This prevents random PDFs/images from entering
    # the invoice extraction pipeline.

    if category == "invoice":

        downloaded_files = (
            download_invoice_attachments(
                msg,
                message_id
            )
        )

    if downloaded_files:

        for path in downloaded_files:

            print(
                f"[FILE]  Downloaded -> "
                f"{path}"
            )

    elif category == "invoice":

        print(
            "[FILE]  Invoice email detected "
            "but no PDF/image attachment found."
        )

    # --------------------------------------------------------
    # Log email
    # --------------------------------------------------------

    row = {

        "message_id":
            message_id,

        "received_at":
            received_at,

        "from":
            sender,

        "subject":
            subject,

        "category":
            category,

        "urgency":
            urgency,

        "has_attachment":
            bool(downloaded_files),

        "attachments_downloaded":
            len(downloaded_files),

        "one_line_summary":
            result.get(
                "one_line_summary",
                ""
            ),

        "suggested_reply":
            result.get(
                "suggested_reply",
                ""
            ),

        "processed_at":
            datetime.now().isoformat(
                timespec="seconds"
            )
    }

    append_email_log(
        row
    )

    print(
        "[EMAIL] Processing completed."
    )


# ============================================================
# POLL GMAIL
# ============================================================

def poll_gmail():

    ensure_email_log()

    processed_ids = load_processed_ids()

    imap = None

    processed_count = 0

    try:

        print(
            "[GMAIL] Connecting..."
        )

        imap = imaplib.IMAP4_SSL(
            "imap.gmail.com"
        )

        imap.login(
            GMAIL_ADDRESS,
            GMAIL_APP_PASSWORD
        )

        imap.select(
            "INBOX"
        )

        status, message_ids = (
            imap.search(
                None,
                "UNSEEN"
            )
        )

        if status != "OK":

            print(
                "[GMAIL] Unable to search inbox."
            )

            return 0

        ids = message_ids[0].split()

        if not ids:

            return 0

        # Only inspect the most recent N unread emails.

        ids = ids[
            -MAX_EMAILS_TO_CHECK:
        ]

        for msg_id in ids:

            message_id = (
                msg_id.decode(
                    "utf-8"
                )
            )

            # ------------------------------------------------
            # Avoid duplicate processing
            # ------------------------------------------------

            if message_id in processed_ids:

                continue

            # ------------------------------------------------
            # BODY.PEEK keeps email unread
            # ------------------------------------------------

            status, msg_data = (
                imap.fetch(
                    msg_id,
                    "(BODY.PEEK[])"
                )
            )

            if status != "OK":

                print(
                    f"[GMAIL] Failed to fetch "
                    f"message {message_id}"
                )

                continue

            raw_email = None

            for response_part in msg_data:

                if (
                    isinstance(
                        response_part,
                        tuple
                    )
                    and len(response_part) > 1
                ):

                    raw_email = (
                        response_part[1]
                    )

                    break

            if not raw_email:

                continue

            msg = email.message_from_bytes(
                raw_email
            )

            # ------------------------------------------------
            # Process email
            # ------------------------------------------------

            try:

                process_email(
                    msg,
                    message_id
                )

                # Save state ONLY after successful
                # email processing.

                save_processed_id(
                    message_id
                )

                processed_count += 1

            except Exception as e:

                print(
                    f"[EMAIL ERROR] "
                    f"{message_id}: {e}"
                )

                # Do not save state here.
                #
                # It will be retried next cycle.

    finally:

        if imap:

            try:
                imap.close()
            except Exception:
                pass

            try:
                imap.logout()
            except Exception:
                pass

    return processed_count


# ============================================================
# TEST / MANUAL RUN
# ============================================================

if __name__ == "__main__":

    print(
        "Starting email agent..."
    )

    count = poll_gmail()

    print()
    print(
        f"Processed {count} email(s)."
    )