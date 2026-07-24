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

## Server / Joomla ρυθμίσεις που χρειάστηκαν (dipe.zak.sch.gr)

Το site τρέχει σε **nginx (proxy mode) μπροστά από Apache**, με **Imunify360**
bot-protection, σε **Joomla 6.1.2**. Μέχρι να δουλέψει το API χρειάστηκαν οι
παρακάτω αλλαγές — αν στηθεί ξανά σε άλλο site/server, πιθανόν να χρειαστούν
κάποια (όχι όλα) από αυτά.

### 1. `.htaccess` — να περνάει το `Authorization` header

Το nginx/Apache setup δεν περνούσε το HTTP header `Authorization` στην PHP από
default (το Joomla έβλεπε κάθε request σαν να μην είχε καθόλου token,
ανεξαρτήτως τι στέλναμε — 401 σε όλες τις περιπτώσεις). Προστέθηκε στο
`.htaccess`, στη ρίζα του Joomla site:

```apache
RewriteEngine On
RewriteCond %{HTTP:Authorization} ^(.*)
RewriteRule .* - [E=HTTP_AUTHORIZATION:%1]
```

Επιβεβαιώθηκε με ένα προσωρινό διαγνωστικό αρχείο (`getallheaders()` dump) πριν
διαγραφεί.

### 2. Imunify360 — whitelist του IP του Windows server

Το Imunify360 bot-protection μπλόκαρε **κάθε** request προς το `/api/*` με
μήνυμα `"Access denied by Imunify360 bot-protection. IPs used for automation
should be whitelisted"` — ανεξάρτητα από token/headers, με βάση αποκλειστικά
το IP προέλευσης.

**Λύση:** στο hosting control panel του site (screen "Apache & nginx Settings
for dipe.zak.sch.gr") → ενότητα **"Deny access to the site"** → προστέθηκε
**exclude/whitelist** για το static IP του Windows server που τρέχει το
script.

> ⚠️ Αν το IP του server αλλάξει ποτέ (π.χ. αλλαγή σύνδεσης/παρόχου), το API
> θα ξαναμπλοκαριστεί μέχρι να ενημερωθεί η λίστα σε αυτή τη σελίδα.

### 3. Joomla plugins που ενεργοποιήθηκαν

System → Manage → Plugins:
- **API Authentication - Web Services Joomla Token** — ενεργό (αυτό
  επιτρέπει την αυθεντικοποίηση με `Authorization: Bearer <token>`).
- **API Authentication - Web Services Basic Auth** — δοκιμάστηκε
  απενεργοποιημένο/ενεργό εναλλάξ κατά τη διάγνωση· μπορεί να μείνει
  ενεργό ή ανενεργό, δεν επηρεάζει το token auth.
- **Web Services - Content**, **Web Services - Media**, **Web Services -
  Tags** — ενεργά (χρειάζονται για τα αντίστοιχα endpoints
  `/content/articles`, `/media/files`, `/tags`).

### 4. Χρήστης API — ομάδα "Super Users"

Ο χρήστης στον οποίο ανήκει το API token πρέπει να είναι στην ομάδα
**Super Users** (Users → Manage → επεξεργασία χρήστη → Account Details →
Assigned User Groups). Με μόνο "Administrator" group το API έδινε **401
Forbidden** παντού, παρότι το token ήταν σωστό.

> Μετά από αλλαγή ομάδας, χρειάζεται να ξαναγίνει **Generate** νέου token
> (tab "Joomla API Token") ώστε να αντιστοιχεί στα νέα δικαιώματα.

### 5. Το πεδίο "Token" στο Joomla UI

Το string που δείχνει το Joomla στο tab "Joomla API Token" (κάτι σαν
`c2hhMjU2Oj...`) **είναι** το πραγματικό token προς χρήση — παρότι μοιάζει με
base64-encoded hash (`sha256:cost:hash`) όταν αποκωδικοποιηθεί. Χρησιμοποιείται
αυτούσιο, ως έχει, στο header `Authorization: Bearer <token>`.

### 6. Πραγματικό API contract (διαφορετικό από την επίσημη τεκμηρίωση/υποθέσεις)

Ανακαλύφθηκαν εμπειρικά (και επιβεβαιώθηκαν στον πηγαίο κώδικα του Joomla,
`plugins/webservices/media` + `api/components/com_media`) τα εξής, που δεν
ήταν προφανή/τεκμηριωμένα:

- Κάθε request στο API **πρέπει** να έχει header
  `Accept: application/vnd.api+json` — χωρίς αυτό, γυρνάει **415 Unsupported
  Media Type** πριν καν φτάσει σε Joomla-level λογική.
- `POST /content/articles` χρειάζεται υποχρεωτικά πεδίο `"language": "*"`
  (αλλιώς 400 `Field 'language' doesn't have a default value`).
- Το media upload **δεν** είναι multipart/form-data. Είναι:
  ```
  POST /api/index.php/v1/media/files
  Content-Type: application/json

  {
    "path": "local-images:/mail-posts/filename.jpg",
    "content": "<base64-encoded περιεχόμενο αρχείου>"
  }
  ```
  Το πραγματικό public URL της εικόνας επιστρέφεται στο πεδίο
  `data.attributes.thumb_path` της απάντησης.
- Τα διαθέσιμα adapter ids ανακαλύπτονται μέσω
  `GET /api/index.php/v1/media/adapters` — σε αυτό το site είναι
  **`local-images`** (φάκελος `images/`) και **`local-files`** (φάκελος
  `files/`), όχι `local-documents` όπως θα περίμενε κανείς.
- `POST /tags` χρειάζεται `parent_id` (π.χ. `1` για root), `language`, και
  `description` (έστω κενό `""`) — χωρίς αυτά γυρνάει 400 με διαφορετικό
  μήνυμα κάθε φορά ανά πεδίο που λείπει.
- **Media upload χρειάζεται query param `mediatypes`.** Χωρίς αυτό, το
  Joomla εσωτερικά κάνει default σε `mediatypes=0` (**μόνο εικόνες**) και
  απορρίπτει *οποιοδήποτε* pdf/docx/xlsx/txt με το γενικό μήνυμα `"Invalid
  path or file type not allowed"` — ανεξάρτητα από τι λένε τα "Allowed
  Extensions"/"Legal MIME Types" στα Media Options (ξοδεύτηκε πολύς χρόνος
  σε αυτό γιατί το μήνυμα σφάλματος παραπέμπει σε λάθος αιτία). Βρέθηκε
  διαβάζοντας το `ApiModel::isMediaFile()` στον πηγαίο κώδικα του Joomla.
  Λύση: στέλνουμε πάντα `?mediatypes=0,1,2,3` (όλοι οι τύποι) σε κάθε
  upload request.
- Τα non-image uploads (`local-files`) **δεν** επιστρέφουν `thumb_path` στο
  response (μόνο οι εικόνες το έχουν, μέσω thumbnail generation). Το
  public URL χτίζεται manually ως
  `{WEBSITE_URL}/{adapter χωρίς το "local-" πρόθεμα}/{path}` — π.χ. adapter
  `local-files` → φάκελος `files/`.
- `GET /tags?filter[title]=...` **δεν φιλτράρει τίποτα** server-side —
  επιστρέφει όλα τα tags με pagination (20/σελίδα) ανεξαρτήτως filter. Αν
  ψάχνεις tag πέρα από τα πρώτα 20, δεν θα το βρεις και θα προσπαθήσεις να
  το ξαναδημιουργήσεις (→ 400 `"Another Tag has the same alias"`). Λύση:
  `?page[limit]=100` και client-side match στο title.

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
