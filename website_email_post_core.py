#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
website_email_post_core.py

Reads new emails from an IMAP mailbox and publishes them as Joomla articles.
Meant to run once per invocation (Windows Task Scheduler, or the central
dashboard's scheduler) - it processes whatever is currently unread and exits.

Email conventions (see README.md for full details):
- Subject line = article title, optionally followed by hashtags:
    "Γιορτή λήξης χρονιάς #featured #εκδηλώσεις #σχολείο"
  #featured / #notfeatured control the "featured" flag, everything else
  becomes a Joomla tag.
- Body (HTML if the client sent rich text, otherwise plain text) becomes
  the article body. YouTube links become embedded players.
- Image attachments are resized/compressed and embedded in the article.
- Non-image attachments (pdf/docx/xlsx/...) are uploaded and linked at the
  bottom of the article under "Συνημμένα αρχεία".
- Only senders in WEBSITE_POST_WHITELIST_EMAIL_ADDRESSES are processed.
"""

from __future__ import annotations

import base64
import csv
import email
import imaplib
import io
import os
import re
import uuid
from datetime import datetime, timezone
from email.header import decode_header
from email.utils import parseaddr
from pathlib import Path

import requests
from PIL import Image, ImageOps

from dashboard_core_common import RunLogger, SafeDict, log_final_status  # noqa: F401

APP_NAME = 'website-email-post'
APP_DIR = Path(__file__).resolve().parent
PREFIX = 'WEBSITE_POST_'
EXTRA_KEYS = ('WEBSITE_URL', 'WEBSITE_PLATFORM')

PROCESSED_FOLDER = 'Processed'
FAILED_FOLDER = 'Failed'

LOG_COLUMNS = [
    'timestamp', 'email_from', 'email_subject', 'status',
    'joomla_article_id', 'attachments_count', 'error_message',
]


def load_config(overrides: dict | None = None) -> dict:
    config = {k: v for k, v in os.environ.items() if k.startswith(PREFIX) or k in EXTRA_KEYS}
    if overrides:
        for k, v in overrides.items():
            if v is not None and str(v).strip() != '':
                config[k] = v
    return config


def load_dotenv_files() -> None:
    from dotenv import load_dotenv
    for candidate in [APP_DIR / '.env', Path.cwd() / '.env', (APP_DIR / '..' / '..' / '.env').resolve()]:
        if candidate.exists():
            load_dotenv(candidate, encoding='utf-8', override=True)
            return


def cfg(config: dict, key: str, default=None):
    val = config.get(key)
    if val is None or str(val).strip() == '':
        return default
    return val


def cfg_bool(config: dict, key: str, default: bool = False) -> bool:
    val = cfg(config, key)
    if val is None:
        return default
    return str(val).strip().upper() == 'YES'


# ---------------------------------------------------------------------------
# CSV log (per-message detail, distinct from the RunLogger tile-status log)
# ---------------------------------------------------------------------------

def log_row(config: dict, email_from, email_subject, status, article_id='', attachments_count=0, error_message=''):
    log_path = Path(cfg(config, PREFIX + 'LOG_FILE_PATH', 'logs/post_log.csv'))
    if not log_path.is_absolute():
        log_path = APP_DIR / log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not log_path.exists()
    with open(log_path, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=LOG_COLUMNS)
        if is_new:
            writer.writeheader()
        writer.writerow({
            'timestamp': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'email_from': email_from,
            'email_subject': email_subject,
            'status': status,
            'joomla_article_id': article_id,
            'attachments_count': attachments_count,
            'error_message': error_message,
        })


def read_recent_log_rows(config: dict, limit: int = 50) -> list[dict]:
    log_path = Path(cfg(config, PREFIX + 'LOG_FILE_PATH', 'logs/post_log.csv'))
    if not log_path.is_absolute():
        log_path = APP_DIR / log_path
    if not log_path.exists():
        return []
    with open(log_path, 'r', newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    return rows[-limit:][::-1]


# ---------------------------------------------------------------------------
# Email parsing
# ---------------------------------------------------------------------------

def decode_mime_words(s):
    if not s:
        return ''
    parts = decode_header(s)
    decoded = ''
    for text, enc in parts:
        if isinstance(text, bytes):
            decoded += text.decode(enc or 'utf-8', errors='replace')
        else:
            decoded += text
    return decoded


HASHTAG_RE = re.compile(r'#(\S+)')


def parse_subject(raw_subject):
    """Split subject into (title, tags, featured_override)."""
    tags = []
    featured_override = None
    for tag in HASHTAG_RE.findall(raw_subject):
        low = tag.lower()
        if low == 'featured':
            featured_override = True
        elif low == 'notfeatured':
            featured_override = False
        else:
            tags.append(tag)
    title = HASHTAG_RE.sub('', raw_subject).strip()
    return title, tags, featured_override


def get_body_and_attachments(msg):
    """Return (body_html, images[], other_files[]) from an email.message.Message.

    images / other_files are lists of (filename, bytes, content_type).

    Gmail marks image attachments as Content-Disposition: inline (with a
    Content-ID), same as it would a genuinely embedded signature/quote
    image - the two are told apart by whether the body HTML actually
    references that Content-ID via "cid:...".
    """
    html_body = None
    text_body = None
    images = []
    other_files = []
    parts = []

    for part in msg.walk():
        if part.is_multipart():
            continue
        parts.append(part)

    referenced_cids = set()
    for part in parts:
        if part.get_content_type() == 'text/html':
            payload = part.get_payload(decode=True)
            if payload:
                charset = part.get_content_charset() or 'utf-8'
                referenced_cids.update(re.findall(r'cid:([^"\'>\s]+)', payload.decode(charset, errors='replace')))

    for part in parts:
        content_type = part.get_content_type()
        disposition = str(part.get('Content-Disposition') or '')

        filename = part.get_filename()
        if filename:
            filename = decode_mime_words(filename)

        content_id = (part.get('Content-ID') or '').strip('<>')
        is_referenced_inline_image = content_id and content_id in referenced_cids

        if not is_referenced_inline_image and (
            'attachment' in disposition or (filename and content_type not in ('text/plain', 'text/html'))
        ):
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            if content_type.startswith('image/'):
                images.append((filename or 'image', payload, content_type))
            else:
                other_files.append((filename or 'attachment', payload, content_type))
            continue

        if content_type == 'text/html' and html_body is None:
            payload = part.get_payload(decode=True)
            charset = part.get_content_charset() or 'utf-8'
            html_body = payload.decode(charset, errors='replace')
        elif content_type == 'text/plain' and text_body is None:
            payload = part.get_payload(decode=True)
            charset = part.get_content_charset() or 'utf-8'
            text_body = payload.decode(charset, errors='replace')

    if html_body:
        return html_body, images, other_files

    if text_body:
        paragraphs = [f'<p>{p.strip()}</p>' for p in text_body.split('\n\n') if p.strip()]
        return '\n'.join(paragraphs), images, other_files

    return '', images, other_files


def resize_image(config: dict, raw_bytes: bytes) -> bytes:
    max_width = int(cfg(config, PREFIX + 'IMAGE_MAX_WIDTH', '1600'))
    quality = int(cfg(config, PREFIX + 'IMAGE_JPEG_QUALITY', '75'))
    img = Image.open(io.BytesIO(raw_bytes))
    img = ImageOps.exif_transpose(img)
    if img.mode != 'RGB':
        img = img.convert('RGB')
    if img.width > max_width:
        ratio = max_width / img.width
        new_size = (max_width, int(img.height * ratio))
        img = img.resize(new_size, Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, format='JPEG', quality=quality, optimize=True)
    return out.getvalue()


def sanitize_filename(name):
    name = re.sub(r'[^\w.\-]+', '_', name, flags=re.UNICODE)
    return name.strip('_') or 'file'


YOUTUBE_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?(?:youtube\.com/(?:watch\?v=|embed/|shorts/)|youtu\.be/)([\w-]{11})[^\s\"'<>]*",
    re.IGNORECASE,
)
ANCHOR_TAG_RE = re.compile(r'<a\b[^>]*href="([^"]*)"[^>]*>.*?</a>', re.IGNORECASE | re.DOTALL)


def youtube_embed_html(video_id):
    return (
        '<div style="position:relative;padding-bottom:56.25%;height:0;overflow:hidden;max-width:100%;margin:1em 0;">'
        f'<iframe src="https://www.youtube.com/embed/{video_id}" '
        'style="position:absolute;top:0;left:0;width:100%;height:100%;" frameborder="0" '
        'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" '
        'allowfullscreen></iframe></div>'
    )


def embed_youtube_links(html):
    """Replace YouTube links/anchors with embedded players.

    Uses placeholder tokens so the embed HTML (which itself contains a
    youtube.com URL) never gets re-matched by the second substitution pass.
    """
    embeds = []

    def store(video_id):
        embeds.append(youtube_embed_html(video_id))
        return f'@@YT_EMBED_{len(embeds) - 1}@@'

    def replace_anchor(match):
        video = YOUTUBE_URL_RE.search(match.group(1))
        return store(video.group(1)) if video else match.group(0)

    html = ANCHOR_TAG_RE.sub(replace_anchor, html)
    html = YOUTUBE_URL_RE.sub(lambda m: store(m.group(1)), html)

    for index, embed_html in enumerate(embeds):
        html = html.replace(f'@@YT_EMBED_{index}@@', embed_html)
    return html


def build_attachments_html(uploaded_files):
    if not uploaded_files:
        return ''
    items = '\n'.join(f'<li><a href="{url}">{name}</a></li>' for name, url in uploaded_files)
    return f'<h4>Συνημμένα αρχεία</h4>\n<ul>\n{items}\n</ul>'


# ---------------------------------------------------------------------------
# Joomla API
# ---------------------------------------------------------------------------

def joomla_headers(config: dict, extra: dict | None = None) -> dict:
    token = cfg(config, PREFIX + 'API_TOKEN', '')
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.api+json',
    }
    if extra:
        headers.update(extra)
    return headers


def joomla_base_url(config: dict) -> str:
    website_url = cfg(config, 'WEBSITE_URL', '').rstrip('/')
    https_port = cfg(config, PREFIX + 'HTTPS_PORT', '443')
    if https_port and https_port != '443':
        return f'{website_url}:{https_port}/api/index.php/v1'
    return f'{website_url}/api/index.php/v1'


def joomla_upload_media(config: dict, filename: str, file_bytes: bytes, adapter: str):
    website_url = cfg(config, 'WEBSITE_URL', '').rstrip('/')
    subpath = cfg(config, PREFIX + 'MEDIA_SUBPATH', 'mail-posts')
    url = f'{joomla_base_url(config)}/media/files'
    payload = {
        'path': f'{adapter}:/{subpath}/{filename}',
        'content': base64.b64encode(file_bytes).decode('ascii'),
    }
    resp = requests.post(
        url,
        headers=joomla_headers(config, {'Content-Type': 'application/json'}),
        params={'mediatypes': '0,1,2,3'},
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    attrs = resp.json()['data']['attributes']

    public_url = attrs.get('thumb_path')
    if not public_url:
        # Non-image uploads don't get a thumb_path back - build the public
        # URL ourselves. Assumes the Joomla convention of adapter id
        # "local-<foldername>" mapping to the "<foldername>/" public path
        # (e.g. "local-files" -> /files/, "local-images" -> /images/).
        public_folder = adapter.removeprefix('local-')
        public_url = f'{website_url}/{public_folder}/{subpath}/{filename}'

    return attrs.get('path'), public_url


def joomla_get_or_create_tag_id(config: dict, tag_name: str):
    search_url = f'{joomla_base_url(config)}/tags'
    # filter[title] is accepted by the API but doesn't actually filter
    # anything server-side - fetch a large page and match client-side.
    resp = requests.get(search_url, headers=joomla_headers(config), params={'page[limit]': 100}, timeout=30)
    resp.raise_for_status()
    results = resp.json().get('data', [])
    for item in results:
        if item['attributes']['title'].strip().lower() == tag_name.strip().lower():
            return item['id']

    create_resp = requests.post(
        search_url,
        headers=joomla_headers(config, {'Content-Type': 'application/json'}),
        json={'title': tag_name, 'published': 1, 'parent_id': 1, 'language': '*', 'description': ''},
        timeout=30,
    )
    create_resp.raise_for_status()
    return create_resp.json()['data']['id']


def joomla_create_article(config: dict, title, body_html, tag_ids, featured, dry_run: bool):
    category_id = int(cfg(config, PREFIX + 'CATEGORY_ID', '0'))
    default_status = cfg(config, PREFIX + 'DEFAULT_STATUS', 'DRAFT').strip().upper()
    url = f'{joomla_base_url(config)}/content/articles'
    payload = {
        'title': title,
        'catid': category_id,
        'articletext': body_html,
        'state': 1 if default_status == 'PUBLISHED' else 0,
        'featured': 1 if featured else 0,
        'language': '*',
    }
    if tag_ids:
        payload['tags'] = tag_ids

    if dry_run:
        return 'DRY_RUN'

    resp = requests.post(url, headers=joomla_headers(config, {'Content-Type': 'application/json'}), json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()['data']['id']


# ---------------------------------------------------------------------------
# IMAP
# ---------------------------------------------------------------------------

def ensure_folder(imap_conn, folder_name):
    status, _ = imap_conn.select(folder_name)
    if status != 'OK':
        imap_conn.create(folder_name)


def move_message(imap_conn, msg_id, destination_folder):
    imap_conn.select('INBOX')
    ensure_folder(imap_conn, destination_folder)
    imap_conn.select('INBOX')

    status, response = imap_conn.copy(msg_id, destination_folder)
    if status != 'OK':
        raise RuntimeError(f'IMAP COPY to {destination_folder} failed: {response}')

    status, response = imap_conn.store(msg_id, '+FLAGS', '\\Deleted')
    if status != 'OK':
        raise RuntimeError(f'IMAP STORE (\\Deleted) failed: {response}')


def process_message(config: dict, raw_email: bytes, logger: RunLogger, dry_run: bool):
    msg = email.message_from_bytes(raw_email)
    sender_name, sender_email = parseaddr(msg.get('From', ''))
    sender_email = sender_email.lower()
    raw_subject = decode_mime_words(msg.get('Subject', '(χωρίς θέμα)'))

    whitelist = {
        a.strip().lower()
        for a in cfg(config, PREFIX + 'WHITELIST_EMAIL_ADDRESSES', '').split(',')
        if a.strip()
    }
    if sender_email not in whitelist:
        logger.log(f'Παράλειψη (μη εγκεκριμένος αποστολέας): {sender_email} - {raw_subject}', 'WARN')
        log_row(config, sender_email, raw_subject, 'SKIPPED_NOT_WHITELISTED')
        return 'skipped'

    default_featured = cfg_bool(config, PREFIX + 'DEFAULT_FEATURED', False)
    media_adapter_images = cfg(config, PREFIX + 'MEDIA_ADAPTER_IMAGES', 'local-images')
    media_adapter_docs = cfg(config, PREFIX + 'MEDIA_ADAPTER_DOCS', 'local-files')

    title, tag_names, featured_override = parse_subject(raw_subject)
    featured = default_featured if featured_override is None else featured_override

    body_html, images, other_files = get_body_and_attachments(msg)
    body_html = embed_youtube_links(body_html)

    # Unique per-message prefix so attachments with common names (e.g. two
    # different "Πρόσκληση.pdf") never collide in the shared media folder.
    unique_prefix = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S') + '-' + uuid.uuid4().hex[:6]

    uploaded_doc_links = []
    for filename, raw_bytes, _content_type in other_files:
        safe_name = f'{unique_prefix}-{sanitize_filename(filename)}'
        _, doc_url = joomla_upload_media(config, safe_name, raw_bytes, media_adapter_docs)
        uploaded_doc_links.append((filename, doc_url))

    image_tags_html = []
    for filename, raw_bytes, _content_type in images:
        jpeg_bytes = resize_image(config, raw_bytes)
        base_name = f'{unique_prefix}-{sanitize_filename(Path(filename).stem)}.jpg'
        _, img_url = joomla_upload_media(config, base_name, jpeg_bytes, media_adapter_images)
        image_tags_html.append(f'<p><img src="{img_url}" alt="{title}"></p>')

    full_body = '\n'.join(image_tags_html) + '\n' + body_html + '\n' + build_attachments_html(uploaded_doc_links)

    tag_ids = [joomla_get_or_create_tag_id(config, t) for t in tag_names] if tag_names else []

    article_id = joomla_create_article(config, title, full_body, tag_ids, featured, dry_run)
    logger.log(f'Αναρτήθηκε άρθρο (id={article_id}): "{title}" από {sender_email}')
    log_row(config, sender_email, raw_subject, 'POSTED', article_id, len(images) + len(other_files))
    return 'posted'


def run_check_mail(config: dict, logger: RunLogger, control=None, progress_cb=None,
                    dry_run_override: bool | None = None) -> dict:
    platform = cfg(config, 'WEBSITE_PLATFORM', 'joomla').strip().lower()
    if platform != 'joomla':
        logger.log(f'WEBSITE_PLATFORM={platform!r} δεν υποστηρίζεται ακόμα (μόνο "joomla")', 'ERROR')
        return {'ok': False, 'exit_code': 1, 'posted': 0, 'skipped': 0, 'failed': 0}

    dry_run = cfg_bool(config, PREFIX + 'DRY_RUN', False) if dry_run_override is None else dry_run_override

    imap_server = cfg(config, PREFIX + 'EMAIL_IMAP_SERVER')
    imap_port = int(cfg(config, PREFIX + 'EMAIL_IMAP_PORT', '993'))
    email_username = cfg(config, PREFIX + 'EMAIL_USERNAME')
    email_password = cfg(config, PREFIX + 'EMAIL_PASSWORD')

    missing = [k for k, v in {
        'IMAP server': imap_server, 'Email username': email_username, 'Email password': email_password,
        'Joomla API token': cfg(config, PREFIX + 'API_TOKEN'),
        'Joomla category ID': cfg(config, PREFIX + 'CATEGORY_ID'),
        'Website URL': cfg(config, 'WEBSITE_URL'),
    }.items() if not v]
    if missing:
        logger.log('Λείπουν ρυθμίσεις: ' + ', '.join(missing), 'ERROR')
        return {'ok': False, 'exit_code': 1, 'posted': 0, 'skipped': 0, 'failed': 0}

    if dry_run:
        logger.log('DRY RUN ενεργό — δεν θα δημιουργηθούν πραγματικά άρθρα ούτε θα μετακινηθούν emails', 'WARN')

    imap_conn = imaplib.IMAP4_SSL(imap_server, imap_port)
    imap_conn.login(email_username, email_password)
    imap_conn.select('INBOX')

    status, data = imap_conn.search(None, 'UNSEEN')
    if status != 'OK':
        logger.log('Αποτυχία αναζήτησης IMAP', 'ERROR')
        imap_conn.logout()
        return {'ok': False, 'exit_code': 1, 'posted': 0, 'skipped': 0, 'failed': 0}

    msg_ids = data[0].split()
    logger.log(f'Βρέθηκαν {len(msg_ids)} μη αναγνωσμένο(α) μήνυμα(τα).')

    posted = skipped = failed = 0

    for i, msg_id in enumerate(msg_ids, start=1):
        if control:
            control.wait_if_paused()
            if control.stop_event.is_set():
                logger.log('Διακόπηκε από τον χρήστη', 'WARN')
                break

        fetch_item = '(BODY.PEEK[])' if dry_run else '(RFC822)'
        status, msg_data = imap_conn.fetch(msg_id, fetch_item)
        if status != 'OK':
            if progress_cb:
                progress_cb(i, len(msg_ids))
            continue
        raw_email = msg_data[0][1]

        try:
            result = process_message(config, raw_email, logger, dry_run)
            if result == 'skipped':
                skipped += 1
            else:
                posted += 1
        except Exception as exc:
            msg = email.message_from_bytes(raw_email)
            sender_email = parseaddr(msg.get('From', ''))[1].lower()
            subject = decode_mime_words(msg.get('Subject', ''))
            log_row(config, sender_email, subject, 'ERROR', error_message=str(exc))
            logger.log(f'ΣΦΑΛΜΑ επεξεργασίας μηνύματος {msg_id}: {exc}', 'ERROR')
            failed += 1
            if not dry_run:
                try:
                    move_message(imap_conn, msg_id, FAILED_FOLDER)
                except Exception as move_exc:
                    logger.log(f'Απέτυχε και η μετακίνηση στο {FAILED_FOLDER}: {move_exc}', 'WARN')
            if progress_cb:
                progress_cb(i, len(msg_ids))
            continue

        if not dry_run:
            try:
                move_message(imap_conn, msg_id, PROCESSED_FOLDER)
            except Exception as move_exc:
                # The article was already posted successfully - only the
                # mailbox tidy-up failed. Not a processing error.
                logger.log(f'Το άρθρο αναρτήθηκε αλλά απέτυχε η μετακίνηση στο {PROCESSED_FOLDER}: {move_exc}', 'WARN')

        if progress_cb:
            progress_cb(i, len(msg_ids))

    imap_conn.expunge()
    imap_conn.close()
    imap_conn.logout()

    logger.log(f'Ολοκληρώθηκε — αναρτήθηκαν: {posted}, παραλείφθηκαν: {skipped}, απέτυχαν: {failed}')
    exit_code = 0 if failed == 0 else (2 if posted > 0 else 1)
    return {'ok': failed == 0, 'exit_code': exit_code, 'posted': posted, 'skipped': skipped, 'failed': failed}
