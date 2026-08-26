# Istruzioni Copilot per PDF OCR Webapp

Questo file contiene le regole operative generali per Copilot. Per architettura,
API, test ufficiali e comportamento dettagliato consulta [AGENTS.md](../AGENTS.md)
e [README.md](../README.md).

## Collaborazione

- Spiega le decisioni con linguaggio semplice e con esempi concreti quando sono utili.
- Prima di modificare il codice, individua il modulo che controlla direttamente il comportamento richiesto.
- Mantieni le modifiche piccole e coerenti con lo stile esistente.
- Aggiungi commenti solo per la logica non immediatamente comprensibile.
- Quando crei un modulo significativo, descrivine brevemente la responsabilita' all'inizio del file.

## Architettura

- Leggi [AGENTS.md](../AGENTS.md) prima di modificare OCR, persistenza, batch o frontend dei risultati.
- Mantieni [app.py](../app.py) leggero e concentra la logica nei moduli [backend](../backend/).
- Mantieni il frontend in [static](../static/) con JavaScript vanilla, senza framework, bundler o build step.
- Usa le convenzioni gia' presenti nel progetto invece di introdurre nuove astrazioni senza necessita'.

## OCR e dati

- Considera la qualita' della conversione la priorita' principale: preserva heading, liste, tabelle, formule, immagini e struttura quando possibile.
- Mantieni il Markdown pagina per pagina come fonte canonica dell'export; i sidecar JSON OCR sono metadata opzionali.
- Per l'overlay `Layout`, mantieni i sidecar separati per pagina (`ocr/page_N.json`): nei documenti multipagina la UI deve mostrare le regioni della pagina selezionata, non solo quelle della prima.
- Normalizza il campo `page` delle regioni all'indice zero-based della pagina del documento; considera i sidecar storici gia' separati per file compatibili in lettura.
- Mantieni la compatibilita' API: aggiungi campi opzionali senza rompere i client esistenti.
- Preserva pagine 0-indexed, stato file-based in `uploads/`, recovery post-crash e semantica `interrupted`/`resumable`.
- Considera `capabilities` nei sidecar come evidenza delle feature realmente restituite dal provider, non di quelle soltanto configurate.
- Quando modifichi il flusso OCR, verifica sia il ramo `glmocr` sia il fallback HTTP a Ollama.
- Quando modifichi i prompt SDK, conserva i task ufficiali `Text Recognition:`, `Table Recognition:` e `Formula Recognition:`.
- Per pipeline, KIE e fine-tuning consulta i riferimenti indicati in [nuovo piano.md](../nuovo%20piano.md).

## Verifica

- Dopo modifiche Python esegui almeno il controllo di compilazione sui moduli interessati.
- Quando possibile esegui la suite con `.venv\Scripts\python.exe -m pytest -q`.
- Per modifiche al flusso OCR esegui anche una verifica end-to-end con Ollama, includendo il provider coinvolto e il fallback quando applicabile.