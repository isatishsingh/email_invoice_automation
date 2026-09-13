"""
Invoice / Document Data Extractor
----------------------------------
Drops PDFs or images of invoices/receipts into an "inbox" folder,
sends each to Claude, extracts structured fields, and appends
them to a CSV. Run it, then open invoices.csv to see the result.

Setup:
    pip install -r requirements.txt
    Create a .env file in this folder containing:
        ANTHROPIC_API_KEY="sk-ant-..."   (get a free trial key at console.anthropic.com)

Usage:
    Put invoice PDFs/images into ./inbox/
    python invoice_extractor.py
"""

import os
import csv
import json
import base64
import mimetypes
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv
import anthropic

load_dotenv()

INBOX_DIR = Path("inbox")
PROCESSED_DIR = Path("processed")
OUTPUT_CSV = Path("invoices.csv")

FIELDS = [
    "file_name", "vendor", "invoice_number", "invoice_date",
    "due_date", "total_amount", "currency", "line_items_summary",
    "confidence_notes", "processed_at"
]

EXTRACTION_PROMPT = """You are an invoice data extraction assistant.
Look at the attached document and extract the following fields as a
single JSON object, with these exact keys:

- vendor: the company/person who issued the invoice
- invoice_number: the invoice or receipt number (or "N/A" if none)
- invoice_date: the date issued, format YYYY-MM-DD if possible
- due_date: the payment due date, format YYYY-MM-DD (or "N/A")
- total_amount: the final total as a plain number, no currency symbol
- currency: the 3-letter currency code (e.g. USD, INR, EUR) if you can tell, else "UNKNOWN"
- line_items_summary: a short one-line summary of what was purchased
- confidence_notes: anything unclear or ambiguous about the extraction (or "none")

Respond with ONLY the JSON object. No markdown fences, no preamble, no explanation.
"""


def build_document_block(file_path: Path) -> dict:
    """Build the correct Claude content block for a PDF or image file."""
    mime_type, _ = mimetypes.guess_type(str(file_path))
    if mime_type is None:
        raise ValueError(f"Could not determine file type for {file_path}")

    with open(file_path, "rb") as f:
        data_b64 = base64.standard_b64encode(f.read()).decode("utf-8")

    if mime_type == "application/pdf":
        return {
            "type": "document",
            "source": {"type": "base64", "media_type": mime_type, "data": data_b64},
        }
    elif mime_type.startswith("image/"):
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": mime_type, "data": data_b64},
        }
    else:
        raise ValueError(f"Unsupported file type: {mime_type}")


def extract_invoice_data(client: anthropic.Anthropic, file_path: Path) -> dict:
    doc_block = build_document_block(file_path)

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[
            {
                "role": "user",
                "content": [
                    doc_block,
                    {"type": "text", "text": EXTRACTION_PROMPT},
                ],
            }
        ],
    )

    raw_text = "".join(
        block.text for block in message.content if block.type == "text"
    ).strip()

    # Guard against accidental markdown fences
    raw_text = raw_text.replace("```json", "").replace("```", "").strip()

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        data = {
            "vendor": "PARSE_ERROR",
            "invoice_number": "N/A",
            "invoice_date": "N/A",
            "due_date": "N/A",
            "total_amount": "N/A",
            "currency": "N/A",
            "line_items_summary": "N/A",
            "confidence_notes": f"Raw model output could not be parsed: {raw_text[:200]}",
        }

    data["file_name"] = file_path.name
    data["processed_at"] = datetime.now().isoformat(timespec="seconds")
    return data


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
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit(
            "Set ANTHROPIC_API_KEY as an environment variable first.\n"
            "Get a free trial key at https://console.anthropic.com"
        )

    client = anthropic.Anthropic(api_key=api_key)

    INBOX_DIR.mkdir(exist_ok=True)
    PROCESSED_DIR.mkdir(exist_ok=True)
    ensure_csv_header()

    files = [
        f for f in INBOX_DIR.iterdir()
        if f.suffix.lower() in (".pdf", ".png", ".jpg", ".jpeg", ".webp")
    ]

    if not files:
        print(f"No files found in {INBOX_DIR}/. Drop some invoice PDFs or images there.")
        return

    print(f"Found {len(files)} file(s) to process...\n")

    for file_path in files:
        print(f"Processing {file_path.name} ...")
        try:
            row = extract_invoice_data(client, file_path)
            append_row(row)
            print(f"  -> {row['vendor']} | {row['total_amount']} {row['currency']} | {row['invoice_number']}")
            file_path.rename(PROCESSED_DIR / file_path.name)
        except Exception as e:
            print(f"  !! Failed to process {file_path.name}: {e}")

    print(f"\nDone. Results appended to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
