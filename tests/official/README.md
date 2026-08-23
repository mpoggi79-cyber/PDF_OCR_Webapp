# Dataset test OCR ufficiali

Questa cartella contiene i casi ufficiali di test per PDF OCR Webapp.

Ogni caso ha sempre questa struttura:

- input: inserisci qui un solo file sorgente PDF o immagine
- expected: opzionale, contiene il markdown atteso con lo stesso nome base del file di input
- actual: contiene il markdown generato dal runner e il report dell'ultima esecuzione
- case.json: descrive il caso, il prompt profile e gli eventuali parametri di rasterizzazione previsti

Regole pratiche:

- usa un solo file di input per cartella caso
- se hai piu' documenti simili, crea piu' casi fratelli nello stesso gruppo logico
- esempio: gruppo T005 con casi T005A, T005B, T005C
- il dataset attuale mantiene almeno 2 casi per ogni tipologia principale
- se aggiungi il file expected, usa lo stesso nome base del file di input e estensione .md
- non usare uploads per i casi ufficiali: uploads resta area runtime del backend

Esempio:

- input/bonifico.pdf
- expected/bonifico.md
- actual/bonifico.md

Runner:

- elenco casi: python tests/run_official_tests.py --list
- controllo struttura: python tests/run_official_tests.py --check-structure
- esegui tutti i casi con input presente: python tests/run_official_tests.py
- esegui un solo caso: python tests/run_official_tests.py --case T001B
- esegui un caso il cui ID coincide con il gruppo: python tests/run_official_tests.py --case T002 --exact-case
- esegui un intero gruppo: python tests/run_official_tests.py --case T005
- confronta actual ed expected senza nuovo OCR: python tests/run_official_tests.py --case T005 --exact-case --compare-only

Regole del runner:

- quando l'ID passato a `--case` coincide con un gruppo, senza `--exact-case` vengono selezionati tutti i casi del gruppo; per esempio `--case T002` include T002, T002A e T002B
- `--check-structure` controlla `case.json`, `input`, `expected` e `actual` senza contattare il backend
- `--compare-only` aggiorna i report di confronto senza eseguire nuovo OCR
- il confronto tra actual ed expected e' testuale esatto; una differenza richiede una verifica visiva prima di consolidare l'expected
- il runner salva `actual/last_run.json` e i riepiloghi in `tests/official/results/`

Confronto risultati:

- quando `expected/<nome>.md` esiste, il runner confronta il Markdown generato in `actual/<nome>.md` con l'expected
- `expected_comparison` vale `match`, `different` oppure `not_available`
- in caso di differenza viene stampato e registrato un avviso; il runner non modifica mai expected/

Baseline verificata per T002 e T002A:

- T002 usa `structured_document_no_html` con `page_rotation = 90` per il PDF scannerizzato con contenuto ruotato
- T002A usa lo stesso profilo con `page_rotation = 0` e conserva l'orientamento nativo del PDF
- l'actual ruotato di T002 coincide byte-per-byte con l'expected consolidato di T002A; anche l'expected di T002 e' consolidato e il confronto risulta `match`
- con il profilo no-HTML le tabelle devono essere pipe-delimited Markdown e l'output non deve contenere tag HTML
