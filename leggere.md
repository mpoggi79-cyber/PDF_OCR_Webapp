User: elencami i prossimi lavori? e spiegameli e motivameli

GitHub Copilot: Elenco attività aggiornato

Per costruire una lista utile parto dalla roadmap e dallo stato reale del codice: verifico le note del repository e i punti ancora scoperti nei test/documenti, poi ti restituisco lavori ordinati per priorità con motivazione e risultato atteso.

Read memory 

Le note confermano che la base è già solida: OCR, fallback, resume, batch e dataset ufficiale esistono. Il punto aperto più concreto è trasformare le capacità OCR strutturate già previste in capacità verificate e usabili, mantenendo export Markdown e compatibilità; controllo ora i TODO e i test per distinguere lavori necessari da rifiniture.

Searched for regex `TODO|FIXME|NotImplemented|pass$|ENABLE_|structured_metadata|layout_visualization|formula_regions|crop_regions|confidence` (`**/backend/**`), 39 results

Searched for regex `TODO|FIXME|structured|formula|layout|crop|confidence|prompt_profile` (`**/static/**`), 16 results

No matches found. Your search pattern might be excluded completely by either the search.exclude settings or .*ignore files.
If you believe that it should have results, you can check into the .*ignore files and the exclude setting (here are some excluded patterns for reference:[**/node_modules,**/bower_components,**/*.code-search]).
Then if you want to include those files you can call the tool again by setting "includeIgnoredFiles" to true.

Read 

Read , lines 1 to 120

Read , lines 680 to 980

Read , lines 1 to 160

Read , lines 1 to 220

Read 

La lettura restringe bene il quadro: le funzioni strutturate non sono più solo una voce di roadmap, sono già cablate e testate a livello unitario, ma l’interfaccia le conserva senza mostrarle e mancano prove comparative/qualitative. Completo la verifica della roadmap e del contratto API per ordinare i prossimi lavori senza proporre attività già concluse.

Read , lines 220 to 432

No matches found. Your search pattern might be excluded completely by either the search.exclude settings or .*ignore files.
If you believe that it should have results, you can check into the .*ignore files and the exclude setting (here are some excluded patterns for reference:[**/node_modules,**/bower_components,**/*.code-search]).
Then if you want to include those files you can call the tool again by setting "includeIgnoredFiles" to true.

Read 

Read , lines 1 to 180

**Stato attuale**

La base tecnica è già funzionante: OCR SDK `glmocr`, fallback HTTP, retry, diagnostica errori, resume, batch, profili prompt e sidecar JSON sono presenti. I prossimi lavori dovrebbero concentrarsi sulla qualità misurabile dell’OCR, non su nuove architetture.

**1. Verificare tutti i fallback reali**

Provare concretamente:

- Ollama non raggiungibile
- modello principale assente
- fallback `glm-ocr:v0.1.5`
- fallback HTTP dopo errore SDK
- timeout e risposta JSON malformata

Motivazione: il codice gestisce già questi casi, ma senza una prova reale non sappiamo se il comportamento sia corretto durante un errore operativo. È il lavoro più importante per evitare job bloccati o errori poco comprensibili.

Riferimenti: `ocr.py`, `nuovo piano.md`.

**2. Completare il dataset ufficiale**

Aggiungere gli input mancanti, soprattutto:

- `T005C` e `T005D`
- `T007` e `T007B`
- eventuali casi immagine ancora vuoti

Poi creare gli `expected` solo dopo controllo visivo.

Motivazione: il confronto testuale è utile, ma misura solo i documenti presenti. Servono almeno due esempi per categoria per capire se un profilo funziona davvero su bollette, moduli, scansioni, formule e pagine web.

**3. Definire metriche di qualità OCR**

Calcolare per ogni documento:

- pagine completate e fallite
- pagine vuote o sospette
- presenza di tabelle, formule e heading
- confidence media, solo quando il provider la restituisce
- score complessivo con motivazione leggibile

Motivazione: oggi un job completato viene trattato quasi come un job corretto. Bisogna distinguere “OCR terminato” da “OCR fedele”.

Attenzione: non bisogna inventare una confidence. Le capability devono riflettere ciò che il provider restituisce davvero, come già previsto in `ocr.py:708`.

**4. Rafforzare i test automatici**

Aggiungere test deterministici per:

- sidecar JSON
- recovery dopo crash
- resume delle sole pagine `pending`
- fallback provider e fallback modello
- batch incompleti
- endpoint API
- pagine senza contenuto
- metadata corrotti o mancanti

Motivazione: retry e classificazione errori sono già coperti parzialmente, ma persistenza e resume sono aree ad alto rischio. Un test automatico evita regressioni quando si modifica l’OCR.

I test attuali sono in `test_ocr_core.py` e `test_official_runner.py`.

**5. Stato della testata e della singola scansione**

L'estrazione supplementare della testata e' stata rimossa. Ogni pagina e' elaborata una sola volta sull'immagine rasterizzata completa, in modo che il Markdown rappresenti esclusivamente cio' che il provider riconosce dalla pagina.

**6. Selezione profilo prompt nella UI**

Completato: la UI espone tutti i profili e il default operativo e' `structured_document_no_html` per upload, OCR pagina e batch.

**7. Diagnostica OCR visibile**

Completato per le bbox disponibili: il controllo `Layout` mostra le regioni restituite dal provider e offre filtri indipendenti per testo, immagini, tabelle e formule. Nei documenti multipagina segue la pagina selezionata e usa il relativo sidecar; il backend normalizza il campo `page` delle regioni all'indice zero-based globale, mantenendo leggibili i sidecar storici gia' separati per pagina. I riquadri sono una diagnosi della segmentazione, non una garanzia di completezza; celle e parole interne alle tabelle non vengono disegnate senza bbox granulari del provider.

**8. Migliorare export e metadata senza cambiare la fonte canonica**

Mantenere:

- Markdown pagina per pagina come contenuto principale
- sidecar JSON come metadata opzionali
- metadata strutturati nell’export solo tramite opzione esplicita

Motivazione: includere automaticamente JSON o immagini nell’export potrebbe rompere i client esistenti e rendere meno leggibile il Markdown. La compatibilità API è un vincolo importante del progetto.

**9. Aggiungere test specifici per formule, tabelle e handwriting**

Preparare casi ufficiali dedicati e verificare visivamente:

- formule convertite in LaTeX
- tabelle con celle unite
- moduli compilati a mano
- immagini e didascalie
- ordine di lettura su layout complessi

Motivazione: sono gli elementi che determinano la qualità reale del prodotto. Un semplice confronto del testo non basta per tabelle, formule e impaginazioni complesse.

**10. Solo dopo: dashboard e architettura estesa**

Rimanderei:

- dashboard storica dei punteggi
- pipeline configurabili
- skill wrapper per agenti
- deployment alternativi
- supporto Apple Silicon
- script automatici di aggiornamento modello

Motivazione: sono utili, ma non risolvono il problema principale finché non sappiamo misurare la qualità OCR e garantire i fallback.

**Ordine consigliato**

1. Fallback e test di errore reali  
2. T006 aggiornato  
3. Dataset ufficiale completato  
4. Metriche di qualità  
5. Test automatici di persistenza e batch  
6. Selettore profili nella UI  
7. Diagnostica strutturata  
8. Export avanzato  
9. Dashboard e nuove architetture  

Questa sequenza è coerente con la roadmap già presente in `nuovo piano.md` e con i vincoli tecnici descritti in `AGENTS.md`.