import time
from pathlib import Path

import email_agent
import invoice_extractor


# ============================================================
# CONFIGURATION
# ============================================================

INBOX_DIR = Path("inbox")

POLL_INTERVAL = 10  # seconds


SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}


# ============================================================
# CHECK INVOICE FILES
# ============================================================

def has_invoice_files():

    if not INBOX_DIR.exists():
        return False

    for file in INBOX_DIR.iterdir():

        if not file.is_file():
            continue

        if file.suffix.lower() in SUPPORTED_EXTENSIONS:
            return True

    return False


# ============================================================
# RUN INVOICE EXTRACTION
# ============================================================

def process_invoices():

    if not has_invoice_files():
        return

    print()
    print("=" * 60)
    print("[INVOICE] New invoice file(s) detected.")
    print("[INVOICE] Starting invoice extraction...")
    print("=" * 60)

    try:

        invoice_extractor.main()

        print()
        print("[INVOICE] Extraction completed.")

    except Exception as e:

        print()
        print(
            f"[INVOICE ERROR] {e}"
        )


# ============================================================
# MAIN LOOP
# ============================================================

def main():

    print()
    print("=" * 60)
    print("       INVOICE EMAIL AUTOMATION")
    print("=" * 60)
    print()

    print(
        f"[SYSTEM] Checking Gmail every "
        f"{POLL_INTERVAL} seconds."
    )

    print(
        "[SYSTEM] Press Ctrl+C to stop."
    )

    print()

    while True:

        try:

            # ------------------------------------------------
            # STEP 1
            # Check Gmail
            # ------------------------------------------------

            print(
                "[GMAIL] Checking for new emails..."
            )

            count = email_agent.poll_gmail()

            if count > 0:

                print(
                    f"[GMAIL] Processed "
                    f"{count} email(s)."
                )

            else:

                print(
                    "[GMAIL] No new emails."
                )

            # ------------------------------------------------
            # STEP 2
            # Check inbox/
            # ------------------------------------------------

            process_invoices()

            # ------------------------------------------------
            # STEP 3
            # Wait before next check
            # ------------------------------------------------

            print()
            print(
                f"[SYSTEM] Sleeping "
                f"{POLL_INTERVAL} seconds..."
            )

            time.sleep(
                POLL_INTERVAL
            )

        except KeyboardInterrupt:

            print()
            print(
                "[SYSTEM] Stopping..."
            )

            break

        except Exception as e:

            print()
            print(
                f"[SYSTEM ERROR] {e}"
            )

            print(
                "[SYSTEM] Retrying..."
            )

            time.sleep(
                POLL_INTERVAL
            )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()