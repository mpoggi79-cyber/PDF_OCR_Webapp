# Dataset test OCR ufficiali

Questa cartella contiene i casi ufficiali usati per verificare la qualità OCR del progetto.

## Struttura di un caso

Ogni caso ha questa struttura:

- `input/`: file sorgente PDF o immagine
- `expected/`: markdown atteso, quando disponibile
- `actual/`: markdown prodotto dal runner e report dell'ultima esecuzione
- `case.json`: descrizione del caso, profilo OCR e parametri previsti

## Regole pratiche

- usare un solo file sorgente per caso
- raggruppare casi simili nello stesso blocco logico
- non usare `uploads/` come area source del dataset ufficiale
- se si aggiunge un `expected`, usare lo stesso nome base del file di input e mantenere `.md`
- il confronto è testuale esatto; prima di consolidare `expected` diversi, verificare visivamente la qualità del contenuto

## Runner ufficiale

Comandi principali:

```powershell
python tests/run_official_tests.py --list
python tests/run_official_tests.py --check-structure
python tests/run_official_tests.py --case T001B
python tests/run_official_tests.py --case T002 --exact-case
python tests/run_official_tests.py --case T005 --exact-case --compare-only
```

Il runner:

- elenca i casi disponibili
- verifica struttura e presenza dei file richiesti
- esegue OCR reale se richiesto
- confronta `actual` con `expected` senza eseguire nuovo OCR quando usato con `--compare-only`
- salva i risultati in `actual/last_run.json` e in `tests/official/results/`

## Regole di selezione

- `--case T002` senza `--exact-case` include il gruppo completo `T002`, `T002A`, `T002B`
- `--check-structure` non contatta il backend, ma verifica la struttura dei casi
- `expected_comparison` può essere `match`, `different` o `not_available`

## Baseline attualmente verificate

### T002 e T002A

- T002 usa `structured_document_no_html` con `page_rotation = 90`
- T002A usa `structured_document_no_html` con `page_rotation = 0`
- il contenuto ruotato di T002 è stato verificato visivamente e confrontato con il caso equivalente non ruotato
- con il profilo `no_html`, le tabelle devono essere pipe-delimited e l'output non deve contenere tag HTML

### T006 e T006B

- T006 è un PDF multipagina scannerizzato e il markdown consolidato è stato verificato visivamente
- T006B è un PDF scannerizzato con firma e timbro; il risultato atteso è stato consolidato dopo confronto valido
- la pipeline PDF usa `PDF_RENDER_SCALE = 2.0`
- ogni pagina è sottoposta a una sola elaborazione OCR sull'immagine rasterizzata completa; le baseline vanno riesaminate con questo comportamento
- l'overlay `Layout` e i relativi filtri mostrano soltanto metadata strutturati del provider e non modificano il Markdown confrontato dal runner

### T010 e T011

- entrambi sono casi di calibrazione geometrica per l'overlay `Layout`, non benchmark di qualita' testuale
- T011 (tabella singola con origine in alto a sinistra) ha rilevato che il layout detector di `glmocr` restituisce `bbox_2d` normalizzato 0-1000 per asse, non in pixel: il riquadro appariva con origine corretta ma dimensione scalata in modo non uniforme su X e Y
- fix applicato in `backend/ocr.py`: le bbox vengono riconvertite in pixel reali usando le dimensioni effettive della pagina rasterizzata prima di essere scritte nel sidecar
- nei documenti multipagina ogni sidecar `ocr/page_N.json` appartiene alla propria pagina; le regioni salvate riportano `page` con indice zero-based globale, anche quando il provider usa un indice locale
- la UI deve mostrare l'overlay della pagina selezionata; una pagina senza regioni del provider puo' continuare a mostrare l'avviso di geometria assente

### T013

- pagina A4 verticale con 4 etichette minuscole agli angoli su sfondo altrimenti bianco
- con la soglia di default (`pipeline.layout.threshold = 0.3`) il layout detector non trova alcuna regione: nessun crop viene sottoposto a OCR e il markdown risulta vuoto, pur essendo il testo leggibile
- abbassando la soglia fino a 0.01 emerge una sola regione a bassa confidenza che copre l'intera pagina e recupera solo 2 delle 4 etichette: non e' una correzione adottabile in produzione, va trattato come limite noto del modello su pagine con contenuto molto sparso

## Nota importante

Il dataset ufficiale non va considerato un insieme statico di “verità assoluta”: i `expected` vanno aggiornati solo dopo verifica visiva e con criterio, perché la qualità OCR dipende anche da struttura, leggibilità e ordine di lettura del documento originale.
