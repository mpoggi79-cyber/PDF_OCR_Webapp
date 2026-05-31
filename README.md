# PDF OCR Webapp

Trasforma PDF e immagini in Markdown strutturato usando GLM-OCR in locale tramite Ollama.

PDF OCR Webapp e' una web app locale con backend FastAPI e frontend statico che accetta PDF, PNG, JPG e JPEG, avvia OCR asincrono pagina per pagina, salva i risultati su file system e permette di riprendere i job dopo riavvio del server. L'obiettivo non e' solo completare il job, ma ottenere un output Markdown il piu' fedele possibile a heading, liste, tabelle, formule e layout del documento originale.

In breve:

- local-first: OCR eseguito in locale con Ollama e GLM-OCR
- output strutturato: Markdown canonico con supporto a metadata OCR opzionali
- robustezza: retry, diagnostica errori e resume post-crash
- stack semplice: FastAPI backend e frontend vanilla JS senza build step
- focus prodotto: massima fedelta' possibile su documenti strutturati, tabelle e moduli

## Perche' usarlo

- OCR locale con Ollama: nessun servizio cloud obbligatorio.
- Output Markdown: pronto per note, report, knowledge base ed export.
- Supporto PDF e immagini singole.
- Supporto batch per piu' PDF.
- Persistenza su disco con resume post-crash.
- Diagnostica OCR strutturata leggibile via API e UI.
- Contratto OCR estendibile con metadata strutturali, layout e regioni.

## Stack e architettura

- Backend: FastAPI con entrypoint leggero in [app.py](app.py) e logica in [backend](backend/).
- Frontend: HTML, CSS e JavaScript vanilla in [static](static/).
- OCR provider primario: SDK glmocr in modalita' self-hosted.
- Fallback provider: chiamata HTTP diretta a Ollama compatibile con lo stesso flusso.
- Storage: file system in uploads, senza database.

Percorso tipico:

1. Upload documento o immagine.
2. Rendering PDF in immagini pagina oppure salvataggio diretto dell'immagine.
3. Avvio OCR asincrono via BackgroundTasks.
4. Polling client sugli endpoint OCR.
5. Persistenza di markdown, stato job e metadata OCR strutturati.
6. Export documento o ZIP batch.

## Prerequisiti

- Windows con Python disponibile nel PATH.
- Ollama installato localmente.
- Modello OCR disponibile in Ollama: glm-ocr:latest.
- Fallback supportato: glm-ocr:v0.1.5.

Comandi utili lato Ollama:

```powershell
ollama serve
ollama pull glm-ocr:latest
ollama pull glm-ocr:v0.1.5
ollama list
```

## Avvio rapido

1. Avvia Ollama in locale oppure lascia che [start.bat](start.bat) provi a farlo partire se gia' installato.
2. Esegui [start.bat](start.bat).
3. Apri il browser su <http://localhost:8080>.
4. Carica un PDF o una singola immagine PNG, JPG o JPEG.
5. Avvia OCR su una pagina, su tutto il documento o su un batch.
6. Esporta il risultato finale in Markdown oppure ZIP batch.

Avvio manuale alternativo:

```powershell
.venv\Scripts\Activate.ps1
python -m uvicorn app:app --host 0.0.0.0 --port 8080 --reload
```

## Healthcheck e stato modelli

L'endpoint GET /api/health verifica Ollama e restituisce informazioni operative sul modello selezionato.

Campi principali:

- ollama: stato della connessione a Ollama.
- glm_ocr: available oppure not_found.
- configured_models: modelli configurati dal backend in ordine di preferenza.
- selected_model: primo modello configurato realmente trovato in Ollama.
- models: lista completa dei modelli visti via /api/tags.
- prompt_profiles: profili prompt OCR selezionabili lato API.
- default_prompt_profile: profilo usato se non viene specificato altro.

Esempio di risposta:

```json
{
   "ollama": "ok",
   "glm_ocr": "available",
   "configured_models": ["glm-ocr:latest", "glm-ocr:v0.1.5"],
   "selected_model": "glm-ocr:latest",
   "models": ["glm-ocr:latest", "llama3.2:3b"]
}
```

## Provider OCR, fallback e retry

Il backend usa questo ordine operativo:

1. Provider primario glmocr self-hosted con modello glm-ocr:latest.
2. Se il modello primario non e' disponibile, prova i fallback configurati come glm-ocr:v0.1.5.
3. Se il ramo SDK non produce un risultato valido, puo' fare fallback al provider HTTP diretto verso Ollama.
4. Se tutti i tentativi falliscono, la pagina viene marcata come errore con diagnostica persistita.

Configurazione attuale in [backend/config.py](backend/config.py):

- Timeout OCR: 240 secondi.
- Retry massimi: 2.
- Backoff base: 0.5 secondi con crescita esponenziale.
- Block size OCR documento: 10 pagine.
- Provider primario: glmocr.

Il retry copre errori transitori come timeout, rate limit e indisponibilita' temporanea del servizio. Gli errori non retryable, come modello mancante o crash runtime del modello, vengono classificati e restituiti in modo esplicito.

## Profili prompt OCR

Il backend supporta profili prompt diversi per adattare l'OCR a tipi di input differenti senza rompere gli endpoint esistenti.

Profili attuali:

- structured_document: profilo consigliato per documenti bancari, moduli, fatture, ricevute e PDF ricchi di tabelle o campi; e' anche il default operativo usato dal frontend quando non viene passato `prompt_profile`.
- default: comportamento OCR generico, adatto a documenti normali, scansioni e PDF non fortemente web-centrici.
- web_article: profilo piu' aggressivo per PDF stampati da pagine web, con istruzioni per ignorare menu, ads, widget, footer e boilerplate del sito.

Il profilo puo' essere selezionato in modo backward-compatible tramite query parameter opzionale `prompt_profile` su:

- POST /api/upload
- POST /api/ocr/{doc_id}/{page_num}
- POST /api/ocr-job/{doc_id}
- POST /api/batch
- POST /api/batch/{batch_id}/start

Esempi:

```text
POST /api/upload?prompt_profile=structured_document
POST /api/upload?prompt_profile=web_article
POST /api/ocr-job/{doc_id}?prompt_profile=default
POST /api/batch/{batch_id}/start?prompt_profile=web_article
```

Il profilo scelto viene persistito nei metadata documento e riusato per i retry successivi, salvo override esplicito su una nuova richiesta OCR. Se il client non passa `prompt_profile`, il backend usa attualmente `structured_document` come profilo predefinito.

## Persistenza e ripresa post-crash

Lo stato OCR e' file-based e sopravvive ai riavvii del server.

- Ogni documento salva metadata in uploads/<doc_id>/metadata.json.
- Lo stato job documento viene salvato in uploads/<doc_id>/job_state.json.
- Il markdown OCR di ogni pagina viene salvato in uploads/<doc_id>/ocr/page_N.md.
- I metadata OCR strutturati di successo possono essere salvati in uploads/<doc_id>/ocr/page_N.json.
- I batch vengono salvati in uploads/_batches/<batch_id>.json.

Semantica dei flag di stato:

- interrupted: il job era in corso al momento di un riavvio o crash e deve essere considerato interrotto.
- resumable: esistono ancora pagine pending e il job puo' riprendere.

Comportamento di recovery:

- Le pagine rimaste in processing durante un crash vengono normalizzate a pending.
- Un nuovo POST su /api/ocr-job/{doc_id} riprende solo le pagine pending del documento.
- Un nuovo POST su /api/batch/{batch_id}/start riprende solo i documenti incompleti del batch.
- Se il file batch e' mancante ma i documenti contengono batch_id nei metadata, il backend puo' ricostruire il batch da disco.

## Output OCR strutturato

Oltre al markdown canonico, il backend puo' restituire campi opzionali con metadata OCR strutturati. Il frontend attuale li conserva in memoria in modo passivo, senza esporre ancora una UI dedicata.

Campi opzionali attualmente supportati:

- provider
- model
- layout_visualization
- crop_regions
- table_regions
- formula_regions
- confidence
- structure_metadata
- raw_provider_payload, se abilitato esplicitamente

Feature flag attuali in [backend/config.py](backend/config.py):

- OCR_ENABLE_STRUCTURED_OUTPUT = True
- OCR_ENABLE_LAYOUT_VISUALIZATION = True
- OCR_RETURN_CROP_IMAGES = False
- OCR_INCLUDE_RAW_PROVIDER_PAYLOAD = False

Questo permette di estendere in seguito la UI verso ispezione layout, formule, tabelle e confidence senza rompere export o compatibilita' esistente.

## Diagnostica errori OCR

Quando una pagina fallisce, GET /api/ocr/{doc_id}/{page_num} puo' restituire un oggetto error con campi strutturati come:

- source
- type
- label
- interpretation
- detail
- retryable
- http_status, se disponibile

Tipi gestiti dal backend:

- timeout
- ollama_unreachable
- model_not_found
- model_runtime_assert
- service_unavailable
- api_error
- file_io_error

La UI legge questi campi e mostra una scheda diagnostica senza perdere la possibilita' di vedere il markdown tecnico grezzo.

## API principali

| Metodo | Path | Descrizione |
| ------ | ---- | ----------- |
| GET | / | Serve la SPA principale |
| GET | /api/health | Stato Ollama, modelli configurati e modello selezionato |
| POST | /api/upload | Carica PDF o immagine e crea il documento; supporta `prompt_profile` opzionale |
| GET | /api/documents/{doc_id} | Metadata documento e stato pagina per pagina |
| GET | /api/page/{doc_id}/{page_num} | Restituisce l'immagine della pagina o l'immagine originale |
| GET | /api/ocr/{doc_id}/{page_num} | Stato pagina OCR, markdown, errore strutturato e campi OCR opzionali |
| POST | /api/ocr/{doc_id}/{page_num} | Avvia OCR su una pagina; supporta `prompt_profile` opzionale |
| GET | /api/ocr-job/{doc_id} | Stato complessivo OCR del documento |
| POST | /api/ocr-job/{doc_id} | Avvia o riprende OCR dell'intero documento; supporta `prompt_profile` opzionale |
| GET | /api/export/{doc_id} | Export Markdown unificato del documento |
| POST | /api/batch | Carica piu' PDF e crea un batch; supporta `prompt_profile` opzionale |
| POST | /api/batch/{batch_id}/start | Avvia o riprende OCR del batch; supporta `prompt_profile` opzionale |
| GET | /api/batch/{batch_id} | Stato batch ricostruito da memoria o disco |
| GET | /api/batch/{batch_id}/report | Report Markdown del batch |
| GET | /api/batch/{batch_id}/export | ZIP con i Markdown del batch |
| POST | /api/shutdown | Spegnimento server locale, utile solo in contesto di sviluppo |

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
