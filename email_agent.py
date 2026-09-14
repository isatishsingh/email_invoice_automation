import os
import json
import imaplib
import email
import re

from email.header import decode_header
from pathlib import Path
from dotenv import load_dotenv


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD")


if not GMAIL_ADDRESS:
    raise RuntimeError("GMAIL_ADDRESS is missing in .env")

if not GMAIL_APP_PASSWORD:
    raise RuntimeError("GMAIL_APP_PASSWORD is missing in .env")


# ============================================================
# CONFIGURATION
# ============================================================

INBOX_DIR = Path("inbox")

STATE_DIR = Path("state")
STATE_FILE = STATE_DIR / "processed_emails.json"

# MAX_EMAILS_TO_CHECK = 50


SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}


# ============================================================
# INVOICE KEYWORDS
# ============================================================

# These are local rules.
# NO Gemini/API call is made here.

INVOICE_KEYWORDS = {
    "invoice",
    "inv",
    "bill",
    "billing",
    "receipt",
    "payment",
    "purchase order",
    "po",
    "tax invoice",
    "credit note",
    "debit note",
    "statement",
}


INVOICE_FILENAME_KEYWORDS = {
    "invoice",
    "inv",
    "bill",
    "receipt",
    "tax",
    "payment",
    "credit",
    "debit",
    "statement",
}


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

        return ""

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
# FIND ATTACHMENTS
# ============================================================

def get_attachments(msg):

    attachments = []

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

        attachments.append({
            "part": part,
            "filename": filename,
            "extension": extension,
        })

    return attachments


# ============================================================
# LOCAL INVOICE DETECTION
# ============================================================

def calculate_invoice_score(
    subject,
    body,
    attachments
):

    score = 0

    subject_lower = subject.lower()
    body_lower = body.lower()

    # --------------------------------------------------------
    # Subject
    # --------------------------------------------------------

    for keyword in INVOICE_KEYWORDS:

        if keyword in subject_lower:

            score += 5

            break

    # --------------------------------------------------------
    # Email body
    # --------------------------------------------------------

    for keyword in INVOICE_KEYWORDS:

        if keyword in body_lower:

            score += 3

            break

    # --------------------------------------------------------
    # Attachment filename
    # --------------------------------------------------------

    for attachment in attachments:

        filename = attachment["filename"].lower()

        for keyword in INVOICE_FILENAME_KEYWORDS:

            if keyword in filename:

                score += 5

                break

    # --------------------------------------------------------
    # Supported attachment
    # --------------------------------------------------------

    if attachments:

        score += 2

    return score


def is_invoice_email(
    subject,
    body,
    attachments
):

    score = calculate_invoice_score(
        subject,
        body,
        attachments
    )

    # Threshold can be adjusted later.
    return score >= 5


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

    attachments = get_attachments(msg)

    for attachment in attachments:

        part = attachment["part"]
        filename = attachment["filename"]

        payload = part.get_payload(
            decode=True
        )

        if not payload:
            continue

        # ----------------------------------------------------
        # Prefix with message ID.
        #
        # Example:
        #
        # 12345_invoice.pdf
        #
        # This prevents different emails containing
        # "invoice.pdf" from overwriting each other.
        # ----------------------------------------------------

        output_filename = (
            f"{message_id}_{filename}"
        )

        output_path = (
            INBOX_DIR / output_filename
        )

        # ----------------------------------------------------
        # Avoid overwriting existing files
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Save file
        # ----------------------------------------------------

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

    body = get_email_body(msg)

    attachments = get_attachments(msg)

    print()
    print("=" * 60)

    print(
        f"[EMAIL] {subject}"
    )

    print(
        f"[FROM]  {sender}"
    )

    print(
        f"[FILES] {len(attachments)} supported attachment(s)"
    )

    # --------------------------------------------------------
    # LOCAL INVOICE DETECTION
    # --------------------------------------------------------

    score = calculate_invoice_score(
        subject,
        body,
        attachments
    )

    invoice = is_invoice_email(
        subject,
        body,
        attachments
    )

    print(
        f"[SCORE] {score}"
    )

    if not invoice:

        print(
            "[SKIP]  Not an invoice candidate."
        )

        return

    print(
        "[MATCH] Invoice candidate detected."
    )

    # --------------------------------------------------------
    # DOWNLOAD ATTACHMENTS
    # --------------------------------------------------------

    downloaded_files = (
        download_invoice_attachments(
            msg,
            message_id
        )
    )

    if not downloaded_files:

        print(
            "[WARN] Invoice-like email found, "
            "but no PDF/image attachment."
        )

        return

    for path in downloaded_files:

        print(
            f"[FILE]  Downloaded -> {path}"
        )

    print(
        "[DONE]  Invoice attachment(s) "
        "added to inbox/"
    )


# ============================================================
# POLL GMAIL
# ============================================================

def poll_gmail():

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

        # ----------------------------------------------------
        # Find unread emails
        # ----------------------------------------------------

        from datetime import datetime

        today = datetime.now().strftime("%d-%b-%Y")

        print(
            f"[GMAIL] Searching emails since {today}..."
        )

        status, message_ids = (
            imap.search(
                None,
                "SINCE",
                today
            )
        )

        if status != "OK":

            print(
                "[GMAIL] Unable to search inbox."
            )

            return 0

        ids = message_ids[0].split()

        print(
            f"[GMAIL] Found {len(ids)} unread email(s)."
        )

        if not ids:

            print(
                "[GMAIL] No unread emails."
            )

            return 0

        print(
            "[GMAIL] Unread message IDs:"
        )

        for msg_id in ids:
            print(
                "   ",
                msg_id.decode("utf-8")
            )

        # ----------------------------------------------------
        # Process newest N emails
        # ----------------------------------------------------

        # ids = ids[
        #     -MAX_EMAILS_TO_CHECK:
        # ]

        for msg_id in ids:

            message_id = (
                msg_id.decode("utf-8")
            )

            # ------------------------------------------------
            # Duplicate protection
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
                    f"{message_id}"
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

            # ------------------------------------------------
            # Parse email
            # ------------------------------------------------

            msg = email.message_from_bytes(
                raw_email
            )

            # ------------------------------------------------
            # Process
            # ------------------------------------------------

            try:

                process_email(
                    msg,
                    message_id
                )

                # Save state only after successful processing
                save_processed_id(
                    message_id
                )

                processed_count += 1

            except Exception as e:

                print(
                    f"[EMAIL ERROR] "
                    f"{message_id}: {e}"
                )

                # Don't save state.
                #
                # It will be retried during the
                # next polling cycle.

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
# MAIN
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