# Copilot Instructions

- Leggi prima [AGENTS.md](../AGENTS.md) quando il task tocca OCR, persistenza, batch o frontend dei risultati.
- Mantieni [app.py](../app.py) leggero e concentra la logica nei moduli in [backend](../backend/).
- Mantieni il frontend in [static](../static/) come JavaScript vanilla senza bundler, framework o build step.
- Tratta la qualita' del risultato OCR come priorita' principale: preserva heading, liste, tabelle, formule, immagini e struttura del documento quando possibile.
- Mantieni compatibilita' API: aggiungi solo campi opzionali ai payload esistenti, senza rompere i client attuali.
- Non sostituire il markdown pagina per pagina come fonte canonica di export; i sidecar JSON OCR sono metadata opzionali.
- Preserva recovery e resume post-crash: pagine 0-indexed, stato file-based in uploads, ricostruzione da disco e semantica interrupted/resumable devono restare coerenti.
- Quando modifichi il flusso OCR, verifica sia il ramo glmocr sia il fallback HTTP a Ollama.