#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dashboard_core_common.py
Κοινό module για το business-logic ("core.py") κάθε dashboard app.
Αντιγράφεται αυτούσιο μέσα σε κάθε app (ίδια σύμβαση με το websign_sign.py —
κάθε app folder μένει self-contained, χωρίς cross-folder imports μέσω
sys.path). Χρησιμοποιείται από: το core.py business logic module, το CLI
entrypoint, και το gui.py.

Παρέχει:
  - RunLogger: συλλέκτης log γραμμών με ενιαία μορφή σε ΟΛΕΣ τις apps
    "{timestamp};{app_name};{LEVEL};{message}" — το κεντρικό dashboard.py
    διαβάζει αυτή τη μορφή για να δείχνει "τελευταία εκτέλεση" στα tiles.
  - log_final_status(logger, exit_code): γράφει την ΤΕΛΕΥΤΑΙΑ γραμμή log πριν
    το exit — σταθερή φράση ανά exit code, ώστε το tile-status parsing στο
    dashboard.py να δουλεύει με έναν απλό, αξιόπιστο κανόνα (διάβασε την
    τελευταία γραμμή του log, όχι heuristic σε πολλές γραμμές).

Συμβόλαιο για κάθε core.py που χρησιμοποιεί αυτό το module:
  - ΚΑΜΙΑ sys.exit() μέσα στο business logic (μόνο στο thin CLI entrypoint).
  - Κάθε run_xxx() function επιστρέφει dict με τουλάχιστον {'ok': bool,
    'exit_code': int}, ώστε το CLI entrypoint να κάνει sys.exit(exit_code)
    και το gui.py να μπορεί να τη «τυλίξει» σε JobManager χωρίς να ξέρει
    λεπτομέρειες της κάθε app.
  - Το CLI entrypoint καλεί log_final_status(logger, exit_code) ΩΣ ΤΕΛΕΥΤΑΙΟ
    βήμα, πριν το logger.write_log_file() / sys.exit().
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

STATUS_SUCCESS_MARKER = 'ΟΛΟΚΛΗΡΩΘΗΚΕ ΕΠΙΤΥΧΩΣ'
STATUS_WARNING_MARKER = 'ΟΛΟΚΛΗΡΩΘΗΚΕ ΜΕ ΠΡΟΕΙΔΟΠΟΙΗΣΕΙΣ'
STATUS_ERROR_MARKER   = 'ΟΛΟΚΛΗΡΩΘΗΚΕ ΜΕ ΣΦΑΛΜΑ'


class RunLogger:
    """Συλλέκτης log γραμμών· κοινή μορφή σε όλες τις dashboard apps:
    "{timestamp};{app_name};{LEVEL};{message}". Υποστηρίζει subscribers
    (callback(line, level)) ώστε ένα GUI να κάνει live-stream το log."""

    def __init__(self, app_name: str, debug: bool = False):
        self.app_name = app_name
        self.lines: list[str] = []
        self.has_warnings = False
        self.has_errors = False
        self.debug = debug
        self._subscribers = []

    def subscribe(self, callback) -> None:
        self._subscribers.append(callback)

    def log(self, message: str, level: str = 'INFO') -> None:
        if level == 'DEBUG' and not self.debug:
            return
        ts   = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        line = f'{ts};{self.app_name};{level};{message}'
        self.lines.append(line)
        if level == 'WARN':
            self.has_warnings = True
        if level == 'ERROR':
            self.has_errors = True
        try:
            print(line)
        except UnicodeEncodeError:
            # Η κονσόλα δεν υποστηρίζει κάποιον χαρακτήρα (π.χ. cp1253 σε
            # ελληνικά Windows χωρίς UTF-8 codepage) — γράφουμε bytes
            # απευθείας στο buffer με replace στο ΠΡΑΓΜΑΤΙΚΟ encoding της
            # κονσόλας, αντί για ένα ενδιάμεσο encode/decode που μπορεί να
            # παράγει U+FFFD (μη αναπαραστάσιμο κι αυτό, ξανακρασάρει).
            enc = getattr(sys.stdout, 'encoding', None) or 'utf-8'
            try:
                sys.stdout.buffer.write(line.encode(enc, errors='replace') + b'\n')
                sys.stdout.flush()
            except Exception:
                pass
        for cb in list(self._subscribers):
            try:
                cb(line, level)
            except Exception:
                pass

    def write_log_file(self, log_file: str, app_dir: Path) -> None:
        if not log_file:
            return
        try:
            p = Path(log_file)
            if not p.is_absolute():
                p = app_dir / p
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, 'a', encoding='utf-8') as f:
                f.write('\n'.join(self.lines) + '\n')
        except Exception as e:
            self.log(f'Αποτυχία εγγραφής log file: {e}', 'WARN')


class SafeDict(dict):
    """dict.format_map helper — placeholders χωρίς τιμή γίνονται κενό string
    αντί για KeyError."""
    def __missing__(self, key):
        return ''


def log_final_status(logger: RunLogger, exit_code: int) -> None:
    """Γράφει την τελευταία γραμμή log πριν το exit, με σταθερή φράση ανά
    exit code — το κεντρικό dashboard.py διαβάζει ΜΟΝΟ την τελευταία γραμμή
    του log file για να αποφασίσει το χρώμα του tile (success/warning/error),
    αντί για ασταθές heuristic πάνω σε πολλές γραμμές."""
    if exit_code == 0:
        logger.log(STATUS_SUCCESS_MARKER)
    elif exit_code == 2:
        logger.log(STATUS_WARNING_MARKER, 'WARN')
    else:
        logger.log(STATUS_ERROR_MARKER, 'ERROR')


def read_last_run_status(log_file_path: Path) -> dict:
    """Διαβάζει την τελευταία γραμμή ενός log αρχείου (μορφή RunLogger) και
    επιστρέφει {'status': 'success'|'warning'|'error'|'unknown'|'never_run',
    'timestamp': str|None, 'message': str|None}. Χρησιμοποιείται από το
    κεντρικό dashboard.py για τα tiles."""
    if not log_file_path.exists():
        return {'status': 'never_run', 'timestamp': None, 'message': None}
    try:
        with open(log_file_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = [ln.strip() for ln in f if ln.strip()]
    except Exception:
        return {'status': 'unknown', 'timestamp': None, 'message': None}
    if not lines:
        return {'status': 'never_run', 'timestamp': None, 'message': None}

    last = lines[-1]
    parts = last.split(';', 3)
    ts = parts[0] if len(parts) > 0 else None
    level = parts[2] if len(parts) > 2 else ''
    message = parts[3] if len(parts) > 3 else last

    if STATUS_SUCCESS_MARKER in last:
        status = 'success'
    elif STATUS_WARNING_MARKER in last:
        status = 'warning'
    elif STATUS_ERROR_MARKER in last or level == 'ERROR':
        status = 'error'
    else:
        status = 'unknown'
    return {'status': status, 'timestamp': ts, 'message': message}
