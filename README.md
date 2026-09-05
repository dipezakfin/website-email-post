# website-email-post

Διαβάζει νέα emails από ένα κοινό Gmail mailbox και τα δημοσιεύει
αυτόματα ως άρθρα σε site Joomla (μέσω του Joomla Web Services API).

Ενσωματωμένο στο κεντρικό dashboard (`dashboard/apps/website-email-post/`) —
ίδιο pattern με τα υπόλοιπα apps: κεντρικό `.env`, κοινό GUI shell (dark
mode, tabs, live progress/pause/stop), tile στο κεντρικό dashboard.py.

**Η πραγματική, συνεχής (24/7) εκτέλεση γίνεται μέσω GitHub Actions**
(`.github/workflows/check-mail.yml`, κάθε 5 λεπτά) — όχι μέσω του τοπικού
Windows server, αφού αυτός δεν μένει πάντα ανοιχτός. Το τοπικό GUI/CLI
παραμένει διαθέσιμο για χειροκίνητους ελέγχους, testing, και reprocess. Βλ.
ενότητα "GitHub Actions" παρακάτω.

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
   - **Read More**: αν `WEBSITE_POST_READMORE_AFTER_PARAGRAPHS` > 0, μπαίνει
     αυτόματα ο ίδιος διαχωριστής που βάζει το κουμπί "Read more" του Joomla
     editor, μετά την Ν-οστή παράγραφο (όχι λέξεις — δεν ρισκάρει να κόψει
     HTML tag στη μέση). `0` (default) = απενεργοποιημένο, ολόκληρο το
     άρθρο φαίνεται στη λίστα κατηγορίας. Δεν υπάρχει εγκατεστημένο
     plugin στο site που να το κάνει αυτό αυτόματα — ελέγχθηκαν και τα
     170 plugins, μόνο το χειροκίνητο κουμπί του editor υπάρχει.
4. Δημοσιεύει το άρθρο μέσω του Joomla API (ως draft ή published, ανάλογα με
   `WEBSITE_POST_DEFAULT_STATUS`).
   **Ειδοποιήσεις** (αν `WEBSITE_POST_NOTIFY_TELEGRAM=YES` και/ή υπάρχουν
   emails στο `WEBSITE_POST_NOTIFY_EMAIL_ADDRESSES` — Telegram bot / Gmail
   SMTP με τα ίδια credentials του mailbox, best-effort, ποτέ δεν
   μπλοκάρουν την ίδια την επεξεργασία) σε τρεις περιπτώσεις:
   - ✅ Επιτυχής ανάρτηση — τίτλος + **link του άρθρου**
   - ⚠️ Μη εγκεκριμένος αποστολέας προσπάθησε να ποστάρει
   - ❌ Σφάλμα επεξεργασίας μηνύματος

   Αυτές πάνε στον **διαχειριστή** (`WEBSITE_POST_NOTIFY_EMAIL_ADDRESSES`/
   Telegram). Αν θες να ενημερώνεται και ο **ίδιος ο αποστολέας** —
   χωρίς να χρειάζεται να ρωτήσει αν "πέρασε" το μήνυμά του — βάλε
   `WEBSITE_POST_REPLY_TO_SENDER=YES`: στέλνεται πραγματικό reply
   (In-Reply-To/References, `Re:` subject) στο ίδιο thread, με το link
   του άρθρου αν αναρτήθηκε ή γενική ενημέρωση αν απέτυχε (χωρίς
   τεχνικές λεπτομέρειες — αυτές μένουν μόνο στην admin ειδοποίηση).
   **Δεν** στέλνεται σε μη εγκεκριμένους αποστολείς (Skipped).
5. Μετακινεί το email σε φάκελο `Processed` (αναρτήθηκε), `Skipped` (μη
   εγκεκριμένος αποστολέας) ή `Failed` (σφάλμα) στο mailbox, ώστε να μην
   ξανα-επεξεργαστεί στο επόμενο run. Το `Skipped` είναι ξεχωριστό από το
   `Processed` ακριβώς για να είναι εύκολο να βρεις/επανεπεξεργαστείς ένα
   μη εγκεκριμένο μήνυμα αφού προσθέσεις τον αποστολέα στη whitelist,
   χωρίς να ψάχνεις ανάμεσα σε πραγματικά αναρτημένα άρθρα.
6. Καταγράφει κάθε ενέργεια σε CSV log (`WEBSITE_POST_LOG_FILE_PATH`,
   default `logs/post_log.csv`) — εμφανίζεται και στο tab "Έλεγχος Mail" του GUI.

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

## Ρυθμίσεις

Όλες οι ρυθμίσεις διαβάζονται από το **κεντρικό** `dashboard/.env` (πρόθεμα
`WEBSITE_POST_*`, συν `WEBSITE_URL`/`WEBSITE_PLATFORM`) — όχι από τοπικό
`.env` μέσα στο app folder. Πιο εύκολος τρόπος να τις δεις/αλλάξεις: άνοιξε το
GUI (tile "Website Email Post" στο κεντρικό dashboard, ή standalone βλ.
παρακάτω) → tab **"⚙ Ρυθμίσεις"** → επεξεργασία πεδίων → **"💾 Αποθήκευση στο
.env"**. Οι αλλαγές γράφονται κατευθείαν στο κεντρικό `dashboard/.env`.

### Gmail στοιχεία

- Ενεργοποίησε IMAP: Gmail → Settings → **Forwarding and POP/IMAP** → Enable IMAP.
- Χρειάζεται **App Password** (όχι το κανονικό password του λογαριασμού):
  Google Account → **Security** → ενεργοποίησε **2-Step Verification** αν δεν
  είναι ήδη → **App passwords** → δημιούργησε ένα νέο (π.χ. όνομα
  "website-email-post") και βάλε το 16-χαρακτήρων αποτέλεσμα στο πεδίο
  Password/App Password.
- Συνιστάται ξεχωριστός Gmail λογαριασμός αφιερωμένος μόνο σε αυτή τη
  λειτουργία, όχι προσωπικός λογαριασμός κανενός.

### Joomla στοιχεία

- **API Token**: Users → Manage → επιλογή χρήστη → tab "Joomla API Token" →
  Generate. Ο χρήστης πρέπει να είναι στην ομάδα **Super Users** (βλ. §4
  παρακάτω) και να έχει δικαίωμα δημιουργίας άρθρων στην κατηγορία-στόχο.
- **Category ID**: Content → Categories, το ID φαίνεται στη λίστα/στο URL επεξεργασίας.
- **Media adapters**: `GET /api/index.php/v1/media/adapters` δίνει τα
  πραγματικά ids (π.χ. `local-images`, `local-files`).

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
**exclude/whitelist** για το static IP του Windows server που τρέχει το app.

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
- `GET /content/articles?filter[category_id]=X` χρειάζεται `page[limit]`
  (όχι `list[limit]`) για να περιορίσει τα αποτελέσματα — το `list[limit]`
  αγνοείται σιωπηλά (επιστρέφει πάντα 20, ανεξαρτήτως τιμής).
- **`PATCH /content/articles/{id}` αγνοεί σιωπηλά το πεδίο `articletext`**
  (αυτό δουλεύει μόνο σε `POST`/create). Για να αλλάξεις το σώμα ενός
  ήδη υπάρχοντος άρθρου, στείλε ξεχωριστά τα πραγματικά DB πεδία:
  `introtext` (το κείμενο πριν το Read More) και `fulltext` (το κείμενο
  μετά) — αν το άρθρο δεν έχει Read More marker, βάλε όλο το κείμενο σε
  `introtext` και `fulltext: ""`. Αν στείλεις μόνο `articletext`, το
  PATCH επιστρέφει 200 αλλά **δεν αλλάζει τίποτα** — παραπλανητικό, δεν
  δίνει κανένα σφάλμα.
- `PATCH` μπορεί να αποτύχει με 400
  `"Check-out failed... does not match the user who checked out"` ακόμα
  κι όταν το `GET` δείχνει `checked_out: null` — λύση: System →
  Maintenance → Global Check-in στο admin (ή απλά άνοιξε/κλείσε το
  άρθρο στο admin UI).
- **413 "Request Entity Too Large" σε media uploads πάνω από ~1MB.**
  Δεν είναι το nginx `client_max_body_size` (ήδη 128MB) — είναι το
  **ModSecurity `SecRequestBodyNoFilesLimit`** (default 1MB,
  εφαρμόζεται σε non-multipart/JSON POST bodies σαν το δικό μας).
  Επιβεβαιώθηκε από το error log:
  `Request body no files data length is larger than the configured
  limit (1048576)`. Χρειάζεται να αυξηθεί από την τεχνική υποστήριξη
  του hosting (δεν είναι ρύθμιση στο control panel — ελέγχθηκε τόσο το
  nginx body-size setting όσο και το Imunify360 firewall, κανένα από
  τα δύο δεν είναι η αιτία). Μέχρι τότε, βλ. "Μεγάλα συνημμένα"
  παρακάτω για το client-side workaround.

## Μεγάλα συνημμένα (μέχρι να λυθεί το hosting limit)

Όσο ισχύει το παραπάνω 1MB όριο, το script προσπαθεί να μικρύνει τα
συνημμένα πριν το upload, ελεγχόμενο από το GUI (fieldset "Μεγάλα
συνημμένα"):

- **`WEBSITE_POST_MAX_ATTACHMENT_KB`** (default `700`) — όριο σε KB,
  πάνω από αυτό ενεργοποιούνται τα παρακάτω.
- **`WEBSITE_POST_SHRINK_LARGE_IMAGES`** (YES/NO, default YES) — αν μια
  εικόνα είναι ακόμα πάνω από το όριο μετά το κανονικό resize, μειώνει
  περαιτέρω ποιότητα (μέχρι 20%) και μετά πλάτος (μέχρι 400px) μέχρι να
  χωρέσει.
- **`WEBSITE_POST_ZIP_LARGE_FILES`** (YES/NO, default YES) — συμπιέζει
  σε zip πριν το upload. **Γνωστός περιορισμός**: δουλεύει καλά για
  doc/txt/csv, αλλά **σχεδόν καθόλου για xlsx/docx/pdf** — είναι ήδη
  συμπιεσμένα εσωτερικά (επιβεβαιώθηκε: πραγματικό xlsx 2366KB →
  2335KB μετά το zip, ουσιαστικά καμία διαφορά). Αγνοείται τελείως αν
  είναι ενεργό το Google Drive παρακάτω.

## Google Drive για μη-εικόνα συνημμένα (λύση στο 1MB όριο)

Αντί να περιμένουμε το hosting fix ή να βασιζόμαστε στο ατελές zip
mitigation, **όλα** τα μη-εικόνα συνημμένα (xlsx, docx, pdf, κ.λπ.)
μπορούν να ανεβαίνουν κατευθείαν σε Google Drive αντί για το Joomla —
αυτό παρακάμπτει εντελώς το ModSecurity όριο, αφού το upload δεν
περνάει καθόλου από το site. Ρυθμίζεται στο GUI (fieldset "Google
Drive για συνημμένα"):

- **`WEBSITE_POST_GDRIVE_ENABLED`** (YES/NO, default NO) — όταν YES,
  ΟΛΑ τα μη-εικόνα συνημμένα ανεβαίνουν σε Drive (όχι μόνο τα μεγάλα),
  και οι ρυθμίσεις ζιπαρίσματος από πάνω αγνοούνται.
- **`WEBSITE_POST_GDRIVE_FOLDER_ID`** — το ID του φακέλου Drive
  (κοινόχρηστου με Editor δικαίωμα με τον λογαριασμό που έκανε το
  OAuth setup παρακάτω).
- **`WEBSITE_POST_GDRIVE_OAUTH_TOKEN_JSON`** — το authorized-user
  token JSON (με `refresh_token`), βλ. setup παρακάτω.

Τα αρχεία ανεβαίνουν ως view-only ("anyone with the link") και το URL
τους μπαίνει στο άρθρο αντί για link προς το Joomla media.

### Γιατί OAuth και όχι service account

Αρχική προσπάθεια με service account (ίδιο μοτίβο με
`sol-decl-extract`/`sol-decl-lookup`) **απέτυχε**: τα service accounts
δεν έχουν δικό τους αποθηκευτικό χώρο σε προσωπικό (μη-Workspace)
Google Drive και το upload αποτυγχάνει πάντα με
`storageQuotaExceeded`, ανεξάρτητα από το ότι ο φάκελος είναι
κοινόχρηστος με Editor δικαίωμα (δουλεύει μόνο με Shared Drives, που
απαιτούν Google Workspace subscription — δεν υπάρχει εδώ, προσωπικός
Gmail λογαριασμός).

Λύση: OAuth **ως ο πραγματικός χρήστης** (ίδιο μοτίβο με το upload
του app-publisher), με προ-παραγόμενο refresh token ώστε να δουλεύει
headless μέσα στο GitHub Actions, χωρίς browser/interactive login σε
κάθε run.

### Εφάπαξ setup (μία φορά, τοπικά)

1. Google Drive → δημιούργησε φάκελο (π.χ. "Email Post Attachments"),
   μοιράσου τον με Editor δικαίωμα με τον εαυτό σου (ήδη δικός σου) —
   απλά κράτα το ID του από το URL.
2. Τρέξε τοπικά: `python gdrive_oauth_setup.py` (μέσα στον φάκελο της
   εφαρμογής). Ανοίγει browser, κάνε login/έγκριση με τον προσωπικό σου
   Google λογαριασμό. Χρησιμοποιεί το ίδιο OAuth Client (Desktop app)
   με το app-publisher (`../app-publisher/gdrive-oauth-credentials.json`)
   — δεν χρειάζεται νέο Google Cloud project.
3. Το script τυπώνει (και αποθηκεύει τοπικά) το token JSON. Επικόλλησέ
   το στο πεδίο "OAuth Token JSON" του GUI, μαζί με το Folder ID, και
   ενεργοποίησε τον διακόπτη.

### OAuth consent screen — "Testing" vs "In production"

Αν το OAuth Client (Google Cloud Console → APIs & Services → OAuth
consent screen → tab "Audience") είναι σε κατάσταση **"Testing"**, τα
refresh tokens λήγουν σε ~7 μέρες — θα σταματούσε το αυτόματο ανέβασμα
κάθε εβδομάδα. **Πρέπει να είναι "In production"** (κουμπί "PUBLISH
APP" στο tab Audience). Αυτό απαιτεί, στο tab "Branding":

- Application home page: `https://dipe.zak.sch.gr`
- Privacy policy link: πραγματική σελίδα με ουσιαστικό περιεχόμενο
  (φτιάχτηκε άρθρο στο ίδιο το Joomla site, id 1778, μη-featured,
  εξηγεί τι δεδομένα συλλέγει η εφαρμογή μέσω του scope `drive.file`)
- App name: να ταιριάζει με το όνομα που εμφανίζεται στο home page
  (`Διεύθυνση Πρωτοβάθμιας Εκπαίδευσης Ζακύνθου`)
- **Home page domain πρέπει να είναι verified στο Google Search
  Console** (Add property → URL prefix → HTML file upload method →
  ανέβασμα του verification αρχείου στο root του site μέσω FTP).
- Το λογότυπο (π.χ. εθνόσημο) μπορεί να απορριφθεί ως "δεν
  αναγνωρίζει μοναδικά το brand" (κοινό σε πολλά public-sector sites)
  — απλά μην ανεβάσεις λογότυπο, δεν είναι υποχρεωτικό πεδίο.

Μετά το "In production", ξανατρέξε το `gdrive_oauth_setup.py` μία
ακόμα φορά ώστε το token να εκδοθεί υπό το νέο καθεστώς (τα ήδη
εκδομένα tokens από όσο ήταν σε Testing μπορεί να κρατήσουν την
7ήμερη λήξη).

### Αποθηκευτικός χώρος — ειδοποίηση (χωρίς αυτόματο καθαρισμό)

Ο προσωπικός Gmail λογαριασμός έχει όριο **15GB δωρεάν χώρο**
(μοιρασμένο Gmail+Drive+Photos). Δεν υπάρχει αυτόματος καθαρισμός
παλιών συνημμένων στο Drive — σκόπιμα, ώστε να μη σβηστεί ποτέ κάτι
που ίσως χρειάζεται ακόμα κάποιο δημοσιευμένο άρθρο. Αντί γι' αυτό, σε
κάθε `run_check_mail()` γίνεται έλεγχος ποσοστού χρήσης
(`check_gdrive_storage_and_notify()`) και στέλνεται ειδοποίηση
(ίδιο κανάλι με τις υπόλοιπες — Telegram/email) όταν η χρήση φτάσει το
**`WEBSITE_POST_GDRIVE_STORAGE_ALERT_PERCENT`** (default `90`). Η
ειδοποίηση στέλνεται μία φορά (marker αρχείο δίπλα στο log) και
ξαναστέλνεται μόνο αν το ποσοστό πέσει κάτω από το όριο και μετά το
ξαναπεράσει — δεν σε ενοχλεί σε κάθε run των 5 λεπτών.

### Ονόματα αρχείων

Το `sanitize_filename()` περικόπτει το όνομα (κρατώντας την επέκταση)
σε max 100 bytes UTF-8 — τα ελληνικά ονόματα παίρνουν 2 bytes/χαρακτήρα,
οπότε ένα φαινομενικά λογικό όνομα μπορεί εύκολα να ξεπεράσει το όριο
μήκους filename του server (συνήθως 255 bytes, λιγότερο με το
`unique_prefix` που προστίθεται μπροστά).

## Χρήση

### Μέσα από το κεντρικό dashboard

Tile "Website Email Post" στο κεντρικό dashboard.py → κλικ ανοίγει το GUI
(tabs: Ρυθμίσεις / Έλεγχος Mail / Βοήθεια).

### Standalone GUI

```
cd dashboard\apps\website-email-post
python website-email-post-gui.py --standalone
```
Ανοίγει browser στο `http://127.0.0.1:5049/`.

### CLI (headless — ό,τι τρέχει και το Windows Task Scheduler)

```
cd dashboard\apps\website-email-post
python website-email-post.py
python website-email-post.py --dry-run   # δοκιμή, χωρίς πραγματική ανάρτηση/μετακίνηση
```

### Πρώτη δοκιμή (χωρίς να δημιουργηθούν πραγματικά άρθρα)

Ενεργοποίησε το toggle **DRY RUN** στο tab Ρυθμίσεις (ή `--dry-run` στο CLI),
στείλε ένα δοκιμαστικό email, και τρέξε έναν έλεγχο (κουμπί "📧 Έλεγχος mail
τώρα" στο GUI, ή το CLI). Έλεγξε το log για να επιβεβαιώσεις ότι το mail
διαβάζεται και μορφοποιείται σωστά, πριν ενεργοποιήσεις πραγματικές
αναρτήσεις.

> Σημείωση: σε DRY RUN mode τα emails **δεν** μετακινούνται σε
> Processed/Failed, ώστε να μπορείς να ξανατρέξεις τον έλεγχο στο ίδιο μήνυμα.

## GitHub Actions (η πραγματική 24/7 εκτέλεση)

`.github/workflows/check-mail.yml` τρέχει το `website-email-post.py`
**αυτούσιο, χωρίς καμία αλλαγή**, κάθε 5 λεπτά, σε GitHub-hosted runner —
δουλεύει ανεξάρτητα από το αν είναι ανοιχτός ο τοπικός υπολογιστής.

- **Ρυθμίσεις**: όλες οι `WEBSITE_POST_*`/`WEBSITE_URL`/`WEBSITE_PLATFORM`
  τιμές περνάνε ως **GitHub Actions Secrets** (Settings → Secrets and
  variables → Actions, στο repo `dipezakfin/website-email-post`) — mirror
  του κεντρικού `dashboard/.env`.
  - **Από το GUI**: το κουμπί "💾 Αποθήκευση στο .env" (tab Ρυθμίσεις)
    ενημερώνει **αυτόματα και τα δύο** — το τοπικό `.env` **και** τα
    αντίστοιχα GitHub Secrets (μέσω `gh` CLI, που πρέπει να είναι
    εγκατεστημένο και συνδεδεμένο ως ο λογαριασμός `dipezakfin` στον
    υπολογιστή που τρέχει το GUI). Το αποτέλεσμα εμφανίζεται δίπλα στο
    κουμπί (πόσα secrets ενημερώθηκαν/απέτυχαν).
  - **Χειροκίνητα** (π.χ. αν αλλάξεις κάτι απευθείας στο `.env` με editor,
    ή δεν έχεις πρόσβαση στο GUI):
    ```
    gh secret set ΟΝΟΜΑ_ΜΕΤΑΒΛΗΤΗΣ --repo dipezakfin/website-email-post
    ```
    (θα ζητήσει την τιμή interactive, ή δώσ' την μέσω pipe:
    `echo "τιμή" | gh secret set ΟΝΟΜΑ --repo dipezakfin/website-email-post`)

    Ή μέσω browser: [github.com/dipezakfin/website-email-post/settings/secrets/actions](https://github.com/dipezakfin/website-email-post/settings/secrets/actions)
    → βρες το secret στη λίστα → **Update** → νέα τιμή → **Update secret**.
    Τα secrets δεν εμφανίζονται ποτέ ξανά μετά την αποθήκευση, μόνο
    αντικατάσταση.
- **Log**: το `logs/post_log.csv` **δεν** γίνεται commit πίσω στο repo —
  περιέχει πραγματικά emails αποστολέων/θέματα, και το git history είναι
  μόνιμο (ακόμα κι αν διαγραφεί αργότερα το αρχείο, παραμένει σε παλιά
  commits). Το log μένει μόνο μέσα στο Actions run output (ορατό μόνο στο
  repo, με αυτόματη λήξη μετά από κάποιο διάστημα — GitHub default
  retention για private repos, ~90 μέρες) — προσωρινό, όχι μόνιμο.
  Για πλήρες μόνιμο ιστορικό, χρησιμοποίησε το τοπικό GUI (tab "Έλεγχος
  Mail" → "Πρόσφατες αναρτήσεις") όταν τρέχεις χειροκίνητα.
- **Χειροκίνητο τρέξιμο**: Actions tab στο GitHub repo → "Check mail and
  post to Joomla" → "Run workflow", ή `gh workflow run check-mail.yml --repo dipezakfin/website-email-post`.
- **Concurrency**: αν ένα run είναι ακόμα σε εξέλιξη όταν πυροδοτήσει το
  επόμενο scheduled, το νέο μπαίνει σε ουρά (δεν τρέχουν ποτέ δύο ταυτόχρονα).
- ⚠️ **Το εσωτερικό `schedule:` trigger του GitHub Actions είναι "best
  effort" — ΔΕΝ αξιόπιστο.** Παρατηρήθηκαν πραγματικά κενά **2-7+ ωρών**
  ανάμεσα σε runs (όχι "λίγα λεπτά" καθυστέρηση όπως θα περίμενε κανείς),
  ειδικά σε private repos με συχνό interval. Το `cron: '*/5 * * * *'`
  παραμένει στα workflow αρχεία σαν αδύναμο fallback, αλλά η
  **πραγματική, αξιόπιστη** εκτέλεση κάθε 5 λεπτά γίνεται μέσω
  εξωτερικού trigger — βλ. παρακάτω.
- **Interval**: 5 λεπτά — το ελάχιστο που υποστηρίζει το GitHub Actions
  για scheduled workflows. Δεν είναι ρύθμιση στο GUI (θα σήμαινε το GUI
  να κάνει commit/push στο ίδιο το workflow αρχείο). Για αλλαγή,
  επεξεργάσου απευθείας τη γραμμή `cron:` σε κάθε workflow αρχείο.

### Αξιόπιστο 5λεπτο interval: εξωτερικό trigger (cron-job.org)

Αντί να βασιζόμαστε στο (αναξιόπιστο) `schedule:` trigger, ένα δωρεάν
εξωτερικό cron service καλεί απευθείας το GitHub API
(`workflow_dispatch`) κάθε 5 λεπτά — αυτό το path τρέχει σχεδόν άμεσα,
χωρίς την υποβάθμιση προτεραιότητας του εσωτερικού scheduler.

**Ρύθμιση (μία φορά):**

1. **GitHub Personal Access Token** (fine-grained, μόνο για αυτό το repo):
   [github.com/settings/personal-access-tokens/new](https://github.com/settings/personal-access-tokens/new)
   → Resource owner: `dipezakfin` → Repository access: μόνο
   `website-email-post` → Permissions → Actions: **Read and write** →
   Generate.

   > ⚠️ **Λήγει στις 31/8/2027.** Μετά χρειάζεται νέο token (ίδια
   > βήματα) και ενημέρωση του header στο cron-job.org — τίποτα άλλο.

2. Δωρεάν λογαριασμός: [console.cron-job.org/signup](https://console.cron-job.org/signup)
   (το URL άλλαξε πρόσφατα από το παλιό `cron-job.org/en/signup/`)

3. Δύο ξεχωριστά cronjobs (ένα ανά workflow), κάθε 5 λεπτά, `POST`:

   | | check-mail | telegram-bot |
   |---|---|---|
   | URL | `.../actions/workflows/check-mail.yml/dispatches` | `.../actions/workflows/telegram-bot.yml/dispatches` |

   Πλήρες URL: `https://api.github.com/repos/dipezakfin/website-email-post/actions/workflows/<αρχείο>/dispatches`

   **Headers (και τα δύο cronjobs):**
   ```
   Authorization: Bearer <το PAT>
   Accept: application/vnd.github+json
   Content-Type: application/json
   ```
   **Body:** `{"ref":"master"}`

Επιβεβαιώθηκε ότι δουλεύει: τα runs πλέον εμφανίζονται ως
`workflow_dispatch` (όχι `schedule`) σε πραγματικά ~5λεπτα διαστήματα.

## Telegram bot — γρήγορο publish/unpublish

`telegram_bot.py` + `.github/workflows/telegram-bot.yml` (ίδιο pattern με
το `check-mail.yml`: polling κάθε 5 λεπτά, GitHub-hosted runner). Δεν
χρειάζεται να ανοίξεις το GUI/dashboard — απλά στέλνεις μήνυμα στο bot.

**Εντολές:**
- `/list` — λίστα πρόσφατων άρθρων, το καθένα με inline κουμπιά
  📢 Publish / 📝 Unpublish (καμία πληκτρολόγηση ID)
- `/publishlast` / `/unpublishlast` — άμεση ενέργεια στο πιο πρόσφατο άρθρο
- `/publish <id>` / `/unpublish <id>` — συγκεκριμένο άρθρο (π.χ. `/publish 1773`)

**Ρύθμιση (μία φορά):**
1. Telegram → μίλα στο **@BotFather** → `/newbot` → πάρε το token
2. `gh secret set TELEGRAM_BOT_TOKEN --repo dipezakfin/website-email-post`
3. Στείλε ένα οποιοδήποτε μήνυμα στο καινούριο bot, μετά βρες το chat_id
   σου μέσω `https://api.telegram.org/bot<TOKEN>/getUpdates`
   (πεδίο `message.chat.id`)
4. `gh secret set TELEGRAM_ALLOWED_CHAT_IDS --repo dipezakfin/website-email-post`
   (comma-separated αν θες να εξουσιοδοτήσεις παραπάνω από έναν λογαριασμό)

Μόνο τα chat ids στο `TELEGRAM_ALLOWED_CHAT_IDS` γίνονται δεκτά — οποιοσδήποτε
άλλος παίρνει ευγενική άρνηση. Καθόλου δικό μας persisted state για το
ποια Telegram updates έχουν ήδη επεξεργαστεί — χρησιμοποιείται το δικό
του server-side offset mechanism του Telegram (getUpdates).

### Ένα κλικ unpublish — χωρίς να χρειάζεται το id του άρθρου

Δύο επιπλέον τρόποι για κάποιον που δεν ξέρει/δεν θέλει να ψάξει το id:

- **Telegram**: κάθε ειδοποίηση "Νέα ανάρτηση" έχει ήδη ενσωματωμένο
  inline κουμπί **🗑 Unpublish** πάνω στο ίδιο μήνυμα (`notify_posted()`
  στο `website_email_post_core.py`) — ένα tap, τίποτα άλλο. Χρησιμοποιεί
  το ίδιο callback mechanism (`u:<id>`) που ήδη χειρίζεται το
  `telegram_bot.py` για το `/list`.
- **Email**: όταν είναι ενεργό το `WEBSITE_POST_REPLY_TO_SENDER`, το
  email επιβεβαίωσης προς τον αποστολέα περιλαμβάνει ένα one-click
  unpublish link, π.χ.
  `https://dipe.zak.sch.gr/email-post/unpublish.php?id=1786&token=...`.

**Πώς δουλεύει το link** (`article_unpublish_link()` στο core.py): το
token είναι HMAC-SHA256(μυστικό κλειδί, article_id) — ρυθμίζεται από το
GUI (`WEBSITE_POST_UNPUBLISH_LINK_SECRET`, fieldset "Ειδοποιήσεις
ανάρτησης"). Δεν χρειάζεται να ρυθμιστεί για να δουλέψουν τα υπόλοιπα —
αν είναι κενό, απλά δεν μπαίνει link στο email.

Το link δείχνει σε ένα μικρό PHP endpoint (`email-post/unpublish.php`)
deployed **πάνω στο ίδιο το Joomla site** μέσω FTP (όχι στο GitHub
Actions/GUI — έπρεπε να είναι κάπου πάντα-ενεργό ώστε να απαντάει σε
ένα κλικ από email, και το site είναι ήδη αυτό). Το script επαληθεύει
το token πριν κάνει οτιδήποτε (timing-safe `hash_equals`) και μπορεί
**μόνο** να κάνει unpublish (`state=0`) στο ακριβές article id του
link — τίποτα άλλο δεν είναι εφικτό, ακόμα κι αν αλλάξει κανείς το id
στο URL χωρίς το σωστό token (403). Αν ποτέ αλλάξει το
`WEBSITE_POST_UNPUBLISH_LINK_SECRET`, πρέπει να ενημερωθεί το ίδιο
secret και μέσα στο `unpublish.php` στον server (ξαναανέβασμα μέσω
FTP), αλλιώς τα νέα links θα αποτυγχάνουν με 403.

## Windows Task Scheduler (εναλλακτικό, τοπικό — προαιρετικό)

Χρήσιμο μόνο αν κάποια στιγμή ο υπολογιστής **μένει πάντα ανοιχτός** και
θέλεις επιπλέον/εναλλακτικό τοπικό trigger. Δεν χρειάζεται για την κανονική
λειτουργία, αφού αυτή καλύπτεται ήδη από το GitHub Actions.

1. Task Scheduler → Create Task.
2. **General**: "Run whether user is logged on or not", "Run with highest privileges".
3. **Triggers**: New → Begin the task "On a schedule" → Repeat task every
   `10 minutes`, for a duration of `Indefinitely`.
4. **Actions**: New → Start a program:
   - Program/script: `python` (ή το πλήρες path στο python.exe που χρησιμοποιεί το dashboard)
   - Add arguments: `website-email-post.py`
   - Start in: `D:\dipezakfin\dashboard\apps\website-email-post`
5. **Settings**: ενεργοποίησε "If the task is already running, do not start a
   new instance" (ώστε να μην τρέχουν παράλληλα δύο runs).

## Log

CSV αρχείο (`WEBSITE_POST_LOG_FILE_PATH`, default `logs/post_log.csv`) με
στήλες: `timestamp, email_from, email_subject, status,
joomla_article_id, attachments_count, error_message`.

`status` ∈ `POSTED`, `SKIPPED_NOT_WHITELISTED`, `ERROR`. Το tab "Έλεγχος Mail"
του GUI δείχνει τις τελευταίες 50 γραμμές.

Ξεχωριστά, το `website-email-post.log` (μορφή `RunLogger`) είναι αυτό που
διαβάζει το tile status στο κεντρικό dashboard.py.

## Ασφάλεια

- Το `.env` (κεντρικό, `dashboard/.env`) **δεν** ανεβαίνει ποτέ στο repo.
- Χρησιμοποιείται ξεχωριστός/κοινός mailbox — όχι προσωπικός λογαριασμός
  κανενός. Η πρόσβαση σε ανάρτηση ελέγχεται αποκλειστικά μέσω
  `WEBSITE_POST_WHITELIST_EMAIL_ADDRESSES` (email του αποστολέα), όχι μέσω
  διαμοιρασμού κωδικών.
