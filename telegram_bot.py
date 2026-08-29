#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
telegram_bot.py

Polls a Telegram bot for commands to quickly publish/unpublish Joomla
articles, without opening the dashboard GUI. Run periodically (GitHub
Actions, every 5 minutes) - one pass per invocation, no sys.exit() needed
since it's not imported anywhere else, kept as a plain script like
website-email-post.py.

Commands:
  /list            - recent articles with inline Publish/Unpublish buttons
  /publishlast     - publish the most recent article
  /unpublishlast   - unpublish the most recent article

Only chat ids listed in TELEGRAM_ALLOWED_CHAT_IDS are honored - anyone
else gets a polite refusal, not silence (it's a private bot, no need to
hide its existence).
"""

import os
import sys

import requests

import website_email_post_core as core

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
ALLOWED_CHAT_IDS = {c.strip() for c in os.environ.get('TELEGRAM_ALLOWED_CHAT_IDS', '').split(',') if c.strip()}
API_BASE = f'https://api.telegram.org/bot{BOT_TOKEN}'

HELP_TEXT = (
    'Εντολές:\n'
    '/list — λίστα πρόσφατων άρθρων με κουμπιά Publish/Unpublish\n'
    '/publishlast — δημοσίευση του πιο πρόσφατου άρθρου\n'
    '/unpublishlast — απόσυρση (unpublish) του πιο πρόσφατου άρθρου\n'
    '/publish <id> — δημοσίευση συγκεκριμένου άρθρου (π.χ. /publish 1773)\n'
    '/unpublish <id> — απόσυρση συγκεκριμένου άρθρου (π.χ. /unpublish 1773)'
)


def tg(method, **params):
    resp = requests.post(f'{API_BASE}/{method}', json=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def send_message(chat_id, text, reply_markup=None):
    params = {'chat_id': chat_id, 'text': text}
    if reply_markup:
        params['reply_markup'] = reply_markup
    return tg('sendMessage', **params)


def articles_keyboard(articles):
    rows = []
    for a in articles:
        published = a['state'] == 1
        action = 'u' if published else 'p'
        icon = '📝' if published else '📢'
        verb = 'Unpublish' if published else 'Publish'
        rows.append([{'text': f'{icon} {verb}: {a["title"][:35]}', 'callback_data': f'{action}:{a["id"]}'}])
    return {'inline_keyboard': rows}


def handle_list(config, chat_id):
    articles = core.joomla_list_recent_articles(config, limit=10)
    if not articles:
        send_message(chat_id, 'Δεν βρέθηκαν άρθρα.')
        return
    send_message(chat_id, 'Πρόσφατα άρθρα:', reply_markup=articles_keyboard(articles))


def handle_publish_last(config, chat_id, publish):
    articles = core.joomla_list_recent_articles(config, limit=1)
    if not articles:
        send_message(chat_id, 'Δεν βρέθηκε κανένα άρθρο.')
        return
    article = articles[0]
    result = core.joomla_set_article_state(config, article['id'], publish)
    verb = 'δημοσιεύτηκε' if publish else 'έγινε unpublish'
    send_message(chat_id, f'✅ Το άρθρο "{result["title"]}" {verb}.')


def handle_publish_by_id(config, chat_id, publish, arg_text):
    article_id = arg_text.strip()
    if not article_id.isdigit():
        send_message(chat_id, f'Χρήση: /{"publish" if publish else "unpublish"} <id>\nπ.χ. /{"publish" if publish else "unpublish"} 1773')
        return
    try:
        result = core.joomla_set_article_state(config, article_id, publish)
    except Exception as e:
        send_message(chat_id, f'✗ Σφάλμα: {e}')
        return
    verb = 'δημοσιεύτηκε' if publish else 'έγινε unpublish'
    send_message(chat_id, f'✅ Το άρθρο "{result["title"]}" (id={article_id}) {verb}.')


def handle_callback(config, callback_query):
    chat_id = callback_query['message']['chat']['id']
    message_id = callback_query['message']['message_id']
    data = callback_query.get('data', '')
    action, _, article_id = data.partition(':')

    if action not in ('p', 'u') or not article_id:
        tg('answerCallbackQuery', callback_query_id=callback_query['id'], text='Άγνωστη ενέργεια')
        return

    result = core.joomla_set_article_state(config, article_id, action == 'p')
    verb = 'Δημοσιεύτηκε' if action == 'p' else 'Έγινε unpublish'
    tg('answerCallbackQuery', callback_query_id=callback_query['id'], text=f'{verb}: {result["title"][:40]}')

    # Ξαναχτίζει τα κουμπιά ώστε να δείχνουν την ενημερωμένη κατάσταση.
    articles = core.joomla_list_recent_articles(config, limit=10)
    tg('editMessageReplyMarkup', chat_id=chat_id, message_id=message_id, reply_markup=articles_keyboard(articles))


def process_update(config, update):
    if 'callback_query' in update:
        cq = update['callback_query']
        chat_id = str(cq['message']['chat']['id'])
        if chat_id not in ALLOWED_CHAT_IDS:
            tg('answerCallbackQuery', callback_query_id=cq['id'], text='Μη εξουσιοδοτημένος χρήστης')
            return
        handle_callback(config, cq)
        return

    msg = update.get('message') or update.get('edited_message')
    if not msg:
        return
    chat_id = str(msg['chat']['id'])
    text = (msg.get('text') or '').strip()

    if chat_id not in ALLOWED_CHAT_IDS:
        send_message(chat_id, 'Δεν είσαι εξουσιοδοτημένος χρήστης αυτού του bot.')
        return

    # Tokenized (όχι startswith chains) ώστε /publish να μη ταιριάζει
    # κατά λάθος και με /publishlast. Το @botusername suffix (εμφανίζεται
    # σε group chats) αφαιρείται πριν τη σύγκριση.
    parts = text.split(maxsplit=1)
    command = parts[0].split('@', 1)[0].lower() if parts else ''
    arg = parts[1] if len(parts) > 1 else ''

    if command == '/list':
        handle_list(config, chat_id)
    elif command == '/publishlast':
        handle_publish_last(config, chat_id, True)
    elif command == '/unpublishlast':
        handle_publish_last(config, chat_id, False)
    elif command == '/publish':
        handle_publish_by_id(config, chat_id, True, arg)
    elif command == '/unpublish':
        handle_publish_by_id(config, chat_id, False, arg)
    elif command in ('/start', '/help'):
        send_message(chat_id, HELP_TEXT)
    else:
        send_message(chat_id, 'Άγνωστη εντολή.\n\n' + HELP_TEXT)


def main() -> int:
    if not BOT_TOKEN:
        print('TELEGRAM_BOT_TOKEN missing - skipping', file=sys.stderr)
        return 0
    if not ALLOWED_CHAT_IDS:
        print('TELEGRAM_ALLOWED_CHAT_IDS missing - skipping', file=sys.stderr)
        return 0

    core.load_dotenv_files()
    config = core.load_config()

    updates = tg('getUpdates', timeout=0).get('result', [])
    if not updates:
        print('No new Telegram updates.')
        return 0

    print(f'Found {len(updates)} update(s).')
    last_update_id = 0
    for update in updates:
        last_update_id = max(last_update_id, update['update_id'])
        try:
            process_update(config, update)
        except Exception as e:
            print(f'Error handling update {update["update_id"]}: {e}', file=sys.stderr)

    # Επιβεβαιώνει την παραλαβή στο Telegram ώστε το επόμενο run να μην
    # ξαναδιαβάσει τα ίδια updates (το offset είναι server-side per-bot,
    # δεν χρειάζεται δικό μας persisted state).
    tg('getUpdates', offset=last_update_id + 1, timeout=0)
    return 0


if __name__ == '__main__':
    sys.exit(main())
