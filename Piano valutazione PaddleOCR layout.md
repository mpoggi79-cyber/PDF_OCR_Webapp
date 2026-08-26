# Piano Di Valutazione PaddleOCR Per Il Layout

**Stato:** sospeso per allineamento overlay. Il benchmark Paddle non parte finché non è verificato che i layer e le coordinate si sovrappongono correttamente al raster di origine. Nessuna dipendenza PaddleOCR installata nel progetto.

## Obiettivo attuale

Risolvere il problema di allineamento tra raster, coordinate del provider e overlay UI. Solo dopo aver verificato un overlay corretto si riprendera' il confronto tra GLM-OCR e Paddle e la valutazione del layout.

## Obiettivo di benchmark

Valutare se PaddleOCR puo' fornire regioni layout piu' precise di quelle restituite dal percorso SDK `glmocr`, mantenendo invariati:

- Markdown canonico pagina per pagina;
- OCR primario e fallback HTTP attuali;
- semantica di resume, batch, export e sidecar esistenti;
- una sola elaborazione OCR della pagina rasterizzata completa.

Nella prima fase PaddleOCR deve essere esclusivamente un detector diagnostico: produce bbox e artefatti di confronto, ma non modifica il Markdown ne' avvia crop OCR.

## Evidenza Raccolta Il 24 Agosto 2026

### Pagina di confronto

Documento: fattura Ayvens, raster `uploads/8e7c9699-ef2f-4483-80cd-abe7f551d77c/pages/page_0.png`.

- dimensione raster: `1191 x 1684` pixel;
- l'immagine visualizzata dalla UI e' la stessa pagina rasterizzata inviata al provider;
- l'endpoint `GET /api/page/{doc_id}/0` ha restituito `200 image/png`;
- l'allineamento SVG usa il `viewBox` delle dimensioni naturali dell'immagine.

Conclusione: i box osservati nella UI riflettono le bbox restituite dal provider e non un problema di rendering frontend.

### Confronto provider sullo stesso raster

Profilo OCR: `structured_document_no_html`. Modello: `glm-ocr:latest`.

| Percorso | Tempo | Markdown | Bbox / regioni |
| --- | ---: | ---: | --- |
| SDK `glmocr` | 70,24 s | 2.961 caratteri | 14 regioni: 5 testo, 8 immagini, 1 tabella |
| HTTP Ollama | 23,55 s | 1.411 caratteri | nessuna bbox |

Il detector usato dal percorso SDK ha prodotto regioni semanticamente grossolane sulla fattura: una regione `table` ingloba solo parte della struttura tabellare e alcune regioni `image` includono aree bianche o campi documento. Il fallback HTTP non restituisce geometria.

Non c'e' evidenza che questa imprecisione dipenda dalle prestazioni: accuratezza della segmentazione e tempo di inferenza vanno misurati separatamente.

## Candidato

### PP-DocLayoutV3

Riferimenti:

- [Repository PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)
- [Modello PP-DocLayoutV3](https://huggingface.co/PaddlePaddle/PP-DocLayoutV3)
- [Tutorial PP-StructureV3](https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/PP-StructureV3.html)

PP-DocLayoutV3 e' un detector layout dedicato: il model card dichiara bbox multipunto e ordine di lettura in una sola inferenza. Il checkpoint e' parte dello stack PaddleOCR/PaddleOCR-VL.

### Perche' iniziare da PP-StructureV3

Il primo test deve usare `PPStructureV3`, non il checkpoint isolato, perche' il pipeline fornisce:

- layout detection;
- OCR generale;
- riconoscimento tabelle e formule opzionali;
- JSON e Markdown esportabili;
- output visivo e configurazione di moduli/modelli.

Il checkpoint PP-DocLayoutV3 isolato resta una seconda fase, utile se PP-StructureV3 dimostra che la famiglia Paddle migliora le bbox ma il pipeline completo e' troppo lento o troppo pesante.

## Vincoli

1. Non aggiungere PaddleOCR a `requirements.txt` prima del confronto.
2. Non installare PaddleOCR nella `.venv` usata dall'app: creare un ambiente virtuale separato, ad esempio `.venv-paddle-layout`.
3. Non modificare `backend/ocr.py`, il flusso OCR, i prompt, le baseline `expected` o i sidecar correnti durante la prova.
4. Riutilizzare gli stessi raster `page_N.png` prodotti dall'app; non eseguire nuova rasterizzazione per il benchmark.
5. Non dedurre nuove bbox dal Markdown e non effettuare crop supplementari.
6. Salvare ogni output sperimentale fuori da `uploads/`, ad esempio in `artifacts/paddle-layout/`, che dovra' restare esclusa dal flusso runtime.
7. Le coordinate devono riportare in modo esplicito il sistema di riferimento dell'immagine (`width`, `height`, raster source) per permettere overlay confrontabili.

## Campione Minimo

| Caso | Input | Motivo |
| --- | --- | --- |
| T001B | fattura PDF pagina singola | tabelle, totali, blocchi indirizzo, logo e banner |
| T006 | PDF scannerizzato multipagina | rumore, testo stampato, pagine complesse |
| T009B | immagine modulo con tabella | input raster e struttura form-like |
| T010 | PDF A4 verticale con blocchi geometrici | test di analisi per allineamento overlay, coordinate, viewBox e scaling prima del confronto tra provider |

Percorsi disponibili:

```text
tests/official/pdf/pagina-singola/T001B_fattura_pagina_singola_strutturata/input/T001B_Fattura 77 SCM Assistenza Pantografi novembre 2025 EU.pdf
tests/official/pdf/multi-pagina/T006_pdf_multipagina_scanner/input/T006_Questionario Denis Albano caso n. 519315705 del 05-05-2023.pdf
tests/official/immagini/pagina-singola/T009B_immagine_modulo_tabella/input/T009B_prinscreen_tabella da web.png
```

La fattura Ayvens resta un caso diagnostico aggiuntivo, gia' presente in `uploads/`, ma non sostituisce i test ufficiali.

## Checklist di ripresa e pre-flight overlay

Prima di avviare qualsiasi benchmark o confronto tra GLM-OCR e Paddle, verificare obbligatoriamente il seguente prerequisito:

- [ ] l'immagine raster usata per il benchmark e' la stessa mostrata nella UI;
- [ ] le dimensioni del raster e del `viewBox` SVG coincidono con i pixel reali dell'immagine;
- [ ] il sistema di riferimento e' identico: origine in alto a sinistra, assi x/y in pixel;
- [ ] non ci sono trasformazioni CSS/SVG che introducano offset, scale o rotazioni invisibili;
- [ ] un box noto o un punto di riferimento resta allineato alla stessa posizione sul raster e nella UI;
- [ ] il layer GLM-OCR e il layer Paddle si sovrappongono correttamente al raster di riferimento;
- [ ] se l'allineamento e' anche solo leggermente differente, il benchmark si ferma e si corregge il rendering/normalizzazione prima di proseguire;
- [ ] la validazione overlay e' considerata prerequisito necessario per ogni caso, non un passaggio opzionale.

Questa verifica e' fondamentale: senza un allineamento affidabile, un confronto di bbox non e' un confronto di layout, ma un confronto di rendering o trasformazioni non dichiarate.

## Fase 0: Preparazione Ambiente Separato

1. Identificare versione Python supportata dalla versione PaddleOCR scelta e compatibile con Windows.
2. Creare `.venv-paddle-layout` dalla root del repository.
3. Installare PaddlePaddle e PaddleOCR con il gruppo richiesto dalla documentazione corrente (`doc-parser` per PP-StructureV3), scegliendo CPU o GPU in base all'hardware disponibile.
4. Registrare in `artifacts/paddle-layout/environment.txt`:
   - Windows e versione Python;
   - `paddlepaddle`, `paddleocr` e backend di inferenza;
   - CPU/GPU, RAM e VRAM rilevate;
   - data, comando di installazione e hash/versione pacchetti.
5. Eseguire il comando demo ufficiale su un'immagine non di test per verificare download pesi e dipendenze.

Non promuovere nessuna modifica applicativa in questa fase.

## Fase 1: Smoke Test PP-StructureV3

Eseguire prima una pagina raster singola con moduli opzionali disabilitati quando non necessari, per capire costo e formato output.

Schema Python ufficiale da adattare:

```python
from paddleocr import PPStructureV3

pipeline = PPStructureV3(device="cpu")
for result in pipeline.predict("path/to/page_0.png"):
    result.save_to_json(save_path="artifacts/paddle-layout/smoke")
```

Per il test registrare:

- tempo di caricamento modello separato dal tempo per pagina;
- tempo totale, memoria e eventuali download;
- JSON prodotto e immagine annotata se disponibile;
- tipi di regione, bbox/poligoni, ordine di lettura e coordinate celle quando presenti;
- eventuali errori, warning o moduli disabilitati.

Criterio di successo: output JSON leggibile con coordinate riferite al raster e almeno un artefatto visuale confrontabile.

## Fase 2: Benchmark Layout Comparativo

### Input

Per ogni caso, usare le immagini `page_N.png` generate dall'app. Per i PDF dei casi ufficiali, usare lo stesso rendering `PDF_RENDER_SCALE = 2.0` e la stessa rotazione prevista dal caso.

### Artefatti per pagina

Salvare in una directory deterministica:

```text
artifacts/paddle-layout/<case-id>/page_<N>/
  input.json
  glmocr_regions.json
  paddle_regions.json
  paddle_raw.json
  paddle_overlay.png
  metrics.json
  notes.md
```

`glmocr_regions.json` deve contenere la copia normalizzata delle regioni gia' restituite dal sidecar o dalla prova SDK. `paddle_regions.json` deve conservare sia la geometria originale sia una normalizzazione comparabile:

```json
{
  "provider": "paddle_ppstructurev3",
  "image_size": {"width": 1191, "height": 1684},
  "regions": [
    {
      "label": "table",
      "bbox": [x1, y1, x2, y2],
      "polygon": [[x, y], [x, y], [x, y], [x, y]],
      "reading_order": 0,
      "source": "paddle"
    }
  ]
}
```

### Valutazione visiva obbligatoria

Per ciascuna pagina segnare manualmente, per GLM-OCR e Paddle:

- blocchi di testo attesi rilevati/non rilevati;
- tabelle complete, parziali o mancanti;
- immagini e banner correttamente delimitati;
- box che includono ampie aree bianche o elementi semanticamente estranei;
- ordine di lettura utile per il documento;
- celle tabella disponibili o non disponibili;
- falsi positivi e duplicazioni.

Non usare il solo conteggio delle regioni come prova di qualita'.

### Metriche

Registrare per ogni pagina:

- `model_load_seconds`;
- `page_seconds`;
- RAM/VRAM di picco, quando ottenibile;
- numero regioni per label;
- numero box con sovrapposizione chiaramente errata;
- tabelle complete/parziali/mancanti;
- punteggio visivo da 0 a 2 per testo, immagini, tabelle e ordine di lettura:
  - 0: inutilizzabile;
  - 1: parziale o ambiguo;
  - 2: coerente con l'immagine.

Il report deve distinguere la qualita' OCR dal layout: un buon Markdown non convalida automaticamente le bbox.

## Criteri Di Decisione

### Promuovere a integrazione diagnostica opzionale

Paddle puo' essere promosso se, sul campione minimo:

1. migliora in modo visibile almeno due casi su tre rispetto alle bbox GLM-OCR;
2. riduce box palesemente errati nelle fatture/moduli senza perdere tabelle importanti;
3. produce coordinate persistibili e overlay allineabili al raster;
4. il tempo per pagina e il consumo memoria sono compatibili con uso locale;
5. non obbliga a sostituire il Markdown GLM-OCR ne' altera API esistenti.

### Restare solo benchmark o scartare

Non integrare se:

- i box restano semanticamente imprecisi o peggiorano il campione;
- il carico CPU/RAM o il tempo rendono l'esperienza locale impraticabile;
- l'installazione non e' riproducibile su Windows;
- le coordinate richiedono trasformazioni non documentate o non verificabili;
- il beneficio riguarda solo un caso isolato.

## Fase 3: Integrazione Solo Dopo Promozione

Se il benchmark soddisfa i criteri:

1. aggiungere un modulo isolato, ad esempio `backend/layout.py`, senza appesantire `app.py`;
2. introdurre feature flag espliciti, disabilitati di default;
3. salvare metadata Paddle in un sidecar separato o in un namespace `layout_providers.paddle`, senza sovrascrivere le regioni GLM-OCR;
4. aggiungere al payload API campi opzionali e retrocompatibili;
5. estendere la UI `Layout` con selettore provider (`GLM-OCR` / `Paddle`) e comparazione, non con sostituzione silenziosa;
6. aggiungere test deterministici per normalizzazione bbox/poligoni, persistenza e fallback quando Paddle non e' installato;
7. eseguire test ufficiali e verifica visiva prima di consolidare nuove baseline.

Integrazione in produzione e uso delle bbox Paddle per crop, OCR secondario o modifica automatica del Markdown restano fuori da questo piano.

## Rischi E Mitigazioni

| Rischio | Mitigazione |
| --- | --- |
| Dipendenze Paddle in conflitto con l'app | ambiente `.venv-paddle-layout` separato |
| Download/modelli grandi o lenti | smoke test e registrazione dimensioni/tempi prima del benchmark |
| Risultati non comparabili | stessi raster, scale e rotazioni dell'app |
| Bbox quadrilatere invece di rettangoli | preservare poligono e derivare bbox solo per overlay comparativo |
| Falsa impressione di precisione | valutazione visiva con categorie complete/parziali/mancanti |
| Regressioni OCR | Paddle non entra nel percorso OCR iniziale |
| Supporto Windows/CPU insufficiente | criterio di stop, nessuna modifica a `.venv` produttiva |

## Comandi Di Ripresa

Prima di riprendere il lavoro:

```powershell
Get-Content ".\Piano valutazione PaddleOCR layout.md"
.\.venv\Scripts\python.exe -m pytest -q tests\test_ocr_core.py tests\test_markdown_cleanup.py
.\.venv\Scripts\python.exe tests\run_official_tests.py --check-structure
```

Poi verificare il contenuto della documentazione ufficiale alla versione PaddleOCR installata, perche' installazione, nomi modello e opzioni possono cambiare.

## Decisioni Prese

- Il percorso HTTP Ollama non e' un candidato layout: non restituisce bbox nella prova eseguita.
- Il percorso SDK GLM-OCR resta proprietario del Markdown canonico durante tutto il benchmark.
- Il detector Paddle, se promosso, entra prima solo nella diagnostica UI.
- Non si introducono crop, OCR secondari, inferenze da Markdown o aggiornamenti automatici delle baseline.
- Le bbox non sono una misura di qualita' OCR: sono evidenza del detector e richiedono validazione visiva.
