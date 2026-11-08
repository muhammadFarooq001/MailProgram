import html
import imaplib
import os
import smtplib
from dataclasses import dataclass
from email import policy
from email.header import decode_header
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from pathlib import Path

from flask import Flask, redirect, render_template_string, request, url_for


app = Flask(__name__)
PAGE_SIZE = 25
credentials: "MailboxCredentials | None" = None


@dataclass
class MailboxCredentials:
	username: str
	password: str
	host: str = "imap.gmail.com"
	port: int = 993


def load_dotenv(dotenv_path: Path = Path(".env")) -> None:
	if not dotenv_path.exists():
		return

	for line in dotenv_path.read_text(encoding="utf-8").splitlines():
		line = line.strip()
		if not line or line.startswith("#") or "=" not in line:
			continue
		key, value = line.split("=", 1)
		os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def configured_credentials() -> MailboxCredentials | None:
	username = os.environ.get("SMTP_USER", "").strip()
	password = os.environ.get("SMTP_PASSWORD", "").strip()
	if not username or not password:
		return None
	return MailboxCredentials(username=username, password=password.replace(" ", ""))


def active_credentials() -> MailboxCredentials | None:
	return credentials or configured_credentials()


def decode_text(value: str | None, fallback: str = "") -> str:
	if not value:
		return fallback
	parts = decode_header(value)
	decoded = []
	for part, encoding in parts:
		if isinstance(part, bytes):
			decoded.append(part.decode(encoding or "utf-8", errors="replace"))
		else:
			decoded.append(part)
	return "".join(decoded)


def format_date(value: str | None) -> str:
	if not value:
		return "Unknown date"
	try:
		return parsedate_to_datetime(value).strftime("%b %d, %Y %H:%M")
	except (TypeError, ValueError, OverflowError):
		return value


def message_body(message) -> str:
	if message.is_multipart():
		for part in message.walk():
			if part.get_content_type() == "text/plain" and "attachment" not in part.get("Content-Disposition", ""):
				return part.get_content().strip()
		return "(This message has no plain-text body.)"
	if message.get_content_type() == "text/plain":
		return message.get_content().strip()
	return "(This message is not plain text.)"


def open_mailbox(readonly: bool = True):
	active = active_credentials()
	if active is None:
		raise ValueError("Enter a Gmail address and App Password to connect.")
	mailbox = imaplib.IMAP4_SSL(active.host, active.port)
	mailbox.login(active.username, active.password)
	mailbox.select("INBOX", readonly=readonly)
	return mailbox


def fetch_header(mailbox, uid: bytes, unread: bool) -> dict[str, str]:
	status, data = mailbox.uid("fetch", uid, "(BODY.PEEK[HEADER])")
	if status != "OK":
		raise RuntimeError("Gmail could not load this message header.")
	raw = b"".join(part[1] for part in data if isinstance(part, tuple))
	message = BytesParser(policy=policy.default).parsebytes(raw)
	return {
		"uid": uid.decode(),
		"subject": decode_text(str(message["Subject"] or ""), "(no subject)"),
		"sender": decode_text(str(message["From"] or ""), "(unknown sender)"),
		"date": format_date(str(message["Date"] or "")),
		"unread": "1" if unread else "0",
	}


def fetch_message(uid: str):
	if not uid.isdigit():
		raise ValueError("Invalid message id.")
	mailbox = open_mailbox()
	try:
		status, data = mailbox.uid("fetch", uid.encode(), "(RFC822)")
		if status != "OK":
			raise RuntimeError("Gmail could not load this message.")
		raw = b"".join(part[1] for part in data if isinstance(part, tuple))
		return BytesParser(policy=policy.default).parsebytes(raw)
	finally:
		mailbox.logout()


def fetch_inbox(page: int, query: str = "") -> tuple[list[dict[str, str]], int]:
	mailbox = open_mailbox()
	try:
		if query:
			escaped_query = query.replace("\\", "\\\\").replace('"', '\\"')
			status, data = mailbox.uid("search", None, "TEXT", f'"{escaped_query}"')
		else:
			status, data = mailbox.uid("search", None, "ALL")
		if status != "OK":
			raise RuntimeError("Gmail could not search the inbox.")
		uids = list(reversed(data[0].split()))
		status, unseen_data = mailbox.uid("search", None, "UNSEEN")
		if status != "OK":
			raise RuntimeError("Gmail could not find unread messages.")
		unread_uids = set(unseen_data[0].split())
		total = len(uids)
		start = max(page - 1, 0) * PAGE_SIZE
		page_uids = uids[start : start + PAGE_SIZE]
		return [fetch_header(mailbox, uid, uid in unread_uids) for uid in page_uids], total
	finally:
		mailbox.logout()


def set_message_seen(uid: str, seen: bool) -> None:
	if not uid.isdigit():
		raise ValueError("Invalid message id.")
	mailbox = open_mailbox(readonly=False)
	try:
		operation = "+FLAGS" if seen else "-FLAGS"
		status, _ = mailbox.uid("store", uid.encode(), operation, "\\Seen")
		if status != "OK":
			raise RuntimeError("Gmail could not update this message.")
	finally:
		mailbox.logout()


def send_ui_message(recipient: str, subject: str, body: str) -> None:
	active = active_credentials()
	if active is None:
		raise ValueError("Connect Gmail before sending a message.")
	host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
	port = int(os.environ.get("SMTP_PORT", "587"))
	message = EmailMessage()
	message["From"] = active.username
	message["To"] = recipient
	message["Subject"] = subject
	message.set_content(body)
	with smtplib.SMTP(host, port) as smtp:
		smtp.starttls()
		smtp.login(active.username, active.password)
		smtp.send_message(message)


def layout(content: str, title: str = "Inbox") -> str:
	return render_template_string(
		"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }} | Mail Automation</title>
<style>
:root { color-scheme: light; font-family: Segoe UI, sans-serif; background: #f3f6f8; color: #17212b; }
body { margin: 0; }
header { background: #123b4a; color: white; padding: 22px max(20px, calc((100% - 1100px) / 2)); display: flex; justify-content: space-between; align-items: center; gap: 20px; }
header h1 { margin: 0; font-size: 22px; }
header a { color: #d7f0e5; text-decoration: none; }
main { max-width: 1100px; margin: 28px auto; padding: 0 20px; }
.panel { background: white; border: 1px solid #dce5e9; border-radius: 8px; padding: 24px; box-shadow: 0 8px 24px #123b4a12; }
.message { padding: 18px 0; border-bottom: 1px solid #e8eef0; }
.message:hover { background: #f5faf8; }
.message:last-child { border-bottom: 0; }
.message-link { display: block; color: inherit; text-decoration: none; }
.message.unread .subject, .message.unread .sender { font-weight: 800; }
.message-actions { margin-top: 10px; }
.small-button { padding: 6px 9px; font-size: 13px; }
.compose-form { max-width: 700px; }
textarea { width: 100%; min-height: 220px; box-sizing: border-box; font: inherit; padding: 11px 12px; border: 1px solid #b9c9cf; border-radius: 5px; }
.row { display: flex; justify-content: space-between; gap: 20px; }
.sender { font-weight: 700; }
.subject { margin-top: 6px; color: #244e5e; }
.meta, .muted { color: #64737a; font-size: 14px; }
.snippet { margin-top: 8px; color: #52636a; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
input, button { font: inherit; padding: 11px 12px; border-radius: 5px; border: 1px solid #b9c9cf; }
input { width: min(100%, 420px); display: block; margin: 7px 0 16px; }
button { background: #16745b; color: white; border-color: #16745b; cursor: pointer; }
.error { background: #fff1ef; border: 1px solid #e6aaa1; padding: 12px; margin-bottom: 16px; color: #8d2920; }
.pagination { display: flex; justify-content: space-between; margin-top: 20px; }
.pagination a { color: #12634f; }
pre { white-space: pre-wrap; font: inherit; line-height: 1.55; }
</style>
</head>
<body>{{ content|safe }}</body>
</html>
""",
		title=title,
		content=content,
	)


def setup_page(error: str = "") -> str:
	error_html = f'<div class="error">{html.escape(error)}</div>' if error else ""
	return layout(
		f"""
<header><h1>Mail Automation</h1></header>
<main><section class="panel">
<h2>Connect Gmail</h2>
<p class="muted">Use a Gmail App Password. It is held in memory and is not saved by this dashboard.</p>
{error_html}
<form method="post" action="{url_for('connect')}">
<label>Gmail address<input name="username" type="email" required autocomplete="username"></label>
<label>App Password<input name="password" type="password" required autocomplete="current-password"></label>
<button type="submit">Open inbox</button>
</form>
</section></main>
""",
		title="Connect Gmail",
	)


def compose_page(recipient: str = "", subject: str = "", body: str = "", error: str = "") -> str:
	error_html = f'<div class="error">{html.escape(error)}</div>' if error else ""
	content = f"""
<header><h1>Compose</h1><a href="{url_for('index')}">Back to inbox</a></header>
<main><section class="panel compose-form">
<h2>New message</h2>
{error_html}
<form method="post" action="{url_for('compose')}">
<label>To<input name="recipient" type="email" required value="{html.escape(recipient)}"></label>
<label>Subject<input name="subject" required value="{html.escape(subject)}"></label>
<label>Message<textarea name="body" required>{html.escape(body)}</textarea></label>
<button type="submit">Send message</button>
</form>
</section></main>
"""
	return layout(content, title="Compose")


@app.get("/")
def index():
	page = max(request.args.get("page", 1, type=int), 1)
	query = request.args.get("q", "").strip()
	try:
		messages, total = fetch_inbox(page, query)
	except Exception as error:
		return setup_page(str(error)), 400
	items = []
	for message in messages:
		unread = message["unread"] == "1"
		seen_value = "true" if unread else "false"
		seen_label = "Mark read" if unread else "Mark unread"
		items.append(
			f"""<div class="message{' unread' if unread else ''}">
<a class="message-link" href="{url_for('message_detail', uid=message['uid'])}">
<div class="row"><span class="sender">{html.escape(message['sender'])}</span><span class="meta">{html.escape(message['date'])}</span></div>
<div class="subject">{html.escape(message['subject'])}</div>
</a>
<form class="message-actions" method="post" action="{url_for('set_seen', uid=message['uid'])}">
<input type="hidden" name="seen" value="{seen_value}"><button class="small-button" type="submit">{seen_label}</button>
</form>
</div>"""
		)
	start = (page - 1) * PAGE_SIZE + 1 if total else 0
	end = min(page * PAGE_SIZE, total)
	previous = f'<a href="{url_for("index", page=page - 1, q=query)}">Previous</a>' if page > 1 else "<span></span>"
	next_link = f'<a href="{url_for("index", page=page + 1, q=query)}">Next</a>' if end < total else "<span></span>"
	content = f"""
<header><h1>Inbox</h1><nav><a href="{url_for('compose')}">Compose</a> <a href="{url_for('index', page=page, q=query)}">Refresh</a> <a href="{url_for('disconnect')}">Disconnect</a></nav></header>
<main><section class="panel">
<form method="get" action="{url_for('index')}">
<label>Search inbox<input name="q" value="{html.escape(query)}" placeholder="Search sender, subject, or message text"></label>
<button type="submit">Search</button>
{'<a href="' + url_for('index') + '">Clear</a>' if query else ''}
</form>
<div class="row"><div><h2>Inbox messages</h2><p class="muted">Showing {start}-{end} of {total}{' matching “' + html.escape(query) + '”' if query else ''}</p></div></div>
{''.join(items) or '<p class="muted">Your inbox is empty.</p>'}
<div class="pagination">{previous}{next_link}</div>
</section></main>
"""
	return layout(content)


@app.get("/compose")
def compose():
	return compose_page(
		recipient=request.args.get("to", ""),
		subject=request.args.get("subject", ""),
	)


@app.post("/compose")
def send_composed_message():
	recipient = request.form.get("recipient", "").strip()
	subject = request.form.get("subject", "").strip()
	body = request.form.get("body", "").strip()
	if not recipient or not subject or not body:
		return compose_page(recipient, subject, body, "Recipient, subject, and message are required."), 400
	try:
		send_ui_message(recipient, subject, body)
		return redirect(url_for("index"))
	except Exception as error:
		return compose_page(recipient, subject, body, f"Message could not be sent: {error}"), 400


@app.post("/message/<uid>/seen")
def set_seen(uid: str):
	try:
		set_message_seen(uid, request.form.get("seen") == "true")
		return redirect(url_for("index"))
	except Exception as error:
		return setup_page(str(error)), 400


@app.post("/connect")
def connect():
	global credentials
	username = request.form.get("username", "").strip()
	password = request.form.get("password", "").replace(" ", "").strip()
	if not username or not password:
		return setup_page("Both Gmail address and App Password are required."), 400
	credentials = MailboxCredentials(username=username, password=password)
	try:
		with open_mailbox() as mailbox:
			mailbox.noop()
		return redirect(url_for("index"))
	except Exception as error:
		credentials = None
		return setup_page(f"Gmail connection failed: {error}"), 400


@app.get("/disconnect")
def disconnect():
	global credentials
	credentials = None
	return redirect(url_for("index"))


@app.get("/message/<uid>")
def message_detail(uid: str):
	try:
		message = fetch_message(uid)
	except Exception as error:
		return setup_page(str(error)), 400
	subject = decode_text(str(message["Subject"] or ""), "(no subject)")
	sender = decode_text(str(message["From"] or ""), "(unknown sender)")
	body = html.escape(message_body(message))
	content = f"""
<header><h1>Message</h1><a href="{url_for('index')}">Back to inbox</a></header>
<main><article class="panel"><p class="muted">From: {html.escape(sender)}</p><h2>{html.escape(subject)}</h2><pre>{body}</pre></article></main>
"""
	return layout(content, title=subject)


if __name__ == "__main__":
	load_dotenv()
	app.run(host="127.0.0.1", port=5000, debug=False)