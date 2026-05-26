# PDF OCR Webapp — Agent Instructions

## Panoramica

Web app locale che converte PDF e immagini raster in Markdown tramite **`glm-ocr:latest`** eseguito su **Ollama locale**. Supporta persistenza e ripresa dei job OCR e batch dopo riavvio del server, oltre a diagnostica strutturata degli errori OCR.

- **Backend**: FastAPI con entrypoint leggero in `app.py` e logica suddivisa nei moduli `backend/`
- **Frontend**: Vanilla JS/HTML/CSS in `static/` — nessun framework, nessun bundler
- **Input supportati**: PDF, PNG, JPG, JPEG
- **OCR**: Ollama locale su `http://localhost:11434` con modello `glm-ocr:latest`
- **Storage**: file system in `uploads/<uuid>/` — nessun database; stato job e batch persistiti localmente
- **Persistenza**: job OCR ripresi dopo crash; batch ricostituito da disco
- **Diagnostica OCR**: gli errori pagina vengono classificati e resi leggibili sia via API sia nel pannello frontend

## Avvio

```bat
start.bat          # crea .venv, installa dipendenze, lancia uvicorn
```

oppure manualmente:

```bat
.venv\Scripts\activate
uvicorn app:app --reload
```

Ollama deve essere già in esecuzione con `ollama serve` e il modello deve essere disponibile con `ollama pull glm-ocr:latest`.

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
uploads/_batches/
  <batch_id>.json             ← indice batch persistente {docs, created_at, status}
```

## Convenzioni importanti

- **Pagine 0-indexed**: `page_0.*` e `page_0.md` sia nel backend che nel frontend.
- **Backend modulare**: mantenere la struttura esistente in `backend/`; non ricondensare tutto in `app.py` senza richiesta esplicita.
- **Frontend senza build**: `static/app.js` è ES6 puro caricato direttamente dal browser. Non introdurre npm, bundler o transpiler.
- **Supporto immagini**: un upload immagine genera un documento a pagina singola con `source_type = image`.
- **Storage file-based e persistente**: usare `uploads/<doc_id>/` e `uploads/_batches/` come fonte di verità; i markdown pagina per pagina rimangono il contenuto OCR immutabile; niente database locale aggiuntivo.
- **Stato OCR persistente**: `ocr_status` viene ricostruito da disco a ogni riavvio leggendo i markdown; `ocr_jobs` viene ricostruito/ripreso da `job_state.json`; `batch_registry` viene ripristinato dai file batch in `uploads/_batches/`. Qualsiasi pagina rimasta in processing durante un crash viene normalizzata a pending e il job a interrupted.
- **Semantica resume post-crash**: un job documento non terminato dopo riavvio viene esposto con flag `interrupted=true` e `resumable=true` se ci sono pagine pending; una nuova richiesta POST avvia la ripresa solo dai pending; un batch ricostruito da disco mantiene lo stesso batch_id e riavvia solo i documenti incompleti.
- **Campi aggiuntivi API**: i payload job documentale, job pagina e batch includono campi opzionali `interrupted`, `resumable` e `updated_at` per compatibilità con il resume; il payload pagina OCR può includere anche `error` con diagnostica strutturata (`source`, `type`, `label`, `interpretation`, `detail`, `retryable`).
- **Diagnostica errori OCR**: `backend/ocr.py` distingue almeno timeout, servizio Ollama non raggiungibile, modello non trovato, errore interno runtime del modello, assert GGML e errori locali di I/O/backend; il frontend mostra queste informazioni nel pannello OCR senza rompere il flusso esistente.
- **CORS wildcard**: configurato per sviluppo locale, non restringerlo senza richiesta.
- **OCR asincrono**: l'OCR parte via `BackgroundTasks`; il client fa polling con `GET /api/ocr/{doc_id}/{page_num}`; il progresso job è tracciato via `GET /api/ocr-job/{doc_id}`.
- **Batch solo PDF**: la modalità batch accetta file PDF multipli; il supporto immagini è al momento per upload singolo. Lo stato batch persiste su disco per sopravvivere a restart.

## API Endpoints

| Metodo | Path | Descrizione |
| ------ | ---- | ----------- |
| GET | `/` | Serve la SPA principale |
| GET | `/api/health` | Stato Ollama + disponibilità glm-ocr |
| POST | `/api/upload` | Carica PDF o immagine → restituisce metadata documento |
| GET | `/api/documents/{doc_id}` | Metadati documento + stato OCR per pagina |
| GET | `/api/page/{doc_id}/{page_num}` | Restituisce l'immagine della pagina o l'immagine originale |
| GET | `/api/ocr/{doc_id}/{page_num}` | Legge il risultato OCR di una pagina; in caso di errore restituisce anche diagnostica strutturata |
| POST | `/api/ocr/{doc_id}/{page_num}` | Avvia OCR su una pagina |
| GET | `/api/export/{doc_id}` | Export Markdown unificato del documento |
| POST | `/api/batch` | Carica più PDF → `{batch_id, docs, errors}` |
| POST | `/api/batch/{batch_id}/start` | Avvia OCR su tutto il batch; riprende documenti incompleti se post-restart |
| GET | `/api/batch/{batch_id}` | Stato avanzamento batch; ricostituito da disco se non in memoria |
| GET | `/api/batch/{batch_id}/report` | Report Markdown del batch |
| GET | `/api/batch/{batch_id}/export` | ZIP con tutti i Markdown del batch; rilegge da disco se post-restart |

## Dipendenze esterne

- **PyMuPDF (`fitz`)**: rendering PDF → immagine pagina, matrice 2× circa 144 DPI.
- **httpx**: client HTTP asincrono verso Ollama.
- **Ollama**: deve girare localmente; `glm-ocr` è multimodale e accetta immagini in base64.

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
