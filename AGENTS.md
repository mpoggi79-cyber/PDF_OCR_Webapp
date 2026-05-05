# PDF OCR Webapp — Agent Instructions

## Panoramica

Web app locale che converte PDF e immagini raster in Markdown tramite **`glm-ocr:latest`** eseguito su **Ollama locale**.

- **Backend**: FastAPI con entrypoint leggero in `app.py` e logica suddivisa nei moduli `backend/`
- **Frontend**: Vanilla JS/HTML/CSS in `static/` — nessun framework, nessun bundler
- **Input supportati**: PDF, PNG, JPG, JPEG
- **OCR**: Ollama locale su `http://localhost:11434` con modello `glm-ocr:latest`
- **Storage**: file system in `uploads/<uuid>/` — nessun database

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

```
app.py                        ← entrypoint FastAPI e wiring degli endpoint
backend/
  config.py                   ← costanti applicative e percorsi
  documents.py                ← upload, conversione PDF, supporto immagini, metadata
  ocr.py                      ← avvio OCR e chiamata a Ollama
  batch.py                    ← workflow batch, report, export ZIP
  state.py                    ← stato OCR in memoria e rebuild da disco
requirements.txt              ← dipendenze Python runtime
static/
  index.html                  ← SPA principale
  app.js                      ← logica frontend, polling OCR, upload, batch, drag & drop
  tooltip.js / tooltip.css    ← tooltip standalone
  style.css                   ← stile UI
uploads/<doc_id>/
  metadata.json               ← {doc_id, filename, page_count, source_type, ...}
  pages/page_N.<ext>          ← pagina renderizzata o immagine originale
  ocr/page_N.md               ← risultato OCR per pagina
```

## Convenzioni importanti

- **Pagine 0-indexed**: `page_0.*` e `page_0.md` sia nel backend che nel frontend.
- **Backend modulare**: mantenere la struttura esistente in `backend/`; non ricondensare tutto in `app.py` senza richiesta esplicita.
- **Frontend senza build**: `static/app.js` è ES6 puro caricato direttamente dal browser. Non introdurre npm, bundler o transpiler.
- **Supporto immagini**: un upload immagine genera un documento a pagina singola con `source_type = image`.
- **Storage file-based**: usare `uploads/<doc_id>/` come fonte di verità persistente; niente database locale aggiuntivo salvo richiesta esplicita.
- **Stato OCR in memoria**: `ocr_status` viene ricostruito da disco a ogni riavvio; `batch_registry` resta solo in memoria e si perde al riavvio.
- **CORS wildcard**: configurato per sviluppo locale, non restringerlo senza richiesta.
- **OCR asincrono**: l'OCR parte via `BackgroundTasks`; il client fa polling con `GET /api/ocr/{doc_id}/{page_num}`.
- **Batch solo PDF**: la modalità batch accetta file PDF multipli; il supporto immagini è al momento per upload singolo.

## API Endpoints

| Metodo | Path | Descrizione |
|--------|------|-------------|
| GET | `/` | Serve la SPA principale |
| GET | `/api/health` | Stato Ollama + disponibilità glm-ocr |
| POST | `/api/upload` | Carica PDF o immagine → restituisce metadata documento |
| GET | `/api/documents/{doc_id}` | Metadati documento + stato OCR per pagina |
| GET | `/api/page/{doc_id}/{page_num}` | Restituisce l'immagine della pagina o l'immagine originale |
| GET | `/api/ocr/{doc_id}/{page_num}` | Legge il risultato OCR di una pagina |
| POST | `/api/ocr/{doc_id}/{page_num}` | Avvia OCR su una pagina |
| GET | `/api/export/{doc_id}` | Export Markdown unificato del documento |
| POST | `/api/batch` | Carica più PDF → `{batch_id, docs, errors}` |
| POST | `/api/batch/{batch_id}/start` | Avvia OCR su tutto il batch |
| GET | `/api/batch/{batch_id}` | Stato avanzamento batch |
| GET | `/api/batch/{batch_id}/report` | Report Markdown del batch |
| GET | `/api/batch/{batch_id}/export` | ZIP con tutti i Markdown del batch |

## Dipendenze esterne

- **PyMuPDF (`fitz`)**: rendering PDF → immagine pagina, matrice 2× circa 144 DPI.
- **httpx**: client HTTP asincrono verso Ollama.
- **Ollama**: deve girare localmente; `glm-ocr` è multimodale e accetta immagini in base64.
