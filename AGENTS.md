# PDF OCR Webapp — Agent Instructions

## Panoramica

Questa web app converte PDF e immagini raster in Markdown usando OCR locale tramite Ollama e il provider `glmocr`. Il focus del progetto non è solo completare il job OCR, ma ottimizzare la fedeltà del contenuto preservando struttura, tabelle, formule, heading e layout quando il provider li restituisce in modo affidabile.

### Componenti principali

- Backend: FastAPI in `app.py` e moduli in `backend/`
- Frontend: Vanilla JS/HTML/CSS in `static/`
- Input supportati: PDF, PNG, JPG, JPEG
- OCR provider primario: `glmocr` self-hosted
- Fallback: `glm-ocr:v0.1.5` e chiamata HTTP diretta a Ollama
- Persistenza: file system in `uploads/`, senza database locale
- Diagnostica: classificazione degli errori OCR e resume post-crash

## Priorità del lavoro

1. Mantenere la qualità OCR come obiettivo principale.
2. Mantenere il backend robusto e persistente.
3. Mantenere compatibilità delle API e dell'export.
4. Aggiungere feature OCR solo quando migliorano il documento finale.

### Regole pratiche

- I documenti strutturati devono preservare heading, liste, tabelle, formule e contenuti form-like.
- Il Markdown pagina per pagina resta la fonte canonica; i sidecar JSON sono metadata opzionali.
- I campi di output strutturato devono essere aggiunti senza rompere client esistenti.
- Le pagine sono 0-indexed.
- La persistenza è file-based in `uploads/`.
- `capabilities` indica ciò che il provider restituisce davvero, non ciò che il backend ha configurato.
- Quando si modifica il flusso OCR, verificare sia il ramo `glmocr` sia il fallback HTTP a Ollama.
- Se si tocca il prompt SDK, conservare i task ufficiali `Text Recognition:`, `Table Recognition:` e `Formula Recognition:`.

## Avvio

```powershell
start.bat
```

oppure manualmente:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn app:app --host 0.0.0.0 --port 8080 --reload --reload-exclude .venv --reload-exclude uploads --reload-exclude tests
```

Ollama deve essere già in esecuzione e il modello primario deve essere presente:

```powershell
ollama serve
ollama pull glm-ocr:latest
ollama pull glm-ocr:v0.1.5
```

## Struttura dei file

```text
app.py
backend/
  config.py
  documents.py
  ocr.py
  batch.py
  state.py
static/
uploads/
requirements.txt
start.bat
AGENTS.md
README.md
```

## Convenzioni operative

- `uploads/<doc_id>/` è la fonte di verità per runtime e resume.
- `metadata.json` contiene metadata documento e prompt profile.
- `job_state.json` traccia stato del job e flags `interrupted` / `resumable`.
- `ocr/page_N.md` contiene il markdown canonico della pagina.
- `ocr/page_N.json` contiene metadata OCR strutturati opzionali.
- I batch persistono in `uploads/_batches/<batch_id>.json`.
- Il batch incrementale usa `init -> files -> complete -> start`.
- Le pagine in `processing` dopo crash vengono normalizzate a `pending`.
- Il resume riparte solo dalle pagine `pending`.

## Prompt OCR e profili

I profili attualmente supportati sono:

- `default`
- `structured_document`
- `structured_document_no_html` (default operativo)
- `web_article`

Il backend usa `prompt_profile` come parametro opzionale e salva il profilo scelto nei metadata del documento.

## Ispezione layout

- La UI `Layout` visualizza le bbox che il provider restituisce nel sidecar della pagina, con filtri per testo, immagini, tabelle e formule.
- Nei documenti multipagina l'overlay deve seguire la pagina selezionata e leggere il relativo `ocr/page_N.json`; non deve limitarsi alla prima pagina.
- Le regioni del sidecar devono avere `page` uguale all'indice zero-based della pagina elaborata, anche se il provider restituisce indici locali o `page: 0` per ogni risposta separata.
- Per compatibilita', il frontend puo' usare il contesto del file sidecar `page_N.json` per visualizzare risultati generati prima della normalizzazione del campo `page`.
- Le bbox sono evidenza di segmentazione del provider, non una validazione della qualita' o completezza della struttura.
- Il testo contenuto in una regione tabella non ha bbox di celle o parole separate, salvo che il provider le restituisca esplicitamente.
- Non derivare regioni dal Markdown e non introdurre crop OCR supplementari: ogni pagina viene elaborata una sola volta sull'immagine rasterizzata completa.
- Il layout detector di `glmocr` restituisce solo `bbox_2d`, normalizzato 0-1000 per asse rispetto alla pagina rasterizzata, mai in pixel reali. Il backend converte queste coordinate in pixel effettivi in `backend/ocr.py` (`_get_image_pixel_size` + `_scale_normalized_bbox`) prima di scriverle nel sidecar; non trattare mai `bbox` come già in pixel senza questa conversione.

## Test ufficiali

I casi ufficiali sono descritti in [tests/Elenco e descrizione test.md](tests/Elenco%20e%20descrizione%20test.md) e organizzati in `tests/official/`.

Comandi principali:

```powershell
.venv\Scripts\python.exe tests\run_official_tests.py --list
.venv\Scripts\python.exe tests\run_official_tests.py --check-structure
.venv\Scripts\python.exe tests\run_official_tests.py --case T002 --exact-case
.venv\Scripts\python.exe tests\run_official_tests.py --case T002 --exact-case --compare-only
```

Regole:

- `--exact-case` è obbligatorio quando l'ID corrisponde a un gruppo.
- `--check-structure` verifica solo la struttura dei casi senza contattare il backend.
- `--compare-only` confronta `actual` con `expected` senza eseguire nuovo OCR.
- I casi ufficiali devono essere verificati visivamente prima di consolidare `expected` diversi dal comportamento attuale.

## Baseline note

- T002 e T002A verificano il profilo `structured_document_no_html` con PDF scannerizzati sia ruotati sia non ruotati.
- T006 e T006B verificano la pipeline PDF multipagina con rendering `2.0` e una sola elaborazione OCR per pagina.
- T010 e T011 sono casi di calibrazione geometrica per l'overlay `Layout` (blocchi noti e tabella con origine 0,0); T011 ha confermato il fix dello scaling bbox 0-1000 -> pixel descritto sopra.
- T013 documenta un limite noto del layout detector: su pagine con testo sparso su sfondo perlopiu' bianco, la soglia di confidenza di default (`pipeline.layout.threshold = 0.3`) non trova alcuna regione e il markdown risulta vuoto anche se il testo e' leggibile. Abbassare la soglia globale non e' una correzione valida: a 0.01 emerge una sola regione grossolana che copre l'intera pagina e recupera solo parte del testo.
- I benchmark non devono essere usati come prova di qualità se un documento non è stato verificato visivamente.

## Verifica e validazione

Dopo modifiche Python, è consigliabile eseguire almeno:

```powershell
.venv\Scripts\python.exe -m py_compile app.py backend\ocr.py backend\state.py backend\batch.py backend\documents.py
```

Quando possibile eseguire anche:

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Per modifiche sul flusso OCR, verificare anche il comportamento end-to-end con Ollama e il provider coinvolto, compreso il fallback.

## Linea guida per interventi

- Se una modifica aumenta la fedeltà del documento convertito, ha priorità.
- Se una modifica non migliora il contenuto OCR, va considerata secondaria rispetto alla qualità del parsing.
- Ogni nuova feature OCR deve preservare persistenza, export e resume post-crash.
- Non introdurre nuove astrazioni se non sono necessarie al problema in corso.
- Mantenere la soluzione semplice, locale e file-based come richiesto dal progetto.
