import time
import threading
import traceback

from fastapi import FastAPI
import uvicorn

import email_agent_g
import invoice_extractor_g


# ============================================================
# CONFIGURATION
# ============================================================

GMAIL_POLL_INTERVAL = 10

INVOICE_CHECK_INTERVAL = 2


# ============================================================
# APPLICATION
# ============================================================

app = FastAPI(
    title="Invoice Email Automation",
    version="1.0.0"
)


# ============================================================
# RUNTIME STATE
# ============================================================

service_state = {

    "running": True,

    "gmail_worker": "starting",

    "invoice_worker": "starting",

    "last_gmail_check": None,

    "last_invoice_check": None,

    "last_error": None,
}


# ============================================================
# GMAIL WORKER
# ============================================================

def gmail_worker():

    service_state[
        "gmail_worker"
    ] = "running"

    while True:

        try:

            print()
            print(
                "[SYSTEM] Checking Gmail..."
            )

            count = (
                email_agent_g.poll_gmail()
            )

            service_state[
                "last_gmail_check"
            ] = time.time()

            service_state[
                "last_error"
            ] = None

            if count > 0:

                print(
                    f"[SYSTEM] Gmail processed "
                    f"{count} email(s)."
                )

        except Exception as e:

            service_state[
                "last_error"
            ] = str(e)

            print(
                "[GMAIL WORKER ERROR]"
            )

            print(e)

            traceback.print_exc()

            # Keep worker alive.
            # It will retry on next cycle.

        time.sleep(
            GMAIL_POLL_INTERVAL
        )


# ============================================================
# INVOICE WORKER
# ============================================================

def invoice_worker():

    service_state[
        "invoice_worker"
    ] = "running"

    while True:

        try:

            # ------------------------------------------------
            # Your existing invoice extractor already:
            #
            # 1. Looks at inbox/
            # 2. Sends documents to Gemini
            # 3. Writes invoices.csv
            # 4. Moves processed documents
            #
            # So we simply reuse it.
            # ------------------------------------------------

            invoice_extractor_g.main()

            service_state[
                "last_invoice_check"
            ] = time.time()

        except Exception as e:

            service_state[
                "last_error"
            ] = str(e)

            print(
                "[INVOICE WORKER ERROR]"
            )

            print(e)

            traceback.print_exc()

        time.sleep(
            INVOICE_CHECK_INTERVAL
        )


# ============================================================
# HEALTH ENDPOINT
# ============================================================

@app.get("/")
def root():

    return {

        "service":
            "Invoice Email Automation",

        "status":
            "running"
    }


@app.get("/health")
def health():

    return {

        "status":
            "healthy",

        "gmail_worker":
            service_state[
                "gmail_worker"
            ],

        "invoice_worker":
            service_state[
                "invoice_worker"
            ]
    }


@app.get("/status")
def status():

    return {

        "service":
            "invoice-email-automation",

        "running":
            service_state[
                "running"
            ],

        "gmail_worker":
            service_state[
                "gmail_worker"
            ],

        "invoice_worker":
            service_state[
                "invoice_worker"
            ],

        "last_gmail_check":
            service_state[
                "last_gmail_check"
            ],

        "last_invoice_check":
            service_state[
                "last_invoice_check"
            ],

        "last_error":
            service_state[
                "last_error"
            ]
    }


# ============================================================
# START SERVICE
# ============================================================

if __name__ == "__main__":

    print()
    print("=" * 70)
    print(
        "      INVOICE EMAIL AUTOMATION"
    )
    print("=" * 70)

    print()
    print(
        "Gmail Worker       : ACTIVE"
    )

    print(
        f"Gmail Interval     : "
        f"{GMAIL_POLL_INTERVAL} seconds"
    )

    print(
        "Invoice Worker     : ACTIVE"
    )

    print(
        f"Invoice Interval   : "
        f"{INVOICE_CHECK_INTERVAL} seconds"
    )

    print()
    print(
        "Health URL         : "
        "http://localhost:8000/health"
    )

    print(
        "Status URL         : "
        "http://localhost:8000/status"
    )

    print()
    print("=" * 70)
    print()

    # --------------------------------------------------------
    # Start Gmail worker
    # --------------------------------------------------------

    gmail_thread = threading.Thread(
        target=gmail_worker,
        daemon=True,
        name="GmailWorker"
    )

    # --------------------------------------------------------
    # Start invoice worker
    # --------------------------------------------------------

    invoice_thread = threading.Thread(
        target=invoice_worker,
        daemon=True,
        name="InvoiceWorker"
    )

    gmail_thread.start()

    invoice_thread.start()

    # --------------------------------------------------------
    # Start HTTP server
    # --------------------------------------------------------

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000
    )