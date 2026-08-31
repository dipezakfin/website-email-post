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
- Το GitHub Actions cron δεν εγγυάται ακριβές timing σε φορτωμένες περιόδους
  (μπορεί να καθυστερήσει λίγα λεπτά) — αποδεκτό για αυτή τη χρήση.
- **Interval**: τρέχει κάθε **5 λεπτά** (`cron: '*/5 * * * *'` στο
  `check-mail.yml`) — το ελάχιστο που υποστηρίζει το GitHub Actions για
  scheduled workflows, δεν χωράει πιο συχνό. Δεν είναι ρύθμιση στο GUI
  (θα σήμαινε το GUI να κάνει commit/push στο ίδιο το workflow αρχείο —
  πολύ περισσότερη πολυπλοκότητα απ' ό,τι αξίζει, δεδομένου ότι είμαστε
  ήδη στο ταχύτερο δυνατό). Για αλλαγή, επεξεργάσου απευθείας τη γραμμή
  `cron:` στο `.github/workflows/check-mail.yml`.

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
