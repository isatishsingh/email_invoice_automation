"""
Invoice / Document Data Extractor
---------------------------------

Drops PDFs or images of invoices/receipts into an "inbox" folder,
sends each to Google Gemini, extracts structured fields, and appends
them to a CSV.

Setup:

    pip install -r requirements.txt

Create a .env file:

    GEMINI_API_KEY="your-api-key"

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
from google import genai
from google.genai import types


# ---------------------------------------------------------
# Environment
# ---------------------------------------------------------

load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise SystemExit(
        "GEMINI_API_KEY is not configured.\n"
        "Create a .env file containing:\n\n"
        'GEMINI_API_KEY="your-api-key"'
    )


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

INBOX_DIR = Path("inbox")
PROCESSED_DIR = Path("processed")
OUTPUT_CSV = Path("invoices.csv")

MODEL_NAME = "gemini-3.6-flash"


# ---------------------------------------------------------
# CSV Fields
# ---------------------------------------------------------

FIELDS = [
    "file_name",
    "vendor",
    "vendor_address",
    "vendor_country",
    "invoice_number",
    "invoice_date",
    "due_date",
    "due_terms",
    "subtotal",
    "tax_amount",
    "shipping_amount",
    "total_amount",
    "currency",
    "total_calculation_method",
    "line_items",
    "confidence_notes",
    "processed_at",
]


# ---------------------------------------------------------
# Extraction Prompt
# ---------------------------------------------------------

EXTRACTION_PROMPT = """
You are a highly accurate invoice/document data extraction system.

Your task is to extract structured financial information from the
ENTIRE attached invoice/document.

This is financial data. Accuracy is more important than guessing.

==================================================
GENERAL RULES
==================================================

1. Read the ENTIRE document, including ALL pages.

2. Do not summarize information that should be extracted as structured data.

3. Never invent or guess a value.

4. If a value is not explicitly available, return:
   "N/A" for text/date/amount fields
   "UNKNOWN" for currency or country when it cannot be established.

5. Preserve the exact order of line items as they appear in the document.

6. If a table continues onto another page, continue extracting the
   items in the same order.

7. Do not stop after the first page.

==================================================
VENDOR
==================================================

vendor:
The company/person that issued the invoice.

vendor_address:
Extract the complete vendor address if visible.

vendor_country:
Return the country ONLY if it is explicitly written or unambiguously
shown as part of the address.

DO NOT infer country from:
- city
- state/province abbreviation
- telephone number
- website domain
- currency
- company name
- logo

If country is not explicit:
"UNKNOWN"

==================================================
INVOICE NUMBER
==================================================

Extract the invoice number or receipt number.

If unavailable:
"N/A"

==================================================
DATES
==================================================

invoice_date:
The date the invoice was issued.

Format:
YYYY-MM-DD

due_date:
Only populate this when the document provides an actual specific
calendar date.

For example:

"Due November 12, 2021"

should become:

"2021-11-12"

==================================================
PAYMENT TERMS
==================================================

due_terms:
Preserve relative payment terms exactly.

For example:

"Due 30 days after receipt"

must become:

due_date = "N/A"

due_terms = "30 days after receipt"

IMPORTANT:
DO NOT calculate a due date from "30 days after receipt" using the
invoice date because the receipt date may be different.

Only calculate a due date when the document explicitly provides a
reference date that makes the calculation unambiguous.

==================================================
CURRENCY
==================================================

Determine currency ONLY from evidence visible in the document.

Priority:

1. Explicit currency code
2. Explicit currency symbol
3. Explicit currency name

Examples:

€ → EUR
$ → USD only when the document/context clearly establishes USD
£ → GBP
₹ → INR

IMPORTANT:

DO NOT infer currency from vendor country.

For example:

Germany does NOT automatically mean EUR.

If the currency cannot be established from the document:

"UNKNOWN"

==================================================
LINE ITEMS
==================================================

Extract EVERY line item.

DO NOT summarize line items.

DO NOT combine multiple line items.

DO NOT omit items because there are many items.

DO NOT stop after the first page.

Preserve the exact order from the document.

Each line item should contain:

- item_number
- description
- product_code
- quantity
- unit
- unit_price
- line_total

If a value does not exist in the document:
"N/A"

If the document has an item number, preserve it.

If the document does not have item numbers, generate sequential
numbers based on the document order.

Example:

[
    {
        "item_number": 1,
        "description": "...",
        "product_code": "...",
        "quantity": 5,
        "unit": "pcs",
        "unit_price": 200,
        "line_total": 1000
    },
    {
        "item_number": 2,
        "description": "...",
        "product_code": "...",
        "quantity": 5,
        "unit": "pcs",
        "unit_price": 500,
        "line_total": 2500
    }
]

==================================================
TOTALS
==================================================

Extract:

subtotal
tax_amount
shipping_amount
total_amount

Prefer explicitly printed totals.

If the final total is explicitly shown:
total_calculation_method = "explicit"

If the document does not provide a final total, but ALL required
line item totals are available and can safely be added:
calculate the total.

Then:
total_calculation_method = "calculated_from_line_items"

If the total cannot safely be calculated:
total_amount = "N/A"

total_calculation_method = "unavailable"

NEVER invent a total.

==================================================
CONFIDENCE NOTES
==================================================

Mention only actual uncertainties, such as:

- unreadable text
- missing page
- ambiguous currency
- missing total
- partially visible line item
- unclear quantity
- unclear price

Do not create warnings based on assumptions.

If everything is clear:
"none"

==================================================
IMPORTANT FINAL REQUIREMENT
==================================================

Return ALL line items.

The output must represent the complete invoice, not a summary.

Preserve the document's ordering exactly.
"""


# ---------------------------------------------------------
# Gemini Client
# ---------------------------------------------------------

client = genai.Client(api_key=GEMINI_API_KEY)


# ---------------------------------------------------------
# Build Gemini document content
# ---------------------------------------------------------

def build_document_part(file_path: Path):
    """
    Convert PDF/image into a Gemini-compatible content part.
    """

    mime_type, _ = mimetypes.guess_type(str(file_path))

    if mime_type is None:
        raise ValueError(
            f"Could not determine file type for {file_path}"
        )

    with open(file_path, "rb") as f:
        file_bytes = f.read()

    encoded_data = base64.b64encode(file_bytes).decode("utf-8")

    return types.Part.from_bytes(
        data=base64.b64decode(encoded_data),
        mime_type=mime_type,
    )


# ---------------------------------------------------------
# Extract Invoice Data
# ---------------------------------------------------------

def extract_invoice_data(
    file_path: Path,
) -> dict:

    document_part = build_document_part(file_path)

    response_schema = {
    "type": "object",
    "properties": {

        "vendor": {
            "type": "string"
        },

        "vendor_address": {
            "type": "string"
        },

        "vendor_country": {
            "type": "string"
        },

        "invoice_number": {
            "type": "string"
        },

        "invoice_date": {
            "type": "string"
        },

        "due_date": {
            "type": "string"
        },

        "due_terms": {
            "type": "string"
        },

        "subtotal": {
            "type": "string"
        },

        "tax_amount": {
            "type": "string"
        },

        "shipping_amount": {
            "type": "string"
        },

        "total_amount": {
            "type": "string"
        },

        "currency": {
            "type": "string"
        },

        "total_calculation_method": {
            "type": "string"
        },

        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {

                    "item_number": {
                        "type": "integer"
                    },

                    "description": {
                        "type": "string"
                    },

                    "product_code": {
                        "type": "string"
                    },

                    "quantity": {
                        "type": "string"
                    },

                    "unit": {
                        "type": "string"
                    },

                    "unit_price": {
                        "type": "string"
                    },

                    "line_total": {
                        "type": "string"
                    }
                },
                "required": [
                    "item_number",
                    "description",
                    "product_code",
                    "quantity",
                    "unit",
                    "unit_price",
                    "line_total"
                ]
            }
        },

        "confidence_notes": {
            "type": "string"
        }
    },

    "required": [
        "vendor",
        "vendor_address",
        "vendor_country",
        "invoice_number",
        "invoice_date",
        "due_date",
        "due_terms",
        "subtotal",
        "tax_amount",
        "shipping_amount",
        "total_amount",
        "currency",
        "total_calculation_method",
        "line_items",
        "confidence_notes"
    ]
}

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=[
            document_part,
            EXTRACTION_PROMPT,
        ],
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
            response_schema=response_schema,
        ),
    )

    try:
        data = json.loads(response.text)

    except json.JSONDecodeError:
        data = {
            "vendor": "PARSE_ERROR",
            "invoice_number": "N/A",
            "invoice_date": "N/A",
            "due_date": "N/A",
            "total_amount": "N/A",
            "currency": "N/A",
            "line_items_summary": "N/A",
            "confidence_notes": (
                f"Gemini returned invalid JSON: "
                f"{response.text[:300]}"
            ),
        }

    data["file_name"] = file_path.name

    data["processed_at"] = datetime.now().isoformat(
        timespec="seconds"
    )

    return data


# ---------------------------------------------------------
# CSV Header
# ---------------------------------------------------------

def ensure_csv_header():

    if not OUTPUT_CSV.exists():

        with open(
            OUTPUT_CSV,
            "w",
            newline="",
            encoding="utf-8",
        ) as f:

            writer = csv.DictWriter(
                f,
                fieldnames=FIELDS,
            )

            writer.writeheader()


# ---------------------------------------------------------
# Append CSV Row
# ---------------------------------------------------------

def append_row(row: dict):

    with open(
        OUTPUT_CSV,
        "a",
        newline="",
        encoding="utf-8",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=FIELDS,
        )

        writer.writerow(
            {
                key: row.get(key, "")
                for key in FIELDS
            }
        )


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

def main():

    INBOX_DIR.mkdir(exist_ok=True)

    PROCESSED_DIR.mkdir(exist_ok=True)

    ensure_csv_header()

    files = [
        f
        for f in INBOX_DIR.iterdir()
        if f.suffix.lower()
        in (
            ".pdf",
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
        )
    ]

    if not files:

        print(
            f"No files found in {INBOX_DIR}/.\n"
            "Drop invoice PDFs or images there."
        )

        return

    print(
        f"Found {len(files)} file(s) to process...\n"
    )

    for file_path in files:

        print(
            f"Processing {file_path.name} ..."
        )

        try:

            row = extract_invoice_data(
                file_path
            )

            append_row(row)

            print(
                f"  -> {row['vendor']} | "
                f"{row['total_amount']} "
                f"{row['currency']} | "
                f"{row['invoice_number']}"
            )

            destination = (
                PROCESSED_DIR / file_path.name
            )

            # Avoid overwriting if same filename exists
            if destination.exists():

                timestamp = datetime.now().strftime(
                    "%Y%m%d_%H%M%S"
                )

                destination = (
                    PROCESSED_DIR
                    / f"{file_path.stem}_{timestamp}"
                    f"{file_path.suffix}"
                )

            file_path.rename(destination)

        except Exception as e:

            print(
                f"  !! Failed to process "
                f"{file_path.name}: {e}"
            )

    print(
        f"\nDone. Results appended to "
        f"{OUTPUT_CSV}"
    )


# ---------------------------------------------------------
# Entry Point
# ---------------------------------------------------------

if __name__ == "__main__":
    main()