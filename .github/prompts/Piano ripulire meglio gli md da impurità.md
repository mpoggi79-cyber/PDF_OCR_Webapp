
Raccolgo il minimo contesto tecnico sul flusso OCR e sul post-processing attuale, poi preparo un piano generale centrato sulla pulizia dell’output senza toccare i prompt.

Ho già la traccia principale: il problema sta nel tratto di normalizzazione/post-processing, non nella selezione del prompt. Leggo il report dell’esplorazione e poi ti restituisco un piano operativo dettagliato.

Metto il piano in memoria di sessione con la diagnosi tecnica e poi te lo mostro in forma scansionabile, così resta pronto per l’handoff o l’implementazione successiva.

Created memory file plan.md

Considering promotion qualifications

I see that only T009B qualifies for the expected promotion, while T001 is already anticipated. Since I'm in plan mode, perhaps I should refer to it as "Fase 0." I want to avoid using nested bullets, opting instead for flat ones. It sounds like I should create a bullet list for file references, and I'm aiming to craft this with short sections for clarity. Keeping it organized is key!

Plan: OCR Output Cleanup
Obiettivo: migliorare l’output OCR senza toccare i prompt, intervenendo in modo generale nel tratto di normalizzazione e post-processing che oggi lascia passare fence letterali come markdown e html. Ho salvato questo piano anche nella memoria di sessione.

Diagnosi

Nei test ufficiali il prompt personalizzato viene già passato per caso dal runner in tests/run_official_tests.py, quindi il problema principale non è che tutti i PDF usino lo stesso prompt.
Il backend estrae il markdown grezzo del provider in backend/ocr.py e backend/ocr.py, poi applica una pulizia minima in backend/ocr.py.
La funzione attuale rimuove solo righe di crop image e righe vuote doppie; non pulisce heading contaminati, fence orfani o blocchi fenced spurii.
Per questo il difetto è trasversale ai tipi di file: web, scannerizzati, strutturati e multi-pagina.
Steps

Fase 0: promuovere a expected solo i casi già puliti. Oggi i candidati sicuri sono T001, già presente, e T009B. Gli altri non vanno promossi finché restano fence spurii o heading degradati.
Fase 1: concentrare la pulizia nel punto unico corretto, cioè backend/ocr.py, così il markdown viene ripulito prima di essere scritto su disco.
Fase 2: trasformare il post-processing in una pipeline più robusta e generale, con helper separati per riconoscere fence orfani, heading contaminati e piccoli blocchi fenced spurii che vanno “unwrap”, non solo rimossi.
Fase 3: mantenere regole conservative. La normalizzazione deve preservare tabelle HTML reali, marker pagina, blocchi code veri e contenuto legittimo; deve colpire solo pattern chiaramente spurii.
Fase 4: lasciare invariati i prompt OCR per ora e non spostare la logica solo in lettura o in export. Il fix deve stare nel percorso di scrittura, così polling, export, batch e resume leggono già contenuto pulito.
Fase 5: aggiungere test di regressione mirati sulla funzione di pulizia con casi sintetici e casi reali del dataset.
Fase 6: rieseguire un sottoinsieme rappresentativo dei test ufficiali per tipologia documento e verificare che spariscano i fence spurii senza perdita di struttura.
Fase 7: rieseguire l’intera suite ufficiale e solo dopo rivalutare nuovi expected.
Relevant files

backend/ocr.py — punto principale di intervento; qui stanno _post_process_markdown e il salvataggio finale.
backend/ocr.py — normalizzazione risposta Ollama.
backend/ocr.py — normalizzazione risultato glmocr.
backend/ocr.py — uso del prompt profile e chiamata al post-processing dentro run_ocr.
backend/documents.py — utile per confermare che export e lettura consumano il markdown già persistito.
tests/run_official_tests.py — conferma che i test passano già prompt_profile.
tests/official/results/latest.json — base per selezionare i casi da verificare.
tests/official/immagini/pagina-singola/T009B_immagine_modulo_tabella/actual/T009B_prinscreen_tabella da web.md — candidato expected pulito.
tests/official/pdf/pagina-singola/T001_documento_strutturato_bancario/expected/T001_BONIFICO_EURO_INSTANT_20241111105222395.md — baseline già valida.
Verification

Test locale della funzione di pulizia con input sintetici: heading contaminati, fence isolati, blocchi fenced con semplice testo, HTML reale, code block reale.
Riesecuzione mirata di casi rappresentativi: T001B o T002, T002B o T006B, T003 o T007B, T005A o T005B, T009B.
Ricerca automatica dei pattern markdown, html e ## ``` nei generated per misurare la riduzione reale.
Riesecuzione completa della suite e controllo del report in tests/official/results/latest.md.
Compilazione rapida backend per escludere regressioni sintattiche.
Decisions

Il fix deve essere generale e provider-agnostico.
Per ora non si toccano i prompt.
Non conviene normalizzare solo in lettura o solo nell’API, perché lascerebbe il disco sporco.
Non conviene promuovere nuovi expected rumorosi: si rischia di congelare difetti del formato.
Se vuoi, il passo successivo è approvare questo piano e poi passare all’implementazione del cleanup generale in backend/ocr.py.e ```html. Ho salvato questo piano anche nella memoria di sessione.

Diagnosi

Nei test ufficiali il prompt personalizzato viene già passato per caso dal runner in tests/run_official_tests.py, quindi il problema principale non è che tutti i PDF usino lo stesso prompt.
Il backend estrae il markdown grezzo del provider in backend/ocr.py e backend/ocr.py, poi applica una pulizia minima in backend/ocr.py.
La funzione attuale rimuove solo righe di crop image e righe vuote doppie; non pulisce heading contaminati, fence orfani o blocchi fenced spurii.
Per questo il difetto è trasversale ai tipi di file: web, scannerizzati, strutturati e multi-pagina.
Steps

Fase 0: promuovere a expected solo i casi già puliti. Oggi i candidati sicuri sono T001, già presente, e T009B. Gli altri non vanno promossi finché restano fence spurii o heading degradati.
Fase 1: concentrare la pulizia nel punto unico corretto, cioè backend/ocr.py, così il markdown viene ripulito prima di essere scritto su disco.
Fase 2: trasformare il post-processing in una pipeline più robusta e generale, con helper separati per riconoscere fence orfani, heading contaminati e piccoli blocchi fenced spurii che vanno “unwrap”, non solo rimossi.
Fase 3: mantenere regole conservative. La normalizzazione deve preservare tabelle HTML reali, marker pagina, blocchi code veri e contenuto legittimo; deve colpire solo pattern chiaramente spurii.
Fase 4: lasciare invariati i prompt OCR per ora e non spostare la logica solo in lettura o in export. Il fix deve stare nel percorso di scrittura, così polling, export, batch e resume leggono già contenuto pulito.
Fase 5: aggiungere test di regressione mirati sulla funzione di pulizia con casi sintetici e casi reali del dataset.
Fase 6: rieseguire un sottoinsieme rappresentativo dei test ufficiali per tipologia documento e verificare che spariscano i fence spurii senza perdita di struttura.
Fase 7: rieseguire l’intera suite ufficiale e solo dopo rivalutare nuovi expected.
Relevant files

backend/ocr.py — punto principale di intervento; qui stanno _post_process_markdown e il salvataggio finale.
backend/ocr.py — normalizzazione risposta Ollama.
backend/ocr.py — normalizzazione risultato glmocr.
backend/ocr.py — uso del prompt profile e chiamata al post-processing dentro run_ocr.
backend/documents.py — utile per confermare che export e lettura consumano il markdown già persistito.
tests/run_official_tests.py — conferma che i test passano già prompt_profile.
tests/official/results/latest.json — base per selezionare i casi da verificare.
tests/official/immagini/pagina-singola/T009B_immagine_modulo_tabella/actual/T009B_prinscreen_tabella da web.md — candidato expected pulito.
tests/official/pdf/pagina-singola/T001_documento_strutturato_bancario/expected/T001_BONIFICO_EURO_INSTANT_20241111105222395.md — baseline già valida.
Verification

Test locale della funzione di pulizia con input sintetici: heading contaminati, fence isolati, blocchi fenced con semplice testo, HTML reale, code block reale.
Riesecuzione mirata di casi rappresentativi: T001B o T002, T002B o T006B, T003 o T007B, T005A o T005B, T009B.
Ricerca automatica dei pattern markdown, html e ## ``` nei generated per misurare la riduzione reale.
Riesecuzione completa della suite e controllo del report in tests/official/results/latest.md.
Compilazione rapida backend per escludere regressioni sintattiche.
Decisions

Il fix deve essere generale e provider-agnostico.
Per ora non si toccano i prompt.
Non conviene normalizzare solo in lettura o solo nell’API, perché lascerebbe il disco sporco.
Non conviene promuovere nuovi expected rumorosi: si rischia di congelare difetti del formato.
Se vuoi, il passo successivo è approvare questo piano e poi passare all’implementazione del cleanup generale in backend/ocr.py.
