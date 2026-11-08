import argparse
import csv
import getpass
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path


DEFAULT_SUBJECT = "A message from our team"
DEFAULT_BODY = "Hello {{name}},\n\nThis is a test message.\n"


def load_dotenv(dotenv_path: Path = Path(".env")) -> None:
	if not dotenv_path.exists():
		return

	for line in dotenv_path.read_text(encoding="utf-8").splitlines():
		line = line.strip()
		if not line or line.startswith("#") or "=" not in line:
			continue
		key, value = line.split("=", 1)
		os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_contacts(csv_path: Path) -> list[dict[str, str]]:
	with csv_path.open(newline="", encoding="utf-8-sig") as contacts_file:
		contacts = list(csv.DictReader(contacts_file))

	if not contacts or any(not contact.get("email", "").strip() for contact in contacts):
		raise ValueError("The CSV must contain at least one row with an email value.")

	return contacts


def collect_interactive_settings(recipient: str | None) -> list[dict[str, str]]:
	configured_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
	host = input(f"SMTP host [{configured_host}]: ").strip() or configured_host
	os.environ["SMTP_HOST"] = host or "smtp.gmail.com"

	configured_username = os.environ.get("SMTP_USER", "")
	username_prompt = f"Sender email [{configured_username}]: " if configured_username else "Sender email: "
	username = input(username_prompt).strip() or configured_username
	if not username:
		raise ValueError("A sender email is required.")
	os.environ["SMTP_USER"] = username
	os.environ.setdefault("FROM_EMAIL", username)

	password = getpass.getpass("SMTP App Password (hidden): ").strip()
	if password:
		os.environ["SMTP_PASSWORD"] = password.replace(" ", "")

	recipient = recipient or input("Recipient email: ").strip()
	if not recipient:
		raise ValueError("A recipient email is required.")
	name = input("Recipient name [there]: ").strip() or "there"
	return [{"name": name, "email": recipient}]


def build_message(contact: dict[str, str], subject: str, body_template: str) -> EmailMessage:
	name = contact.get("name", "there").strip() or "there"
	body = body_template.replace("{{name}}", name)

	message = EmailMessage()
	message["To"] = contact["email"].strip()
	message["Subject"] = subject
	message.set_content(body)
	return message


def send_messages(messages: list[EmailMessage]) -> None:
	host = os.environ.get("SMTP_HOST")
	port = int(os.environ.get("SMTP_PORT", "587"))
	username = os.environ.get("SMTP_USER")
	password = os.environ.get("SMTP_PASSWORD")
	sender = os.environ.get("FROM_EMAIL", username or "")

	if not all((host, username, password, sender)):
		raise ValueError(
			"Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD, and FROM_EMAIL before using --send."
		)

	with smtplib.SMTP(host, port) as smtp:
		smtp.starttls()
		smtp.login(username, password)
		for message in messages:
			message["From"] = sender
			smtp.send_message(message)


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(description="Preview or send personalized emails from a CSV file.")
	parser.add_argument("--csv", type=Path, default=Path("data/contacts.csv"))
	parser.add_argument("--to", help="Send to one recipient instead of loading the CSV.")
	parser.add_argument("--subject", default=DEFAULT_SUBJECT)
	parser.add_argument("--body", default=DEFAULT_BODY)
	parser.add_argument("--interactive", action="store_true", help="Prompt for recipient and SMTP settings.")
	parser.add_argument("--send", action="store_true", help="Send emails instead of previewing them.")
	return parser.parse_args()


def main() -> None:
	load_dotenv()
	args = parse_args()
	if args.interactive:
		contacts = collect_interactive_settings(args.to)
		args.subject = input(f"Subject [{args.subject}]: ").strip() or args.subject
		args.body = input("Message (use {{name}} for the recipient name): ").strip() or args.body
	else:
		contacts = load_contacts(args.csv)
		if args.to:
			contacts = [{"name": "there", "email": args.to}]
	messages = [build_message(contact, args.subject, args.body) for contact in contacts]

	if args.send:
		send_messages(messages)
		print(f"Sent {len(messages)} email(s).")
		return

	print(f"Preview for {len(messages)} email(s):")
	for message in messages:
		print("\n---")
		print(f"To: {message['To']}")
		print(f"Subject: {message['Subject']}")
		print(message.get_content())
	print("\nNothing was sent. Use --send only after reviewing the preview.")


if __name__ == "__main__":
	main()