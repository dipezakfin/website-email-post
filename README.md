# website-email-post

Διαβάζει νέα emails από ένα κοινό Gmail mailbox και τα δημοσιεύει
αυτόματα ως άρθρα σε site Joomla (μέσω του Joomla Web Services API).

Σχεδιασμένο να τρέχει **περιοδικά μέσω Windows Task Scheduler** (όχι σαν
συνεχής υπηρεσία) — κάθε φορά που εκτελείται, διαβάζει τα μη-αναγνωσμένα
μηνύματα, τα δημοσιεύει, και τερματίζει.

## Πώς λειτουργεί

1. Συνδέεται στο mailbox μέσω IMAP και διαβάζει τα μη-αναγνωσμένα μηνύματα.
2. Ελέγχει αν ο αποστολέας είναι στη whitelist (`WEBSITE_POST_WHITELIST_EMAIL_ADDRESSES`).
   Αν όχι, το μήνυμα αγνοείται (καταγράφεται στο log ως `SKIPPED_NOT_WHITELISTED`).
3. Μετατρέπει το μήνυμα σε άρθρο Joomla:
   - **Θέμα** → τίτλος άρθρου, βλ. σύμβαση hashtags παρακάτω.
   - **Σώμα** → κείμενο άρθρου (χρησιμοποιείται η HTML έκδοση του μηνύματος αν
     υπάρχει, αλλιώς το plain text μετατρέπεται σε παραγράφους).
   - **Εικόνες** → αλλάζουν μέγεθος/συμπιέζονται και ενσωματώνονται στην αρχή
     του άρθρου.
   - **Λοιπά αρχεία** (pdf/docx/xlsx/...) → ανεβαίνουν στο Media Manager και
     προστίθενται ως links στο τέλος του άρθρου, κάτω από "Συνημμένα αρχεία".
   - **YouTube links** (μέσα στο κείμενο, ως link ή σκέτο URL) →
     αντικαθίστανται αυτόματα με ενσωματωμένο (embedded) video player.
4. Δημοσιεύει το άρθρο μέσω του Joomla API (ως draft ή published, ανάλογα με
   `WEBSITE_POST_DEFAULT_STATUS`).
5. Μετακινεί το email σε φάκελο `Processed` (επιτυχία) ή `Failed` (σφάλμα) στο
   mailbox, ώστε να μην ξανα-επεξεργαστεί στο επόμενο run.
6. Καταγράφει κάθε ενέργεια σε CSV log (`WEBSITE_POST_LOG_FILE_PATH`).

## Σύμβαση email

**Θέμα:**
```
Τίτλος άρθρου #featured #εκδηλώσεις #σχολείο
```
- Οτιδήποτε hashtag εκτός από `#featured`/`#notfeatured` γίνεται **tag** στο Joomla.
- `#featured` → το άρθρο σημαδεύεται ως featured.
- `#notfeatured` → εξαιρείται ρητά από featured, ακόμα κι αν το
  `WEBSITE_POST_DEFAULT_FEATURED=YES`.
- Αν δεν υπάρχει κανένα από τα δύο, χρησιμοποιείται το
  `WEBSITE_POST_DEFAULT_FEATURED`.

**Σώμα:** Το κείμενο του άρθρου — plain text ή μορφοποιημένο (rich text/HTML),
ό,τι βολεύει τον αποστολέα.

**Συνημμένα:** Εικόνες μπαίνουν μέσα στο άρθρο· οποιοδήποτε άλλο αρχείο μπαίνει
ως link στο τέλος.

## Εγκατάσταση

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Συμπλήρωσε το `.env` με τα πραγματικά στοιχεία (βλ. σχόλια μέσα στο αρχείο).

### Gmail στοιχεία

- Ενεργοποίησε IMAP: Gmail → Settings → **Forwarding and POP/IMAP** → Enable IMAP.
- Χρειάζεται **App Password** (όχι το κανονικό password του λογαριασμού):
  Google Account → **Security** → ενεργοποίησε **2-Step Verification** αν δεν
  είναι ήδη → **App passwords** → δημιούργησε ένα νέο (π.χ. όνομα
  "website-email-post") και βάλε το 16-χαρακτήρων αποτέλεσμα στο
  `WEBSITE_POST_EMAIL_PASSWORD`.
- Συνιστάται ξεχωριστός Gmail λογαριασμός αφιερωμένος μόνο σε αυτή τη
  λειτουργία, όχι προσωπικός λογαριασμός κανενός.

### Joomla στοιχεία

- **API Token**: Users → Manage → επιλογή χρήστη → tab "API Token" → Generate.
  Ο χρήστης πρέπει να έχει δικαίωμα δημιουργίας άρθρων στην κατηγορία-στόχο.
- **Category ID**: Content → Categories, το ID φαίνεται στη λίστα/στο URL επεξεργασίας.
- **Media adapters**: Content → Media → Settings → Adapters — επιβεβαίωσε τα
  ονόματα adapters που θα χρησιμοποιηθούν για εικόνες/έγγραφα και βάλτα στο
  `.env` (`WEBSITE_POST_MEDIA_ADAPTER_IMAGES`, `WEBSITE_POST_MEDIA_ADAPTER_DOCS`).

### Πρώτη δοκιμή (χωρίς να δημιουργηθούν πραγματικά άρθρα)

Βάλε `WEBSITE_POST_DRY_RUN=YES` στο `.env`, στείλε ένα δοκιμαστικό email, και
τρέξε:
```
python script.py
```
Έλεγξε την κονσόλα/το log για να επιβεβαιώσεις ότι το mail διαβάζεται και
μορφοποιείται σωστά, πριν ενεργοποιήσεις πραγματικές αναρτήσεις
(`WEBSITE_POST_DRY_RUN=NO`).

> Σημείωση: σε `DRY_RUN` mode τα emails **δεν** μετακινούνται σε
> Processed/Failed, ώστε να μπορείς να ξανατρέξεις το script στο ίδιο μήνυμα.

## Windows Task Scheduler

1. Task Scheduler → Create Task.
2. **General**: "Run whether user is logged on or not", "Run with highest privileges".
3. **Triggers**: New → Begin the task "On a schedule" → Repeat task every
   `10 minutes`, for a duration of `Indefinitely`.
4. **Actions**: New → Start a program:
   - Program/script: `C:\path\to\website-email-post\.venv\Scripts\python.exe`
   - Add arguments: `script.py`
   - Start in: `C:\path\to\website-email-post`
5. **Settings**: ενεργοποίησε "If the task is already running, do not start a
   new instance" (ώστε να μην τρέχουν παράλληλα δύο runs).

## Log

CSV αρχείο (`WEBSITE_POST_LOG_FILE_PATH`, default `logs/post_log.csv`) με
στήλες: `timestamp, email_from, email_subject, status,
joomla_article_id, attachments_count, error_message`.

`status` ∈ `POSTED`, `SKIPPED_NOT_WHITELISTED`, `ERROR`.

## Ασφάλεια

- Το `.env` **δεν** ανεβαίνει ποτέ στο repo (`.gitignore`).
- Χρησιμοποιείται ξεχωριστός/κοινός mailbox — όχι προσωπικός λογαριασμός
  κανενός. Η πρόσβαση σε ανάρτηση ελέγχεται αποκλειστικά μέσω
  `WEBSITE_POST_WHITELIST_EMAIL_ADDRESSES` (email του αποστολέα), όχι μέσω
  διαμοιρασμού κωδικών.
