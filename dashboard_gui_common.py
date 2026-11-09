#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dashboard_gui_common.py
Κοινό Flask/UI shell για το gui.py κάθε dashboard app. Αντιγράφεται αυτούσιο
μέσα σε κάθε app folder (ίδια σύμβαση με το websign_sign.py — κάθε app
παραμένει self-contained, χωρίς cross-folder imports μέσω sys.path).

Παρέχει το ΚΟΙΝΟ οπτικό/λειτουργικό στρώμα που χτίστηκε αρχικά για το
email-sender: dark mode (CSS variables + toggle, localStorage), μοντέρνο
styling (στρογγυλεμένα fieldsets/inputs/buttons, toggle switches, πίνακες),
confirm modal, loading-state σε κουμπιά, rich text editor (contenteditable,
χωρίς CDN), native Windows file/folder browse dialog, "Επεξεργασία" αρχείου
με τον προεπιλεγμένο editor των Windows, και debounced graceful shutdown όταν
κλείνει το browser tab (standalone mode).

Χρήση από ένα app's gui.py:

    import dashboard_gui_common as shell

    HTML_PAGE = f\"\"\"<!DOCTYPE html>
    <html lang="el"><head><meta charset="utf-8"><title>...</title>
    {shell.render_head(theme_key='myapp-theme')}
    <style>{shell.COMMON_CSS}
      /* ...app-specific CSS εδώ... */
    </style>
    </head><body>
    <header><h1>...</h1>{shell.THEME_TOGGLE_BUTTON_HTML}</header>
    ...δικό σου tabs/panels HTML...
    <script>
    {shell.COMMON_JS}
    // ...δικό σου JS εδώ (χρησιμοποιεί api(), withLoading(), showConfirmModal(),
    // browsePath(), makeRichEditor(), syncRichEditor() από το COMMON_JS)...
    </script>
    </body></html>\"\"\"

    flask_app = Flask(__name__)
    jobs = shell.JobManager(app_name='myapp')
    shell.register_common_routes(flask_app, app_dir=APP_DIR, any_job_active=jobs.any_active)

    @flask_app.route('/')
    def _index(): return HTML_PAGE

    if __name__ == '__main__':
        shell.run_standalone_cli(flask_app, default_port=5020)
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from flask import jsonify, request

try:
    from dashboard_core_common import RunLogger, log_final_status
except ImportError:  # αν αντιγράφτηκε μόνο αυτό το αρχείο χωρίς το core_common
    RunLogger = None


# ---------------------------------------------------------------------------

LOGO_WHITE_DATA_URI = "data:image/png;base64,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"
# CSS (dark mode via CSS variables + toggle, μοντέρνο styling)
# ---------------------------------------------------------------------------

COMMON_CSS = r"""
  :root {
    --bg: #eef1f5; --fg: #222; --header-bg: #223A66; --header-fg: #fff;
    --tabs-bg: #2B4574; --tab-fg: #ccd3da; --tab-hover-bg: #355285;
    --fieldset-bg: #fff; --fieldset-border: #d8dee4; --legend-fg: #223A66;
    --input-bg: #fff; --input-border: #c7ccd1; --input-fg: #222;
    --btn-bg: #eef1f5; --btn-border: #b8bec4; --btn-fg: #222; --btn-hover-bg: #e0e5ea;
    --table-border: #e0e4e8; --table-head-bg: #eef1f5; --table-row-hover: #f7f9fb;
    --table-cell-border: #eceff2;
    --log-bg: #1e1e1e; --log-fg: #d4d4d4;
    --hint-fg: #777; --shadow: rgba(0,0,0,0.06); --accent: #223A66;
    --obtn-fg: #223A66; --pbtn-bg: #223A66; --pbtn-hover: #285a9f;
  }
  [data-theme="dark"] {
    --bg: #181c20; --fg: #e2e5e8; --header-bg: #11151a; --header-fg: #f0f0f0;
    --tabs-bg: #11151a; --tab-fg: #98a2ab; --tab-hover-bg: #232a31;
    --fieldset-bg: #22272c; --fieldset-border: #333a41; --legend-fg: #7fb3e0;
    --input-bg: #2a3138; --input-border: #454e57; --input-fg: #e2e5e8;
    --btn-bg: #2a3138; --btn-border: #454e57; --btn-fg: #e2e5e8; --btn-hover-bg: #333c45;
    --table-border: #333a41; --table-head-bg: #22272c; --table-row-hover: #262c32;
    --table-cell-border: #2c333a;
    --log-bg: #0d0f11; --log-fg: #c8c8c8;
    --hint-fg: #93a0ab; --shadow: rgba(0,0,0,0.3); --accent: #4ea3e0;
    --obtn-fg: #7fb3e0; --pbtn-bg: #285a9f; --pbtn-hover: #3470b8;
  }
  * { box-sizing: border-box; }
  body { font-family: "Segoe UI", Arial, sans-serif; margin: 0; background: var(--bg); color: var(--fg);
    font-size: 14px; transition: background 0.2s, color 0.2s; }
  header { background: var(--header-bg); color: var(--header-fg); padding: 16px 22px;
    display: flex; align-items: center; justify-content: space-between; }
  header h1 { margin: 0; font-size: 20px; }
  /* dipe-logo: λογότυπο αριστερά από τον τίτλο */
  header h1 { display: flex; align-items: center; gap: 12px; }
  header h1::before { content: ""; flex: none; width: 38px; height: 38px;
    background: url(data:image/png;base64,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) center / contain no-repeat; }
  .header-actions { display: flex; align-items: center; gap: 6px; }
  .header-actions button { margin: 0; }
  #theme_toggle { background: transparent; border: 1px solid rgba(255,255,255,0.3); color: inherit;
    font-size: 16px; padding: 6px 12px; margin: 0; }
  #theme_toggle:hover { background: rgba(255,255,255,0.1); }
  .tabs { display: flex; background: var(--tabs-bg); padding: 0 8px; }
  .tab { padding: 12px 18px; color: var(--tab-fg); cursor: pointer; user-select: none;
    background: transparent; border: none; font: inherit;
    border-radius: 8px 8px 0 0; transition: background 0.15s, color 0.15s; }
  .tab:hover { background: var(--tab-hover-bg); color: var(--header-fg); }
  .tab.active { background: var(--bg); color: var(--fg); font-weight: bold; }
  /* Καρφωμένο (sticky) το πάνω τμήμα: header + μπάρα tabs μένουν ορατά στο scroll (το --hdr-h το ορίζει το κοινό JS) */
  body > header { position: sticky; top: 0; z-index: 100; }
  body > .tabs { position: sticky; top: var(--hdr-h, 0px); z-index: 100; }
  .panel { display: none; padding: 22px; max-width: 1100px; margin: 0 auto; }
  .panel.active { display: block; }
  fieldset { border: 1px solid var(--fieldset-border); border-radius: 12px; margin-bottom: 16px;
    padding: 14px 16px; background: var(--fieldset-bg); box-shadow: 0 1px 3px var(--shadow); }
  legend { font-weight: bold; padding: 0 8px; color: var(--legend-fg); }
  label { display: inline-block; min-width: 220px; }
  input:not([type=checkbox]), select, textarea {
    width: 320px; padding: 7px 10px; margin: 3px 0; border: 1px solid var(--input-border);
    background: var(--input-bg); color: var(--input-fg);
    border-radius: 8px; font-family: inherit; font-size: 14px; transition: border-color 0.15s; }
  input:not([type=checkbox]):focus, select:focus, textarea:focus {
    outline: none; border-color: var(--accent); }
  textarea { width: 100%; height: 140px; font-family: monospace; border-radius: 8px; }
  input[type=checkbox] { width: 20px; height: 20px; vertical-align: middle; cursor: pointer;
    accent-color: var(--accent); }
  /* !important: κανένα per-panel `label { min-width }` override (π.χ. #panel-settings label) δεν πρέπει
     ποτέ να τεντώνει το switch — έχει πάντα σταθερό μέγεθος 34x18. */
  .switch { position: relative; display: inline-block; width: 34px !important; min-width: 34px !important;
    max-width: 34px !important; height: 18px; vertical-align: middle; flex: 0 0 34px; }
  .switch input[type=checkbox] { opacity: 0; width: 0; height: 0; position: absolute; }
  .switch .slider { position: absolute; inset: 0; background: var(--btn-border); transition: background 0.2s;
    border-radius: 999px; cursor: pointer; }
  .switch .slider::before { content: ""; position: absolute; height: 14px; width: 14px; left: 2px; bottom: 2px;
    background: #fff; transition: transform 0.2s; border-radius: 50%; box-shadow: 0 1px 3px rgba(0,0,0,0.3); }
  .switch input[type=checkbox]:checked + .slider { background: var(--accent); }
  .switch input[type=checkbox]:checked + .slider::before { transform: translateX(16px); }
  .switch input[type=checkbox]:disabled + .slider { opacity: 0.5; cursor: default; }
  .switch input[type=checkbox]:focus-visible + .slider { outline: 2px solid var(--accent); outline-offset: 2px; }
  button { padding: 8px 16px; margin: 4px 4px 4px 0; cursor: pointer; border: 1px solid var(--btn-border);
    border-radius: 8px; background: var(--btn-bg); color: var(--btn-fg); font-size: 14px;
    transition: background 0.15s, transform 0.05s; }
  /* στυλ κουμπιών όπως dipe.zak.sch.gr: outline (.btn-outline) και γεμάτο navy (.btn) */
  button { background: transparent; color: var(--obtn-fg); border-color: var(--obtn-fg); font-weight: 600; }
  button:hover { background: var(--pbtn-bg); color: #fff; border-color: var(--pbtn-hover); }
  button:active { transform: scale(0.97); }
  button:disabled { opacity: 0.6; cursor: default; transform: none; }
  button.primary { background: var(--pbtn-bg); color: #fff; border-color: var(--pbtn-bg); }
  button.primary:hover { background: var(--pbtn-hover); border-color: var(--pbtn-hover); }
  header button { background: transparent; color: #fff; border-color: rgba(255,255,255,0.55); }
  header button:hover { background: #fff; color: #223A66; border-color: #fff; }
  header button.primary { background: #285a9f; border-color: #285a9f; }
  header button.primary:hover { background: #3470b8; color: #fff; border-color: #3470b8; }
  header button.success, header button.danger { color: #fff; }
  button.success { background: #27ae60; color: #fff; border-color: #27ae60; }
  button.success:hover { background: #229954; }
  button.danger { background: #c0392b; color: #fff; border-color: #c0392b; }
  button.danger:hover { background: #a93226; }
  table { border-collapse: separate; border-spacing: 0; width: 100%; margin-top: 8px;
    border: 1px solid var(--table-border); border-radius: 10px; overflow: hidden; }
  th, td { border-bottom: 1px solid var(--table-cell-border); padding: 7px 10px; font-size: 13px;
    text-align: left; }
  th { background: var(--table-head-bg); }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: var(--table-row-hover); }
  #log, .log-box { background: var(--log-bg); color: var(--log-fg); font-family: monospace; font-size: 12px;
    height: 220px; overflow-y: auto; padding: 10px; white-space: pre-wrap; border-radius: 10px; }
  .warn { color: #f1c40f; } .error { color: #e74c3c; } .debug { color: #7f8c8d; }
  progress { width: 100%; height: 1.8em; border-radius: 999px; overflow: hidden; border: none; }
  progress::-webkit-progress-bar { background: var(--btn-hover-bg); border-radius: 999px; }
  progress::-webkit-progress-value { background: var(--accent); border-radius: 999px; transition: width 0.2s; }
  progress::-moz-progress-bar { background: var(--accent); border-radius: 999px; }
  .row { margin: 8px 0; }
  hr { border: none; border-top: 1px solid var(--fieldset-border); margin: 14px 0; }
  .hint { color: var(--hint-fg); font-size: 12px; }
  .rte-toolbar { margin: 4px 0 6px; }
  .rte-btn { padding: 5px 11px; margin-right: 4px; cursor: pointer; border: 1px solid var(--btn-border);
    border-radius: 8px; background: var(--btn-bg); color: var(--btn-fg); font-size: 13px; }
  .rte-btn:hover { background: var(--btn-hover-bg); }
  .rte-editor { border: 1px solid var(--input-border); border-radius: 8px; min-height: 140px;
    max-height: 400px; padding: 10px; background: var(--input-bg); color: var(--input-fg);
    overflow-y: auto; margin-bottom: 8px; }
  .rte-editor:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(34,58,102,0.18); }
  .rte-editor img { max-width: 100%; }
  .chip-btn { padding: 3px 10px; margin: 2px 4px 2px 0; border-radius: 999px; border: 1px solid var(--btn-border);
    background: var(--btn-bg); color: var(--btn-fg); cursor: pointer; font-size: 12px; font-family: monospace; }
  .chip-btn:hover { background: var(--accent); color: #fff; border-color: var(--accent); }
  .modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex;
    align-items: center; justify-content: center; z-index: 1000; }
  .modal-box { background: var(--fieldset-bg); color: var(--fg); border-radius: 12px; padding: 22px;
    max-width: 480px; width: 90%; box-shadow: 0 8px 30px rgba(0,0,0,0.3); }
  .modal-box h3 { margin-top: 0; }
  .restart-progress { width: 260px; height: 6px; border-radius: 999px; overflow: hidden;
    background: var(--btn-hover-bg); margin: 20px auto 0; }
  .restart-progress-fill { width: 40%; height: 100%; background: var(--accent); border-radius: 999px;
    animation: restart-bar-slide 1.1s infinite ease-in-out; }
  @keyframes restart-bar-slide { 0% { margin-left: -40%; } 100% { margin-left: 100%; } }
  .scroll-top-btn { position: fixed; right: 22px; bottom: 22px; width: 42px; height: 42px; border-radius: 50%;
    background: var(--accent); color: #fff; border: none; font-size: 20px; line-height: 1; cursor: pointer;
    box-shadow: 0 2px 10px rgba(0,0,0,0.35); display: none; align-items: center; justify-content: center; z-index: 500; }
  .scroll-top-btn.visible { display: flex; }
  .scroll-top-btn:hover { filter: brightness(1.1); }
"""

THEME_TOGGLE_BUTTON_HTML = (
    '<button id="theme_toggle" onclick="toggleTheme()" '
    'title="Εναλλαγή σκούρου/ανοιχτού θέματος">🌙</button>'
)


def render_head(theme_key: str) -> str:
    """Ό,τι πρέπει να μπει στο <head> ΠΡΙΝ αποδοθεί το body: το viewport meta
    tag (χωρίς αυτό, τα κινητά «προσποιούνται» πλάτος οθόνης ~980px και τα
    media queries δεν ενεργοποιούνται ΠΟΤΕ, ανεξάρτητα από το πραγματικό
    μέγεθος της οθόνης) + το inline <script> που θέτει data-theme νωρίς
    (ώστε να μην τρεμοπαίξει λάθος θέμα). theme_key: μοναδικό localStorage
    key ανά app (π.χ. 'email-sender-theme')."""
    return f"""<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" type="image/png" sizes="32x32" href="data:image/png;base64,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">
<script>
  (function () {{
    const saved = localStorage.getItem('{theme_key}');
    const theme = saved || (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    document.documentElement.setAttribute('data-theme', theme);
  }})();
</script>"""


def render_common_js(theme_key: str, unload_warning_message: str = 'Υπάρχει ενεργή εργασία σε εξέλιξη. Σίγουρα θέλετε να φύγετε;',
                     shutdown_on_close: bool = True) -> str:
    """Το κοινό JS (χωρίς τα <script> tags — βάλε το μέσα στο δικό σου
    <script> block, πριν το app-specific JS σου, αφού το δικό σου JS
    πιθανώς καλεί api()/withLoading()/showConfirmModal()/browsePath()/
    makeRichEditor() που ορίζονται εδώ).

    shutdown_on_close: True (default) για apps όπου «έκλεισα το tab» σημαίνει
    «τελείωσα με αυτό» — τερματίζει τον server στο pagehide (με debounce ώστε
    ένα απλό F5 να ΜΗΝ το σκοτώνει, βλ. register_common_routes). Βάλε False
    για κόμβους σαν το κεντρικό dashboard, όπου ο χρήστης μπορεί να έχει
    πολλά tabs ανοιχτά και δεν πρέπει ΠΟΤΕ ένα refresh (ή απλό κλείσιμο ενός
    tab) να τερματίσει τον κοινό server."""
    return f"""
function api(endpoint, body) {{
  return fetch('api/' + endpoint, {{
    method: body === undefined ? 'GET' : 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: body === undefined ? undefined : JSON.stringify(body),
  }}).then(r => r.json());
}}

// Δείχνει ⏳ + απενεργοποιεί το κουμπί όσο εκκρεμεί το promise, επαναφέρει μετά.
function withLoading(btn, promise) {{
  if (!btn) return promise;
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = '⏳ ' + original;
  return promise.finally(() => {{ btn.disabled = false; btn.textContent = original; }});
}}

// Δικά μας παράθυρα μηνυμάτων αντί για τα native του browser (που γράφουν
// «localhost:50xx says»). Το alert() αντικαθίσταται καθολικά (μη μπλοκάρον)·
// για επιβεβαίωση χρησιμοποίησε: if (!await dashConfirm('...')) return;
function _dashDialog(message, withCancel) {{
  return new Promise(resolve => {{
    const ov = document.createElement('div');
    ov.className = 'modal-overlay';
    ov.style.zIndex = 2000;
    const box = document.createElement('div');
    box.className = 'modal-box';
    const h = document.createElement('h3');
    h.textContent = 'Dashboard ΔΙΠΕ';
    const p = document.createElement('div');
    p.style.whiteSpace = 'pre-wrap';
    p.style.margin = '10px 0 16px';
    p.textContent = String(message === undefined ? '' : message);
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;gap:8px;justify-content:flex-end';
    const done = (v) => {{ document.removeEventListener('keydown', onKey, true); ov.remove(); resolve(v); }};
    const ok = document.createElement('button');
    ok.type = 'button'; ok.textContent = 'OK'; ok.onclick = () => done(true);
    if (withCancel) {{
      const cancel = document.createElement('button');
      cancel.type = 'button'; cancel.textContent = 'Άκυρο'; cancel.onclick = () => done(false);
      row.appendChild(cancel);
    }}
    row.appendChild(ok);
    box.append(h, p, row);
    ov.appendChild(box);
    const onKey = (e) => {{
      if (e.key === 'Escape') {{ e.preventDefault(); done(!withCancel); }}
      else if (e.key === 'Enter') {{ e.preventDefault(); done(true); }}
    }};
    document.addEventListener('keydown', onKey, true);
    document.body.appendChild(ov);
    ok.focus();
  }});
}}
window.alert = function (message) {{ _dashDialog(message, false); }};
function dashConfirm(message) {{ return _dashDialog(message, true); }}

// Γενικό βοήθημα αντιγραφής κειμένου (π.χ. το περιεχόμενο ενός log panel) στο πρόχειρο —
// navigator.clipboard χρειάζεται secure context (https ή localhost)· fallback σε
// document.execCommand('copy') για http/embedded contexts όπου δεν είναι διαθέσιμο.
function copyTextToClipboard(text, btn) {{
  const done = (ok) => {{
    if (!btn) return;
    const original = btn.dataset.origLabel || btn.textContent;
    btn.dataset.origLabel = original;
    btn.textContent = ok ? '✓ Αντιγράφηκε' : '✗ Αποτυχία αντιγραφής';
    setTimeout(() => {{ btn.textContent = original; }}, 1500);
  }};
  if (navigator.clipboard && navigator.clipboard.writeText) {{
    navigator.clipboard.writeText(text).then(() => done(true), () => done(false));
    return;
  }}
  try {{
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    done(ok);
  }} catch (e) {{
    done(false);
  }}
}}

function showConfirmModal(title, bodyHtml, confirmLabel, onConfirm) {{
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `<div class="modal-box">
    <h3>${{title}}</h3>
    <div>${{bodyHtml}}</div>
    <div class="row" style="text-align:right;margin-top:16px">
      <button type="button" id="modal_cancel">Άκυρο</button>
      <button type="button" class="danger" id="modal_confirm">${{confirmLabel}}</button>
    </div>
  </div>`;
  document.body.appendChild(overlay);
  const close = () => overlay.remove();
  overlay.querySelector('#modal_cancel').onclick = close;
  overlay.querySelector('#modal_confirm').onclick = () => {{ close(); onConfirm(); }};
  overlay.addEventListener('click', (e) => {{ if (e.target === overlay) close(); }});
}}

function updateThemeToggleIcon() {{
  const theme = document.documentElement.getAttribute('data-theme') || 'light';
  const el = document.getElementById('theme_toggle');
  if (el) el.textContent = theme === 'dark' ? '☀️' : '🌙';
}}
function toggleTheme() {{
  const current = document.documentElement.getAttribute('data-theme') || 'light';
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('{theme_key}', next);
  updateThemeToggleIcon();
}}

// Ανοίγει native Windows file/folder picker (μόνο standalone mode — βλ. /api/browse)
// και γεμίζει το πεδίο inputId με το επιλεγμένο path.
function browsePath(inputId, type, filter, onSet) {{
  let url = 'api/browse?type=' + type;
  if (filter) url += '&filter=' + filter;
  fetch(url).then(r => r.json()).then(r => {{
    if (r.error) {{ alert('Το Browse δεν είναι διαθέσιμο: ' + r.error); return; }}
    if (r.path) {{
      document.getElementById(inputId).value = r.path;
      if (onSet) onSet();
    }}
  }});
}}

function editFile(inputId) {{
  const el = document.getElementById(inputId);
  const path = el ? el.value : '';
  if (!path) {{ alert('Δεν έχει οριστεί διαδρομή αρχείου'); return; }}
  api('edit-file', {{file: path}}).then(r => {{
    if (!r.ok) alert('Σφάλμα ανοίγματος: ' + (r.error || ''));
  }});
}}

// Ανοίγει τη διεύθυνση URL που περιέχει το πεδίο inputId στον προεπιλεγμένο
// browser των Windows (server-side webbrowser.open — όχι window.open, ώστε
// να ανοίγει πάντα τον πραγματικό default browser ακόμα κι όταν το GUI
// τρέχει μέσα σε embedded webview και όχι σε κανονικό browser tab).
function openUrl(inputId) {{
  const el = document.getElementById(inputId);
  const url = el ? el.value.trim() : '';
  if (!url) {{ alert('Δεν έχει οριστεί διεύθυνση URL'); return; }}
  api('open-url', {{url: url}}).then(r => {{
    if (!r.ok) alert('Σφάλμα ανοίγματος: ' + (r.error || ''));
  }});
}}

// --- Rich text editor (contenteditable, χωρίς CDN/internet) ---
// Αντικαθιστά οπτικά ένα textarea με toolbar + contenteditable div. Το ίδιο
// το textarea παραμένει στο DOM (κρυφό) ως πηγή αλήθειας — val()/.value
// συνεχίζουν να δουλεύουν αναλλοίωτα σε όλο τον υπόλοιπο κώδικα. Όποτε
// κάποια function κάνει textarea.value = ... απευθείας (π.χ. load από
// template/προφίλ/αρχείο), κάλεσε syncRichEditor(id) αμέσως μετά.
function makeRichEditor(textareaId) {{
  const ta = document.getElementById(textareaId);
  if (!ta || ta.dataset.richInit) return;
  ta.dataset.richInit = '1';
  ta.style.display = 'none';

  const toolbar = document.createElement('div');
  toolbar.className = 'rte-toolbar';
  const editor = document.createElement('div');
  editor.className = 'rte-editor';
  editor.contentEditable = 'true';
  editor.innerHTML = ta.value || '';

  function sync() {{ ta.value = editor.innerHTML; }}
  function exec(cmd, value) {{ editor.focus(); document.execCommand(cmd, false, value || null); sync(); }}

  function addBtn(label, onClick) {{
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'rte-btn';
    btn.innerHTML = label;
    btn.onclick = (e) => {{ e.preventDefault(); onClick(); }};
    toolbar.appendChild(btn);
  }}
  addBtn('<b>B</b>', () => exec('bold'));
  addBtn('<i>I</i>', () => exec('italic'));
  addBtn('<u>U</u>', () => exec('underline'));
  addBtn('• Λίστα', () => exec('insertUnorderedList'));
  addBtn('🔗 Link', () => {{ const url = prompt('Διεύθυνση URL:'); if (url) exec('createLink', url); }});
  addBtn('🖼 Εικόνα', () => {{
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.onchange = () => {{
      const file = input.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => exec('insertImage', reader.result);
      reader.readAsDataURL(file);
    }};
    input.click();
  }});
  addBtn('✕ Καθαρισμός', () => {{ dashConfirm('Καθαρισμός περιεχομένου;').then(ok => {{ if (ok) {{ editor.innerHTML = ''; sync(); }} }}); }});

  editor.addEventListener('input', sync);
  editor.addEventListener('blur', sync);

  ta.parentNode.insertBefore(toolbar, ta);
  ta.parentNode.insertBefore(editor, ta);
  ta._rteSync = () => {{ editor.innerHTML = ta.value || ''; }};
}}
function syncRichEditor(textareaId) {{
  const ta = document.getElementById(textareaId);
  if (ta && ta._rteSync) ta._rteSync();
}}

// Αν υπάρχει global μεταβλητή JOB_ACTIVE=true (ενεργό background job — κάθε
// app ορίζει/ενημερώνει αυτή τη μεταβλητή μόνο του, π.χ. στο polling του),
// προειδοποίηση πριν το κλείσιμο tab· ο browser δείχνει το δικό του native
// dialog (custom μήνυμα αγνοείται από σύγχρονους browsers).
window.addEventListener('beforeunload', (e) => {{
  if (typeof JOB_ACTIVE !== 'undefined' && JOB_ACTIVE) {{
    e.preventDefault();
    e.returnValue = '{unload_warning_message}';
  }}
}});

// Ύψος του καρφωμένου header → CSS μεταβλητή --hdr-h, ώστε η μπάρα tabs να κολλάει ακριβώς κάτω του.
(function initStickyTop() {{
  const set = () => {{
    const h = document.querySelector('body > header');
    if (h) document.documentElement.style.setProperty('--hdr-h', h.offsetHeight + 'px');
  }};
  window.addEventListener('load', () => {{
    set();
    const h = document.querySelector('body > header');
    if (h && window.ResizeObserver) new ResizeObserver(set).observe(h);
  }});
  window.addEventListener('resize', set);
}})();

// Κουμπί «μετάβαση στην κορυφή» — αυτοδημιουργείται εδώ ώστε κάθε app να το
// παίρνει έτοιμο απλώς αντιγράφοντας αυτό το module, χωρίς δικό του HTML/CSS/JS.
(function initScrollTopButton() {{
  window.addEventListener('load', () => {{
    if (document.getElementById('scroll_top_btn') || document.querySelector('.scroll-top-btn')) return;
  const btn = document.createElement('button');
  btn.className = 'scroll-top-btn';
  btn.type = 'button';
  btn.title = 'Μετάβαση στην κορυφή';
  btn.setAttribute('aria-label', 'Μετάβαση στην κορυφή');
  btn.textContent = '↑';
  btn.onclick = () => window.scrollTo({{top: 0, behavior: 'smooth'}});
  document.body.appendChild(btn);
  window.addEventListener('scroll', () => {{
    btn.classList.toggle('visible', window.scrollY > 300);
  }}, {{passive: true}});
  }});
}})();

{f'''// Standalone mode μόνο: όταν κλείνει πραγματικά το tab, ζητάμε από τον
// server να τερματίσει. Σε embedded mode το endpoint δεν υπάρχει στο
// routing του parent, οπότε το beacon απλά αποτυγχάνει αθόρυβα. Αν υπάρχει
// ενεργό job τη στιγμή του beacon, ο server ΔΕΝ σκοτώνεται απότομα (βλ.
// register_common_routes / graceful exit στο Python side).
window.addEventListener('pagehide', () => {{
  navigator.sendBeacon('api/shutdown');
}});
''' if shutdown_on_close else ''}"""


# ---------------------------------------------------------------------------
# Κοινά standalone-only routes: /api/browse, /api/edit-file, /api/shutdown
# ---------------------------------------------------------------------------

try:
    import schedule as _schedule_lib
except ImportError:
    _schedule_lib = None


class AppScheduler:
    """Προγραμματισμός (daily/weekly/workdays + ώρα) ΓΙΑ ΑΥΤΟ το app μέσω Windows Task Scheduler (εργασία «Dash_<app>»):
    τρέχει headless το main_script ακόμα κι όταν το app/dashboard είναι κλειστό. Persist σε apps/<app>/schedule.json.
    Η λογική δημιουργίας της εργασίας βρίσκεται στο dashboard_winsched.py της ρίζας του dashboard (δουλεύει από πηγαίο κώδικα)."""

    WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')

    def __init__(self, app_dir: Path):
        self.app_dir = app_dir
        self.schedule_file = app_dir / 'schedule.json'
        self.main_script = self._resolve_main_script()
        self._winsched = self._load_winsched()
        saved = self.get_schedule()
        if self._winsched is not None and saved.get('type', 'none') != 'none':
            threading.Thread(target=self._sync, args=(saved['type'], saved.get('time', '09:00'), saved.get('weekday', 'monday'), saved.get('days'), saved.get('date'), bool(saved.get('skip_holidays'))), daemon=True).start()

    def _load_winsched(self):
        try:
            import importlib.util
            p = Path(self.app_dir).resolve().parent.parent / 'dashboard_winsched.py'
            if not p.exists():
                return None
            spec = importlib.util.spec_from_file_location('dashboard_winsched', p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
        except Exception:
            return None

    def _resolve_main_script(self) -> Path | None:
        try:
            import json
            cfg = json.loads((self.app_dir / 'config.json').read_text(encoding='utf-8'))
            main_script = cfg.get('main_script')
            return (self.app_dir / main_script) if main_script else None
        except Exception:
            return None

    def get_schedule(self) -> dict:
        if self.schedule_file.exists():
            try:
                import json
                return json.loads(self.schedule_file.read_text(encoding='utf-8'))
            except Exception:
                pass
        return {'type': 'none', 'time': '09:00', 'weekday': 'monday'}

    def _sync(self, schedule_type: str, time_str: str, weekday: str, days=None, date=None, skip_holidays=False) -> tuple:
        try:
            return self._winsched.sync_task(self.app_dir.name, self.app_dir, self.main_script, schedule_type, time_str, weekday,
                                            None, days, date, skip_holidays)
        except TypeError:   # παλιό dashboard_winsched.py χωρίς days/date/skip_holidays
            return self._winsched.sync_task(self.app_dir.name, self.app_dir, self.main_script, schedule_type, time_str, weekday)

    def set_schedule(self, schedule_type: str, time_str: str = '09:00', weekday: str = 'monday',
                     days=None, date=None, skip_holidays=None) -> tuple:
        if self._winsched is None:
            return False, 'Δεν βρέθηκε το dashboard_winsched.py (ο προγραμματισμός δουλεύει από πηγαίο κώδικα, μέσα στο φάκελο του dashboard).'
        if schedule_type not in ('none', 'daily', 'weekly', 'workdays', 'days', 'once'):
            return False, 'Άγνωστος τύπος προγραμματισμού.'
        days = [d for d in self.WEEKDAYS if d in (days or [])]
        if skip_holidays is None:
            skip_holidays = bool(self.get_schedule().get('skip_holidays'))
        ok, msg = self._sync(schedule_type, time_str, weekday, days, date, skip_holidays)
        if not ok:
            return False, msg
        try:
            import json
            self.schedule_file.write_text(
                json.dumps({'type': schedule_type, 'time': time_str, 'weekday': weekday,
                            **({'days': days} if schedule_type == 'days' else {}),
                            **({'date': date} if schedule_type == 'once' else {}),
                            **({'skip_holidays': True} if skip_holidays and schedule_type not in ('none', 'once') else {})},
                           ensure_ascii=False, indent=2),
                encoding='utf-8')
        except Exception:
            pass
        return True, msg


HEADER_ACTIONS_HTML = (
    '<div class="header-actions">'
    + THEME_TOGGLE_BUTTON_HTML +
    '<button id="schedule_btn" onclick="openScheduleModal()" title="Προγραμματισμός αυτόματης εκτέλεσης">🕒</button>'
    '<button id="restart_app_btn" class="success" onclick="confirmRestartApp()" style="display:none" '
    'title="Επανεκκίνηση της εφαρμογής και του dashboard">⟳</button>'
    '<button id="close_app_btn" class="danger" onclick="confirmCloseApp()" title="Κλείσιμο εφαρμογής">⏻</button>'
    '</div>'
)

SCHEDULING_JS = r'''
const SCHEDULE_TYPE_LABELS = {none: 'Χωρίς', daily: 'Καθημερινά', weekly: 'Εβδομαδιαία', workdays: 'Εργάσιμες', days: 'Συγκεκριμένες μέρες', once: 'Μία φορά'};
const SCHEDULE_WEEKDAY_LABELS = {monday:'Δευτέρα', tuesday:'Τρίτη', wednesday:'Τετάρτη', thursday:'Πέμπτη', friday:'Παρασκευή', saturday:'Σάββατο', sunday:'Κυριακή'};

function confirmCloseApp() {
  showConfirmModal('Κλείσιμο εφαρμογής', 'Σίγουρα θέλεις να κλείσεις αυτή την εφαρμογή;', 'Κλείσιμο', () => {
    api('shutdown', {}).then(() => {
      document.body.innerHTML = '<div style="padding:40px;text-align:center;font-size:18px">Η εφαρμογή έκλεισε. Μπορείς να κλείσεις αυτή την καρτέλα.</div>';
      // Δουλεύει μόνο σε tabs που ανοίχτηκαν από script (π.χ. από το tile
      // του κεντρικού dashboard) — σε tab που άνοιξε ο χρήστης ο ίδιος οι
      // browsers το αγνοούν σιωπηλά, γι' αυτό μένει και το μήνυμα ως fallback.
      setTimeout(() => window.close(), 300);
    });
  });
}

// Επανεκκίνηση: κλείνει η εφαρμογή (περιμένει τυχόν ενεργή εργασία), κάνει
// restart το dashboard και το ΝΕΟ dashboard ξανανοίγει την εφαρμογή. Το κουμπί
// φαίνεται μόνο όταν η σελίδα σερβίρεται μέσα από το dashboard (/<app_id>/).
const _DASH_APP_ID = location.pathname.split('/')[1] || '';
setTimeout(() => {
  if (!_DASH_APP_ID) return;
  fetch('/api/apps').then(r => r.ok ? r.json() : []).then(list => {
    if (Array.isArray(list) && list.some(a => a.id === _DASH_APP_ID)) {
      const b = document.getElementById('restart_app_btn');
      if (b) b.style.display = '';
    }
  }).catch(() => {});
}, 0);

function confirmRestartApp() {
  showConfirmModal('Επανεκκίνηση εφαρμογής',
    'Θα κλείσει η εφαρμογή, θα γίνει επανεκκίνηση του dashboard και θα ξανανοίξει η εφαρμογή. Οι άλλες ανοιχτές εφαρμογές θα χάσουν τη σύνδεσή τους. Αν τρέχει εργασία, θα περιμένει να τελειώσει. Σίγουρα;',
    'Επανεκκίνηση', () => {
    // Το pid του τρέχοντος dashboard πριν το restart: το reload γίνεται όταν απαντήσει
    // ΝΕΟ dashboard (άλλο pid) ΚΑΙ η εφαρμογή ξανατρέχει — δεν εξαρτάται από το να
    // προλάβουμε να δούμε το διάστημα που το dashboard είναι κάτω.
    const getPid = () => fetch('/api/dashboard-pid', {cache: 'no-store'}).then(r => r.json()).then(r => r.pid);
    getPid().catch(() => null).then(oldPid => fetch('/api/restart-app/' + encodeURIComponent(_DASH_APP_ID), {method: 'POST'})
      .then(r => r.json()).then(r => {
      if (!r.ok) { alert('Αποτυχία επανεκκίνησης: ' + (r.message || '')); return; }
      document.body.innerHTML = '<div style="padding:60px;text-align:center;font-size:18px">' +
        'Η εφαρμογή επανεκκινείται…</div>' +
        '<div class="restart-progress"><div class="restart-progress-fill"></div></div>' +
        '<div style="text-align:center;margin-top:10px" class="hint">Αν τρέχει εργασία, περιμένει να τελειώσει. Η σελίδα θα φορτώσει ξανά αυτόματα.</div>';
      const tmo = (ms) => { const c = new AbortController(); setTimeout(() => c.abort(), ms); return c.signal; };
      const poll = async () => {
        try {
          const pid = await fetch('/api/dashboard-pid', {cache: 'no-store', signal: tmo(3000)}).then(x => x.json()).then(x => x.pid);
          if (pid !== oldPid) {
            const resp = await fetch(location.pathname, {cache: 'no-store', signal: tmo(5000)});
            if (resp.ok) { location.reload(); return; }
          }
        } catch (e) { /* το dashboard είναι ακόμα κάτω */ }
        setTimeout(poll, 1000);
      };
      setTimeout(poll, 2000);
    })).catch(e => alert('Αποτυχία επανεκκίνησης: ' + e));
  });
}

function openScheduleModal() {
  api('schedule').then(sched => {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    const typeOptions = Object.keys(SCHEDULE_TYPE_LABELS).map(s =>
      `<option value="${s}" ${sched.type === s ? 'selected' : ''}>${SCHEDULE_TYPE_LABELS[s]}</option>`).join('');
    const dayOptions = Object.keys(SCHEDULE_WEEKDAY_LABELS).map(d =>
      `<option value="${d}" ${sched.weekday === d ? 'selected' : ''}>${SCHEDULE_WEEKDAY_LABELS[d]}</option>`).join('');
    overlay.innerHTML = `<div class="modal-box">
      <h3>🕒 Προγραμματισμός</h3>
      <div class="row"><label>Τύπος</label><select id="sm_type" onchange="_smUpdateVisibility()">${typeOptions}</select></div>
      <div class="row" id="sm_day_row"><label>Ημέρα</label><select id="sm_day">${dayOptions}</select></div>
      <div class="row" id="sm_days_row"><label>Μέρες</label><span>${Object.keys(SCHEDULE_WEEKDAY_LABELS).map(d =>
        `<label style="display:inline-flex;align-items:center;gap:3px;margin-right:8px;min-width:0"><input type="checkbox" class="sm_dayck" value="${d}" ${(sched.days || []).includes(d) ? 'checked' : ''} style="width:auto"> ${SCHEDULE_WEEKDAY_LABELS[d].slice(0, 3)}</label>`).join('')}</span></div>
      <div class="row" id="sm_date_row"><label>Ημερομηνία</label><input type="date" id="sm_date" value="${sched.date || ''}" style="width:160px"></div>
      <div class="row"><label>Ώρα</label><input type="time" id="sm_time" value="${sched.time || '09:00'}"></div>
      <div class="row" id="sm_hol_row"><label>Αργίες</label><label class="switch"><input type="checkbox" id="sm_skip_hol" ${sched.skip_holidays ? 'checked' : ''}><span class="slider"></span></label><span style="margin-left:8px;font-size:12px" title="Αν η μέρα είναι επίσημη αργία (Πάσχα, 25η Μαρτίου, 28η Οκτωβρίου κ.λπ.) το app δεν τρέχει και η εκτέλεση παραλείπεται.">Να μην τρέχει τις αργίες</span></div>
      <div class="row" style="text-align:right;margin-top:16px">
        <span id="sm_result" class="hint"></span>
        <button type="button" id="sm_cancel">Κλείσιμο</button>
        <button type="button" class="primary" onclick="_smSave()">Αποθήκευση</button>
      </div>
    </div>`;
    document.body.appendChild(overlay);
    overlay.querySelector('#sm_cancel').onclick = () => overlay.remove();
    overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
    window._smOverlay = overlay;
    _smUpdateVisibility();
  });
}
function _smUpdateVisibility() {
  // disabled (όχι display:none στη γραμμή) — το πεδίο Ημέρα μένει πάντα
  // ορατό, γκριζαρισμένο όταν δεν εφαρμόζεται, ώστε να μη μοιάζει σαν να
  // λείπει τελείως.
  const type = document.getElementById('sm_type').value;
  document.getElementById('sm_day').disabled = (type !== 'weekly');
  document.getElementById('sm_days_row').style.display = (type === 'days') ? '' : 'none';
  document.getElementById('sm_date_row').style.display = (type === 'once') ? '' : 'none';
  document.getElementById('sm_hol_row').style.display = (type === 'none' || type === 'once') ? 'none' : '';
  if (type === 'once' && !document.getElementById('sm_date').value) {
    const d = new Date(Date.now() + 86400000), p = n => String(n).padStart(2, '0');
    document.getElementById('sm_date').value = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  }
}
function _smSave() {
  const body = {
    type: document.getElementById('sm_type').value,
    time: document.getElementById('sm_time').value || '09:00',
    weekday: document.getElementById('sm_day').value,
    days: [...document.querySelectorAll('.sm_dayck:checked')].map(e => e.value),
    date: (document.getElementById('sm_date') || {}).value || '',
    skip_holidays: document.getElementById('sm_skip_hol').checked,
  };
  if (body.type === 'days' && !body.days.length) { document.getElementById('sm_result').textContent = 'Διάλεξε τουλάχιστον μία ημέρα.'; return; }
  api('schedule', body).then(r => {
    document.getElementById('sm_result').textContent = r.message || '';
    if (r.ok) setTimeout(() => { if (window._smOverlay) window._smOverlay.remove(); }, 1200);
  });
}
'''


def register_common_routes(flask_app, app_dir: Path, any_job_active=None,
                           shutdown_grace_seconds: float = 1.5,
                           max_graceful_wait_seconds: int = 3600) -> None:
    """Καταχωρεί /api/browse, /api/edit-file, /api/shutdown απευθείας στο
    flask_app (standalone-only — ΔΕΝ πρέπει να περνούν από τυχόν
    _API_HANDLERS/handle_api_request dict που χρησιμοποιείς για legacy
    dashboard.py in-process proxy compatibility, αφού ένα blocking tkinter
    dialog ή ένα shutdown εκεί θα πάγωνε/σκότωνε κοινόχρηστο server).

    any_job_active: προαιρετική callable() -> bool· αν επιστρέφει True τη
    στιγμή του shutdown, ο server περιμένει να τελειώσει το job (μέχρι
    max_graceful_wait_seconds) αντί να τερματίσει απότομα."""
    any_job_active = any_job_active or (lambda: False)
    state = {'shutdown_timer': None}
    lock = threading.Lock()
    scheduler = AppScheduler(app_dir)

    @flask_app.route('/api/schedule', methods=['GET', 'POST'])
    def _schedule():
        if request.method == 'GET':
            return jsonify(scheduler.get_schedule())
        body = request.get_json(force=True, silent=True) or {}
        ok, message = scheduler.set_schedule(
            body.get('type', 'none'), body.get('time', '09:00'), body.get('weekday', 'monday'),
            body.get('days'), body.get('date'), body.get('skip_holidays'))
        return jsonify({'ok': ok, 'message': message})

    @flask_app.before_request
    def _cancel_pending_shutdown():
        if request.path == '/api/shutdown':
            return
        with lock:
            if state.get('final'):
                return  # οριστικό κλείσιμο (restart από το dashboard) — δεν ακυρώνεται
            if state['shutdown_timer'] is not None:
                state['shutdown_timer'].cancel()
                state['shutdown_timer'] = None

    def _graceful_exit():
        waited = 0
        while any_job_active() and waited < max_graceful_wait_seconds:
            time.sleep(1)
            waited += 1
        os._exit(0)

    def _do_shutdown():
        if any_job_active():
            _graceful_exit()
        else:
            os._exit(0)

    @flask_app.route('/api/shutdown', methods=['POST'])
    def _shutdown():
        body = request.get_json(force=True, silent=True) or {}
        with lock:
            if body.get('final'):
                state['final'] = True
            if state['shutdown_timer'] is not None:
                state['shutdown_timer'].cancel()
            timer = threading.Timer(shutdown_grace_seconds, _do_shutdown)
            timer.daemon = True
            state['shutdown_timer'] = timer
            timer.start()
        return jsonify({'ok': True})

    @flask_app.route('/api/browse')
    def _browse():
        browse_type = request.args.get('type', 'file')
        browse_filter = request.args.get('filter', '')
        filetypes_by_key = {
            'excel': [('Excel/CSV αρχεία', '*.xlsx *.xlsm *.xls *.csv'), ('Όλα τα αρχεία', '*.*')],
            'pdf':   [('Αρχεία PDF', '*.pdf'), ('Όλα τα αρχεία', '*.*')],
            'json':  [('Αρχεία JSON', '*.json'), ('Όλα τα αρχεία', '*.*')],
            'image': [('Εικόνες', '*.png *.jpg *.jpeg *.gif *.bmp'), ('Όλα τα αρχεία', '*.*')],
        }
        filetypes = filetypes_by_key.get(browse_filter, [('Όλα τα αρχεία', '*.*')])
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.wm_attributes('-topmost', True)
            if browse_type == 'folder':
                path = filedialog.askdirectory(parent=root)
            elif browse_type == 'savefile':
                path = filedialog.asksaveasfilename(parent=root, filetypes=filetypes, confirmoverwrite=False)
            else:
                path = filedialog.askopenfilename(parent=root, filetypes=filetypes)
            root.destroy()
            return jsonify({'path': path or ''})
        except Exception as e:
            return jsonify({'path': '', 'error': str(e)})

    @flask_app.route('/api/edit-file', methods=['POST'])
    def _edit_file():
        body = request.get_json(force=True, silent=True) or {}
        file_path = (body.get('file') or '').strip()
        if not file_path:
            return jsonify({'ok': False, 'error': 'Δεν έχει οριστεί διαδρομή αρχείου'}), 400
        p = Path(file_path)
        if not p.is_absolute():
            p = app_dir / p
        try:
            if not p.exists():
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text('', encoding='utf-8')
            os.startfile(str(p))
            return jsonify({'ok': True})
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)})

    @flask_app.route('/api/open-url', methods=['POST'])
    def _open_url():
        body = request.get_json(force=True, silent=True) or {}
        url = (body.get('url') or '').strip()
        if not url:
            return jsonify({'ok': False, 'error': 'Δεν έχει οριστεί διεύθυνση URL'}), 400
        if not re.match(r'^https?://', url, re.IGNORECASE):
            url = 'https://' + url
        try:
            import webbrowser
            webbrowser.open(url)
            return jsonify({'ok': True})
        except Exception as e:
            return jsonify({'ok': False, 'error': str(e)})

    @flask_app.route('/api/help-info')
    def _help_info():
        return jsonify(get_help_info(app_dir))

    @flask_app.route('/api/check-update')
    def _check_update():
        return jsonify(check_for_update(app_dir))

    @flask_app.route('/api/apply-update', methods=['POST'])
    def _apply_update():
        return jsonify(apply_update(app_dir))

    @flask_app.route('/api/local-versions')
    def _local_versions():
        return jsonify({'ok': True, 'versions': list_local_versions_for_rollback()})

    @flask_app.route('/api/rollback-version', methods=['POST'])
    def _rollback_version():
        body = request.get_json(force=True, silent=True) or {}
        version = (body.get('version') or '').strip()
        if not version:
            return jsonify({'ok': False, 'message': 'Δεν ορίστηκε έκδοση'}), 400
        return jsonify(rollback_to_version(app_dir, version))


# ---------------------------------------------------------------------------
# Tab "Βοήθεια" — README, copyright (μη επεξεργάσιμο από το app), έκδοση +
# έλεγχος ενημέρωσης. Κοινό σε όλα τα apps, ώστε να μην μπορεί κάθε app να
# ορίσει το δικό του copyright.
# ---------------------------------------------------------------------------

def _dashboard_root(app_dir: Path) -> Path:
    """apps/<app>/ -> dashboard root (δύο φακέλους πάνω), ίδια σύμβαση με το
    .env lookup του κάθε core.py (APP_DIR / '..' / '..')."""
    return (app_dir / '..' / '..').resolve()


def resolve_settings_env_file(app_dir: Path) -> Path:
    """Πού αποθηκεύεται το 'Αποθήκευση στο .env' κουμπί κάθε Ρυθμίσεις tab.
    Σε packaged exe (sys.frozen — υπολογιστής παραλήπτη) ΠΑΝΤΑ το τοπικό
    config.env δίπλα στο exe (δημιουργείται αν δεν υπάρχει ακόμα — πρώτη
    ρύθμιση από τον παραλήπτη). Σε dev mode (τρέξιμο από πηγαίο κώδικα μέσα
    στο dashboard) το ήδη υπάρχον app .env ή, αν δεν υπάρχει, το κοινό
    dashboard root .env — ίδια συμπεριφορά με πριν."""
    import sys
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent / 'config.env'
    candidates = [app_dir / '.env', (app_dir / '..' / '..' / '.env').resolve()]
    existing = next((p for p in candidates if p.exists()), None)
    return existing or candidates[-1]


def find_copyright_html(app_dir: Path) -> str:
    """Διαβάζει το copyright.html — ΠΑΝΤΑ από κεντρικό σημείο, ποτέ από το ίδιο
    το app folder, ώστε να μην μπορεί να αλλαχτεί ανά-app. Σειρά αναζήτησης:
    1) bundled resource μέσα σε packaged exe (PyInstaller, sys._MEIPASS) — για
       όταν το app τρέχει ως standalone exe σε υπολογιστή παραλήπτη.
    2) dashboard root (τρέχουσα λειτουργία, μέσα από τον ίδιο υπολογιστή)."""
    import sys
    candidates = []
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        candidates.append(Path(meipass) / 'copyright.html')
    candidates.append(_dashboard_root(app_dir) / 'copyright.html')
    for p in candidates:
        try:
            if p.exists():
                return p.read_text(encoding='utf-8')
        except Exception:
            pass
    return '<p class="hint">(Δεν βρέθηκε αρχείο copyright.html)</p>'


def app_display_name(app_dir: Path) -> str:
    """Το όνομα του app όπως εμφανίζεται στο tile του κεντρικού dashboard
    (config.json 'name') — διαβάζεται εδώ ώστε ο τίτλος (header <h1>) του
    ίδιου του app να είναι ΠΑΝΤΑ ίδιος με το tile, χωρίς να χρειάζεται να
    ενημερώνονται δύο σημεία χωριστά όταν αλλάζει το όνομα."""
    try:
        import json
        data = json.loads((app_dir / 'config.json').read_text(encoding='utf-8'))
        return data.get('name') or app_dir.name
    except Exception:
        return app_dir.name


def find_readme_path(app_dir: Path) -> Path | None:
    for name in ('README.md', 'README.txt', 'readme.md', 'readme.txt'):
        p = app_dir / name
        if p.exists():
            return p
    return None


def load_version_info(app_dir: Path) -> dict:
    """Διαβάζει version.json — σε packaged exe (sys._MEIPASS) ΠΡΩΤΑ από το
    bundled αντίγραφο (--add-data στο build_exe, ίδια λογική με το
    copyright.html), αλλιώς δεν θα ήξερε καν ο εαυτός του ποια έκδοση είναι.
    Σε dev mode διαβάζεται κανονικά από το app folder (εδώ ΕΠΙΤΡΕΠΕΤΑΙ να
    διαφέρει ανά app — το version.json ανεβαίνει χειροκίνητα από τον
    διαχειριστή μέσω του app-publisher, όχι κάτι που αλλάζει ο παραλήπτης)."""
    import sys
    candidates = []
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        candidates.append(Path(meipass) / 'version.json')
    candidates.append(app_dir / 'version.json')
    p = next((c for c in candidates if c.exists()), None)
    if p is None:
        return {'version': None, 'changelog': '', 'release_date': ''}
    try:
        import json
        data = json.loads(p.read_text(encoding='utf-8'))
        return {
            'version': data.get('version'),
            'changelog': data.get('changelog', ''),
            'release_date': data.get('release_date', ''),
        }
    except Exception:
        return {'version': None, 'changelog': '', 'release_date': ''}


def get_help_info(app_dir: Path) -> dict:
    info = load_version_info(app_dir)
    info['has_readme'] = find_readme_path(app_dir) is not None
    return info


try:
    import dashboard_update_common as _update
except ImportError:  # αντιγράφτηκε μόνο το gui_common χωρίς το update_common
    _update = None


def check_for_update(app_dir: Path) -> dict:
    """Πραγματικός έλεγχος μέσω Google Drive (δημόσιο link, ανώνυμο — βλ.
    dashboard_update_common.py). Graceful 'δεν έχει ρυθμιστεί' αν το app δεν
    έχει ανέβει ποτέ στο Drive (δεν υπάρχει distribution.json) ή αν αυτό το
    module δεν είναι διαθέσιμο."""
    if _update is None:
        return {'ok': True, 'configured': False,
                'message': 'Ο μηχανισμός ενημερώσεων δεν είναι διαθέσιμος σε αυτή την εγκατάσταση.'}
    current = load_version_info(app_dir).get('version') or '0.0.0'
    return _update.check_for_update(app_dir, current)


def apply_update(app_dir: Path) -> dict:
    """Κατεβάζει και εγκαθιστά τη νέα έκδοση (μόνο σε packaged exe — βλ.
    dashboard_update_common.apply_update). Η ίδια η διεργασία τερματίζει
    μέσα σε αυτή την κλήση αν όλα πάνε καλά (os._exit) — δεν επιστρέφει."""
    if _update is None or not _update.is_frozen():
        return {'ok': False, 'message': 'Η αυτόματη ενημέρωση λειτουργεί μόνο στην packaged έκδοση (.exe).'}
    info = check_for_update(app_dir)
    if not info.get('configured') or not info.get('available'):
        return {'ok': False, 'message': 'Δεν υπάρχει διαθέσιμη ενημέρωση αυτή τη στιγμή.'}
    current = load_version_info(app_dir).get('version') or '0.0.0'
    return _update.apply_update(info['exe_file_id'], info['latest_version'], current)


def list_local_versions_for_rollback() -> list[dict]:
    if _update is None:
        return []
    return _update.list_local_versions()


def rollback_to_version(app_dir: Path, version: str) -> dict:
    if _update is None or not _update.is_frozen():
        return {'ok': False, 'message': 'Το rollback λειτουργεί μόνο στην packaged έκδοση (.exe).'}
    current = load_version_info(app_dir).get('version') or '0.0.0'
    return _update.rollback_to_version(version, current)


def render_help_panel_html(app_dir: Path, panel_id: str = 'panel-help') -> str:
    readme = find_readme_path(app_dir)
    readme_btn = (
        f'<button type="button" onclick="helpOpenReadme()">📖 Άνοιγμα README</button>'
        if readme else
        '<span class="hint">(Δεν υπάρχει αρχείο README σε αυτή την εφαρμογή)</span>'
    )
    copyright_html = find_copyright_html(app_dir)
    readme_path = str(readme) if readme else ''
    return f'''
    <div id="{panel_id}" class="panel">
      <fieldset>
        <legend>Οδηγίες χρήσης</legend>
        <div class="row">{readme_btn}</div>
      </fieldset>
      <fieldset>
        <legend>Έκδοση</legend>
        <div class="row"><span id="help_version_line">Φόρτωση...</span></div>
        <div class="row">
          <button type="button" onclick="helpCheckUpdate(this)">🔄 Έλεγχος για ενημερώσεις</button>
          <span id="help_update_result" class="hint"></span>
        </div>
        <div class="row" id="help_update_install_row" style="display:none">
          <button type="button" class="success" onclick="helpApplyUpdate(this)">⬇ Λήψη &amp; Εγκατάσταση Ενημέρωσης</button>
          <span class="hint">Η εφαρμογή θα κλείσει και θα ξανανοίξει αυτόματα στη νέα έκδοση.</span>
        </div>
      </fieldset>
      <fieldset>
        <legend>Ιστορικό εκδόσεων (σε αυτόν τον υπολογιστή)</legend>
        <p class="hint">Παλιότερες εκδόσεις που έχεις ήδη τρέξει εδώ — άμεση επαναφορά, χωρίς λήψη.</p>
        <div id="help_local_versions">—</div>
      </fieldset>
      <fieldset>
        <legend>Πνευματικά δικαιώματα</legend>
        <div id="help_copyright_box">{copyright_html}</div>
      </fieldset>
    </div>
    <script>window.__HELP_README_PATH = {readme_path!r};</script>
    '''


HELP_TAB_JS = r'''
function helpOpenReadme() {
  if (!window.__HELP_README_PATH) return;
  api('edit-file', {file: window.__HELP_README_PATH});
}
function helpLoadInfo() {
  api('help-info').then(r => {
    const el = document.getElementById('help_version_line');
    if (!el) return;
    el.textContent = r.version ? ('Τρέχουσα έκδοση: ' + r.version + (r.release_date ? ' (' + r.release_date + ')' : '')) : 'Δεν έχει οριστεί έκδοση για αυτή την εφαρμογή.';
  });
  helpLoadLocalVersions();
}
function helpCheckUpdate(btn) {
  withLoading(btn, api('check-update')).then(r => {
    document.getElementById('help_update_result').textContent = r.message || '';
    document.getElementById('help_update_install_row').style.display =
      (r.configured && r.available) ? '' : 'none';
  });
}
function helpApplyUpdate(btn) {
  btn.disabled = true;
  btn.textContent = 'Λήψη σε εξέλιξη — μη κλείνεις το παράθυρο...';
  // Η εφαρμογή τερματίζει μόνη της (os._exit) μόλις ολοκληρωθεί το κατέβασμα,
  // οπότε το fetch συνήθως δεν προλαβαίνει να πάρει ποτέ απάντηση — αυτό
  // ΔΕΝ σημαίνει σφάλμα, σημαίνει επιτυχία (η σύνδεση κόβεται επειδή η
  // διεργασία μόλις έκλεισε για να ξανανοίξει στη νέα έκδοση).
  api('apply-update', {}).then(r => {
    if (r && r.ok === false) {
      alert('Αποτυχία ενημέρωσης: ' + (r.message || ''));
      btn.disabled = false;
      btn.textContent = '⬇ Λήψη & Εγκατάσταση Ενημέρωσης';
    }
  }).catch(() => {
    btn.textContent = 'Η εφαρμογή επανεκκινείται...';
  });
}
function helpLoadLocalVersions() {
  const el = document.getElementById('help_local_versions');
  if (!el) return;
  api('local-versions').then(r => {
    const versions = r.versions || [];
    if (!versions.length) { el.innerHTML = '<span class="hint">(Καμία παλιότερη έκδοση αποθηκευμένη ακόμα εδώ)</span>'; return; }
    el.innerHTML = versions.map(v =>
      `<div class="row"><span>${v.version}</span> ` +
      `<button type="button" onclick="helpRollback('${v.version}', this)">↩ Επαναφορά</button></div>`
    ).join('');
  });
}
async function helpRollback(version, btn) {
  if (!await dashConfirm('Επαναφορά στην έκδοση ' + version + '; Η εφαρμογή θα επανεκκινήσει.')) return;
  btn.disabled = true;
  api('rollback-version', {version: version}).then(r => {
    if (r && r.ok === false) { alert('Αποτυχία: ' + (r.message || '')); btn.disabled = false; }
  }).catch(() => { btn.textContent = 'Επανεκκίνηση...'; });
}
'''


# ---------------------------------------------------------------------------
# JobManager — γενικό background-job runner (start/status/pause/resume/stop)
# ---------------------------------------------------------------------------

class JobControl:
    """Δίνεται σε κάθε target function· η ίδια η function ελέγχει τα events
    (π.χ. καλώντας wait_if_paused() σε κάθε βήμα ενός loop) — το JobManager
    δεν διακόπτει τίποτα μαγικά, απλώς περνάει τα handles."""
    def __init__(self):
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()

    def wait_if_paused(self):
        while self.pause_event.is_set() and not self.stop_event.is_set():
            self.stop_event.wait(0.5)


class JobManager:
    """Τυλίγει οποιαδήποτε callable(logger, control, progress_cb, ...) -> dict
    σε background thread με start/status/pause/resume/stop/progress.
    Αντικαθιστά το bespoke _JOBS/_run_send_job/_start_send_job pattern που
    χτίστηκε αρχικά ειδικά για το email-sender — τώρα επαναχρησιμοποιήσιμο
    από οποιαδήποτε app."""

    def __init__(self, app_name: str):
        self.app_name = app_name
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def any_active(self) -> bool:
        with self._lock:
            return any(j['status'] in ('running', 'paused') for j in self._jobs.values())

    def start(self, target_fn, *args, debug: bool = True, total: int = 0,
              log_file: str | None = None, app_dir: 'Path | None' = None, **kwargs) -> str:
        """target_fn(logger, control, progress_cb, *args, **kwargs) -> dict.
        Η επιστρεφόμενη dict αποθηκεύεται ως 'result' — καλό να περιέχει
        τουλάχιστον {'exit_code': int}.
        log_file/app_dir (προαιρετικά): αν δοθούν, κάθε γραμμή log γράφεται
        (append) στο αρχείο ΤΗ ΣΤΙΓΜΗ που παράγεται (μέσω logger.subscribe),
        όχι μόνο στο τέλος — ένα run πολλών ωρών πρέπει να είναι ορατό στο
        αρχείο ενώ ακόμα τρέχει, αλλιώς ο χρήστης βλέπει μόνο τα παλιά logs
        προηγούμενων runs και νομίζει ότι κόλλησε. Πέρασέ τα πάντα από τα
        _api_run handlers: JOBS.start(target, debug=debug,
        log_file=config.get('<APP>_LOG_FILE'), app_dir=APP_DIR)."""
        if RunLogger is None:
            raise RuntimeError('dashboard_core_common.py δεν βρέθηκε δίπλα σε αυτό το αρχείο')
        if not (log_file and app_dir):
            # Προεπιλογή: το log_file του config.json (το ίδιο που διαβάζει το
            # dashboard για το χρώμα του tile) — ώστε ΚΑΘΕ run από GUI να
            # ενημερώνει το tile, χωρίς να χρειάζεται να το περάσει κάθε app.
            try:
                import json
                _dir = Path(__file__).resolve().parent
                _lf = json.loads((_dir / 'config.json').read_text(encoding='utf-8')).get('log_file')
                if _lf:
                    log_file, app_dir = _lf, _dir
            except Exception:
                pass
        job_id = uuid.uuid4().hex[:12]
        logger = RunLogger(self.app_name, debug=debug)
        control = JobControl()
        job = {'logger': logger, 'control': control, 'status': 'running',
              'progress': {'current': 0, 'total': total}, 'result': None}
        with self._lock:
            self._jobs[job_id] = job

        if log_file and app_dir:
            log_path = Path(log_file)
            if not log_path.is_absolute():
                log_path = app_dir / log_path
            log_path.parent.mkdir(parents=True, exist_ok=True)

            def _append_line(line, level):
                try:
                    with open(log_path, 'a', encoding='utf-8') as f:
                        f.write(line + '\n')
                except Exception:
                    pass

            logger.subscribe(_append_line)

        def progress_cb(current, total_=None, **extra):
            job['progress'] = {'current': current, 'total': total_ if total_ is not None else job['progress']['total'], **extra}

        def runner():
            try:
                result = target_fn(logger, control, progress_cb, *args, **kwargs)
                job['result'] = result
                job['status'] = 'stopped' if control.stop_event.is_set() else 'done'
                if log_file and app_dir and isinstance(result, dict) and isinstance(result.get('exit_code'), int):
                    log_final_status(logger, result['exit_code'])
            except Exception as e:
                logger.log(f'Απρόσμενο σφάλμα: {e}', 'ERROR')
                job['status'] = 'error'
                if log_file and app_dir:
                    log_final_status(logger, 1)

        t = threading.Thread(target=runner, daemon=True)
        job['thread'] = t
        t.start()
        return job_id

    def status(self, job_id: str) -> dict | None:
        job = self._jobs.get(job_id)
        if not job:
            return None
        return {'status': job['status'], 'progress': job['progress'],
               'log': job['logger'].lines, 'result': job['result']}

    def pause(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        job['control'].pause_event.set()
        job['status'] = 'paused'
        return True

    def resume(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        job['control'].pause_event.clear()
        job['status'] = 'running'
        return True

    def stop(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        job['control'].stop_event.set()
        job['control'].pause_event.clear()
        return True

    def get_result(self, job_id: str) -> dict | None:
        job = self._jobs.get(job_id)
        return job['result'] if job else None


# ---------------------------------------------------------------------------
# Standalone runner boilerplate (--standalone/--port/--host/--no-browser)
# ---------------------------------------------------------------------------

def run_standalone_cli(flask_app, default_port: int, app_label: str = 'GUI') -> None:
    """Σε packaged exe (PyInstaller, sys.frozen) ο παραλήπτης απλά κάνει διπλό
    κλικ — δεν περνάει ποτέ --standalone. Σε αυτή την περίπτωση η προεπιλογή
    είναι standalone+browser χωρίς να χρειάζεται κανένα flag· η ρητή σημαία
    --standalone εξακολουθεί να δουλεύει κανονικά και στο dev mode (τρέξιμο
    από πηγαίο κώδικα μέσα από το dashboard)."""
    import sys
    is_frozen = getattr(sys, 'frozen', False)

    parser = argparse.ArgumentParser(description=f'{app_label} (Flask)')
    parser.add_argument('--standalone', action='store_true', help='Τρέξιμο ως αυτόνομος Flask server')
    parser.add_argument('--port', type=int, default=default_port)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--no-browser', action='store_true', help='Να μην ανοίξει αυτόματα ο browser')
    args = parser.parse_args()

    if args.standalone or is_frozen:
        url = f'http://{args.host}:{args.port}/'
        print(f'{app_label}: {url}')
        if not args.no_browser:
            import webbrowser
            threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        flask_app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
    else:
        parser.print_help()
