# AI Automation Demo — Build Plan (1 Day)

Two working scripts:

1. `invoice_extractor.py` — turns invoice/receipt PDFs or photos into structured CSV rows.
2. `email_classifier.py` — reads unread Gmail messages, classifies them, and drafts replies.

Both use the Claude API and free-tier credits. Total cost to build and demo: $0.

---

## 0. Before you start (15 min)

- Get a free Anthropic API key: https://console.anthropic.com (new accounts get free trial credits — plenty for a demo).
- Install dependencies:
  ```bash
  pip install -r requirements.txt
  ```
- Copy `.env.example` to a new file named `.env` in the same folder, then fill in your real values:
  ```
  ANTHROPIC_API_KEY=sk-ant-your-key-here
  GMAIL_ADDRESS=youraddress@gmail.com
  GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
  ```
  Both scripts load this file automatically on startup — no need to `export` anything in your terminal. Never share this `.env` file or commit it to git (it's already listed in `.gitignore`).

---

## 1. Invoice / Document Extractor (target: 2–3 hours)

**What it proves to the client:** "Drop any invoice in, structured data comes out in seconds — no manual typing."

### Steps
1. `mkdir inbox` in the project folder.
2. Drop 3–5 sample invoices/receipts in there (PDFs or photos — grab a few real ones from the client if possible, or search "sample invoice pdf" for demo data).
3. Run:
   ```bash
   python invoice_extractor.py
   ```
4. Open `invoices.csv` — you'll see vendor, invoice number, date, total, etc. auto-filled.

### Edge cases to test before the demo (budget 30–45 min)
- A blurry phone photo of a receipt.
- An invoice in a different currency.
- A messy/non-standard layout.

If something misparses, look at `confidence_notes` in the CSV — it explains what the model was unsure about. Tune `EXTRACTION_PROMPT` in the script if you see a recurring issue.

### Upgrade path (mention to client, don't need to build it)
- Swap the CSV write for a Google Sheets API call or Airtable — same JSON, different destination.
- Add a simple drag-and-drop web upload (Streamlit — free) instead of a folder.

---

## 2. Email Classifier + Auto-Draft (target: 2–3 hours)

**What it proves to the client:** "Every incoming email gets triaged and a draft reply is ready before a human even opens it."

### Steps
1. Use a test Gmail account (not the client's real inbox for the first run).
2. Enable 2-Step Verification → generate an App Password: https://myaccount.google.com/apppasswords
3. Set env vars:
   ```bash
   export GMAIL_ADDRESS="test@gmail.com"
   export GMAIL_APP_PASSWORD="xxxx xxxx xxxx xxxx"
   ```
4. Send yourself 3–5 test emails that look like real inquiries (a sales question, a complaint, a support request, some spam-like promo).
5. Run:
   ```bash
   python email_classifier.py
   ```
6. Open `email_log.csv` — category, urgency, and a drafted reply appear for each email.

Note: the script only reads emails (`BODY.PEEK`) and never marks them read or sends anything — safe to re-run live during the demo as many times as you want.

### Upgrade path (mention, don't need to build)
- Auto-create a Gmail draft via the Gmail API instead of just logging to CSV (one more API call).
- Route "high urgency" + "complaint" emails to Slack/SMS instantly.

---

## 3. Demo Script (10–15 min with client)

1. **Open with the pain point** (30 sec): "Right now, someone on your team manually reads invoices / triages emails. That's hours a week and it's error-prone."
2. **Live invoice demo** (3–4 min): Drop a real invoice into `inbox/`, run the script live, show the CSV row appear.
3. **Live email demo** (3–4 min): Send a test email live from your phone, run the classifier, show the classification + draft reply appear within seconds.
4. **Show the CSV as "your data, your system"** — emphasize nothing is locked into a black box; the output is just a spreadsheet they already know how to use.
5. **Close with the upgrade path** — this is a working prototype; a production version would connect directly to their inbox/accounting software and run automatically in the background.

---

## Common gotchas
- **PDF too large / scanned at low quality**: Claude can still read most scanned PDFs, but very low-res phone photos may need better lighting.
- **IMAP login fails**: almost always means you used your normal Gmail password instead of the App Password, or 2-Step Verification isn't turned on yet.
- **JSON parse errors**: rare, but if the model adds extra commentary, the scripts already strip markdown fences — if you still see `PARSE_ERROR` rows, tighten the prompt with "Respond with ONLY the JSON object."