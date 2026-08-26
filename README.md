# PDF OCR Webapp

Applicazione locale per trasformare PDF e immagini in Markdown strutturato, usando OCR tramite Ollama e il provider `glmocr` con fallback HTTP.

## Obiettivo del progetto

Questo progetto è pensato per lavorare in locale, senza dipendenze cloud, e per produrre output Markdown il più fedele possibile a:

- heading e struttura del documento
- liste e paragrafi
- tabelle e campi form-like
- formule e blocchi speciali
- layout, quando il provider lo restituisce in modo affidabile

L'architettura è semplice: FastAPI per il backend, HTML/CSS/JS vanilla per la UI, file system per la persistenza dei job. La fonte canonica di output resta il Markdown pagina per pagina salvato in `uploads/<doc_id>/ocr/`.

## Stato attuale

Le funzionalità già presenti nel codice sono:

- upload singolo di PDF, PNG, JPG e JPEG
- OCR asincrono pagina per pagina
- batch PDF con preparazione incrementale
- persistenza su disco dei job e dei batch
- resume post-crash su pagine `pending`
- profili prompt OCR configurabili
- diagnostica errori strutturata
- overlay Layout con filtri per testo, immagini, tabelle e formule quando il provider restituisce bbox
- fallback tra provider SDK e chiamata HTTP verso Ollama
- export Markdown documento e ZIP batch

## Architettura

- Backend: [app.py](app.py) + cartella [backend](backend/)
- Frontend: [static](static/)
- Persistenza: [uploads](uploads/)
- Documentazione operativa: [AGENTS.md](AGENTS.md), [README.md](README.md), [tests/official/README.md](tests/official/README.md)

### Componenti principali

- [backend/config.py](backend/config.py): costanti del sistema, prompt, timeout, fallback, scale di rendering PDF
- [backend/documents.py](backend/documents.py): upload, conversione PDF in immagini, metadata documento
- [backend/ocr.py](backend/ocr.py): orchestrazione OCR, provider, retry, gestione errori
- [backend/batch.py](backend/batch.py): workflow batch, preparazione, avvio e report
- [backend/state.py](backend/state.py): stato in memoria, rebuild da disco, job_state e batch_state

## Requisiti

- Python 3.10+ disponibile nel PATH
- Ollama in esecuzione localmente
- modello OCR disponibile: `glm-ocr:latest`
- fallback supportato: `glm-ocr:v0.1.5`

Comandi utili per Ollama:

```powershell
ollama serve
ollama pull glm-ocr:latest
ollama pull glm-ocr:v0.1.5
ollama list
```

## Avvio rapido

### Opzione consigliata

```powershell
start.bat
```

### Avvio manuale

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn app:app --host 0.0.0.0 --port 8080 --reload --reload-exclude .venv --reload-exclude uploads --reload-exclude tests
```

Poi apri:

- http://localhost:8080

## Health e modello selezionato

L'endpoint `GET /api/health` verifica la disponibilità di Ollama e i modelli OCR configurati. La risposta contiene in particolare:

- `ollama`
- `glm_ocr`
- `configured_models`
- `selected_model`
- `models`
- `prompt_profiles`
- `default_prompt_profile`

Esempio:

```json
{
  "ollama": "ok",
  "glm_ocr": "available",
  "configured_models": ["glm-ocr:latest", "glm-ocr:v0.1.5"],
  "selected_model": "glm-ocr:latest",
  "models": ["glm-ocr:latest", "llama3.2:3b"],
  "prompt_profiles": ["default", "structured_document", "structured_document_no_html", "web_article"],
  "default_prompt_profile": "structured_document_no_html"
}
```

## Provider OCR, fallback e retry

Il backend usa il seguente ordine operativo:

1. provider primario `glmocr` con `glm-ocr:latest`
2. fallback configurato verso `glm-ocr:v0.1.5`
3. fallback diretto HTTP verso Ollama
4. classificazione e persistenza dell'errore se tutti i tentativi falliscono

Parametri attuali di configurazione:

- timeout OCR: `240.0` secondi
- retry massimi: `2`
- backoff base: `0.5` secondi
- block size documento: `10` pagine
- rendering PDF: `PDF_RENDER_SCALE = 2.0`
- ogni pagina viene elaborata una sola volta, usando l'immagine rasterizzata completa

La configurazione attuale è stata usata come baseline operativa per i casi ufficiali; la scelta di `2.0` è stata verificata come la più stabile per i PDF scannerizzati complessi.

## Profili prompt OCR

I profili disponibili sono i seguenti:

- `default`: output generico
- `structured_document`: profilo per documenti strutturati, bancari, fatture, ricevute e moduli che privilegia tabelle HTML quando utili
- `structured_document_no_html`: default operativo; usa solo Markdown e tabelle pipe-delimited
- `web_article`: ottimizzato per PDF stampati da pagine web

Questi profili possono essere passati come query parameter su endpoint di upload e di OCR:

```text
POST /api/upload?prompt_profile=structured_document
POST /api/ocr-job/{doc_id}?prompt_profile=default
POST /api/batch/{batch_id}/start?prompt_profile=web_article
```

Se non viene specificato alcun profilo, il backend usa `structured_document_no_html`.

## PDF e immagini

Supporto attuale:

- PDF
- PNG
- JPG
- JPEG

Per PDF con orientamento scorretto, il backend accetta `page_rotation` con valori `0`, `90`, `180`, `270`. La rotazione viene applicata prima dell'OCR al rendering pagina.

## Persistenza e resume post-crash

La persistenza è file-based e si basa su `uploads/`:

- `uploads/<doc_id>/metadata.json`
- `uploads/<doc_id>/job_state.json`
- `uploads/<doc_id>/ocr/page_N.md`
- `uploads/<doc_id>/ocr/page_N.json` (sidecar opzionale)
- `uploads/_batches/<batch_id>.json`

La semantica è la seguente:

- `interrupted`: il job era in corso al momento di un riavvio o crash
- `resumable`: ci sono ancora pagine `pending` da processare
- pagine lasciate in `processing` vengono normalizzate a `pending` al riavvio
- un nuovo `POST /api/ocr-job/{doc_id}` riprende solo le pagine pendenti
- un nuovo `POST /api/batch/{batch_id}/start` riprende solo i documenti incompleti

## Output OCR strutturato e diagnostica

Il backend può salvare metadata strutturate come:

- `layout_visualization`
- `crop_regions`
- `table_regions`
- `formula_regions`
- `confidence`
- `structure_metadata`
- `capabilities`

Il markdown delle pagine resta la fonte canonica. I JSON sidecar non sostituiscono l'export, ma sono utili per diagnostica e approfondimento.

Quando una pagina è in errore, l'API `GET /api/ocr/{doc_id}/{page_num}` può includere un payload `error` con campi come:

- `source`
- `type`
- `label`
- `interpretation`
- `detail`
- `retryable`
- `http_status`

I tipi attualmente classificati includono timeout, model not found, model runtime assert, Ollama unreachable, service unavailable e file I/O errors.

## Ispezione layout nella UI

Nel pannello **Documento originale**, il controllo `Layout` sovrappone all'immagine rasterizzata le regioni effettivamente restituite dal provider. I filtri indipendenti permettono di mostrare o nascondere `Testo`, `Immagini`, `Tabelle` e `Formule`.

- per un documento multipagina, l'overlay segue la pagina selezionata: navigando tra le pagine vengono lette le regioni del relativo sidecar `ocr/page_N.json`;
- i riquadri derivano da `structure_metadata.regions` del sidecar della pagina e usano le bbox fornite dal provider;
- il campo `page` delle regioni è l'indice zero-based della pagina del documento; il backend lo imposta anche quando il provider restituisce un indice locale alla singola risposta;
- i sidecar già presenti restano leggibili perché il file `page_N.json` identifica già la pagina a cui appartengono;
- il riquadro `Tabella rilevata` indica una regione classificata come tabella, non una tabella validata o ricostruita dall'app;
- il contenuto interno della tabella e' disponibile nella regione, ma non vengono disegnate celle o parole quando il provider non restituisce bbox piu' granulari;
- layout visualization, crop images e confidence sono mostrabili solo se il provider li restituisce realmente.
- il layout detector di `glmocr` restituisce le bbox normalizzate 0-1000 per asse rispetto alla pagina rasterizzata, non in pixel; il backend le riconverte in pixel reali prima di salvarle nel sidecar, cosi' l'overlay resta allineato indipendentemente dall'aspect ratio della pagina.

## Endpoint principali

| Metodo | Path | Descrizione |
| --- | --- | --- |
| GET | `/` | Serve la SPA principale |
| GET | `/api/health` | Stato di Ollama e modelli OCR |
| POST | `/api/upload` | Carica PDF o immagine |
| GET | `/api/documents/{doc_id}` | Metadati documento e stato pagine |
| GET | `/api/page/{doc_id}/{page_num}` | Restituisce l'immagine della pagina |
| GET | `/api/ocr/{doc_id}/{page_num}` | Legge il risultato OCR o l'errore |
| POST | `/api/ocr/{doc_id}/{page_num}` | Avvia OCR di una pagina |
| GET | `/api/ocr-job/{doc_id}` | Stato complessivo del documento |
| POST | `/api/ocr-job/{doc_id}` | Avvia o riprende OCR di un documento |
| GET | `/api/export/{doc_id}` | Export Markdown finale |
| POST | `/api/batch` | Upload batch atomico |
| POST | `/api/batch/init` | Inizializza batch incrementale |
| POST | `/api/batch/{batch_id}/files` | Prepara un PDF del batch |
| POST | `/api/batch/{batch_id}/complete` | Finalizza preparazione |
| POST | `/api/batch/{batch_id}/start` | Avvia OCR del batch |
| GET | `/api/batch/{batch_id}` | Stato batch |
| GET | `/api/batch/{batch_id}/report` | Report Markdown del batch |
| GET | `/api/batch/{batch_id}/export` | ZIP con i Markdown del batch |
| POST | `/api/shutdown` | Spegnimento locale del server |

## Documentazione e test

- [AGENTS.md](AGENTS.md): regole operative e vincoli tecnici del progetto
- [tests/official/README.md](tests/official/README.md): struttura del dataset ufficiale e modalità di confronto
- [tests/Elenco e descrizione test.md](tests/Elenco%20e%20descrizione%20test.md): casi di test OCR e profili attesi
- [tests/run_official_tests.py](tests/run_official_tests.py): runner dei test ufficiali

## Note di qualità

La qualità dell'OCR è prioritariamente valutata su fedeltà del contenuto, non solo su terminazione del job. In particolare l'output deve preservare:

- heading e leggibilità
- tabelle e campi form-like
- formule e blocchi strutturali
- immagini e didascalie dove il provider le restituisce
- ordine di lettura e semantica del documento

Le feature strutturate rendono il sistema più potente, ma devono essere considerate disponibili solo quando il provider le restituisce davvero e non solo quando sono configurate nel backend.

## Sviluppo e manutenzione

Per modifiche sull'OCR, sulla persistenza o sul batch:

- lavorare sempre sui moduli in [backend](backend/)
- mantenere app.py leggero
- non rompere la compatibilità API esistente
- preservare `uploads/` come fonte di verità di runtime
- mantenere export Markdown e sidecar JSON come livelli separati

## Troubleshooting

Se il servizio non parte:

1. verificare che Ollama sia attivo
2. verificare che il modello `glm-ocr:latest` sia disponibile
3. controllare `GET /api/health`
4. controllare i log del backend e il file `uploads/`

Se un PDF è ruotato o poco leggibile:

- usare `page_rotation` al momento dell'upload
- verificare il profilo `prompt_profile` corretto
- rieseguire il documento con il profilo giusto, senza alterare i markdown già completi se non necessario


## Configurazione rapida

I parametri principali sono in [backend/config.py](backend/config.py).

Modelli e provider:

- MODEL_NAME
- MODEL_FALLBACK_NAMES
- OCR_PROVIDER
- GLMOCR_MODE
- GLMOCR_LAYOUT_DEVICE
- GLMOCR_OCR_API_URL

Robustezza:

- OCR_TIMEOUT
- OCR_RETRY_MAX_ATTEMPTS
- OCR_RETRY_BACKOFF_BASE_SECONDS
- OCR_BLOCK_SIZE

Rendering PDF:

- PDF_RENDER_SCALE

Structured output:

- OCR_ENABLE_STRUCTURED_OUTPUT
- OCR_ENABLE_LAYOUT_VISUALIZATION
- OCR_RETURN_CROP_IMAGES
- OCR_INCLUDE_RAW_PROVIDER_PAYLOAD
- GLMOCR_SAVE_LAYOUT_VISUALIZATION

## Sviluppo locale

Repository attuale:

- Nessun bundler frontend.
- Nessun database.
- Nessun sistema di migrazioni.
- Stato applicativo ricostruibile da disco a ogni riavvio.

Test automatici locali:

```powershell
.venv\Scripts\python.exe -m unittest tests.test_ocr_core tests.test_markdown_cleanup -v
.venv\Scripts\python.exe -m pytest -q
python tests/run_official_tests.py --check-structure
```

I test unitari verificano le parti deterministiche del backend OCR, come classificazione degli errori,
retry/backoff, normalizzazione dei metadata strutturati e pulizia del Markdown. I test ufficiali eseguono
invece il flusso HTTP reale e richiedono backend e Ollama disponibili.

### Test ufficiali OCR

I casi ufficiali sono descritti in [tests/Elenco e descrizione test.md](tests/Elenco%20e%20descrizione%20test.md) e organizzati in `tests/official/`. Per un test OCR reale devono essere attivi il backend FastAPI e Ollama.

```powershell
.venv\Scripts\python.exe tests\run_official_tests.py --list
.venv\Scripts\python.exe tests\run_official_tests.py --check-structure
.venv\Scripts\python.exe tests\run_official_tests.py --case T002 --exact-case
.venv\Scripts\python.exe tests\run_official_tests.py --case T002 --exact-case --compare-only
```

- Usare `--exact-case` quando l'ID coincide con un gruppo: senza questa opzione `--case T002` esegue anche T002A e T002B.
- Usare `--check-structure` per controllare le cartelle standard senza contattare il backend.
- Usare `--compare-only` per confrontare actual ed expected e aggiornare i report senza eseguire nuovo OCR.
- Il confronto e' testuale esatto. Consolidare un nuovo expected solo dopo una verifica visiva di heading, liste, tabelle, formule, immagini e ordine di lettura.
- Gli actual e gli expected dei casi ufficiali sono distinti dai risultati runtime in `uploads/`; i report sono salvati in `tests/official/results/`.

Baseline verificata il 23 agosto 2026:

- T002 usa `structured_document_no_html` con `page_rotation = 90`.
- T002A usa lo stesso profilo con `page_rotation = 0` e rappresenta il riferimento in orientamento nativo.
- L'actual ruotato di T002 coincide byte-per-byte con l'expected di T002A; l'expected di T002 e' stato quindi consolidato e il confronto risulta `match`.
- In modalità no-HTML le tabelle sono pipe-delimited Markdown e l'output non contiene tag HTML.

- T006 è un PDF scannerizzato di 4 pagine, con scansione sporca e compilazione manuale; l'expected è stato verificato visivamente e il confronto risulta `match` nell'ultima esecuzione registrata.
- T006B è un PDF scannerizzato firmato e timbrato con 1 pagina disponibile; usa `structured_document_no_html` e il confronto expected/actual risulta `match`.

Supporto workspace VS Code gia' incluso:

- [.vscode/tasks.json](.vscode/tasks.json) con task per bootstrap, avvio backend, health check e compile rapido.
- [.vscode/launch.json](.vscode/launch.json) con configurazione debug FastAPI via uvicorn.
- [.vscode/extensions.json](.vscode/extensions.json) con estensioni consigliate per Python e Copilot.
- [.github/copilot-instructions.md](.github/copilot-instructions.md) con linee guida minime per agenti e completamenti coerenti con il progetto.

Controlli rapidi utili:

```powershell
python -m py_compile app.py
python -m py_compile backend\ocr.py
python -m py_compile backend\state.py
```

## Pubblicazione della repo

Il repository e' pensato per essere pubblicabile senza includere i dati OCR locali o i documenti di test reali.

Elementi esclusi dal versionamento tramite [.gitignore](.gitignore):

- uploads/
- Pdf_Test/
- .venv/
- out.txt
- nuovo piano.md
- cache, coverage e log locali

Checklist minima prima di rendere pubblica la repo:

1. Verificare `git status` e confermare che nel commit entrino solo codice, documentazione e configurazioni utili.
2. Non forzare in Git file reali di test con dati personali, OCR output locali o cartelle `uploads/`.
3. Verificare che Ollama e i modelli richiesti siano documentati in questo README.
4. Scegliere esplicitamente una licenza prima della pubblicazione pubblica, se la repo deve essere riusabile da terzi.

Flusso tipico di pubblicazione:

```powershell
git add .
git status
git commit -m "Add structured OCR prompt profiles and publishing setup"
git push origin HEAD
```

Nota: se vuoi mantenere la repo pubblica ma i documenti di esempio contengono dati sensibili, crea eventualmente sample sintetici o anonimizzati invece di togliere le esclusioni correnti.

## Troubleshooting essenziale

Ollama non raggiungibile:

- Verifica che ollama serve sia attivo.
- Controlla GET /api/health.
- Verifica che l'endpoint configurato sia quello atteso in [backend/config.py](backend/config.py).

Modello non trovato:

- Esegui ollama list.
- Se manca glm-ocr:latest, scaricalo con ollama pull glm-ocr:latest.
- Se disponibile solo il fallback, il backend prova glm-ocr:v0.1.5 automaticamente.

OCR lento o timeout:

- Aumenta OCR_TIMEOUT in [backend/config.py](backend/config.py) per documenti pesanti.
- Controlla che Ollama non sia saturo o in errore runtime.

Pagina in errore ma export documento coerente:

- Il markdown di errore viene persistito con metadata diagnostici.
- La pagina puo' essere rieseguita senza perdere il resto del documento.

Batch apparentemente perso dopo restart:

- Verifica la presenza di uploads/_batches/<batch_id>.json.
- Se il file manca, il backend prova a ricostruire il batch dai metadata dei documenti.

## Note operative

- Le pagine sono 0-indexed in tutto il progetto.
- Il frontend lavora tramite polling, non via websocket.
- Il markdown pagina per pagina resta la fonte canonica per l'export.
- Non esistono al momento endpoint di delete o cleanup applicativo.
