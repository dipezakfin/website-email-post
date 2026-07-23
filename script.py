"""
website-email-post

Reads new emails from an IMAP mailbox and publishes them as Joomla articles.
Meant to run once per invocation (e.g. every few minutes via Windows Task
Scheduler) - it processes whatever is currently unread and exits.

Email conventions (see README.md for full details):
- Subject line = article title, optionally followed by hashtags:
    "Γιορτή λήξης χρονιάς #featured #εκδηλώσεις #σχολείο"
  #featured / #notfeatured control the "featured" flag, everything else
  becomes a Joomla tag.
- Body (HTML if the client sent rich text, otherwise plain text) becomes
  the article body.
- Image attachments are resized/compressed and embedded in the article.
- Non-image attachments (pdf/docx/xlsx/...) are uploaded and linked at the
  bottom of the article under "Συνημμένα αρχεία".
- Only senders in WEBSITE_POST_WHITELIST_EMAIL_ADDRESSES are processed.
"""

import csv
import email
import imaplib
import io
import os
import re
import sys
from datetime import datetime, timezone
from email.header import decode_header
from email.utils import parseaddr
from pathlib import Path

import requests
from dotenv import load_dotenv
from PIL import Image, ImageOps

load_dotenv()

IMAP_SERVER = os.environ["WEBSITE_POST_EMAIL_IMAP_SERVER"]
IMAP_PORT = int(os.environ.get("WEBSITE_POST_EMAIL_IMAP_PORT", "993"))
EMAIL_USERNAME = os.environ["WEBSITE_POST_EMAIL_USERNAME"]
EMAIL_PASSWORD = os.environ["WEBSITE_POST_EMAIL_PASSWORD"]

WEBSITE_URL = os.environ["WEBSITE_URL"].rstrip("/")
WEBSITE_HTTPS_PORT = os.environ.get("WEBSITE_POST_HTTPS_PORT", "443")
API_TOKEN = os.environ["WEBSITE_POST_API_TOKEN"]
CATEGORY_ID = int(os.environ["WEBSITE_POST_CATEGORY_ID"])

WHITELIST = {
    a.strip().lower()
    for a in os.environ.get("WEBSITE_POST_WHITELIST_EMAIL_ADDRESSES", "").split(",")
    if a.strip()
}

DEFAULT_STATUS = os.environ.get("WEBSITE_POST_DEFAULT_STATUS", "DRAFT").strip().upper()
DEFAULT_FEATURED = os.environ.get("WEBSITE_POST_DEFAULT_FEATURED", "NO").strip().upper() == "YES"

IMAGE_MAX_WIDTH = int(os.environ.get("WEBSITE_POST_IMAGE_MAX_WIDTH", "1600"))
IMAGE_JPEG_QUALITY = int(os.environ.get("WEBSITE_POST_IMAGE_JPEG_QUALITY", "75"))

MEDIA_ADAPTER_IMAGES = os.environ.get("WEBSITE_POST_MEDIA_ADAPTER_IMAGES", "local-images")
MEDIA_ADAPTER_DOCS = os.environ.get("WEBSITE_POST_MEDIA_ADAPTER_DOCS", "local-documents")
MEDIA_SUBPATH = os.environ.get("WEBSITE_POST_MEDIA_SUBPATH", "mail-posts")

LOG_FILE_PATH = Path(os.environ.get("WEBSITE_POST_LOG_FILE_PATH", "logs/post_log.csv"))

DRY_RUN = os.environ.get("WEBSITE_POST_DRY_RUN", "NO").strip().upper() == "YES"

PROCESSED_FOLDER = "Processed"
FAILED_FOLDER = "Failed"

LOG_COLUMNS = [
    "timestamp",
    "email_from",
    "email_subject",
    "status",
    "joomla_article_id",
    "attachments_count",
    "error_message",
]


def log_row(email_from, email_subject, status, article_id="", attachments_count=0, error_message=""):
    LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    is_new = not LOG_FILE_PATH.exists()
    with open(LOG_FILE_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_COLUMNS)
        if is_new:
            writer.writeheader()
        writer.writerow({
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "email_from": email_from,
            "email_subject": email_subject,
            "status": status,
            "joomla_article_id": article_id,
            "attachments_count": attachments_count,
            "error_message": error_message,
        })


def decode_mime_words(s):
    if not s:
        return ""
    parts = decode_header(s)
    decoded = ""
    for text, enc in parts:
        if isinstance(text, bytes):
            decoded += text.decode(enc or "utf-8", errors="replace")
        else:
            decoded += text
    return decoded


HASHTAG_RE = re.compile(r"#(\S+)")


def parse_subject(raw_subject):
    """Split subject into (title, tags, featured_override)."""
    tags = []
    featured_override = None
    for tag in HASHTAG_RE.findall(raw_subject):
        low = tag.lower()
        if low == "featured":
            featured_override = True
        elif low == "notfeatured":
            featured_override = False
        else:
            tags.append(tag)
    title = HASHTAG_RE.sub("", raw_subject).strip()
    return title, tags, featured_override


def get_body_and_attachments(msg):
    """Return (body_html, images[], other_files[]) from an email.message.Message.

    images / other_files are lists of (filename, bytes, content_type).
    """
    html_body = None
    text_body = None
    images = []
    other_files = []

    for part in msg.walk():
        content_type = part.get_content_type()
        disposition = str(part.get("Content-Disposition") or "")

        if part.is_multipart():
            continue

        filename = part.get_filename()
        if filename:
            filename = decode_mime_words(filename)

        if "attachment" in disposition or (filename and "inline" not in disposition and content_type not in ("text/plain", "text/html")):
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            if content_type.startswith("image/"):
                images.append((filename or "image", payload, content_type))
            else:
                other_files.append((filename or "attachment", payload, content_type))
            continue

        if content_type == "text/html" and html_body is None:
            payload = part.get_payload(decode=True)
            charset = part.get_content_charset() or "utf-8"
            html_body = payload.decode(charset, errors="replace")
        elif content_type == "text/plain" and text_body is None:
            payload = part.get_payload(decode=True)
            charset = part.get_content_charset() or "utf-8"
            text_body = payload.decode(charset, errors="replace")

    if html_body:
        return html_body, images, other_files

    if text_body:
        paragraphs = [f"<p>{p.strip()}</p>" for p in text_body.split("\n\n") if p.strip()]
        return "\n".join(paragraphs), images, other_files

    return "", images, other_files


def resize_image(raw_bytes):
    """Return (jpeg_bytes, filename_ext) resized/compressed per config."""
    img = Image.open(io.BytesIO(raw_bytes))
    img = ImageOps.exif_transpose(img)
    if img.mode != "RGB":
        img = img.convert("RGB")
    if img.width > IMAGE_MAX_WIDTH:
        ratio = IMAGE_MAX_WIDTH / img.width
        new_size = (IMAGE_MAX_WIDTH, int(img.height * ratio))
        img = img.resize(new_size, Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=IMAGE_JPEG_QUALITY, optimize=True)
    return out.getvalue()


def joomla_headers(extra=None):
    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "X-Joomla-Token": API_TOKEN,
    }
    if extra:
        headers.update(extra)
    return headers


def joomla_base_url():
    if WEBSITE_HTTPS_PORT and WEBSITE_HTTPS_PORT != "443":
        return f"{WEBSITE_URL}:{WEBSITE_HTTPS_PORT}/api/index.php/v1"
    return f"{WEBSITE_URL}/api/index.php/v1"


def sanitize_filename(name):
    name = re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE)
    return name.strip("_") or "file"


def upload_media(filename, file_bytes, adapter):
    url = f"{joomla_base_url()}/media/{adapter}"
    files = {"file": (filename, file_bytes)}
    data = {"path": MEDIA_SUBPATH}
    resp = requests.post(url, headers=joomla_headers(), files=files, data=data, timeout=60)
    resp.raise_for_status()
    attrs = resp.json()["data"]["attributes"]
    return attrs.get("path"), attrs.get("url") or f"/{attrs.get('path')}"


def get_or_create_tag_id(tag_name):
    search_url = f"{joomla_base_url()}/tags"
    resp = requests.get(search_url, headers=joomla_headers(), params={"filter[title]": tag_name}, timeout=30)
    resp.raise_for_status()
    results = resp.json().get("data", [])
    for item in results:
        if item["attributes"]["title"].strip().lower() == tag_name.strip().lower():
            return item["id"]

    create_resp = requests.post(
        search_url,
        headers=joomla_headers({"Content-Type": "application/json"}),
        json={"title": tag_name, "published": 1},
        timeout=30,
    )
    create_resp.raise_for_status()
    return create_resp.json()["data"]["id"]


def build_attachments_html(uploaded_files):
    if not uploaded_files:
        return ""
    items = "\n".join(f'<li><a href="{url}">{name}</a></li>' for name, url in uploaded_files)
    return f"<h4>Συνημμένα αρχεία</h4>\n<ul>\n{items}\n</ul>"


def create_article(title, body_html, tag_ids, featured):
    url = f"{joomla_base_url()}/content/articles"
    payload = {
        "title": title,
        "catid": CATEGORY_ID,
        "articletext": body_html,
        "state": 1 if DEFAULT_STATUS == "PUBLISHED" else 0,
        "featured": 1 if featured else 0,
    }
    if tag_ids:
        payload["tags"] = tag_ids

    if DRY_RUN:
        print(f"[DRY RUN] Would create article: {payload}")
        return "DRY_RUN"

    resp = requests.post(url, headers=joomla_headers({"Content-Type": "application/json"}), json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()["data"]["id"]


def ensure_folder(imap_conn, folder_name):
    status, _ = imap_conn.select(folder_name)
    if status != "OK":
        imap_conn.create(folder_name)


def move_message(imap_conn, msg_id, destination_folder):
    imap_conn.select("INBOX")
    ensure_folder(imap_conn, destination_folder)
    imap_conn.select("INBOX")
    imap_conn.copy(msg_id, destination_folder)
    imap_conn.store(msg_id, "+FLAGS", "\\Deleted")


def process_message(raw_email):
    msg = email.message_from_bytes(raw_email)
    sender_name, sender_email = parseaddr(msg.get("From", ""))
    sender_email = sender_email.lower()
    raw_subject = decode_mime_words(msg.get("Subject", "(χωρίς θέμα)"))

    if sender_email not in WHITELIST:
        log_row(sender_email, raw_subject, "SKIPPED_NOT_WHITELISTED")
        return "skipped"

    title, tag_names, featured_override = parse_subject(raw_subject)
    featured = DEFAULT_FEATURED if featured_override is None else featured_override

    body_html, images, other_files = get_body_and_attachments(msg)

    uploaded_doc_links = []
    for filename, raw_bytes, _content_type in other_files:
        safe_name = sanitize_filename(filename)
        _, doc_url = upload_media(safe_name, raw_bytes, MEDIA_ADAPTER_DOCS)
        uploaded_doc_links.append((filename, doc_url))

    image_tags_html = []
    for filename, raw_bytes, _content_type in images:
        jpeg_bytes = resize_image(raw_bytes)
        base_name = sanitize_filename(Path(filename).stem) + ".jpg"
        _, img_url = upload_media(base_name, jpeg_bytes, MEDIA_ADAPTER_IMAGES)
        image_tags_html.append(f'<p><img src="{img_url}" alt="{title}"></p>')

    full_body = "\n".join(image_tags_html) + "\n" + body_html + "\n" + build_attachments_html(uploaded_doc_links)

    tag_ids = [get_or_create_tag_id(t) for t in tag_names] if tag_names else []

    article_id = create_article(title, full_body, tag_ids, featured)
    log_row(sender_email, raw_subject, "POSTED", article_id, len(images) + len(other_files))
    return "posted"


def run():
    imap_conn = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    imap_conn.login(EMAIL_USERNAME, EMAIL_PASSWORD)
    imap_conn.select("INBOX")

    status, data = imap_conn.search(None, "UNSEEN")
    if status != "OK":
        print("IMAP search failed", file=sys.stderr)
        return

    msg_ids = data[0].split()
    print(f"Found {len(msg_ids)} unread message(s).")

    for msg_id in msg_ids:
        status, msg_data = imap_conn.fetch(msg_id, "(RFC822)")
        if status != "OK":
            continue
        raw_email = msg_data[0][1]

        try:
            process_message(raw_email)
            if not DRY_RUN:
                move_message(imap_conn, msg_id, PROCESSED_FOLDER)
        except Exception as exc:
            msg = email.message_from_bytes(raw_email)
            sender_email = parseaddr(msg.get("From", ""))[1].lower()
            subject = decode_mime_words(msg.get("Subject", ""))
            log_row(sender_email, subject, "ERROR", error_message=str(exc))
            print(f"ERROR processing message {msg_id}: {exc}", file=sys.stderr)
            if not DRY_RUN:
                move_message(imap_conn, msg_id, FAILED_FOLDER)

    imap_conn.expunge()
    imap_conn.close()
    imap_conn.logout()


if __name__ == "__main__":
    run()
