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
import time
import uuid
import zipfile
from datetime import datetime, timezone
from email.header import decode_header
from email.utils import parseaddr
from pathlib import Path
from urllib.parse import quote

import requests
from PIL import Image, ImageOps

from dashboard_core_common import RunLogger, SafeDict, log_final_status  # noqa: F401

APP_NAME = 'website-email-post'
APP_DIR = Path(__file__).resolve().parent
PREFIX = 'WEBSITE_POST_'
EXTRA_KEYS = ('WEBSITE_URL', 'WEBSITE_PLATFORM')

PROCESSED_FOLDER = 'Processed'
FAILED_FOLDER = 'Failed'
SKIPPED_FOLDER = 'Skipped'

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

    # Το πεδίο τίτλου άρθρου στο Joomla (#__content.title) είναι VARCHAR(255)
    # - ένα πολύ μακρύ θέμα email (έχουν εμφανιστεί θέματα 500+ χαρακτήρων)
    # κάνει το POST /content/articles να αποτυγχάνει με 400 Bad Request.
    max_title_len = 250
    if len(title) > max_title_len:
        truncated = title[:max_title_len].rsplit(' ', 1)[0]
        title = (truncated or title[:max_title_len]).rstrip('.,·-') + '…'

    return title, tags, featured_override


def get_body_and_attachments(msg):
    """Return (body_html, images[], other_files[]) from an email.message.Message.

    other_files: list of (filename, bytes, content_type).
    images: list of (filename, bytes, content_type, content_id_or_None).

    Every image part is captured, whether Gmail tagged it
    Content-Disposition: attachment (a "normal" attached photo) or inline
    with a Content-ID (a photo pasted directly into the body, or a
    signature logo) - process_message() decides what to do with the
    content_id afterwards (rewrite the "cid:..." reference in body_html to
    the uploaded URL instead of leaving a broken image).
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

    for part in parts:
        content_type = part.get_content_type()
        disposition = str(part.get('Content-Disposition') or '')

        filename = part.get_filename()
        if filename:
            filename = decode_mime_words(filename)

        content_id = (part.get('Content-ID') or '').strip('<>')
        is_image = content_type.startswith('image/')

        if is_image and (filename or content_id):
            payload = part.get_payload(decode=True)
            if payload is not None:
                images.append((filename or 'image', payload, content_type, content_id or None))
            continue

        if not is_image and ('attachment' in disposition or (filename and content_type not in ('text/plain', 'text/html'))):
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
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
    result = out.getvalue()

    # Ο server (ModSecurity SecRequestBodyNoFilesLimit) απορρίπτει request
    # bodies πάνω από ένα όριο - αν η εικόνα είναι ακόμα πάνω από το
    # ρυθμισμένο όριο μετά το κανονικό resize, τη σμικρύνουμε παραπάνω
    # (πρώτα ποιότητα, μετά πλάτος) μέχρι να χωρέσει ή να φτάσουμε σε
    # κατώτατο αποδεκτό όριο.
    if cfg_bool(config, PREFIX + 'SHRINK_LARGE_IMAGES', True):
        max_bytes = int(cfg(config, PREFIX + 'MAX_ATTACHMENT_KB', '700')) * 1024
        attempt_quality = quality
        attempt_img = img
        while len(result) > max_bytes and (attempt_quality > 20 or attempt_img.width > 400):
            if attempt_quality > 20:
                attempt_quality -= 10
            else:
                new_width = max(400, int(attempt_img.width * 0.8))
                ratio = new_width / attempt_img.width
                attempt_img = attempt_img.resize((new_width, int(attempt_img.height * ratio)), Image.LANCZOS)
            out = io.BytesIO()
            attempt_img.save(out, format='JPEG', quality=attempt_quality, optimize=True)
            result = out.getvalue()

    return result


def sanitize_filename(name, max_bytes=100):
    name = re.sub(r'[^\w.\-]+', '_', name, flags=re.UNICODE)
    # Joomla's media filter rejects filenames with consecutive dots (e.g.
    # "Υ.Α..pdf" from an abbreviation right before the extension) as a
    # possible double-extension attack ("Invalid path or file type not
    # allowed", regardless of the actual extension being fine) - collapse
    # them to one dot so a legitimate name never trips that check.
    name = re.sub(r'\.{2,}', '.', name)
    name = name.strip('_.') or 'file'

    # Ελληνικοί (και άλλοι μη-ASCII) χαρακτήρες παίρνουν 2+ bytes σε UTF-8 -
    # ένα ονοματάκι που φαίνεται λογικό σε χαρακτήρες μπορεί να ξεπεράσει το
    # όριο μήκους filename του server (συνήθως 255 bytes, λιγότερο αν
    # προστεθεί και το unique_prefix). Κόβουμε το stem κρατώντας την
    # επέκταση, με byte-aware περικοπή ώστε να μη σπάσει multi-byte char.
    if len(name.encode('utf-8')) > max_bytes:
        stem, dot, ext = name.rpartition('.')
        if not dot:
            stem, ext = name, ''
        ext_bytes = ('.' + ext).encode('utf-8') if ext else b''
        budget = max(max_bytes - len(ext_bytes), 1)
        stem_bytes = stem.encode('utf-8')[:budget]
        stem = stem_bytes.decode('utf-8', errors='ignore').strip('_.')
        name = f'{stem}.{ext}' if ext else stem
        name = name.strip('_.') or 'file'

    return name


def zip_file_bytes(filename: str, raw_bytes: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(filename, raw_bytes)
    return buf.getvalue()


def gdrive_upload_file(config: dict, filename: str, raw_bytes: bytes, mimetype: str) -> str:
    """Ανεβάζει σε Google Drive και επιστρέφει δημόσιο (view-only,
    "anyone with the link") URL. Παρακάμπτει εντελώς το Joomla API -
    καμία επίδραση από το ModSecurity request-body-size όριο, αφού δεν
    περνάει καν από το site.

    Χρησιμοποιεί OAuth (ως πραγματικός χρήστης) και όχι service account:
    τα service accounts δεν έχουν δικό τους αποθηκευτικό χώρο σε
    προσωπικό (μη-Workspace) Google Drive και αποτυγχάνουν με
    "storageQuotaExceeded" όταν προσπαθούν να ανεβάσουν αρχεία - μόνο σε
    Shared Drives δουλεύουν, που απαιτούν Google Workspace. Το token
    (με refresh_token) παράγεται μία φορά τοπικά με το
    gdrive_oauth_setup.py και αποθηκεύεται ως WEBSITE_POST_GDRIVE_OAUTH_TOKEN_JSON
    - ανανεώνεται αυτόματα, χωρίς νέο interactive login, άρα δουλεύει
    κανονικά μέσα στο GitHub Actions."""
    from googleapiclient.http import MediaInMemoryUpload

    folder_id = cfg(config, PREFIX + 'GDRIVE_FOLDER_ID')
    if not folder_id:
        raise RuntimeError('WEBSITE_POST_GDRIVE_FOLDER_ID δεν έχει ρυθμιστεί')
    service = _gdrive_service(config)

    media = MediaInMemoryUpload(raw_bytes, mimetype=mimetype or 'application/octet-stream', resumable=False)
    file = service.files().create(
        body={'name': filename, 'parents': [folder_id]}, media_body=media, fields='id',
    ).execute()
    file_id = file['id']

    service.permissions().create(fileId=file_id, body={'type': 'anyone', 'role': 'reader'}).execute()
    return f'https://drive.google.com/file/d/{file_id}/view'


def _gdrive_service(config: dict):
    import json as _json
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token_json = cfg(config, PREFIX + 'GDRIVE_OAUTH_TOKEN_JSON')
    if not token_json:
        raise RuntimeError('WEBSITE_POST_GDRIVE_OAUTH_TOKEN_JSON δεν έχει ρυθμιστεί')

    creds = Credentials.from_authorized_user_info(_json.loads(token_json))
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleAuthRequest())
    return build('drive', 'v3', credentials=creds)


def check_gdrive_storage_and_notify(config: dict, logger: 'RunLogger') -> None:
    """Ελέγχει το ποσοστό χρήσης του Google Drive λογαριασμού και στέλνει
    ειδοποίηση (Telegram/email, ίδιο κανάλι με τις υπόλοιπες ειδοποιήσεις)
    όταν πλησιάζει το όριο - ΜΟΝΟ ειδοποίηση, καμία αυτόματη διαγραφή
    αρχείων. Χρησιμοποιεί ένα marker αρχείο δίπλα στο log ώστε να μη
    στέλνει την ίδια ειδοποίηση σε κάθε run (κάθε 5 λεπτά) - ξαναστέλνει
    μόνο αν το ποσοστό χρήσης πέσει κάτω από το όριο και μετά το
    ξαναπεράσει."""
    if not cfg_bool(config, PREFIX + 'GDRIVE_ENABLED', False):
        return

    threshold_pct = float(cfg(config, PREFIX + 'GDRIVE_STORAGE_ALERT_PERCENT', '90'))
    marker_path = Path(cfg(config, PREFIX + 'LOG_FILE_PATH', 'logs/post_log.csv')).parent / '.gdrive_storage_alert_sent'

    try:
        service = _gdrive_service(config)
        about = service.about().get(fields='storageQuota').execute()
        quota = about.get('storageQuota', {})
        limit = quota.get('limit')
        usage = quota.get('usage')
        if not limit or not usage:
            return  # π.χ. Workspace λογαριασμός χωρίς όριο - δεν εφαρμόζεται

        limit, usage = int(limit), int(usage)
        used_pct = usage / limit * 100

        if used_pct >= threshold_pct:
            if not marker_path.exists():
                send_notification(
                    config, logger, 'Google Drive - χώρος αποθήκευσης',
                    f'Ο λογαριασμός Google Drive που χρησιμοποιείται για τα συνημμένα emails '
                    f'έχει φτάσει {used_pct:.1f}% χρήση ({usage // (1024**3)}GB / {limit // (1024**3)}GB). '
                    f'Σύντομα μπορεί να αρχίσουν να αποτυγχάνουν τα uploads συνημμένων.',
                )
                marker_path.parent.mkdir(parents=True, exist_ok=True)
                marker_path.write_text(f'{used_pct:.1f}', encoding='utf-8')
        elif marker_path.exists():
            marker_path.unlink()
    except Exception as e:
        logger.log(f'Αποτυχία ελέγχου χώρου Google Drive: {e}', 'WARN')


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
    items = '\n'.join(
        f'<li><a href="{url}" target="_blank" rel="noopener">{name}</a></li>' for name, url in uploaded_files
    )
    return f'<h4>Συνημμένα αρχεία</h4>\n<ul>\n{items}\n</ul>'


READMORE_MARKER = '<hr id="system-readmore" />'


def insert_readmore_marker(html: str, after_paragraphs: int) -> str:
    """Εισάγει το ίδιο marker που βάζει το κουμπί "Read more" του Joomla
    editor, μετά την Ν-οστή παράγραφο (`</p>`) - όχι μέτρηση λέξεων, ώστε
    να μη ρισκάρουμε να κόψουμε ένα HTML tag στη μέση. Αν το κείμενο έχει
    λιγότερες παραγράφους από όσες ζητήθηκαν, δεν μπαίνει καθόλου marker
    (όλο το άρθρο θα φαίνεται σαν intro - ασφαλές fallback)."""
    if after_paragraphs <= 0:
        return html
    pos = 0
    for _ in range(after_paragraphs):
        idx = html.find('</p>', pos)
        if idx == -1:
            return html
        pos = idx + len('</p>')
    return html[:pos] + READMORE_MARKER + html[pos:]


# ---------------------------------------------------------------------------
# Joomla API
# ---------------------------------------------------------------------------

def joomla_request(method: str, url: str, retries: int = 3, backoff: float = 2.0, **kwargs):
    """requests.<method>() με retry/backoff - το shared hosting του site
    κάνει περιστασιακά ConnectionResetError/timeout σε τυχαία requests
    (επιβεβαιώθηκε: συνέβη ακόμα και σε απλό GET), άσχετο με το μέγεθος ή
    το είδος του request. Ξαναπροσπαθεί μόνο σε πρόβλημα σύνδεσης, ποτέ σε
    πραγματικό HTTP σφάλμα (4xx/5xx από τον server) - αυτά ανεβαίνουν
    αμέσως όπως πριν."""
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            return getattr(requests, method)(url, **kwargs)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_exc = e
            if attempt < retries:
                time.sleep(backoff * attempt)
    raise last_exc


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
    resp = joomla_request(
        'post', url,
        headers=joomla_headers(config, {'Content-Type': 'application/json'}),
        params={'mediatypes': '0,1,2,3'},
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    attrs = resp.json()['data']['attributes']
    actual_path = attrs.get('path', '')  # e.g. "local-files:/mail-posts/actual-name.xlsx"

    public_url = attrs.get('thumb_path')
    if not public_url:
        # Non-image uploads don't get a thumb_path back - build the public
        # URL ourselves. Uses the actual returned path, NOT the filename we
        # sent: Joomla transliterates Greek (and possibly other) filenames
        # when saving (e.g. "ΜΟΡΙΑ.xlsx" -> "MORIA.xlsx"), so a URL built
        # from our original filename 404s. Assumes the Joomla convention of
        # adapter id "local-<foldername>" mapping to the "<foldername>/"
        # public path (e.g. "local-files" -> /files/, "local-images" -> /images/).
        public_folder = adapter.removeprefix('local-')
        _, _, relative_path = actual_path.partition(':')
        encoded_path = '/'.join(quote(part) for part in relative_path.strip('/').split('/'))
        public_url = f'{website_url}/{public_folder}/{encoded_path}'

    return actual_path, public_url


def joomla_get_or_create_tag_id(config: dict, tag_name: str):
    search_url = f'{joomla_base_url(config)}/tags'
    # filter[title] is accepted by the API but doesn't actually filter
    # anything server-side - fetch a large page and match client-side.
    resp = joomla_request('get', search_url, headers=joomla_headers(config), params={'page[limit]': 100}, timeout=30)
    resp.raise_for_status()
    results = resp.json().get('data', [])
    for item in results:
        if item['attributes']['title'].strip().lower() == tag_name.strip().lower():
            return item['id']

    create_resp = joomla_request(
        'post', search_url,
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

    resp = joomla_request('post', url, headers=joomla_headers(config, {'Content-Type': 'application/json'}), json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()['data']['id']


def joomla_list_recent_articles(config: dict, limit: int = 10) -> list[dict]:
    """Πιο πρόσφατα πρώτα, μέσα στην ίδια κατηγορία-στόχο - χρησιμοποιείται
    από το GUI (panel "Άρθρα") και το Telegram bot για publish/unpublish."""
    category_id = int(cfg(config, PREFIX + 'CATEGORY_ID', '0'))
    url = f'{joomla_base_url(config)}/content/articles'
    params = {
        'filter[category_id]': category_id,
        'page[limit]': limit,
        'list[fullordering]': 'a.created DESC',
    }
    resp = joomla_request('get', url, headers=joomla_headers(config), params=params, timeout=30)
    resp.raise_for_status()
    items = resp.json().get('data', [])
    return [
        {
            'id': item['id'],
            'title': item['attributes'].get('title', ''),
            'state': item['attributes'].get('state', 0),
            'created': item['attributes'].get('created', ''),
        }
        for item in items
    ]


def is_duplicate_article(config: dict, title: str, lookback: int = 40) -> bool:
    """Ελέγχει αν υπάρχει ήδη πρόσφατο άρθρο με πανομοιότυπο τίτλο (μετά
    από normalization κενών/πεζών-κεφαλαίων) - συμβαίνει όταν δύο
    διαφορετικοί εγκεκριμένοι αποστολείς (π.χ. ο διευθυντής ξαναστέλνει
    ό,τι είχε ήδη στείλει κάποιος άλλος) στέλνουν το ίδιο ακριβώς κείμενο
    ανακοίνωσης. Δεν μπλοκάρει ποτέ την ανάρτηση αν ο ίδιος ο έλεγχος
    αποτύχει (π.χ. προσωρινό πρόβλημα Joomla API)."""
    normalized = re.sub(r'\s+', ' ', title).strip().lower()
    if not normalized:
        return False
    try:
        recent = joomla_list_recent_articles(config, limit=lookback)
    except Exception:
        return False
    for article in recent:
        existing = re.sub(r'\s+', ' ', article.get('title', '')).strip().lower()
        if existing and existing == normalized:
            return True
    return False


def joomla_set_article_state(config: dict, article_id, published: bool) -> dict:
    url = f'{joomla_base_url(config)}/content/articles/{article_id}'
    resp = joomla_request(
        'patch', url,
        headers=joomla_headers(config, {'Content-Type': 'application/json'}),
        json={'state': 1 if published else 0},
        timeout=30,
    )
    resp.raise_for_status()
    attrs = resp.json()['data']['attributes']
    return {'id': attrs.get('id'), 'title': attrs.get('title'), 'state': attrs.get('state')}


# ---------------------------------------------------------------------------
# IMAP
# ---------------------------------------------------------------------------

def ensure_folder(imap_conn, folder_name):
    status, _ = imap_conn.select(folder_name)
    if status != 'OK':
        imap_conn.create(folder_name)


def move_message(imap_conn, msg_uid, destination_folder, source_folder='INBOX'):
    """msg_uid: IMAP UID (stable across mid-session mailbox mutations),
    NOT a sequence number - sequence numbers can silently shift when other
    messages in the same loop get moved/expunged earlier in the same run,
    which caused fetches for later messages to return garbage."""
    imap_conn.select(source_folder)
    ensure_folder(imap_conn, destination_folder)
    imap_conn.select(source_folder)

    status, response = imap_conn.uid('COPY', msg_uid, destination_folder)
    if status != 'OK':
        raise RuntimeError(f'IMAP COPY to {destination_folder} failed: {response}')

    status, response = imap_conn.uid('STORE', msg_uid, '+FLAGS', '\\Deleted')
    if status != 'OK':
        raise RuntimeError(f'IMAP STORE (\\Deleted) failed: {response}')


def _open_imap(config: dict):
    imap_conn = imaplib.IMAP4_SSL(cfg(config, PREFIX + 'EMAIL_IMAP_SERVER'), int(cfg(config, PREFIX + 'EMAIL_IMAP_PORT', '993')))
    imap_conn.login(cfg(config, PREFIX + 'EMAIL_USERNAME'), cfg(config, PREFIX + 'EMAIL_PASSWORD'))
    return imap_conn


def list_folder_messages(config: dict, folder: str, limit: int = 50) -> list[dict]:
    """Πιο πρόσφατα πρώτα. Χρησιμοποιείται από το GUI για να επιλέξεις ένα
    μήνυμα από Processed/Failed προς επανεπεξεργασία."""
    imap_conn = _open_imap(config)
    status, _ = imap_conn.select(folder)
    if status != 'OK':
        imap_conn.logout()
        return []

    status, data = imap_conn.uid('SEARCH', None, 'ALL')
    if status != 'OK':
        imap_conn.logout()
        return []

    uids = data[0].split()[-limit:][::-1]
    results = []
    for uid in uids:
        status, hdr = imap_conn.uid('FETCH', uid, '(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM DATE)])')
        if status != 'OK' or not hdr or not isinstance(hdr[0], tuple):
            continue
        msg = email.message_from_bytes(hdr[0][1])
        results.append({
            'uid': uid.decode(),
            'subject': decode_mime_words(msg.get('Subject', '')),
            'from': parseaddr(msg.get('From', ''))[1],
            'date': msg.get('Date', ''),
        })
    imap_conn.logout()
    return results


def reprocess_message(config: dict, logger: RunLogger, folder: str, uid: str, dry_run: bool) -> dict:
    """Ξανατρέχει process_message() πάνω σε ένα μήνυμα που βρίσκεται ήδη σε
    Processed/Failed/Skipped - χρήσιμο μετά από ένα bugfix, ή αφού
    προστέθηκε ο αποστολέας στη whitelist, χωρίς να χρειάζεται να
    ξαναστείλει κανείς το ίδιο email. Το μήνυμα μετακινείται αυτόματα στον
    φάκελο που ταιριάζει στο νέο αποτέλεσμα (π.χ. Skipped -> Processed αν
    δημοσιεύτηκε τελικά). ΠΡΟΣΟΧΗ: αν δημιουργηθεί άρθρο, είναι ΝΕΟ - δεν
    ενημερώνει/αντικαθιστά κάποιο προηγούμενο, αφού δεν υπάρχει σύνδεση
    email <-> article id."""
    imap_conn = _open_imap(config)
    status, _ = imap_conn.select(folder)
    if status != 'OK':
        imap_conn.logout()
        logger.log(f'Ο φάκελος {folder} δεν βρέθηκε', 'ERROR')
        return {'ok': False, 'exit_code': 1}

    status, msg_data = imap_conn.uid('FETCH', uid, '(BODY.PEEK[])')
    if status != 'OK' or not msg_data or not isinstance(msg_data[0], tuple):
        imap_conn.logout()
        logger.log(f'Δεν βρέθηκε το μήνυμα uid={uid} στο φάκελο {folder}', 'ERROR')
        return {'ok': False, 'exit_code': 1}
    raw_email = msg_data[0][1]

    try:
        result = process_message(config, raw_email, logger, dry_run)
    except Exception as exc:
        logger.log(f'ΣΦΑΛΜΑ επανεπεξεργασίας: {exc}', 'ERROR')
        imap_conn.logout()
        return {'ok': False, 'exit_code': 1}

    target_folder = PROCESSED_FOLDER if result == 'posted' else SKIPPED_FOLDER
    if target_folder != folder and not dry_run:
        try:
            move_message(imap_conn, uid, target_folder, source_folder=folder)
            imap_conn.expunge()
            logger.log(f'Μετακινήθηκε από {folder} σε {target_folder}')
        except Exception as move_exc:
            logger.log(f'Απέτυχε η μετακίνηση: {move_exc}', 'WARN')

    imap_conn.logout()
    return {'ok': True, 'exit_code': 0, 'result': result}


def article_frontend_url(config: dict, article_id) -> str:
    website_url = cfg(config, 'WEBSITE_URL', '').rstrip('/')
    # Δουλεύει πάντα, ανεξάρτητα από SEF routing/menu assignment - δεν
    # χρειάζεται το άρθρο να είναι συνδεδεμένο με κάποιο menu item.
    return f'{website_url}/index.php?option=com_content&view=article&id={article_id}'


def send_telegram_notification(text: str) -> None:
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat_ids = [c.strip() for c in os.environ.get('TELEGRAM_ALLOWED_CHAT_IDS', '').split(',') if c.strip()]
    if not token or not chat_ids:
        return
    for chat_id in chat_ids:
        requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': chat_id, 'text': text},
            timeout=15,
        )


def send_email_notification(config: dict, subject: str, body: str, recipients: list[str]) -> None:
    import smtplib
    from email.mime.text import MIMEText

    username = cfg(config, PREFIX + 'EMAIL_USERNAME')
    password = cfg(config, PREFIX + 'EMAIL_PASSWORD')
    if not username or not password or not recipients:
        return

    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = username
    msg['To'] = ', '.join(recipients)

    with smtplib.SMTP('smtp.gmail.com', 587, timeout=20) as server:
        server.starttls()
        server.login(username, password)
        server.sendmail(username, recipients, msg.as_string())


def send_notification(config: dict, logger: RunLogger, subject: str, text: str) -> None:
    """Best-effort - ποτέ δεν πρέπει να ρίξει το process_message()/
    run_check_mail() αφού καλείται ΜΕΤΑ το πραγματικό αποτέλεσμα
    (ανάρτηση/skip/error), όχι πριν."""
    if cfg_bool(config, PREFIX + 'NOTIFY_TELEGRAM', False):
        try:
            send_telegram_notification(text)
        except Exception as e:
            logger.log(f'Απέτυχε ειδοποίηση Telegram: {e}', 'WARN')

    notify_emails = [e.strip() for e in cfg(config, PREFIX + 'NOTIFY_EMAIL_ADDRESSES', '').split(',') if e.strip()]
    if notify_emails:
        try:
            send_email_notification(config, subject, text, notify_emails)
        except Exception as e:
            logger.log(f'Απέτυχε ειδοποίηση email: {e}', 'WARN')


def notify_posted(config: dict, logger: RunLogger, title: str, article_id, sender_email: str) -> None:
    article_url = article_frontend_url(config, article_id)
    send_notification(
        config, logger, f'Νέα ανάρτηση: {title}',
        f'📢 Νέα ανάρτηση: "{title}"\nΑπό: {sender_email}\n{article_url}',
    )


def notify_skipped(config: dict, logger: RunLogger, sender_email: str, subject: str) -> None:
    send_notification(
        config, logger, 'Μη εγκεκριμένος αποστολέας προσπάθησε να ποστάρει',
        f'⚠️ Μη εγκεκριμένος αποστολέας προσπάθησε να ποστάρει:\nΑπό: {sender_email}\nΘέμα: {subject}',
    )


def notify_failed(config: dict, logger: RunLogger, sender_email: str, subject: str, error: str) -> None:
    send_notification(
        config, logger, 'Σφάλμα ανάρτησης',
        f'❌ Σφάλμα επεξεργασίας μηνύματος:\nΑπό: {sender_email}\nΘέμα: {subject}\nΣφάλμα: {error}',
    )


def reply_to_sender(config: dict, logger: RunLogger, original_msg, body_text: str) -> None:
    """Best-effort auto-reply στον ΙΔΙΟ τον αποστολέα (όχι στη λίστα
    ειδοποιήσεων διαχειριστή) - ώστε να μαθαίνει αν αναρτήθηκε/απέτυχε το
    μήνυμά του χωρίς να χρειάζεται να ρωτήσει. Στέλνεται ως πραγματικό
    reply (In-Reply-To/References) ώστε να μπει στο ίδιο thread. Gated
    από WEBSITE_POST_REPLY_TO_SENDER - δεν στέλνεται για SKIPPED
    (μη εγκεκριμένος αποστολέας), μόνο για posted/failed."""
    if not cfg_bool(config, PREFIX + 'REPLY_TO_SENDER', False):
        return

    import smtplib
    from email.mime.text import MIMEText

    username = cfg(config, PREFIX + 'EMAIL_USERNAME')
    password = cfg(config, PREFIX + 'EMAIL_PASSWORD')
    sender_email = parseaddr(original_msg.get('From', ''))[1]
    if not username or not password or not sender_email:
        return

    original_subject = decode_mime_words(original_msg.get('Subject', ''))
    reply_subject = original_subject if original_subject.lower().startswith('re:') else f'Re: {original_subject}'

    reply = MIMEText(body_text)
    reply['Subject'] = reply_subject
    reply['From'] = username
    reply['To'] = sender_email
    original_message_id = original_msg.get('Message-ID', '')
    if original_message_id:
        reply['In-Reply-To'] = original_message_id
        reply['References'] = original_message_id

    try:
        with smtplib.SMTP('smtp.gmail.com', 587, timeout=20) as server:
            server.starttls()
            server.login(username, password)
            server.sendmail(username, [sender_email], reply.as_string())
    except Exception as e:
        logger.log(f'Απέτυχε αυτόματη απάντηση στον αποστολέα: {e}', 'WARN')


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
        if not dry_run:
            notify_skipped(config, logger, sender_email, raw_subject)
        return 'skipped'

    default_featured = cfg_bool(config, PREFIX + 'DEFAULT_FEATURED', False)
    media_adapter_images = cfg(config, PREFIX + 'MEDIA_ADAPTER_IMAGES', 'local-images')
    media_adapter_docs = cfg(config, PREFIX + 'MEDIA_ADAPTER_DOCS', 'local-files')

    title, tag_names, featured_override = parse_subject(raw_subject)
    featured = default_featured if featured_override is None else featured_override

    if is_duplicate_article(config, title):
        logger.log(f'Παράλειψη (διπλότυπο περιεχόμενο - υπάρχει ήδη πρόσφατο άρθρο με ίδιο τίτλο): {title}', 'WARN')
        log_row(config, sender_email, raw_subject, 'SKIPPED_DUPLICATE')
        if not dry_run:
            send_notification(
                config, logger, 'Παράλειψη διπλότυπου μηνύματος',
                f'⚠️ Παραλείφθηκε μήνυμα με περιεχόμενο που έχει ήδη αναρτηθεί πρόσφατα (πιθανό διπλό email '
                f'από άλλον αποστολέα):\nΑπό: {sender_email}\nΘέμα: {raw_subject}',
            )
        return 'skipped'

    body_html, images, other_files = get_body_and_attachments(msg)
    body_html = embed_youtube_links(body_html)

    readmore_after = int(cfg(config, PREFIX + 'READMORE_AFTER_PARAGRAPHS', '0'))
    body_html = insert_readmore_marker(body_html, readmore_after)

    # Unique per-message prefix so attachments with common names (e.g. two
    # different "Πρόσκληση.pdf") never collide in the shared media folder.
    unique_prefix = datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S') + '-' + uuid.uuid4().hex[:6]

    gdrive_enabled = cfg_bool(config, PREFIX + 'GDRIVE_ENABLED', False)
    zip_large_files = cfg_bool(config, PREFIX + 'ZIP_LARGE_FILES', True)
    max_attachment_bytes = int(cfg(config, PREFIX + 'MAX_ATTACHMENT_KB', '700')) * 1024

    uploaded_doc_links = []
    for filename, raw_bytes, content_type in other_files:
        safe_name = f'{unique_prefix}-{sanitize_filename(filename)}'

        if gdrive_enabled:
            # Google Drive παρακάμπτει εντελώς το Joomla API - όχι zip/
            # shrink ανάγκη, δεν υπόκειται στο ModSecurity όριο του site.
            doc_url = gdrive_upload_file(config, safe_name, raw_bytes, content_type)
            uploaded_doc_links.append((filename, doc_url))
            continue

        upload_bytes, upload_filename = raw_bytes, filename
        if zip_large_files and len(raw_bytes) > max_attachment_bytes:
            # Ο server (ModSecurity) απορρίπτει μεγάλα request bodies -
            # zip πριν το upload. Σημείωση: μορφές ήδη συμπιεσμένες
            # (xlsx/docx/pdf) μπορεί να μη μικρύνουν πολύ, αλλά είναι το
            # καλύτερο που μπορούμε να κάνουμε χωρίς να πειράξουμε το
            # ίδιο το περιεχόμενο του αρχείου.
            upload_bytes = zip_file_bytes(filename, raw_bytes)
            upload_filename = filename + '.zip'
            safe_name = f'{unique_prefix}-{sanitize_filename(upload_filename)}'
            logger.log(
                f'Το συνημμένο "{filename}" ({len(raw_bytes) // 1024}KB) συμπιέστηκε σε zip '
                f'({len(upload_bytes) // 1024}KB) πριν το ανέβασμα',
            )
        _, doc_url = joomla_upload_media(config, safe_name, upload_bytes, media_adapter_docs)
        uploaded_doc_links.append((upload_filename, doc_url))

    image_tags_html = []
    for filename, raw_bytes, _content_type, content_id in images:
        jpeg_bytes = resize_image(config, raw_bytes)
        base_name = f'{unique_prefix}-{sanitize_filename(Path(filename).stem)}.jpg'
        _, img_url = joomla_upload_media(config, base_name, jpeg_bytes, media_adapter_images)

        cid_ref = f'cid:{content_id}'
        if content_id and cid_ref in body_html:
            # Pasted-inline image (or signature logo) - replace the broken
            # "cid:..." reference in place instead of also appending it as
            # a separate block, so it renders exactly where it was.
            body_html = body_html.replace(cid_ref, img_url)
        else:
            image_tags_html.append(f'<p><img src="{img_url}" alt="{title}"></p>')

    full_body = '\n'.join(image_tags_html) + '\n' + body_html + '\n' + build_attachments_html(uploaded_doc_links)

    tag_ids = [joomla_get_or_create_tag_id(config, t) for t in tag_names] if tag_names else []

    article_id = joomla_create_article(config, title, full_body, tag_ids, featured, dry_run)
    logger.log(f'Αναρτήθηκε άρθρο (id={article_id}): "{title}" από {sender_email}')
    log_row(config, sender_email, raw_subject, 'POSTED', article_id, len(images) + len(other_files))

    if not dry_run:
        notify_posted(config, logger, title, article_id, sender_email)
        article_url = article_frontend_url(config, article_id)
        reply_to_sender(config, logger, msg, f'Το μήνυμά σας "{title}" αναρτήθηκε επιτυχώς:\n{article_url}')

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

    check_gdrive_storage_and_notify(config, logger)

    imap_conn = imaplib.IMAP4_SSL(imap_server, imap_port)
    imap_conn.login(email_username, email_password)
    imap_conn.select('INBOX')

    # UIDs (not sequence numbers) - sequence numbers can silently shift
    # mid-loop once move_message() starts copying/flagging earlier messages
    # in the same session, which caused fetches for later messages to
    # return garbage ("'NoneType' object is not subscriptable").
    status, data = imap_conn.uid('SEARCH', None, 'UNSEEN')
    if status != 'OK':
        logger.log('Αποτυχία αναζήτησης IMAP', 'ERROR')
        imap_conn.logout()
        return {'ok': False, 'exit_code': 1, 'posted': 0, 'skipped': 0, 'failed': 0}

    msg_uids = data[0].split()
    logger.log(f'Βρέθηκαν {len(msg_uids)} μη αναγνωσμένο(α) μήνυμα(τα).')

    posted = skipped = failed = 0

    for i, msg_uid in enumerate(msg_uids, start=1):
        if control:
            control.wait_if_paused()
            if control.stop_event.is_set():
                logger.log('Διακόπηκε από τον χρήστη', 'WARN')
                break

        fetch_item = '(BODY.PEEK[])' if dry_run else '(RFC822)'
        status, msg_data = imap_conn.uid('FETCH', msg_uid, fetch_item)
        if status != 'OK' or not msg_data or not isinstance(msg_data[0], tuple):
            logger.log(f'Παράλειψη μηνύματος uid={msg_uid.decode() if isinstance(msg_uid, bytes) else msg_uid}: μη έγκυρη απάντηση IMAP FETCH ({status})', 'WARN')
            failed += 1
            if progress_cb:
                progress_cb(i, len(msg_uids))
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
            logger.log(f'ΣΦΑΛΜΑ επεξεργασίας μηνύματος uid={msg_uid}: {exc}', 'ERROR')
            failed += 1
            if not dry_run:
                notify_failed(config, logger, sender_email, subject, str(exc))
                reply_to_sender(
                    config, logger, msg,
                    f'Δυστυχώς παρουσιάστηκε τεχνικό πρόβλημα κατά την αυτόματη ανάρτηση του '
                    f'μηνύματός σας με θέμα "{subject}". Ο διαχειριστής του συστήματος έχει ήδη '
                    f'ενημερωθεί.',
                )
                try:
                    move_message(imap_conn, msg_uid, FAILED_FOLDER)
                except Exception as move_exc:
                    logger.log(f'Απέτυχε και η μετακίνηση στο {FAILED_FOLDER}: {move_exc}', 'WARN')
            if progress_cb:
                progress_cb(i, len(msg_uids))
            continue

        if not dry_run:
            # Skipped (not-whitelisted) messages go to their own folder,
            # separate from real posts - otherwise finding one to reprocess
            # later (e.g. after adding the sender to the whitelist) means
            # wading through every successfully posted message too.
            target_folder = SKIPPED_FOLDER if result == 'skipped' else PROCESSED_FOLDER
            try:
                move_message(imap_conn, msg_uid, target_folder)
            except Exception as move_exc:
                # The message was already handled successfully - only the
                # mailbox tidy-up failed. Not a processing error.
                logger.log(f'Επεξεργάστηκε αλλά απέτυχε η μετακίνηση στο {target_folder}: {move_exc}', 'WARN')

        if progress_cb:
            progress_cb(i, len(msg_uids))

    imap_conn.expunge()
    imap_conn.close()
    imap_conn.logout()

    logger.log(f'Ολοκληρώθηκε — αναρτήθηκαν: {posted}, παραλείφθηκαν: {skipped}, απέτυχαν: {failed}')
    exit_code = 0 if failed == 0 else (2 if posted > 0 else 1)
    return {'ok': failed == 0, 'exit_code': exit_code, 'posted': posted, 'skipped': skipped, 'failed': failed}
