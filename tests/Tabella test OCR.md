# Tabella test OCR

Tabella riepilogativa dei casi descritti in [Elenco e descrizione test.md](Elenco%20e%20descrizione%20test.md).

| N. | Numero / nome test | Descrizione | Tipo input | Quantita' pagine | Data Ultimo Test | Tempo di conversione totale (min) |
| ---: | --- | --- | --- | ---: | --- | ---: |
| 1 | T001 - Documento strutturato bancario | Verifica OCR di un documento bancario strutturato con campi, importi e tabella riepilogativa; ultima esecuzione completata con confronto actual/expected: match. | PDF | 1 | 2026-08-22 | 0,72 |
| 2 | T001B - Fattura pagina singola strutturata | Verifica OCR di una fattura strutturata su pagina singola, con dati anagrafici, righe articolo e totali; ultima esecuzione completata con confronto actual/expected: match. | PDF | 1 | 2026-08-22 | 0,48 |
| 3 | T002 - PDF fotografico scannerizzato | Verifica OCR no-HTML di una fattura scansionata con contenuto ruotato di 90 gradi; confronto actual/expected: match, con intestazione, tabelle, pagamento e riepilogo recuperati. | PDF | 1 | 2026-08-23 | 0,94 |
| 4 | T002A - PDF fotografico diritto | Caso di riferimento per la stessa fattura fotografica in orientamento nativo: verifica OCR no-HTML su pagina singola, con confronto actual/expected: match. | PDF | 1 | 2026-08-23 | 1,18 |
| 5 | T002B - Modulo singolo scannerizzato | Verifica OCR no-HTML di un modulo scannerizzato su pagina singola; confronto actual/expected: match, con il risultato visionato e consolidato come expected. | PDF | 1 | 2026-08-23 | 3,03 |
| 6 | T003 - PDF da stampa browser | Verifica OCR di un documento ottenuto dalla stampa di una pagina web; confronto actual/expected: match, con il risultato consolidato come expected. | PDF | 1 | 2026-08-23 | 0,31 |
| 7 | T003B - Articolo singolo da stampa browser | Verifica OCR di un articolo web stampato su pagina singola; confronto actual/expected: match, con il risultato consolidato come expected. | PDF | 1 | 2026-08-23 | 0,19 |
| 8 | T005 - Documento multipagina strutturato | Verifica OCR di un documento multipagina strutturato con dati organizzati, pagine vuote e layout complesso; il runner è andato in timeout dopo 300 secondi, ma il backend ha completato il job dopo 328 secondi senza errori. L'actual disponibile coincide con expected. | PDF | 15 | 2026-08-22 | 4,98 |
| 9 | T005A - Bolletta luce multipagina strutturata | Verifica OCR no-HTML di una bolletta elettrica multipagina con dati strutturati e tabelle; risultato consolidato come expected con confronto actual/expected: match. | PDF | 8 | 2026-08-23 | 3,68 |
| 10 | T005B - Bolletta gas multipagina strutturata | Verifica OCR no-HTML su bolletta del gas multipagina con tabelle complesse; risultato migliore rispetto alla precedente versione MD+HTML, consolidato come expected con confronto actual/expected: match. | PDF | 4 | 2026-08-23 | 2,25 |
| 11 | T005C - Bolletta acqua multipagina strutturata | Caso previsto per una bolletta dell'acqua multipagina; l'input non e' ancora disponibile. | PDF | N/D | 2026-06-05 | N/D |
| 12 | T005D - Bolletta gas BN multipagina strutturata | Caso predisposto per verificare l'OCR no-HTML di una bolletta gas multipagina in bianco e nero. | PDF | 4 | 2026-08-23 | 2,15 |
| 13 | T005E - Movimenti Telepass multipagina strutturato | Verifica OCR no-HTML di un documento multipagina di movimenti Telepass; risultato verificato visivamente e consolidato come expected con confronto actual/expected: match. | PDF | 4 | 2026-08-23 | 2,64 |
| 14 | T006 - PDF multipagina scannerizzato | Verifica OCR no-HTML e continuita' del risultato su un documento scannerizzato multipagina; expected presente e confronto actual/expected: match nell'ultima verifica. | PDF | 4 | 2026-08-23 | 3,03 |
| 15 | T006B - Verbale multipagina scannerizzato | Verifica OCR no-HTML di un PDF scannerizzato firmato e timbrato; il file disponibile contiene 1 pagina, con intestazione recuperata tramite estrazione supplementare; confronto actual/expected: match. | PDF | 1 | 2026-08-23 | 1,11 |
| 16 | T007 - PDF multipagina da stampa browser | Verifica OCR e reading order di un documento web stampato multipagina. | PDF | 15 | 2026-06-05 | 3,52 |
| 17 | T007B - Report web multipagina da stampa browser | Verifica OCR di un report web multipagina da stampa browser, con rimozione del boilerplate non pertinente. | PDF | 9 | 2026-06-05 | 2,38 |
| 18 | T009 - Immagine con testi e tabelle | Verifica OCR di un'immagine contenente testo e tabelle; l'immagine di input non e' ancora disponibile. | Immagine | N/D | 2026-06-05 | N/D |
| 19 | T009B - Immagine modulo con tabella | Verifica OCR di un'immagine di modulo contenente una tabella. | Immagine | 1 | 2026-06-05 | 0,32 |
| 20 | T010 - Pagina A4 verticale con blocchi | Test di analisi per allineamento overlay, coordinate e viewBox su PDF A4 verticale con blocchi geometrici; usato come gate prima del benchmark. | PDF | 1 | 2026-08-25 | N/D |
| 21 | T011 - Pagina A4 verticale con tabella x0y0 | Test di calibrazione geometrica con tabella singola in alto a sinistra; ha individuato e confermato il fix dello scaling bbox 0-1000 -> pixel nell'overlay Layout; Markdown verificato visivamente. | PDF | 1 | 2026-08-25 | N/D |
| 22 | T013 - Pagina A4 verticale solo scritte sparse | Test con 4 etichette minuscole agli angoli su pagina bianca; ha rilevato un limite del layout detector (0 regioni trovate, markdown vuoto) non risolvibile abbassando la soglia globale senza introdurre rumore. | PDF | 1 | 2026-08-26 | N/D |

## Note

- `T005` e' un test autonomo relativo al documento multipagina dell'Agenzia delle Entrate; `T005A`, `T005B` e `T005C` appartengono invece al gruppo logico delle bollette.
- `N/D` indica che il file sorgente non e' presente nella cartella `input/` del caso.
- Per i PDF il numero di pagine e' quello del file attualmente presente; per le immagini disponibili e' indicata una pagina.
- I casi elencati sono 21; i casi con input attualmente disponibile sono 17.
- La data indica l'ultima esecuzione del test OCR registrata in `actual/last_run.json`; un eventuale confronto successivo con `--compare-only` non cambia questa data.
- Il tempo di conversione totale è espresso in minuti, arrotondato a due decimali, e corrisponde a `ocr_total_duration_seconds / 60`; `N/D` indica che il test non è ancora stato eseguito.
