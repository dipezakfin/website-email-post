#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
website-email-post.py — thin CLI entrypoint. Καλεί μόνο functions του
website_email_post_core.py· καμία business logic εδώ. Αυτό είναι το script
που τρέχει το scheduling subsystem του κεντρικού dashboard.py για
headless/scheduled εκτελέσεις (χωρίς GUI).
"""

import argparse
import io
import sys

if hasattr(sys.stdout, 'buffer') and getattr(sys.stdout, 'encoding', 'utf-8').lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import website_email_post_core as core
from dashboard_core_common import RunLogger, log_final_status


def main() -> int:
    parser = argparse.ArgumentParser(description='website-email-post CLI')
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--dry-run', action='store_true', help='Δεν δημιουργεί πραγματικά άρθρα ούτε μετακινεί emails')
    args = parser.parse_args()

    core.load_dotenv_files()
    config = core.load_config()
    logger = RunLogger(core.APP_NAME, debug=args.debug)

    dry_run_override = True if args.dry_run else None
    result = core.run_check_mail(config, logger, dry_run_override=dry_run_override)
    exit_code = result['exit_code']

    log_final_status(logger, exit_code)
    logger.write_log_file(f'{core.APP_NAME}.log', core.APP_DIR)
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
