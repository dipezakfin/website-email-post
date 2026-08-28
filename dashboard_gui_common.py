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
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from flask import jsonify, request

try:
    from dashboard_core_common import RunLogger
except ImportError:  # αν αντιγράφτηκε μόνο αυτό το αρχείο χωρίς το core_common
    RunLogger = None


# ---------------------------------------------------------------------------
# CSS (dark mode via CSS variables + toggle, μοντέρνο styling)
# ---------------------------------------------------------------------------

COMMON_CSS = r"""
  :root {
    --bg: #eef1f5; --fg: #222; --header-bg: #2c3e50; --header-fg: #fff;
    --tabs-bg: #34495e; --tab-fg: #ccd3da; --tab-hover-bg: #3d5166;
    --fieldset-bg: #fff; --fieldset-border: #d8dee4; --legend-fg: #2c3e50;
    --input-bg: #fff; --input-border: #c7ccd1; --input-fg: #222;
    --btn-bg: #eef1f5; --btn-border: #b8bec4; --btn-fg: #222; --btn-hover-bg: #e0e5ea;
    --table-border: #e0e4e8; --table-head-bg: #eef1f5; --table-row-hover: #f7f9fb;
    --table-cell-border: #eceff2;
    --log-bg: #1e1e1e; --log-fg: #d4d4d4;
    --hint-fg: #777; --shadow: rgba(0,0,0,0.06); --accent: #2980b9;
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
  }
  * { box-sizing: border-box; }
  body { font-family: "Segoe UI", Arial, sans-serif; margin: 0; background: var(--bg); color: var(--fg);
    font-size: 14px; transition: background 0.2s, color 0.2s; }
  header { background: var(--header-bg); color: var(--header-fg); padding: 16px 22px;
    display: flex; align-items: center; justify-content: space-between; }
  header h1 { margin: 0; font-size: 20px; }
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
  .switch { position: relative; display: inline-block; width: 44px; min-width: 44px; height: 24px;
    vertical-align: middle; }
  .switch input[type=checkbox] { opacity: 0; width: 0; height: 0; position: absolute; }
  .switch .slider { position: absolute; inset: 0; background: var(--btn-border); transition: background 0.2s;
    border-radius: 999px; cursor: pointer; }
  .switch .slider::before { content: ""; position: absolute; height: 18px; width: 18px; left: 3px; bottom: 3px;
    background: #fff; transition: transform 0.2s; border-radius: 50%; box-shadow: 0 1px 3px rgba(0,0,0,0.3); }
  .switch input[type=checkbox]:checked + .slider { background: var(--accent); }
  .switch input[type=checkbox]:checked + .slider::before { transform: translateX(20px); }
  .switch input[type=checkbox]:disabled + .slider { opacity: 0.5; cursor: default; }
  .switch input[type=checkbox]:focus-visible + .slider { outline: 2px solid var(--accent); outline-offset: 2px; }
  button { padding: 8px 16px; margin: 4px 4px 4px 0; cursor: pointer; border: 1px solid var(--btn-border);
    border-radius: 8px; background: var(--btn-bg); color: var(--btn-fg); font-size: 14px;
    transition: background 0.15s, transform 0.05s; }
  button:hover { background: var(--btn-hover-bg); }
  button:active { transform: scale(0.97); }
  button:disabled { opacity: 0.6; cursor: default; transform: none; }
  button.primary { background: #2980b9; color: #fff; border-color: #2980b9; }
  button.primary:hover { background: #2471a3; }
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
  .rte-editor:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(41,128,185,0.15); }
  .rte-editor img { max-width: 100%; }
  .chip-btn { padding: 3px 10px; margin: 2px 4px 2px 0; border-radius: 999px; border: 1px solid var(--btn-border);
    background: var(--btn-bg); color: var(--btn-fg); cursor: pointer; font-size: 12px; font-family: monospace; }
  .chip-btn:hover { background: var(--accent); color: #fff; border-color: var(--accent); }
  .modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: flex;
    align-items: center; justify-content: center; z-index: 1000; }
  .modal-box { background: var(--fieldset-bg); color: var(--fg); border-radius: 12px; padding: 22px;
    max-width: 480px; width: 90%; box-shadow: 0 8px 30px rgba(0,0,0,0.3); }
  .modal-box h3 { margin-top: 0; }
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
  addBtn('✕ Καθαρισμός', () => {{ if (confirm('Καθαρισμός περιεχομένου;')) {{ editor.innerHTML = ''; sync(); }} }});

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
    """Προγραμματισμός (daily/weekly/workdays + ώρα) ΓΙΑ ΑΥΤΟ ΚΑΙ ΜΟΝΟ ΑΥΤΟ το
    app — ίδια λογική/βιβλιοθήκη (`schedule`) με τον προγραμματισμό ανά-app
    του κεντρικού dashboard.py, αλλά ένα instance ζει μέσα στο δικό του gui.py
    process, μόνο για τον εαυτό του. Persist σε apps/<app>/schedule.json.
    Όταν χτυπήσει η ώρα, τρέχει headless το main_script (subprocess, ίδιος
    τρόπος με το κεντρικό dashboard) — δουλεύει όταν το app τρέχει από πηγαίο
    κώδικα· σε packaged exe δεν υπάρχει ξεχωριστό main_script αρχείο ώστε να
    γίνει subprocess (θα χρειαστεί follow-up όταν ενεργοποιηθεί πραγματικά η
    διανομή exe)."""

    WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')

    def __init__(self, app_dir: Path):
        self.app_dir = app_dir
        self.schedule_file = app_dir / 'schedule.json'
        self.main_script = self._resolve_main_script()
        self._jobs: list = []
        self._lock = threading.Lock()
        if _schedule_lib is not None:
            saved = self.get_schedule()
            if saved.get('type', 'none') != 'none':
                self._apply(saved['type'], saved.get('time', '09:00'), saved.get('weekday', 'monday'))
            t = threading.Thread(target=self._run_loop, daemon=True)
            t.start()

    def _resolve_main_script(self) -> Path | None:
        try:
            import json
            cfg = json.loads((self.app_dir / 'config.json').read_text(encoding='utf-8'))
            main_script = cfg.get('main_script')
            return (self.app_dir / main_script) if main_script else None
        except Exception:
            return None

    def _run_loop(self) -> None:
        while True:
            try:
                _schedule_lib.run_pending()
            except Exception:
                pass
            time.sleep(1)

    def get_schedule(self) -> dict:
        if self.schedule_file.exists():
            try:
                import json
                return json.loads(self.schedule_file.read_text(encoding='utf-8'))
            except Exception:
                pass
        return {'type': 'none', 'time': '09:00', 'weekday': 'monday'}

    def _apply(self, schedule_type: str, time_str: str, weekday: str) -> None:
        for job in self._jobs:
            _schedule_lib.cancel_job(job)
        self._jobs = []
        if schedule_type == 'daily':
            self._jobs.append(_schedule_lib.every().day.at(time_str).do(self._run_async))
        elif schedule_type == 'weekly':
            self._jobs.append(getattr(_schedule_lib.every(), weekday).at(time_str).do(self._run_async))
        elif schedule_type == 'workdays':
            for day in ('monday', 'tuesday', 'wednesday', 'thursday', 'friday'):
                self._jobs.append(getattr(_schedule_lib.every(), day).at(time_str).do(self._run_async))

    def set_schedule(self, schedule_type: str, time_str: str = '09:00', weekday: str = 'monday') -> tuple:
        if _schedule_lib is None:
            return False, 'Η βιβλιοθήκη scheduling δεν είναι διαθέσιμη σε αυτή την εγκατάσταση.'
        if schedule_type not in ('none', 'daily', 'weekly', 'workdays'):
            return False, 'Άγνωστος τύπος προγραμματισμού.'
        with self._lock:
            for job in self._jobs:
                _schedule_lib.cancel_job(job)
            self._jobs = []
            if schedule_type != 'none':
                self._apply(schedule_type, time_str, weekday)
        try:
            import json
            self.schedule_file.write_text(
                json.dumps({'type': schedule_type, 'time': time_str, 'weekday': weekday}, ensure_ascii=False, indent=2),
                encoding='utf-8')
        except Exception:
            pass
        if schedule_type == 'none':
            return True, 'Ο προγραμματισμός απενεργοποιήθηκε.'
        return True, f'Προγραμματίστηκε: {schedule_type} στις {time_str}.'

    def _run_async(self) -> None:
        threading.Thread(target=self._run_once, daemon=True).start()

    def _run_once(self) -> None:
        if not self.main_script or not self.main_script.exists():
            return
        try:
            subprocess.run([sys.executable, str(self.main_script)], cwd=str(self.app_dir),
                           capture_output=True, text=True, encoding='utf-8', errors='replace',
                           timeout=3600)
        except Exception:
            pass


HEADER_ACTIONS_HTML = (
    '<div class="header-actions">'
    '<button id="schedule_btn" onclick="openScheduleModal()" title="Προγραμματισμός αυτόματης εκτέλεσης">🕒</button>'
    '<button id="close_app_btn" class="danger" onclick="confirmCloseApp()" title="Κλείσιμο εφαρμογής">⏻</button>'
    + THEME_TOGGLE_BUTTON_HTML +
    '</div>'
)

SCHEDULING_JS = r'''
const SCHEDULE_TYPE_LABELS = {none: 'Χωρίς', daily: 'Καθημερινά', weekly: 'Εβδομαδιαία', workdays: 'Εργάσιμες'};
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
      <div class="row"><label>Ώρα</label><input type="time" id="sm_time" value="${sched.time || '09:00'}"></div>
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
}
function _smSave() {
  const body = {
    type: document.getElementById('sm_type').value,
    time: document.getElementById('sm_time').value || '09:00',
    weekday: document.getElementById('sm_day').value,
  };
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
            body.get('type', 'none'), body.get('time', '09:00'), body.get('weekday', 'monday'))
        return jsonify({'ok': ok, 'message': message})

    @flask_app.before_request
    def _cancel_pending_shutdown():
        if request.path == '/api/shutdown':
            return
        with lock:
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
        with lock:
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
            'excel': [('Excel/CSV αρχεία', '*.xlsx *.xls *.csv'), ('Όλα τα αρχεία', '*.*')],
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
function helpRollback(version, btn) {
  if (!confirm('Επαναφορά στην έκδοση ' + version + '; Η εφαρμογή θα επανεκκινήσει.')) return;
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

    def start(self, target_fn, *args, debug: bool = True, total: int = 0, **kwargs) -> str:
        """target_fn(logger, control, progress_cb, *args, **kwargs) -> dict.
        Η επιστρεφόμενη dict αποθηκεύεται ως 'result' — καλό να περιέχει
        τουλάχιστον {'exit_code': int}."""
        if RunLogger is None:
            raise RuntimeError('dashboard_core_common.py δεν βρέθηκε δίπλα σε αυτό το αρχείο')
        job_id = uuid.uuid4().hex[:12]
        logger = RunLogger(self.app_name, debug=debug)
        control = JobControl()
        job = {'logger': logger, 'control': control, 'status': 'running',
              'progress': {'current': 0, 'total': total}, 'result': None}
        with self._lock:
            self._jobs[job_id] = job

        def progress_cb(current, total_=None, **extra):
            job['progress'] = {'current': current, 'total': total_ if total_ is not None else job['progress']['total'], **extra}

        def runner():
            try:
                result = target_fn(logger, control, progress_cb, *args, **kwargs)
                job['result'] = result
                job['status'] = 'stopped' if control.stop_event.is_set() else 'done'
            except Exception as e:
                logger.log(f'Απρόσμενο σφάλμα: {e}', 'ERROR')
                job['status'] = 'error'

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
