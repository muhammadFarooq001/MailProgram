# Mail Automation

This project previews personalized emails from a CSV file and can send them through an SMTP provider.

## First run

From the project directory, activate the root environment and run:

```powershell
.\.venv\Scripts\Activate.ps1
python mail.py
```

The default command is preview-only. Contacts must have `name` and `email` columns in `data/contacts.csv`.

Keep real contact lists in `data/contacts.local.csv` and run with `--csv data/contacts.local.csv`; that file is ignored by Git. The committed `data/contacts.csv` contains only a placeholder address.

## Sending

For Gmail, copy `.env.example` to `.env` and replace the placeholder values:

```powershell
Copy-Item .env.example .env
notepad .env
python mail.py --send
```

For Gmail, use an App Password, not your normal Google password. Enable two-step verification in your Google account first, then create an App Password. Do not put real credentials in the notebook, source code, or Git.

## Interactive sending

To enter the recipient and SMTP App Password at runtime, use:

```powershell
& .\.venv\Scripts\python.exe .\mail.py --interactive
```

This previews the message. The password is hidden and held only in memory. To send after reviewing the preview, use:

```powershell
& .\.venv\Scripts\python.exe .\mail.py --interactive --send
```

Interactive mode also asks for the subject and message. Enter `{{name}}` in the message if you want to personalize it.

The optional `--to` argument skips the recipient email prompt:

```powershell
& .\.venv\Scripts\python.exe .\mail.py --interactive --to recipient@example.com --send
```

The message template supports `{{name}}`, for example:

```powershell
python mail.py --subject "Welcome" --body "Hello {{name}},`n`nWelcome to the course."
```

The next improvements should be delivery logs, duplicate-send protection, tests, and provider-specific authentication.

## Gmail inbox dashboard

Install the web dependency and start the local dashboard:

```powershell
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe .\inbox_app.py
```

Open http://127.0.0.1:5000 in your browser. Enter the Gmail address and App Password in the page. The password is kept in memory only. The dashboard lists the inbox in pages of 25 messages and opens plain-text message details without marking messages as read.

The inbox page also supports searching sender, subject, and message text. Search results keep their own pagination. Messages can be marked read or unread without opening them.

Use **Compose** to send a message from the connected Gmail account. Sending uses the same in-memory App Password and returns to the inbox after success. No delete or archive action is included yet, so mailbox data is not removed accidentally.