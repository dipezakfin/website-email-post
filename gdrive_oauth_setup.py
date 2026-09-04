"""gdrive_oauth_setup.py — Μίας φοράς τοπικό setup για το Google Drive
upload του website-email-post.

Ανοίγει browser για login/έγκριση με τον προσωπικό σου Google λογαριασμό
(αυτόν στον οποίο ανήκει ο φάκελος Drive που μοιράστηκες), και τυπώνει το
token JSON που πρέπει να επικολλήσεις στο πεδίο "OAuth Token JSON" του
dashboard GUI (tab Ρυθμίσεις → Google Drive για συνημμένα).

Απαιτεί το ίδιο OAuth Client (Desktop app) που χρησιμοποιεί ήδη το
app-publisher — δεν χρειάζεται νέο Google Cloud project.

Χρήση:
    python gdrive_oauth_setup.py
"""
from pathlib import Path

SCOPES = ['https://www.googleapis.com/auth/drive.file']
CLIENT_SECRETS_FILE = Path(__file__).resolve().parent.parent / 'app-publisher' / 'gdrive-oauth-credentials.json'


def main() -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not CLIENT_SECRETS_FILE.exists():
        raise SystemExit(f'Δεν βρέθηκε το αρχείο OAuth client: {CLIENT_SECRETS_FILE}')

    print('Ανοίγει browser για login/έγκριση με τον Google λογαριασμό σου...')
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRETS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)

    token_json = creds.to_json()
    out_path = Path(__file__).resolve().parent / 'gdrive-oauth-token.json'
    out_path.write_text(token_json, encoding='utf-8')

    print()
    print(f'Επιτυχία! Το token αποθηκεύτηκε τοπικά και εδώ: {out_path}')
    print()
    print('Αντίγραψε ολόκληρο το παρακάτω περιεχόμενο και επικόλλησέ το στο πεδίο')
    print('"OAuth Token JSON" του dashboard GUI (tab Ρυθμίσεις → Google Drive):')
    print()
    print(token_json)


if __name__ == '__main__':
    main()
