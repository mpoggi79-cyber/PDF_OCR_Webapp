# PDF OCR Webapp — Agent Instructions

## Panoramica

Web app locale che converte PDF e immagini raster in Markdown tramite **`glm-ocr:latest`** eseguito su **Ollama locale**. Supporta persistenza e ripresa dei job OCR e batch dopo riavvio del server, oltre a diagnostica strutturata degli errori OCR. La priorita' di prodotto non e' solo far terminare il job, ma ottenere la conversione piu' fedele possibile sfruttando tutte le funzionalita' disponibili del modello OCR.

- **Backend**: FastAPI con entrypoint leggero in `app.py` e logica suddivisa nei moduli `backend/`
- **Frontend**: Vanilla JS/HTML/CSS in `static/` — nessun framework, nessun bundler
- **Input supportati**: PDF, PNG, JPG, JPEG
- **OCR**: Ollama locale su `http://localhost:11434` con modello primario `glm-ocr:latest` e fallback `glm-ocr:v0.1.5`
- **Storage**: file system in `uploads/<uuid>/` — nessun database; stato job e batch persistiti localmente
- **Persistenza**: job OCR ripresi dopo crash; batch ricostituito da disco
- **Diagnostica OCR**: gli errori pagina vengono classificati e resi leggibili sia via API sia nel pannello frontend

## Priorita' Correnti

- **Qualita' di conversione prima di tutto**: quando si interviene sul backend OCR o sul frontend dei risultati, privilegiare la fedelta' del contenuto estratto; tabelle, formule, heading, liste, immagini e layout devono essere preservati il piu' possibile. Evitare scorciatoie che semplificano l'output a scapito della struttura del documento.

- **Usare tutte le feature OCR disponibili del modello quando migliorano il risultato**: prioritizzare integrazione di layout visualization, crop regions, metadata strutturali, formule, tabelle, handwriting e confidence se esposte dal modello o dall'SDK. Se una feature richiede campi opzionali o nuove chiavi API, aggiungerle in modo compatibile senza rompere il flusso esistente.

- **Mantenere robustezza e resume come vincoli di base**: retry, error classification, persistenza job e resume post-crash restano obbligatori, ma sono un requisito di affidabilita', non il fine ultimo del prodotto.

- **Integrare l'SDK `glmocr` solo quando porta un vantaggio OCR concreto**: se l'SDK consente accesso a funzionalita' migliori rispetto alla chiamata HTTP diretta, valutarne l'adozione. Se non porta un miglioramento tangibile di qualita' o struttura dell'output, evitare complessita' inutile.

## Avvio

```bat
start.bat          # crea .venv, installa dipendenze, lancia uvicorn
```

oppure manualmente:

```bat
.venv\Scripts\activate
uvicorn app:app --reload
```

Ollama deve essere gia' in esecuzione con `ollama serve` e il modello deve essere disponibile con `ollama pull glm-ocr:latest`. Il backend puo' fare fallback a `glm-ocr:v0.1.5` se il tag principale non e' disponibile.

## Test ufficiali OCR

I casi ufficiali sono descritti in [tests/Elenco e descrizione test.md](tests/Elenco%20e%20descrizione%20test.md) e organizzati in `tests/official/`. Il runner usa le API HTTP del backend locale, quindi per un test OCR reale devono essere attivi sia FastAPI sia Ollama.

Comandi principali da eseguire dalla radice del progetto:

```powershell
.venv\Scripts\python.exe tests\run_official_tests.py --list
.venv\Scripts\python.exe tests\run_official_tests.py --check-structure
.venv\Scripts\python.exe tests\run_official_tests.py --case T002 --exact-case
.venv\Scripts\python.exe tests\run_official_tests.py --case T002 --exact-case --compare-only
```

- `--exact-case` e' obbligatorio quando l'ID coincide con un gruppo: senza questa opzione `--case T002` esegue T002, T002A e T002B.
- `--check-structure` controlla `case.json`, `input`, `expected` e `actual` senza contattare il backend.
- `--compare-only` confronta gli actual gia' presenti con gli expected e aggiorna i report, senza eseguire nuovo OCR.
- Il confronto e' testuale esatto. Prima di consolidare un expected diverso dall'attuale, eseguire una verifica visiva del risultato e controllare heading, liste, tabelle, formule, immagini e ordine di lettura.
- Il runner salva i risultati in `actual/last_run.json` e nei report riepilogativi in `tests/official/results/`; non usare i file in `uploads/` come expected del dataset.
- La data nella tabella dei test rappresenta l'ultima esecuzione OCR; un successivo `--compare-only` aggiorna il confronto ma non cambia quella data.

### Baseline verificata T002

- T002 usa `structured_document_no_html` e `page_rotation = 90`: il PDF scannerizzato viene ruotato durante la rasterizzazione prima dell'OCR.
- T002A usa lo stesso profilo con `page_rotation = 0` e conserva l'orientamento nativo del PDF.
- L'actual di T002 ruotato coincide byte-per-byte con l'expected consolidato di T002A; dopo la verifica visiva, anche l'expected di T002 e' stato consolidato e il confronto ufficiale risulta `match`.
- Con il profilo no-HTML le tabelle devono essere pipe-delimited Markdown e l'output non deve contenere tag HTML; questa proprieta' va verificata nell'actual prima di aggiornare expected.

## Struttura chiave

```text
app.py                        ← entrypoint FastAPI e wiring degli endpoint
backend/
  config.py                   ← costanti applicative e percorsi
  documents.py                ← upload, conversione PDF, supporto immagini, metadata
  ocr.py                      ← avvio OCR, chiamata a Ollama, classificazione errori OCR
  batch.py                    ← workflow batch, report, export ZIP
  state.py                    ← stato OCR in memoria, rebuild da disco, persistenza job/batch
requirements.txt              ← dipendenze Python runtime
static/
  index.html                  ← SPA principale
  app.js                      ← logica frontend, polling OCR, upload, batch, drag & drop, diagnostica errori OCR
  tooltip.js / tooltip.css    ← tooltip standalone
  style.css                   ← stile UI e pannello diagnostico errore OCR
uploads/<doc_id>/
  metadata.json               ← {doc_id, filename, page_count, source_type, batch_id, ...}
  job_state.json              ← stato persistente del job OCR {status, done_pages, error_pages, ...}
  pages/page_N.<ext>          ← pagina renderizzata o immagine originale
  ocr/page_N.md               ← risultato OCR per pagina o markdown di errore con metadata diagnostici
  ocr/page_N.json             ← sidecar opzionale con metadata OCR strutturati di successo e capability osservate
uploads/_batches/
  <batch_id>.json             ← indice batch persistente {docs, created_at, status}
```

## Convenzioni importanti

- **Pagine 0-indexed**: `page_0.*` e `page_0.md` sia nel backend che nel frontend.
- **Backend modulare**: mantenere la struttura esistente in `backend/`; non ricondensare tutto in `app.py` senza richiesta esplicita.
- **Frontend senza build**: `static/app.js` è ES6 puro caricato direttamente dal browser. Non introdurre npm, bundler o transpiler.
- **Supporto immagini**: un upload immagine genera un documento a pagina singola con `source_type = image`; gli upload PDF possono usare il parametro opzionale `page_rotation` (`0`, `90`, `180` o `270`) per correggere scansioni ruotate prima dell'OCR.
- **Storage file-based e persistente**: usare `uploads/<doc_id>/` e `uploads/_batches/` come fonte di verità; i markdown pagina per pagina rimangono il contenuto OCR immutabile; i sidecar JSON OCR sono metadata opzionali, non sostituiscono l'export canonico; niente database locale aggiuntivo.
- **Stato OCR persistente**: `ocr_status` viene ricostruito da disco a ogni riavvio leggendo i markdown; `ocr_jobs` viene ricostruito/ripreso da `job_state.json`; `batch_registry` viene ripristinato dai file batch in `uploads/_batches/`. Qualsiasi pagina rimasta in processing durante un crash viene normalizzata a pending e il job a interrupted.
- **Semantica resume post-crash**: un job documento non terminato dopo riavvio viene esposto con flag `interrupted=true` e `resumable=true` se ci sono pagine pending; una nuova richiesta POST avvia la ripresa solo dai pending; un batch ricostruito da disco mantiene lo stesso batch_id e riavvia solo i documenti incompleti.
- **Campi aggiuntivi API**: i payload job documentale, job pagina e batch includono campi opzionali `interrupted`, `resumable` e `updated_at` per compatibilità con il resume; il payload pagina OCR può includere anche `error` con diagnostica strutturata (`source`, `type`, `label`, `interpretation`, `detail`, `retryable`) e campi OCR strutturati opzionali come `layout_visualization`, `crop_regions`, `table_regions`, `formula_regions`, `confidence`, `capabilities` e `structure_metadata`. `capabilities` descrive le feature realmente restituite dal provider, senza confondere un'opzione configurata con un dato disponibile.
- **Diagnostica errori OCR**: `backend/ocr.py` distingue timeout, `ollama_unreachable`, `model_not_found`, `model_runtime_assert`, `service_unavailable`, `api_error` e errori locali di I/O/backend; il frontend mostra queste informazioni nel pannello OCR senza rompere il flusso esistente.
- **CORS wildcard**: configurato per sviluppo locale, non restringerlo senza richiesta.
- **OCR asincrono**: l'OCR parte via `BackgroundTasks`; il client fa polling con `GET /api/ocr/{doc_id}/{page_num}`; il progresso job è tracciato via `GET /api/ocr-job/{doc_id}`.
- **Batch solo PDF**: la modalità batch accetta file PDF multipli; il supporto immagini è al momento per upload singolo. Lo stato batch persiste su disco per sopravvivere a restart.

## Profili Prompt OCR

Il backend supporta profili prompt selezionabili per adattare l'OCR al tipo di documento senza rompere gli endpoint esistenti.

- **Profili attuali**:
  - `structured_document`: profilo consigliato per documenti bancari, moduli, fatture, ricevute e PDF con tabelle o campi; e' anche il default operativo usato dal frontend quando il client non passa `prompt_profile`.
  - `structured_document_no_html`: variante che forza output Markdown senza tag HTML e converte le tabelle HTML restituite dal provider in tabelle pipe-delimited.
  - `default`: comportamento OCR generico, adatto a documenti normali, scansioni e PDF non fortemente web-centrici.
  - `web_article`: profilo piu' aggressivo per PDF stampati da pagine web, con istruzioni per ignorare menu, ads, widget, footer e boilerplate del sito.
- **Selezione backward-compatible**: il client puo' passare `prompt_profile` come query parameter opzionale sugli endpoint di upload e avvio OCR.
- **Persistenza del profilo**: il profilo scelto viene salvato nei metadata documento e riusato per retry, resume e nuove esecuzioni salvo override esplicito.
- **Prompt canonici SDK**: il provider `glmocr` usa i prompt ufficiali `Text Recognition:`, `Table Recognition:` e `Formula Recognition:` per il riconoscimento specializzato per regioni; i profili locali piu' descrittivi restano disponibili per la pagina completa e per il fallback HTTP a Ollama.
- **Compatibilita'**: ogni estensione futura dei prompt deve preservare l'API attuale e mantenere un comportamento predefinito stabile e documentato quando il parametro non e' fornito.

## Direzione Tecnica OCR

- **Output target**: Markdown strutturato e semanticamente ricco, non semplice testo lineare.
- **Elementi da preservare**: heading, paragrafi, elenchi, tabelle, formule, immagini, didascalie e blocchi speciali.
- **Feature da integrare appena possibile**:
  - `need_layout_visualization`
  - `return_crop_images`
  - output formule in LaTeX
  - output tabelle in HTML o Markdown strutturato
  - region metadata e bounding boxes
  - confidence score o segnali di qualita' equivalenti
- **Regola di priorita'**: se una modifica aumenta la qualita' del parsing del documento senza compromettere compatibilita' e persistenza, va considerata prioritaria rispetto a rifiniture secondarie UI.

## API Endpoints

| Metodo | Path | Descrizione |
| ------ | ---- | ----------- |
| GET | `/` | Serve la SPA principale |
| GET | `/api/health` | Stato Ollama + disponibilita' modello OCR primario/fallback |
| POST | `/api/upload` | Carica PDF o immagine → restituisce metadata documento; supporta `prompt_profile` e `page_rotation` opzionali |
| GET | `/api/documents/{doc_id}` | Metadati documento + stato OCR per pagina |
| GET | `/api/page/{doc_id}/{page_num}` | Restituisce l'immagine della pagina o l'immagine originale |
| GET | `/api/ocr/{doc_id}/{page_num}` | Legge il risultato OCR di una pagina; in caso di errore restituisce anche diagnostica strutturata |
| POST | `/api/ocr/{doc_id}/{page_num}` | Avvia OCR su una pagina; supporta `prompt_profile` opzionale |
| GET | `/api/ocr-job/{doc_id}` | Stato complessivo OCR del documento |
| POST | `/api/ocr-job/{doc_id}` | Avvia o riprende OCR dell'intero documento; supporta `prompt_profile` opzionale |
| GET | `/api/export/{doc_id}` | Export Markdown unificato del documento |
| POST | `/api/batch` | Carica più PDF → `{batch_id, docs, errors}`; supporta `prompt_profile` opzionale |
| POST | `/api/batch/{batch_id}/start` | Avvia OCR su tutto il batch; riprende documenti incompleti se post-restart; supporta `prompt_profile` opzionale |
| GET | `/api/batch/{batch_id}` | Stato avanzamento batch; ricostituito da disco se non in memoria |
| GET | `/api/batch/{batch_id}/report` | Report Markdown del batch |
| GET | `/api/batch/{batch_id}/export` | ZIP con tutti i Markdown del batch; rilegge da disco se post-restart |

## Dipendenze esterne

- **PyMuPDF (`fitz`)**: rendering PDF → immagine pagina, matrice 2× circa 144 DPI.
- **httpx**: client HTTP asincrono verso Ollama.
- **Ollama**: deve girare localmente; `glm-ocr` e' multimodale e accetta immagini in base64.
- **GLM-OCR SDK (`glmocr`)**: provider OCR primario in modalita' self-hosted; mantenere il fallback HTTP diretto a Ollama per compatibilita' e resilienza.

La prima verifica reale del percorso SDK e' stata eseguita il 22 agosto 2026 su T001/T001B con `glmocr 0.1.5` e `glm-ocr:latest`: il provider ha restituito regioni testuali e tabelle con bounding box. Nella configurazione locale verificata non sono risultati popolati layout visualization, crop images o confidence; queste feature non devono essere considerate disponibili finche' un test dedicato non le conferma.

## Persistenza e Resume Post-Crash

A partire da maggio 2026, la webapp persiste lo stato dei job OCR e batch, consentendo la ripresa automatica dopo riavvio del server:

- **Job documento**: salvato in `uploads/<doc_id>/job_state.json` con status, block_size, pagine completate/errore/pending, flag interrupt e resumable.
- **Batch**: salvato in `uploads/_batches/<batch_id>.json` come indice dei documenti e stato riassuntivo.
- **Pagine in recovery**: qualsiasi pagina rimasta in stato `processing` dopo un crash viene normalizzata a `pending`; il job viene marcato `interrupted=true` e `resumable=true`.
- **Ripresa deterministica**: un nuovo POST `/api/ocr-job/{doc_id}` o `POST /api/batch/{batch_id}/start` riparte esclusivamente dalle pagine `pending`, lasciando intatte le pagine già completate o in errore.
- **Fallback da metadata**: se il file batch è smarrito ma i documenti contengono `batch_id` nei metadata, il batch viene ricostruito automaticamente.
- **Export invariato**: la logica di export documento ed export batch continua a leggere unicamente dai markdown in `uploads/<doc_id>/ocr/page_N.md`, garantendo coerenza e assenza di duplicazioni.

## Diagnostica Errori OCR

La webapp, a partire da fine maggio 2026, espone una diagnostica OCR più esplicita sia nel backend sia nel frontend:

- **Formato errore persistito**: in caso di errore OCR, `uploads/<doc_id>/ocr/page_N.md` contiene un blocco markdown di errore e un metadata header HTML con payload JSON serializzato.
- **Payload API pagina**: `GET /api/ocr/{doc_id}/{page_num}` restituisce `status`, `markdown` e, in caso di errore, un oggetto `error` con chiavi `source`, `type`, `label`, `interpretation`, `detail`, `retryable` ed eventualmente `http_status`.
- **Interpretazione errori modello**: errori come `GGML_ASSERT(...) failed` vengono classificati come `model_runtime_assert`, cioè crash del runtime del modello locale, non come errore generico del backend.
- **UI diagnostica**: `static/app.js` conserva `ocrErrors` per pagina e mostra una scheda diagnostica nel pannello OCR quando una pagina fallisce; il toggle raw permette comunque di leggere il markdown tecnico completo.
- **Compatibilità**: il frontend continua a funzionare anche senza usare il nuovo oggetto `error`; la diagnostica aggiuntiva è un’estensione compatibile dei payload esistenti.

## Linea Guida per Futuri Interventi

- Se il task riguarda OCR, chiedersi prima: "questa modifica migliora la fedelta' del documento convertito?"
- Se la risposta e' si, dare priorita' a struttura, formula, tabella, layout e quality metadata.
- Se la risposta e' no, trattare l'intervento come secondario rispetto alla roadmap OCR.
- Qualsiasi nuova feature OCR va progettata preservando persistenza, export e resume post-crash.
