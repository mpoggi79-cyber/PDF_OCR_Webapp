# Tabella test OCR

Tabella riepilogativa dei casi descritti in [Elenco e descrizione test.md](Elenco%20e%20descrizione%20test.md).

| N. | Numero / nome test | Descrizione | Tipo input | Quantita' pagine | Data Ultimo Test |
| ---: | --- | --- | --- | ---: | --- |
| 1 | T001 - Documento strutturato bancario | Verifica OCR di un documento bancario strutturato con campi, importi e tabella riepilogativa; ultima esecuzione completata con confronto actual/expected: match. | PDF | 1 | 2026-08-22 |
| 2 | T001B - Fattura pagina singola strutturata | Verifica OCR di una fattura strutturata su pagina singola, con dati anagrafici, righe articolo e totali; ultima esecuzione completata con confronto actual/expected: match. | PDF | 1 | 2026-08-22 |
| 3 | T002 - PDF fotografico scannerizzato | Verifica OCR no-HTML di una fattura scansionata con contenuto ruotato di 90 gradi; confronto actual/expected: match, con intestazione, tabelle, pagamento e riepilogo recuperati. | PDF | 1 | 2026-08-23 |
| 4 | T002A - PDF fotografico diritto | Caso di riferimento per la stessa fattura fotografica in orientamento nativo: verifica OCR no-HTML su pagina singola, con confronto actual/expected: match. | PDF | 1 | 2026-08-23 |
| 5 | T002B - Modulo singolo scannerizzato | Verifica OCR di un modulo scannerizzato su pagina singola. | PDF | 1 | 2026-06-05 |
| 6 | T003 - PDF da stampa browser | Verifica OCR di un documento ottenuto dalla stampa di una pagina web. | PDF | 1 | 2026-06-05 |
| 7 | T003B - Articolo singolo da stampa browser | Verifica OCR di un articolo web stampato su pagina singola. | PDF | 1 | 2026-06-05 |
| 8 | T005 - Documento multipagina strutturato | Verifica OCR di un documento multipagina strutturato con dati organizzati, pagine vuote e layout complesso; il runner è andato in timeout dopo 300 secondi, ma il backend ha completato il job dopo 328 secondi senza errori. L'actual disponibile coincide con expected. | PDF | 15 | 2026-08-22 |
| 9 | T005A - Bolletta luce multipagina strutturata | Verifica OCR di una bolletta elettrica multipagina con dati strutturati e tabelle. | PDF | 8 | 2026-06-05 |
| 10 | T005B - Bolletta gas multipagina strutturata | Verifica OCR di una bolletta del gas multipagina con dati strutturati e tabelle. | PDF | 4 | 2026-06-05 |
| 11 | T005C - Bolletta acqua multipagina strutturata | Caso previsto per una bolletta dell'acqua multipagina; l'input non e' ancora disponibile. | PDF | N/D | 2026-06-05 |
| 12 | T006 - PDF multipagina scannerizzato | Verifica OCR e continuita' del risultato su un documento scannerizzato multipagina. | PDF | 4 | 2026-06-05 |
| 13 | T006B - Verbale multipagina scannerizzato | Verifica OCR di un verbale scannerizzato; il file attualmente disponibile contiene 1 pagina. | PDF | 1 | 2026-06-05 |
| 14 | T007 - PDF multipagina da stampa browser | Verifica OCR e reading order di un documento web stampato multipagina. | PDF | 15 | 2026-06-05 |
| 15 | T007B - Report web multipagina da stampa browser | Verifica OCR di un report web stampato multipagina, con rimozione del boilerplate non pertinente. | PDF | 9 | 2026-06-05 |
| 16 | T009 - Immagine con testi e tabelle | Verifica OCR di un'immagine contenente testo e tabelle; l'immagine di input non e' ancora disponibile. | Immagine | N/D | 2026-06-05 |
| 17 | T009B - Immagine modulo con tabella | Verifica OCR di un'immagine di modulo contenente una tabella. | Immagine | 1 | 2026-06-05 |

## Note

- `T005` e' un test autonomo relativo al documento multipagina dell'Agenzia delle Entrate; `T005A`, `T005B` e `T005C` appartengono invece al gruppo logico delle bollette.
- `N/D` indica che il file sorgente non e' presente nella cartella `input/` del caso.
- Per i PDF il numero di pagine e' quello del file attualmente presente; per le immagini disponibili e' indicata una pagina.
- I casi elencati sono 17; i casi con input attualmente disponibile sono 15.
- La data indica l'ultima esecuzione del test OCR registrata in `actual/last_run.json`; un eventuale confronto successivo con `--compare-only` non cambia questa data.
