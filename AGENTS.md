# PDF OCR Webapp — Agent Instructions

## Panoramica

Web app che converte pagine PDF in immagini e le invia al modello **`glm-ocr:latest`** su **Ollama locale** per estrarre testo in formato Markdown pulito.

- **Backend**: FastAPI (`app.py`) — unico file, tutti gli endpoint
- **Frontend**: Vanilla JS/HTML/CSS (`static/`) — nessun framework, nessun bundler
- **OCR**: Ollama in locale su `http://localhost:11434` con modello `glm-ocr:latest`
- **Storage**: file system (`uploads/<uuid>/`) — nessun database

## Avvio

```bat
start.bat          # crea .venv, installa dipendenze, lancia uvicorn
```

oppure manualmente:

```bat
.venv\Scripts\activate
uvicorn app:app --reload
```

Ollama deve essere già in esecuzione (`ollama serve`) con il modello scaricato (`ollama pull glm-ocr`).

## Struttura chiave

```
app.py                        ← backend FastAPI (tutto il server)
requirements.txt              ← fastapi, uvicorn, pymupdf, httpx, python-multipart
static/
  index.html                  ← SPA principale
  app.js                      ← logica frontend (stato, polling OCR, batch)
  tooltip.js / tooltip.css    ← sistema tooltip standalone
  style.css
uploads/<doc_id>/
  document.pdf
  metadata.json               ← {doc_id, filename, page_count, [batch_id]}
  pages/page_N.png            ← pagine renderizzate a 2× (≈144 DPI)
  ocr/page_N.md               ← risultato OCR (Markdown)
```

## Convenzioni importanti

- **Pagine 0-indexed**: `page_0.png`, `page_0.md` — sia nel backend che nel frontend.
- **Stato OCR in memoria**: `ocr_status: dict[str, dict[int, str]]` viene ricostruito da disco a ogni riavvio; il **batch registry** (`batch_registry`) è solo in memoria e si perde al riavvio.
- **Un solo file backend**: tutta la logica server sta in `app.py`. Non creare moduli aggiuntivi a meno che non venga richiesto esplicitamente.
- **Frontend senza build**: `static/app.js` è ES6 puro, caricato direttamente dal browser. Non introdurre npm/bundler.
- **CORS wildcard**: configurato per sviluppo locale — non modificare senza indicazione.
- **OCR asincrono**: le chiamate Ollama avvengono in `BackgroundTasks`; il client fa polling con `GET /api/ocr/{doc_id}/{page_num}`.

## API Endpoints

| Metodo | Path | Descrizione |
|--------|------|-------------|
| GET | `/api/health` | Stato Ollama + disponibilità glm-ocr |
| POST | `/api/upload` | Carica PDF → restituisce `{doc_id, filename, page_count}` |
| GET | `/api/documents/{doc_id}` | Metadati + stato OCR per pagina |
| GET | `/api/page/{doc_id}/{page_num}` | Immagine PNG della pagina (0-indexed) |
| GET | `/api/ocr/{doc_id}/{page_num}` | Leggi risultato OCR |
| POST | `/api/ocr/{doc_id}/{page_num}` | Avvia OCR su una pagina |
| GET | `/api/export/{doc_id}` | Export Markdown unificato di tutte le pagine |
| POST | `/api/batch` | Carica più PDF → `{batch_id, docs, errors}` |
| POST | `/api/batch/{batch_id}/start` | Avvia OCR su tutto il batch |
| GET | `/api/batch/{batch_id}/status` | Stato avanzamento batch |
| GET | `/api/batch/{batch_id}/export` | ZIP con tutti i Markdown del batch |

## Dipendenze esterne

- **PyMuPDF (`fitz`)**: rendering PDF → PNG. Matrice 2× = ≈144 DPI, buon equilibrio qualità/dimensione.
- **httpx**: client HTTP asincrono per chiamare Ollama.
- **Ollama**: deve girare localmente; il modello `glm-ocr` è multimodale (accetta immagini in base64).
