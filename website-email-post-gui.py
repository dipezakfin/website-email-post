#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
website-email-post-gui.py — Flask GUI πάνω στο dashboard_gui_common shell.
Κάνει import το website_email_post_core.py απευθείας (όχι subprocess).
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

if hasattr(sys.stdout, 'buffer') and getattr(sys.stdout, 'encoding', 'utf-8').lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from flask import Flask, jsonify, request

import website_email_post_core as core
import dashboard_gui_common as shell

core.load_dotenv_files()

APP_DIR = core.APP_DIR
JOBS = shell.JobManager(app_name=core.APP_NAME)
_STATE = {'overrides': {}}

GITHUB_REPO = 'dipezakfin/website-email-post'
# Μόνο οι μεταβλητές που πραγματικά χρησιμοποιεί το check-mail.yml ως
# secrets - π.χ. το LOG_FILE_PATH είναι hardcoded στο workflow, δεν είναι
# secret.
GITHUB_SECRET_KEYS = {
    'WEBSITE_PLATFORM', 'WEBSITE_URL',
    'WEBSITE_POST_EMAIL_IMAP_SERVER', 'WEBSITE_POST_EMAIL_IMAP_PORT',
    'WEBSITE_POST_EMAIL_USERNAME', 'WEBSITE_POST_EMAIL_PASSWORD',
    'WEBSITE_POST_HTTPS_PORT', 'WEBSITE_POST_API_TOKEN', 'WEBSITE_POST_CATEGORY_ID',
    'WEBSITE_POST_MEDIA_ADAPTER_IMAGES', 'WEBSITE_POST_MEDIA_ADAPTER_DOCS', 'WEBSITE_POST_MEDIA_SUBPATH',
    'WEBSITE_POST_WHITELIST_EMAIL_ADDRESSES', 'WEBSITE_POST_DEFAULT_STATUS', 'WEBSITE_POST_DEFAULT_FEATURED',
    'WEBSITE_POST_IMAGE_MAX_WIDTH', 'WEBSITE_POST_IMAGE_JPEG_QUALITY', 'WEBSITE_POST_DRY_RUN',
}


def _sync_github_secrets(values: dict) -> dict:
    """Καλεί `gh secret set` για κάθε τιμή που αντιστοιχεί σε γνωστό secret
    του workflow. Απαιτεί το `gh` CLI εγκατεστημένο/συνδεδεμένο στον
    υπολογιστή που τρέχει το GUI - αν αποτύχει, δεν μπλοκάρει το τοπικό
    .env save, απλά αναφέρεται ξεχωριστά."""
    import shutil
    import subprocess

    if shutil.which('gh') is None:
        return {'available': False, 'updated': [], 'failed': [], 'message': 'Το gh CLI δεν βρέθηκε σε αυτόν τον υπολογιστή'}

    updated, failed = [], []
    for key, value in values.items():
        if key not in GITHUB_SECRET_KEYS:
            continue
        try:
            result = subprocess.run(
                ['gh', 'secret', 'set', key, '--repo', GITHUB_REPO],
                input=str(value), capture_output=True, text=True, timeout=30,
            )
            (updated if result.returncode == 0 else failed).append(key)
        except Exception:
            failed.append(key)
    return {'available': True, 'updated': updated, 'failed': failed}


def _get_config(request_overrides: dict | None = None) -> dict:
    core.load_dotenv_files()  # ξαναδιαβάζει το .env σε κάθε κλήση
    overrides = dict(_STATE['overrides'])
    if request_overrides:
        overrides.update(request_overrides)
    return core.load_config(overrides)


def _json_body() -> dict:
    return request.get_json(force=True, silent=True) or {}


# --- API handlers ---

def _api_config_get(_req):
    return jsonify(_get_config())


def _api_config_set(req):
    body = _json_body()
    _STATE['overrides'].update({k: v for k, v in body.items() if isinstance(k, str)})
    return jsonify({'ok': True})


def _api_settings_save_env(_req):
    from dotenv import set_key
    body = _json_body()
    candidates = [APP_DIR / '.env', (APP_DIR / '..' / '..' / '.env').resolve()]
    env_file = next((p for p in candidates if p.exists()), None)
    if not env_file:
        return jsonify({'ok': False, 'message': '.env αρχείο δεν βρέθηκε'}), 400
    for key, value in body.items():
        if isinstance(key, str):
            set_key(str(env_file), key, str(value))
    _STATE['overrides'] = {}
    core.load_dotenv_files()

    github = _sync_github_secrets({k: v for k, v in body.items() if isinstance(k, str)})
    return jsonify({'ok': True, 'file': str(env_file), 'github': github})


def _api_run_check_mail(_req):
    config = _get_config()

    def target(logger, control, progress_cb):
        return core.run_check_mail(config, logger, control=control, progress_cb=progress_cb)

    job_id = JOBS.start(target)
    return jsonify({'ok': True, 'job_id': job_id})


def _api_job_status(req):
    job_id = request.args.get('job_id', '')
    status = JOBS.status(job_id)
    if status is None:
        return jsonify({'error': 'unknown job_id'}), 404
    return jsonify(status)


def _api_job_pause(req):
    return jsonify({'ok': JOBS.pause(_json_body().get('job_id'))})


def _api_job_resume(req):
    return jsonify({'ok': JOBS.resume(_json_body().get('job_id'))})


def _api_job_stop(req):
    return jsonify({'ok': JOBS.stop(_json_body().get('job_id'))})


def _api_recent_log(_req):
    rows = core.read_recent_log_rows(_get_config(), limit=50)
    return jsonify({'rows': rows})


def _api_list_folder_messages(req):
    folder = request.args.get('folder', 'Processed')
    rows = core.list_folder_messages(_get_config(), folder)
    return jsonify({'rows': rows})


def _api_reprocess(req):
    body = _json_body()
    folder = body.get('folder', 'Processed')
    uid = body.get('uid', '')
    config = _get_config()

    def target(logger, control, progress_cb):
        return core.reprocess_message(config, logger, folder, uid, core.cfg_bool(config, core.PREFIX + 'DRY_RUN', False))

    job_id = JOBS.start(target)
    return jsonify({'ok': True, 'job_id': job_id})


_API_HANDLERS = {
    'config': _api_config_get,
    'config/set': _api_config_set,
    'settings/save-env': _api_settings_save_env,
    'run-check-mail': _api_run_check_mail,
    'job/status': _api_job_status,
    'job/pause': _api_job_pause,
    'job/resume': _api_job_resume,
    'job/stop': _api_job_stop,
    'recent-log': _api_recent_log,
    'list-folder-messages': _api_list_folder_messages,
    'reprocess': _api_reprocess,
}


def _dispatch_api(endpoint: str, req):
    handler = _API_HANDLERS.get(endpoint)
    if not handler:
        return jsonify({'error': f'Unknown endpoint: {endpoint}'}), 404
    try:
        return handler(req)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# --- HTML ---

def get_web_interface() -> str:
    return (_HTML_PAGE
        .replace('__COMMON_CSS__', shell.COMMON_CSS)
        .replace('__HEAD_SCRIPT__', shell.render_head(theme_key='website-email-post-theme'))
        .replace('__THEME_TOGGLE_BUTTON__', shell.HEADER_ACTIONS_HTML)
        .replace('__APP_TITLE__', shell.app_display_name(core.APP_DIR))
        .replace('__COMMON_JS__', shell.render_common_js(
            theme_key='website-email-post-theme',
            unload_warning_message='Υπάρχει ενεργός έλεγχος mail σε εξέλιξη. Σίγουρα θέλετε να φύγετε;'))
        .replace('__HELP_PANEL__', shell.render_help_panel_html(core.APP_DIR))
        .replace('__HELP_JS__', shell.HELP_TAB_JS + shell.SCHEDULING_JS))


_HTML_PAGE = r"""<!DOCTYPE html>
<html lang="el">
<head>
<meta charset="utf-8">
<title>Website Email Post</title>
<style>
__COMMON_CSS__
.postlog-table { width: 100%; border-collapse: collapse; font-size: 0.9em; margin-top: 10px; }
.postlog-table th, .postlog-table td { border: 1px solid var(--border, #444); padding: 4px 8px; text-align: left; }
.postlog-table td.status-POSTED { color: #4caf50; }
.postlog-table td.status-ERROR { color: #f44336; }
.postlog-table td.status-SKIPPED_NOT_WHITELISTED { color: #999; }
.email-chips { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.email-chip { display: inline-flex; align-items: center; gap: 6px; padding: 3px 6px 3px 10px;
  border-radius: 999px; border: 1px solid var(--btn-border); background: var(--btn-bg); color: var(--btn-fg); font-size: 13px; }
.email-chip .remove { cursor: pointer; font-weight: bold; opacity: 0.7; padding: 0 3px; border-radius: 50%; }
.email-chip .remove:hover { opacity: 1; background: var(--accent); color: #fff; }
</style>
__HEAD_SCRIPT__
</head>
<body>
<header><h1>__APP_TITLE__</h1>
  __THEME_TOGGLE_BUTTON__
</header>
<div class="tabs" id="tabs"></div>

<div class="panel" id="panel-settings">
  <fieldset><legend>Email (IMAP mailbox)</legend>
    <div class="row"><label>IMAP Server</label><input id="cfg_WEBSITE_POST_EMAIL_IMAP_SERVER" onchange="saveCfg()"></div>
    <div class="row"><label>IMAP Port</label><input type="number" id="cfg_WEBSITE_POST_EMAIL_IMAP_PORT" style="width:100px" onchange="saveCfg()"></div>
    <div class="row"><label>Διεύθυνση mailbox</label><input id="cfg_WEBSITE_POST_EMAIL_SENDER_ADDRESS" style="width:320px" onchange="saveCfg()"></div>
    <div class="row"><label>Username</label><input id="cfg_WEBSITE_POST_EMAIL_USERNAME" style="width:320px" onchange="saveCfg()"></div>
    <div class="row"><label>Password / App Password</label><input type="password" id="cfg_WEBSITE_POST_EMAIL_PASSWORD" style="width:320px" onchange="saveCfg()"></div>
  </fieldset>

  <fieldset><legend>Joomla / Ιστότοπος</legend>
    <div class="row"><label>Πλατφόρμα</label>
      <select id="cfg_WEBSITE_PLATFORM" onchange="saveCfg()">
        <option value="joomla">Joomla</option>
      </select>
      <span class="hint">Μόνο "joomla" υποστηρίζεται προς το παρόν</span></div>
    <div class="row"><label>Website URL</label><input id="cfg_WEBSITE_URL" style="width:320px" onchange="saveCfg()"></div>
    <div class="row"><label>HTTPS Port</label><input id="cfg_WEBSITE_POST_HTTPS_PORT" style="width:100px" onchange="saveCfg()"></div>
    <div class="row"><label>API Token</label><input type="password" id="cfg_WEBSITE_POST_API_TOKEN" style="width:400px" onchange="saveCfg()"></div>
    <div class="row"><label>Category ID</label><input type="number" id="cfg_WEBSITE_POST_CATEGORY_ID" style="width:100px" onchange="saveCfg()"></div>
    <div class="row"><label>Media adapter (εικόνες)</label><input id="cfg_WEBSITE_POST_MEDIA_ADAPTER_IMAGES" style="width:200px" onchange="saveCfg()"></div>
    <div class="row"><label>Media adapter (έγγραφα)</label><input id="cfg_WEBSITE_POST_MEDIA_ADAPTER_DOCS" style="width:200px" onchange="saveCfg()"></div>
    <div class="row"><label>Υποφάκελος media</label><input id="cfg_WEBSITE_POST_MEDIA_SUBPATH" style="width:200px" onchange="saveCfg()"></div>
  </fieldset>

  <fieldset><legend>Έλεγχος πρόσβασης &amp; Δημοσίευση</legend>
    <div class="row"><label>Εγκεκριμένοι αποστολείς</label>
      <div style="flex:1">
        <div class="email-chips" id="whitelist_chips"></div>
        <div style="margin-top:6px">
          <input id="whitelist_new_email" placeholder="email@example.gr" style="width:260px"
            onkeydown="if(event.key==='Enter'){event.preventDefault();addWhitelistEmail();}">
          <button type="button" onclick="addWhitelistEmail()">➕ Προσθήκη</button>
        </div>
      </div>
      <input type="hidden" id="cfg_WEBSITE_POST_WHITELIST_EMAIL_ADDRESSES">
    </div>
    <div class="row"><label>Κατάσταση άρθρου</label>
      <select id="cfg_WEBSITE_POST_DEFAULT_STATUS" onchange="saveCfg()">
        <option value="DRAFT">DRAFT</option>
        <option value="PUBLISHED">PUBLISHED</option>
      </select>
    </div>
    <div class="row"><label>Featured by default</label><label class="switch"><input type="checkbox" id="cfg_WEBSITE_POST_DEFAULT_FEATURED" onchange="saveCfg()"><span class="slider"></span></label></div>
  </fieldset>

  <fieldset><legend>Εικόνες</legend>
    <div class="row"><label>Μέγιστο πλάτος (px)</label><input type="number" id="cfg_WEBSITE_POST_IMAGE_MAX_WIDTH" style="width:100px" onchange="saveCfg()"></div>
    <div class="row"><label>Ποιότητα JPEG (%)</label><input type="number" id="cfg_WEBSITE_POST_IMAGE_JPEG_QUALITY" style="width:100px" onchange="saveCfg()"></div>
  </fieldset>

  <fieldset><legend>Log &amp; Δοκιμή</legend>
    <div class="row"><label>CSV Log αρχείο</label><input id="cfg_WEBSITE_POST_LOG_FILE_PATH" style="width:400px" onchange="saveCfg()">
      <button type="button" title="Επιλογή αρχείου" onclick="browsePath('cfg_WEBSITE_POST_LOG_FILE_PATH','savefile','csv', () => saveCfg())">📁</button>
      <button type="button" title="Επεξεργασία αρχείου (άνοιγμα με τον προεπιλεγμένο editor)" onclick="editFile('cfg_WEBSITE_POST_LOG_FILE_PATH')">✏️</button>
    </div>
    <div class="row"><label>DRY RUN (δοκιμή, χωρίς πραγματική ανάρτηση)</label><label class="switch"><input type="checkbox" id="cfg_WEBSITE_POST_DRY_RUN" onchange="saveCfg()"><span class="slider"></span></label></div>
  </fieldset>

  <div class="row" style="margin-top:10px">
    <button class="success" onclick="saveSettingsToEnv(this)">💾 Αποθήκευση στο .env</button>
    <span class="hint">Ενημερώνει αυτόματα και τα GitHub Secrets (χρειάζεται συνδεδεμένο gh CLI)</span>
  </div>
  <div class="row"><span id="settings_save_result" class="hint"></span></div>
</div>

<div class="panel active" id="panel-run">
  <fieldset><legend>Έλεγχος mail</legend>
    <button class="success" onclick="runCheckMail(this)">📧 Έλεγχος mail τώρα</button>
    <button onclick="pauseResumeJob(this)" id="pause_btn" style="display:none">⏸ Παύση</button>
    <button class="danger" onclick="stopJob(this)" id="stop_btn" style="display:none">⏹ Διακοπή</button>
  </fieldset>
  <progress id="job_progress" value="0" max="100" style="width:100%"></progress>
  <div id="log"></div>

  <fieldset><legend>Πρόσφατες αναρτήσεις <button type="button" onclick="loadRecentLog()" title="Ανανέωση">🔄</button></legend>
    <div style="overflow-x:auto">
      <table class="postlog-table" id="recent_log_table">
        <thead><tr><th>Ώρα</th><th>Από</th><th>Θέμα</th><th>Κατάσταση</th><th>Άρθρο</th><th>Συνημμένα</th><th>Σφάλμα</th></tr></thead>
        <tbody id="recent_log_tbody"></tbody>
      </table>
    </div>
  </fieldset>

  <fieldset><legend>Επανεπεξεργασία μηνύματος</legend>
    <span class="hint">Ξανατρέχει ένα μήνυμα που είναι ήδη σε Processed/Failed — π.χ. μετά από ένα bugfix, χωρίς να χρειάζεται να ξανασταλεί το email. Δημιουργεί ΝΕΟ άρθρο, δεν ενημερώνει το προηγούμενο.</span>
    <div class="row"><label>Φάκελος</label>
      <select id="reprocess_folder" onchange="loadFolderMessages()">
        <option value="Processed">Processed</option>
        <option value="Failed">Failed</option>
      </select>
      <button type="button" onclick="loadFolderMessages()" title="Ανανέωση λίστας">🔄</button>
    </div>
    <div class="row"><label>Μήνυμα</label>
      <select id="reprocess_uid" style="width:500px"></select>
    </div>
    <div class="row">
      <button class="success" onclick="reprocessMessage(this)">🔁 Επανεπεξεργασία</button>
    </div>
  </fieldset>
</div>

__HELP_PANEL__

<script>
__COMMON_JS__

__HELP_JS__
helpLoadInfo();

const TABS = [
  ['settings', 'Ρυθμίσεις'], ['run', 'Έλεγχος Mail'], ['help', 'Βοήθεια'],
];
let JOB_ACTIVE = false;
let CURRENT_JOB_ID = null;
let WHITELIST_EMAILS = [];

function val(id) { const el = document.getElementById(id); return el ? el.value : ''; }
function setVal(id, v) { const el = document.getElementById(id); if (el) el.value = (v === undefined || v === null) ? '' : v; }
function checked(id) { const el = document.getElementById(id); return el ? el.checked : false; }
function setChecked(id, v) { const el = document.getElementById(id); if (el) el.checked = String(v).trim().toUpperCase() === 'YES'; }

function renderWhitelistChips() {
  document.getElementById('whitelist_chips').innerHTML = WHITELIST_EMAILS.map((email, i) =>
    `<span class="email-chip">${email}<span class="remove" onclick="removeWhitelistEmail(${i})" title="Αφαίρεση">×</span></span>`
  ).join('');
  setVal('cfg_WEBSITE_POST_WHITELIST_EMAIL_ADDRESSES', WHITELIST_EMAILS.join(','));
}

function addWhitelistEmail() {
  const input = document.getElementById('whitelist_new_email');
  const email = input.value.trim();
  if (!email) return;
  if (!WHITELIST_EMAILS.includes(email)) {
    WHITELIST_EMAILS.push(email);
    renderWhitelistChips();
    saveCfg();
  }
  input.value = '';
}

function removeWhitelistEmail(index) {
  WHITELIST_EMAILS.splice(index, 1);
  renderWhitelistChips();
  saveCfg();
}

function _collectSettings() {
  return {
    WEBSITE_POST_EMAIL_IMAP_SERVER: val('cfg_WEBSITE_POST_EMAIL_IMAP_SERVER'),
    WEBSITE_POST_EMAIL_IMAP_PORT: val('cfg_WEBSITE_POST_EMAIL_IMAP_PORT'),
    WEBSITE_POST_EMAIL_SENDER_ADDRESS: val('cfg_WEBSITE_POST_EMAIL_SENDER_ADDRESS'),
    WEBSITE_POST_EMAIL_USERNAME: val('cfg_WEBSITE_POST_EMAIL_USERNAME'),
    WEBSITE_POST_EMAIL_PASSWORD: val('cfg_WEBSITE_POST_EMAIL_PASSWORD'),
    WEBSITE_PLATFORM: val('cfg_WEBSITE_PLATFORM'),
    WEBSITE_URL: val('cfg_WEBSITE_URL'),
    WEBSITE_POST_HTTPS_PORT: val('cfg_WEBSITE_POST_HTTPS_PORT'),
    WEBSITE_POST_API_TOKEN: val('cfg_WEBSITE_POST_API_TOKEN'),
    WEBSITE_POST_CATEGORY_ID: val('cfg_WEBSITE_POST_CATEGORY_ID'),
    WEBSITE_POST_MEDIA_ADAPTER_IMAGES: val('cfg_WEBSITE_POST_MEDIA_ADAPTER_IMAGES'),
    WEBSITE_POST_MEDIA_ADAPTER_DOCS: val('cfg_WEBSITE_POST_MEDIA_ADAPTER_DOCS'),
    WEBSITE_POST_MEDIA_SUBPATH: val('cfg_WEBSITE_POST_MEDIA_SUBPATH'),
    WEBSITE_POST_WHITELIST_EMAIL_ADDRESSES: val('cfg_WEBSITE_POST_WHITELIST_EMAIL_ADDRESSES'),
    WEBSITE_POST_DEFAULT_STATUS: val('cfg_WEBSITE_POST_DEFAULT_STATUS'),
    WEBSITE_POST_DEFAULT_FEATURED: checked('cfg_WEBSITE_POST_DEFAULT_FEATURED') ? 'YES' : 'NO',
    WEBSITE_POST_IMAGE_MAX_WIDTH: val('cfg_WEBSITE_POST_IMAGE_MAX_WIDTH'),
    WEBSITE_POST_IMAGE_JPEG_QUALITY: val('cfg_WEBSITE_POST_IMAGE_JPEG_QUALITY'),
    WEBSITE_POST_LOG_FILE_PATH: val('cfg_WEBSITE_POST_LOG_FILE_PATH'),
    WEBSITE_POST_DRY_RUN: checked('cfg_WEBSITE_POST_DRY_RUN') ? 'YES' : 'NO',
  };
}

function saveCfg() { return api('config/set', _collectSettings()); }

function saveSettingsToEnv(btn) {
  withLoading(btn, api('settings/save-env', _collectSettings())).then(r => {
    const el = document.getElementById('settings_save_result');
    if (!r.ok) {
      el.textContent = '✗ ' + (r.message || 'Σφάλμα');
      return;
    }
    let msg = '✓ Αποθηκεύτηκε στο ' + r.file;
    const gh = r.github || {};
    if (!gh.available) {
      msg += ' — ⚠ GitHub Secrets ΔΕΝ ενημερώθηκαν (' + (gh.message || 'gh CLI μη διαθέσιμο') + ')';
    } else {
      msg += ' — GitHub Secrets: ✓ ' + (gh.updated || []).length + ' ενημερώθηκαν';
      if ((gh.failed || []).length) {
        msg += ', ✗ απέτυχαν: ' + gh.failed.join(', ');
      }
    }
    el.textContent = msg;
  });
}

function loadSettings() {
  api('config').then(c => {
    setVal('cfg_WEBSITE_POST_EMAIL_IMAP_SERVER', c.WEBSITE_POST_EMAIL_IMAP_SERVER);
    setVal('cfg_WEBSITE_POST_EMAIL_IMAP_PORT', c.WEBSITE_POST_EMAIL_IMAP_PORT || '993');
    setVal('cfg_WEBSITE_POST_EMAIL_SENDER_ADDRESS', c.WEBSITE_POST_EMAIL_SENDER_ADDRESS);
    setVal('cfg_WEBSITE_POST_EMAIL_USERNAME', c.WEBSITE_POST_EMAIL_USERNAME);
    setVal('cfg_WEBSITE_POST_EMAIL_PASSWORD', c.WEBSITE_POST_EMAIL_PASSWORD);
    setVal('cfg_WEBSITE_PLATFORM', c.WEBSITE_PLATFORM || 'joomla');
    setVal('cfg_WEBSITE_URL', c.WEBSITE_URL);
    setVal('cfg_WEBSITE_POST_HTTPS_PORT', c.WEBSITE_POST_HTTPS_PORT || '443');
    setVal('cfg_WEBSITE_POST_API_TOKEN', c.WEBSITE_POST_API_TOKEN);
    setVal('cfg_WEBSITE_POST_CATEGORY_ID', c.WEBSITE_POST_CATEGORY_ID);
    setVal('cfg_WEBSITE_POST_MEDIA_ADAPTER_IMAGES', c.WEBSITE_POST_MEDIA_ADAPTER_IMAGES || 'local-images');
    setVal('cfg_WEBSITE_POST_MEDIA_ADAPTER_DOCS', c.WEBSITE_POST_MEDIA_ADAPTER_DOCS || 'local-files');
    setVal('cfg_WEBSITE_POST_MEDIA_SUBPATH', c.WEBSITE_POST_MEDIA_SUBPATH || 'mail-posts');
    WHITELIST_EMAILS = String(c.WEBSITE_POST_WHITELIST_EMAIL_ADDRESSES || '').split(',').map(s => s.trim()).filter(Boolean);
    renderWhitelistChips();
    setVal('cfg_WEBSITE_POST_DEFAULT_STATUS', c.WEBSITE_POST_DEFAULT_STATUS || 'DRAFT');
    setChecked('cfg_WEBSITE_POST_DEFAULT_FEATURED', c.WEBSITE_POST_DEFAULT_FEATURED || 'NO');
    setVal('cfg_WEBSITE_POST_IMAGE_MAX_WIDTH', c.WEBSITE_POST_IMAGE_MAX_WIDTH || '1600');
    setVal('cfg_WEBSITE_POST_IMAGE_JPEG_QUALITY', c.WEBSITE_POST_IMAGE_JPEG_QUALITY || '75');
    setVal('cfg_WEBSITE_POST_LOG_FILE_PATH', c.WEBSITE_POST_LOG_FILE_PATH || 'logs/post_log.csv');
    setChecked('cfg_WEBSITE_POST_DRY_RUN', c.WEBSITE_POST_DRY_RUN || 'NO');
  });
}

function runCheckMail(btn) {
  withLoading(btn, api('run-check-mail', {})).then(r => {
    if (r.ok) {
      CURRENT_JOB_ID = r.job_id;
      JOB_ACTIVE = true;
      document.getElementById('pause_btn').style.display = '';
      document.getElementById('stop_btn').style.display = '';
      pollJob();
    }
  });
}

function loadFolderMessages() {
  const folder = val('reprocess_folder');
  const sel = document.getElementById('reprocess_uid');
  sel.innerHTML = '<option>...φόρτωση...</option>';
  api('list-folder-messages?folder=' + encodeURIComponent(folder)).then(r => {
    const rows = r.rows || [];
    sel.innerHTML = rows.length
      ? rows.map(m => `<option value="${m.uid}">${m.date || ''} — ${m.from || ''} — ${m.subject || ''}</option>`).join('')
      : '<option value="">(κανένα μήνυμα)</option>';
  });
}

function reprocessMessage(btn) {
  const folder = val('reprocess_folder');
  const uid = val('reprocess_uid');
  if (!uid) { alert('Επίλεξε πρώτα ένα μήνυμα'); return; }
  withLoading(btn, api('reprocess', {folder: folder, uid: uid})).then(r => {
    if (r.ok) {
      CURRENT_JOB_ID = r.job_id;
      JOB_ACTIVE = true;
      document.getElementById('pause_btn').style.display = '';
      document.getElementById('stop_btn').style.display = '';
      pollJob();
    }
  });
}

function pauseResumeJob(btn) {
  if (!CURRENT_JOB_ID) return;
  const isPausing = btn.textContent.indexOf('Παύση') !== -1;
  api('job/' + (isPausing ? 'pause' : 'resume'), {job_id: CURRENT_JOB_ID}).then(() => {
    btn.textContent = isPausing ? '▶ Συνέχεια' : '⏸ Παύση';
  });
}

function stopJob(btn) {
  if (!CURRENT_JOB_ID) return;
  api('job/stop', {job_id: CURRENT_JOB_ID});
}

function pollJob() {
  if (!CURRENT_JOB_ID) return;
  api('job/status?job_id=' + CURRENT_JOB_ID).then(r => {
    const logDiv = document.getElementById('log');
    logDiv.innerHTML = r.log.map(l => {
      const cls = l.includes(';ERROR;') ? 'error' : l.includes(';WARN;') ? 'warn' : '';
      return `<div class="${cls}">${l}</div>`;
    }).join('');
    logDiv.scrollTop = logDiv.scrollHeight;
    const p = r.progress || {};
    const pct = p.total ? Math.round(100 * p.current / p.total) : 0;
    document.getElementById('job_progress').value = pct;
    JOB_ACTIVE = (r.status === 'running' || r.status === 'paused');
    if (JOB_ACTIVE) {
      setTimeout(pollJob, 1000);
    } else {
      document.getElementById('pause_btn').style.display = 'none';
      document.getElementById('stop_btn').style.display = 'none';
      loadRecentLog();
    }
  });
}

function loadRecentLog() {
  api('recent-log').then(r => {
    const tbody = document.getElementById('recent_log_tbody');
    tbody.innerHTML = (r.rows || []).map(row => `<tr>
      <td>${row.timestamp || ''}</td>
      <td>${row.email_from || ''}</td>
      <td>${row.email_subject || ''}</td>
      <td class="status-${row.status || ''}">${row.status || ''}</td>
      <td>${row.joomla_article_id || ''}</td>
      <td>${row.attachments_count || ''}</td>
      <td>${row.error_message || ''}</td>
    </tr>`).join('');
  });
}

function initTabs() {
  const bar = document.getElementById('tabs');
  TABS.forEach(([id, label], i) => {
    const el = document.createElement('div');
    el.className = 'tab' + (i === 0 ? ' active' : '');
    el.textContent = label;
    el.onclick = () => showTab(id);
    el.dataset.tab = id;
    bar.appendChild(el);
  });
  showTab('settings');
}

function showTab(id) {
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === id));
  document.querySelectorAll('.panel').forEach(p => p.classList.toggle('active', p.id === 'panel-' + id));
}

initTabs();
loadSettings();
loadRecentLog();
loadFolderMessages();
updateThemeToggleIcon();
</script>
</body>
</html>"""


_flask_app = Flask(__name__)
shell.register_common_routes(_flask_app, app_dir=APP_DIR, any_job_active=JOBS.any_active)


@_flask_app.route('/')
def _index():
    return get_web_interface()


@_flask_app.route('/api/<path:endpoint>', methods=['GET', 'POST'])
def _api(endpoint):
    return _dispatch_api(endpoint, request)


if __name__ == '__main__':
    shell.run_standalone_cli(_flask_app, default_port=5049, app_label='Website Email Post GUI')
