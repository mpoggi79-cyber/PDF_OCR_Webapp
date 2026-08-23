# Elenco test ufficiali OCR

Questo file tiene l'elenco ufficiale dei casi da preparare ed eseguire.

La struttura reale dei casi si trova in tests/official.
Ogni caso ha sempre queste sottocartelle:

- input: contiene il file sorgente PDF o immagine
- expected: contiene opzionalmente il markdown atteso con lo stesso nome base del file di input
- actual: contiene il markdown generato dal runner e il report dell'ultima esecuzione
- se expected esiste, il runner confronta actual ed expected e registra un avviso quando sono differenti

Regole semplici:

- mettere un solo file di input per caso
- se hai piu' file dello stesso tipo, creare casi fratelli nello stesso gruppo logico
- esempio: T005A, T005B, T005C appartengono tutti al gruppo T005
- mantenere almeno 2 casi per ogni tipologia principale
- usare lo stesso nome base tra input e output markdown
- lasciare uploads al runtime del backend, non ai casi ufficiali

## Comandi utili

- Elenco casi: python tests/run_official_tests.py --list
- Controllo struttura: python tests/run_official_tests.py --check-structure
- Esecuzione di tutti i casi con input presente: python tests/run_official_tests.py
- Test unitari backend OCR e pulizia Markdown: .venv\Scripts\python.exe -m unittest tests.test_ocr_core tests.test_markdown_cleanup -v
- Esecuzione di un caso singolo non ambiguo: python tests/run_official_tests.py --case T005A
- Esecuzione del caso esatto quando l'ID coincide con un gruppo: python tests/run_official_tests.py --case T005 --exact-case
- Esecuzione di un gruppo logico: python tests/run_official_tests.py --case T005
- Confronto senza nuovo OCR: python tests/run_official_tests.py --case T005 --exact-case --compare-only
- Esecuzione di una famiglia dove il caso base coincide con il gruppo: python tests/run_official_tests.py --case T001

Nota importante:

- quando l'ID del gruppo coincide con il caso base, il comando esegue tutta la famiglia
- esempio: --case T001 esegue T001 e T001B
- per eseguire un solo caso in modo certo, usa un ID variante univoco come T001B, T005A, T006B, T009B

## Stati usati

- ready-for-input: cartella pronta, file non ancora inseriti
- generated: markdown generato dal runner
- missing_input: nessun file trovato in input
- timeout: job OCR non concluso entro il timeout del runner
- failed: errore tecnico durante l'esecuzione automatica

## Da PDF a MD

### Documenti pagina singola

1. T001 - Documento strutturato bancario
    - Stato iniziale: ready-for-input
    - Cartella: tests/official/pdf/pagina-singola/T001_documento_strutturato_bancario
    - Prompt profile: structured_document
    - Input previsto: 1 PDF strutturato

2. T001B - Fattura pagina singola strutturata
    - Stato: generated; expected presente e confronto actual/expected: match
    - Cartella: tests/official/pdf/pagina-singola/T001B_fattura_pagina_singola_strutturata
    - Prompt profile: structured_document
    - Input previsto: 1 PDF pagina singola strutturato di fattura

3. T002 - PDF fotografico scannerizzato
    - Stato: generated; confronto actual/expected: match; profilo no-HTML attivo; il contenuto è stato ruotato di 90 gradi prima dell'OCR
    - Cartella: tests/official/pdf/pagina-singola/T002_pdf_fotografico_scanner
    - Prompt profile: structured_document_no_html
    - Rotazione pagina: 90 gradi
    - Output: Markdown puro, senza tag HTML
    - Verifica: actual T002 identico all'expected consolidato di T002A
    - Input previsto: 1 PDF scannerizzato o fotografico

4. T002A - PDF fotografico diritto
    - Stato: generated; confronto actual/expected: match; risultato no-HTML consolidato come expected
    - Cartella: tests/official/pdf/pagina-singola/T002A_pdf_fotografico_diritto
    - Prompt profile: structured_document_no_html
    - Rotazione pagina: 0 gradi; il PDF conserva la rotazione nativa
    - Output: Markdown puro, senza tag HTML
    - Funzione nel gruppo: caso di riferimento per la stessa fattura verificata in T002 con rotazione di 90 gradi
    - Input previsto: 1 PDF fotografico o scannerizzato orientato correttamente

5. T002B - Modulo singolo scannerizzato
    - Stato iniziale: ready-for-input
    - Cartella: tests/official/pdf/pagina-singola/T002B_modulo_pagina_singola_scanner
    - Prompt profile: default
    - Input previsto: 1 PDF scannerizzato di modulo singolo

6. T003 - PDF da stampa browser
    - Stato iniziale: ready-for-input
    - Cartella: tests/official/pdf/pagina-singola/T003_pdf_stampa_browser
    - Prompt profile: web_article
    - Input previsto: 1 PDF derivato da stampa pagina web

7. T003B - Articolo singolo da stampa browser
    - Stato iniziale: ready-for-input
    - Cartella: tests/official/pdf/pagina-singola/T003B_articolo_pagina_singola_stampa_browser
    - Prompt profile: web_article
    - Input previsto: 1 PDF pagina singola derivato da stampa articolo web

### Documenti multi pagina

1. T005 - Documento multipagina strutturato
    - Stato: generated
    - Cartella: tests/official/pdf/multi-pagina/T005_documento_multipagina_strutturato
    - Prompt profile: structured_document
    - Input previsto: 1 PDF multipagina strutturato
    - Risultato: 15/15 pagine completate, 0 errori; pagina 2 vuota mantenuta nell'output
    - Nota: i numeri di pagina presenti nell'intestazione del PDF non risultano acquisiti nel Markdown

2. T005A - Bolletta luce multipagina strutturata
    - Stato iniziale: ready-for-input
    - Cartella: tests/official/pdf/multi-pagina/T005A_bolletta_luce_multipagina_strutturata
    - Prompt profile: structured_document
    - Input previsto: 1 PDF multipagina strutturato di bolletta luce

3. T005B - Bolletta gas multipagina strutturata
    - Stato iniziale: ready-for-input
    - Cartella: tests/official/pdf/multi-pagina/T005B_bolletta_gas_multipagina_strutturata
    - Prompt profile: structured_document
    - Input previsto: 1 PDF multipagina strutturato di bolletta gas

4. T005C - Bolletta acqua multipagina strutturata
    - Stato iniziale: ready-for-input
    - Cartella: tests/official/pdf/multi-pagina/T005C_bolletta_acqua_multipagina_strutturata
    - Prompt profile: structured_document
    - Input previsto: 1 PDF multipagina strutturato di bolletta acqua

5. T006 - PDF multipagina scannerizzato
    - Stato iniziale: ready-for-input
    - Cartella: tests/official/pdf/multi-pagina/T006_pdf_multipagina_scanner
    - Prompt profile: default
    - Input previsto: 1 PDF multipagina scannerizzato

6. T006B - Verbale multipagina scannerizzato
    - Stato iniziale: ready-for-input
    - Cartella: tests/official/pdf/multi-pagina/T006B_verbale_multipagina_scanner
    - Prompt profile: default
    - Input previsto: 1 PDF multipagina scannerizzato di verbale

7. T007 - PDF multipagina da stampa browser
    - Stato iniziale: ready-for-input
    - Cartella: tests/official/pdf/multi-pagina/T007_pdf_multipagina_stampa_browser
    - Prompt profile: web_article
    - Input previsto: 1 PDF multipagina derivato da stampa pagina web

8. T007B - Report web multipagina da stampa browser
    - Stato iniziale: ready-for-input
    - Cartella: tests/official/pdf/multi-pagina/T007B_report_web_multipagina_stampa_browser
    - Prompt profile: web_article
    - Input previsto: 1 PDF multipagina derivato da report web stampato

## Da immagine a MD

### Documento pagina singola

1. T009 - Immagine con testi e tabelle
    - Stato iniziale: ready-for-input
    - Cartella: tests/official/immagini/pagina-singola/T009_immagine_testi_tabelle
    - Prompt profile: structured_document
    - Input previsto: 1 immagine PNG, JPG o JPEG

2. T009B - Immagine modulo con tabella
    - Stato iniziale: ready-for-input
    - Cartella: tests/official/immagini/pagina-singola/T009B_immagine_modulo_tabella
    - Prompt profile: structured_document
    - Input previsto: 1 immagine PNG, JPG o JPEG di modulo con tabella

## Tempi di elaborazione

Il backend salva ora tempi opzionali per pagina e per job:

- duration_ms per pagina nel sidecar JSON OCR
- total_duration_ms e pages_duration_ms nel payload del job OCR

Il runner converte questi tempi in secondi quando scrive i report del caso in actual/last_run.json e il riepilogo generale in tests/official/results/latest.json.

Quando il caso dispone di un file in expected/, il report registra `expected_comparison` con valore `match`,
`different` oppure `not_available`. In caso di differenza viene generato un avviso; la verifica visiva resta
manuale e il runner non sovrascrive mai expected/.
