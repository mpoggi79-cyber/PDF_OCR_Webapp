'use strict';

// ── Stato applicazione ────────────────────────────────────────────────────────
const state = {
  docId:       null,
  currentPage: 0,
  totalPages:  0,
  filename:    '',
  /** @type {Object.<number, string>} page → markdown */
  ocrResults:  {},
  /** @type {Object.<number, string>} page → 'pending'|'processing'|'done'|'error' */
  ocrStatuses: {},
  /** @type {Object.<number, number>} page → setInterval id */
  polls:       {},
  /** @type {Object.<number, number>} page → timestamp ms avvio OCR */
  ocrStartTimes: {},
  /** Ultime durate OCR completate (ms) — usate per stimare la % */
  ocrDurations: [],
};

// Timer che aggiorna il display ogni secondo mentre l'OCR è in corso
let _displayTimer = null;

function startDisplayTimer() {
  if (_displayTimer) return;
  _displayTimer = setInterval(() => {
    if (state.ocrStatuses[state.currentPage] === 'processing') {
      renderOcrPanel();   // aggiorna timer ed eventuale barra
    } else {
      stopDisplayTimer();
    }
  }, 1000);
}

function stopDisplayTimer() {
  if (_displayTimer) { clearInterval(_displayTimer); _displayTimer = null; }
}

/** Formatta secondi in mm:ss */
function fmtElapsed(sec) {
  const m = String(Math.floor(sec / 60)).padStart(2, '0');
  const s = String(sec % 60).padStart(2, '0');
  return `${m}:${s}`;
}

// ── Riferimenti DOM ───────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);

const els = {
  uploadOverlay:  $('upload-overlay'),
  uploadArea:     $('upload-area'),
  mainContainer:  $('main-container'),
  loadingOverlay: $('loading-overlay'),
  loadingText:    $('loading-text'),
  docInfo:        $('doc-info'),
  docFilename:    $('doc-filename'),
  docPages:       $('doc-pages'),
  pageImage:      $('page-image'),
  pageIndicator:  $('page-indicator'),
  prevBtn:        $('prev-btn'),
  nextBtn:        $('next-btn'),
  ocrBtn:         $('ocr-btn'),
  ocrAllBtn:      $('ocr-all-btn'),
  copyBtn:        $('copy-btn'),
  rawToggle:      $('raw-toggle'),
  ocrPlaceholder: $('ocr-placeholder'),
  ocrRendered:    $('ocr-rendered'),
  ocrRaw:         $('ocr-raw'),
  pageStrip:      $('page-strip'),
  exportBtn:      $('export-btn'),
  statusBar:      $('status-bar'),
  ollamaBadge:    $('ollama-badge'),
  pdfInput:       $('pdf-input'),
  pdfInputOverlay:$('pdf-input-overlay'),
};

// ── Inizializzazione ──────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // Input file header e overlay
  els.pdfInput.addEventListener('change',        e => handleFile(e.target.files[0]));
  els.pdfInputOverlay.addEventListener('change', e => handleFile(e.target.files[0]));

  // Drag & drop sull'area di upload
  ['dragenter', 'dragover'].forEach(ev =>
    els.uploadArea.addEventListener(ev, e => {
      e.preventDefault();
      els.uploadArea.classList.add('drag-over');
    })
  );
  ['dragleave', 'drop'].forEach(ev =>
    els.uploadArea.addEventListener(ev, e => {
      e.preventDefault();
      els.uploadArea.classList.remove('drag-over');
      if (ev === 'drop') {
        const f = e.dataTransfer.files[0];
        if (f?.name.toLowerCase().endsWith('.pdf')) handleFile(f);
      }
    })
  );

  // Navigazione con tasti freccia
  document.addEventListener('keydown', e => {
    // Non interferire se il focus è in un campo di testo
    if (['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName)) return;
    if (e.key === 'ArrowLeft')  changePage(-1);
    if (e.key === 'ArrowRight') changePage(1);
  });

  // Divisore ridimensionabile
  setupDivider();

  // Controllo salute Ollama
  checkOllama();

  // ── Inizializzazione Batch ──────────────────────────────────────────

  // Folder input (webkitdirectory)
  document.getElementById('folder-input').addEventListener('change', e => {
    const pdfs = Array.from(e.target.files).filter(f => f.name.toLowerCase().endsWith('.pdf'));
    if (pdfs.length === 0) { alert('Nessun file PDF trovato nella cartella selezionata.'); return; }
    batchState.files = pdfs;
    renderBatchFileList();
  });

  // Multi-file input
  document.getElementById('files-input').addEventListener('change', e => {
    const pdfs = Array.from(e.target.files).filter(f => f.name.toLowerCase().endsWith('.pdf'));
    if (pdfs.length === 0) { alert('Nessun file PDF selezionato.'); return; }
    batchState.files = pdfs;
    renderBatchFileList();
  });

  // Drag & drop sull'area batch
  const dropArea = document.getElementById('batch-drop-area');
  if (dropArea) {
    ['dragenter', 'dragover'].forEach(ev =>
      dropArea.addEventListener(ev, e => { e.preventDefault(); dropArea.classList.add('drag-over'); })
    );
    ['dragleave', 'drop'].forEach(ev =>
      dropArea.addEventListener(ev, e => {
        e.preventDefault();
        dropArea.classList.remove('drag-over');
        if (ev === 'drop') {
          const pdfs = Array.from(e.dataTransfer.files).filter(f => f.name.toLowerCase().endsWith('.pdf'));
          if (pdfs.length === 0) { alert('Nessun file PDF trovato nel trascinamento.'); return; }
          batchState.files = pdfs;
          renderBatchFileList();
        }
      })
    );
  }
});

// ── Controllo Ollama ──────────────────────────────────────────────────────────
async function checkOllama() {
  try {
    const res  = await fetch('/api/health');
    const data = await res.json();

    if (data.ollama !== 'ok') {
      setBadge('error', '● Ollama non raggiungibile');
    } else if (data.glm_ocr !== 'available') {
      setBadge('warn', '⚠ glm-ocr non trovato');
    } else {
      setBadge('ok', '● Ollama OK');
    }
  } catch {
    setBadge('error', '● Ollama offline');
  }
}

function setBadge(type, text) {
  els.ollamaBadge.textContent = text;
  els.ollamaBadge.className   = `badge badge-${type}`;
}

// ── Upload PDF ────────────────────────────────────────────────────────────────
function handleFile(file) {
  if (!file) return;
  if (!file.name.toLowerCase().endsWith('.pdf')) {
    alert('Seleziona un file PDF (.pdf).');
    return;
  }
  uploadPdf(file);
}

async function uploadPdf(file) {
  showLoading('Caricamento e conversione pagine PDF...');
  try {
    const form = new FormData();
    form.append('file', file);

    const res = await fetch('/api/upload', { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();

    // Ferma eventuali polling e timer in corso
    Object.values(state.polls).forEach(clearInterval);
    stopDisplayTimer();

    // Aggiorna stato
    Object.assign(state, {
      docId:          data.doc_id,
      currentPage:    0,
      totalPages:     data.page_count,
      filename:       data.filename,
      ocrResults:     {},
      ocrStatuses:    {},
      polls:          {},
      ocrStartTimes:  {},
      ocrDurations:   [],
    });

    // Aggiorna UI
    els.docFilename.textContent = data.filename;
    els.docPages.textContent    = `— ${data.page_count} ${data.page_count === 1 ? 'pagina' : 'pagine'}`;
    els.docInfo.style.display   = 'flex';
    els.exportBtn.style.display = '';

    els.uploadOverlay.style.display = 'none';
    els.mainContainer.style.display = 'flex';

    renderPageStrip();
    loadPage(0);

  } catch (err) {
    alert('Errore caricamento: ' + err.message);
  } finally {
    hideLoading();
    els.pdfInput.value        = '';
    els.pdfInputOverlay.value = '';
  }
}

// ── Navigazione pagine ────────────────────────────────────────────────────────
function loadPage(n) {
  state.currentPage = n;

  els.pageIndicator.textContent = `${n + 1} / ${state.totalPages}`;
  els.prevBtn.disabled = n === 0;
  els.nextBtn.disabled = n === state.totalPages - 1;

  // Carica immagine pagina (cache-bust con timestamp)
  els.pageImage.src = `/api/page/${state.docId}/${n}?_=${Date.now()}`;

  updateAllThumbs();
  renderOcrPanel();
}

function changePage(delta) {
  const n = state.currentPage + delta;
  if (n >= 0 && n < state.totalPages) loadPage(n);
}

// ── Striscia miniature ────────────────────────────────────────────────────────
function renderPageStrip() {
  els.pageStrip.innerHTML = '';
  for (let i = 0; i < state.totalPages; i++) {
    const btn       = document.createElement('button');
    btn.className   = 'thumb';
    btn.textContent = i + 1;
    btn.title       = `Vai a pagina ${i + 1}`;
    btn.addEventListener('click', () => loadPage(i));
    els.pageStrip.appendChild(btn);
  }
}

function updateAllThumbs() {
  const thumbs = els.pageStrip.querySelectorAll('.thumb');
  thumbs.forEach((btn, i) => {
    btn.classList.remove('thumb-active', 'thumb-done', 'thumb-processing', 'thumb-error');
    if (i === state.currentPage) btn.classList.add('thumb-active');

    const status = state.ocrStatuses[i] ?? 'pending';
    if (state.ocrResults[i] !== undefined) {
      btn.classList.add('thumb-done');
    } else if (status === 'processing') {
      btn.classList.add('thumb-processing');
    } else if (status === 'error') {
      btn.classList.add('thumb-error');
    }
  });

  // Scorri la striscia in modo che la pagina corrente sia visibile
  const thumb = els.pageStrip.children[state.currentPage];
  if (thumb) thumb.scrollIntoView({ inline: 'nearest', behavior: 'smooth', block: 'nearest' });
}

// ── Pannello OCR ──────────────────────────────────────────────────────────────
function renderOcrPanel() {
  const page    = state.currentPage;
  const status  = state.ocrStatuses[page] ?? 'pending';
  const md      = state.ocrResults[page];
  const showRaw = els.rawToggle.checked;

  // Reset
  els.ocrPlaceholder.style.display = 'none';
  els.ocrRendered.style.display    = 'none';
  els.ocrRaw.style.display         = 'none';
  els.copyBtn.disabled             = true;
  els.ocrBtn.disabled              = false;

  if (md !== undefined) {
    // Risultato disponibile
    els.copyBtn.disabled = false;
    if (showRaw) {
      els.ocrRaw.style.display = 'block';
      els.ocrRaw.textContent   = md;
    } else {
      els.ocrRendered.style.display = 'block';
      els.ocrRendered.innerHTML     = marked.parse(md);
    }
    els.ocrBtn.textContent = '🔄 Riesegui OCR';
    els.ocrBtn.disabled    = false;

  } else if (status === 'processing') {
    els.ocrPlaceholder.style.display = 'flex';

    // Calcola secondi trascorsi
    const startTs  = state.ocrStartTimes[page];
    const elapsed  = startTs ? Math.floor((Date.now() - startTs) / 1000) : 0;

    // Barra di avanzamento: stimata se abbiamo dati storici, altrimenti indeterminata
    let barHtml;
    if (state.ocrDurations.length > 0) {
      const avgSec = (state.ocrDurations.reduce((a, b) => a + b, 0) / state.ocrDurations.length) / 1000;
      const pct    = Math.min(95, Math.round((elapsed / avgSec) * 100));
      barHtml = `
        <div class="ocr-progress-wrap">
          <div class="ocr-progress-bar">
            <div class="ocr-progress-fill" style="width:${pct}%"></div>
          </div>
          <span class="ocr-progress-label">~${pct}% stimato</span>
        </div>`;
    } else {
      barHtml = `
        <div class="ocr-progress-wrap">
          <div class="ocr-progress-bar indeterminate">
            <div class="ocr-progress-fill"></div>
          </div>
          <span class="ocr-progress-label">elaborazione in corso…</span>
        </div>`;
    }

    els.ocrPlaceholder.innerHTML = `
      <span class="spinner"></span>
      <span class="ocr-processing-label">OCR in elaborazione</span>
      <span class="ocr-timer">${fmtElapsed(elapsed)}</span>
      ${barHtml}`;

    els.ocrBtn.textContent = '⏳ Elaborazione...';
    els.ocrBtn.disabled    = true;
    startDisplayTimer();

  } else if (status === 'error') {
    els.ocrPlaceholder.style.display = 'flex';
    els.ocrPlaceholder.textContent   = '❌ Errore OCR. Riprova.';
    els.ocrBtn.textContent           = '▶ Esegui OCR';

  } else {
    els.ocrPlaceholder.style.display = 'flex';
    els.ocrPlaceholder.textContent   =
      'Clicca "Esegui OCR" per convertire questa pagina';
    els.ocrBtn.textContent = '▶ Esegui OCR';
  }
}

// ── Esecuzione OCR ────────────────────────────────────────────────────────────
async function runOcr() {
  if (!state.docId) return;
  await triggerOcr(state.currentPage);
  renderOcrPanel();
  updateAllThumbs();
}

async function runOcrAll() {
  if (!state.docId) return;
  setStatus(`Avvio OCR per tutte le ${state.totalPages} pagine…`);

  for (let i = 0; i < state.totalPages; i++) {
    if (state.ocrResults[i] !== undefined) continue;
    if (state.ocrStatuses[i] === 'processing') continue;
    await triggerOcr(i);
  }
  setStatus('OCR avviato su tutte le pagine. Attendere i risultati…');
  renderOcrPanel();
  updateAllThumbs();
}

async function triggerOcr(page) {
  if (state.ocrStatuses[page] === 'processing') return;
  state.ocrStatuses[page]   = 'processing';
  state.ocrStartTimes[page] = Date.now();   // registra inizio
  if (page === state.currentPage) { renderOcrPanel(); startDisplayTimer(); }
  updateAllThumbs();

  try {
    const res  = await fetch(`/api/ocr/${state.docId}/${page}`, { method: 'POST' });
    const data = await res.json();

    if (data.status === 'done' && data.markdown != null) {
      state.ocrResults[page]  = data.markdown;
      state.ocrStatuses[page] = 'done';
      if (page === state.currentPage) renderOcrPanel();
      updateAllThumbs();
    } else {
      // Il backend sta elaborando in background: avvia polling
      startPolling(page);
    }
  } catch (e) {
    state.ocrStatuses[page] = 'error';
    if (page === state.currentPage) renderOcrPanel();
    updateAllThumbs();
  }
}

function startPolling(page) {
  if (state.polls[page]) return;  // già in polling

  state.polls[page] = setInterval(async () => {
    try {
      const res  = await fetch(`/api/ocr/${state.docId}/${page}`);
      const data = await res.json();

      if (data.status === 'done' && data.markdown != null) {
        // Registra durata per la stima futura
        if (state.ocrStartTimes[page]) {
          const duration = Date.now() - state.ocrStartTimes[page];
          if (duration > 0) {
            state.ocrDurations.push(duration);
            if (state.ocrDurations.length > 6) state.ocrDurations.shift();
          }
        }
        state.ocrResults[page]  = data.markdown;
        state.ocrStatuses[page] = 'done';
        clearInterval(state.polls[page]);
        delete state.polls[page];
        const sec = state.ocrStartTimes[page]
          ? Math.round((Date.now() - state.ocrStartTimes[page]) / 1000)
          : null;
        setStatus(`✓ Pagina ${page + 1} completata${sec !== null ? ` in ${fmtElapsed(sec)}` : ''}.`);
        if (page === state.currentPage) { stopDisplayTimer(); renderOcrPanel(); }
        updateAllThumbs();

      } else if (data.status === 'error') {
        state.ocrStatuses[page] = 'error';
        clearInterval(state.polls[page]);
        delete state.polls[page];
        if (page === state.currentPage) { stopDisplayTimer(); renderOcrPanel(); }
        updateAllThumbs();
      }
    } catch (_) { /* ignora errori di rete transitori */ }
  }, 2500);
}

// ── Azioni UI ─────────────────────────────────────────────────────────────────
function toggleRaw() {
  renderOcrPanel();
}

async function copyMarkdown() {
  const md = state.ocrResults[state.currentPage];
  if (!md) return;
  try {
    await navigator.clipboard.writeText(md);
    setStatus('📋 Copiato negli appunti!');
  } catch {
    // Fallback per browser/contesti senza clipboard API
    const ta = document.createElement('textarea');
    ta.value = md;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    ta.remove();
    setStatus('📋 Copiato!');
  }
}

async function exportAll() {
  if (!state.docId) return;
  try {
    const res  = await fetch(`/api/export/${state.docId}`);
    const data = await res.json();
    const blob = new Blob([data.content], { type: 'text/markdown;charset=utf-8' });
    const url  = URL.createObjectURL(blob);
    const a    = Object.assign(document.createElement('a'), { href: url, download: data.filename });
    a.click();
    URL.revokeObjectURL(url);
    setStatus(`⬇ Esportato come ${data.filename}`);
  } catch (e) {
    alert('Errore export: ' + e.message);
  }
}

// ── Divisore ridimensionabile ─────────────────────────────────────────────────
function setupDivider() {
  const divider  = $('divider');
  const left     = document.querySelector('.left-panel');
  const right    = document.querySelector('.right-panel');
  if (!divider || !left || !right) return;

  let dragging = false;
  let startX   = 0;
  let startLeft = 0;

  divider.addEventListener('mousedown', e => {
    dragging  = true;
    startX    = e.clientX;
    startLeft = left.getBoundingClientRect().width;
    divider.classList.add('dragging');
    document.body.style.userSelect    = 'none';
    document.body.style.pointerEvents = 'none';
  });

  document.addEventListener('mousemove', e => {
    if (!dragging) return;
    const container = document.querySelector('.main-container');
    const totalW    = container.getBoundingClientRect().width - 4; // 4 = divider
    const delta     = e.clientX - startX;
    const newLeft   = Math.min(Math.max(startLeft + delta, 200), totalW - 200);
    const pct       = (newLeft / totalW) * 100;
    left.style.flex  = `0 0 ${pct}%`;
    right.style.flex = `0 0 ${100 - pct}%`;
  });

  document.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    divider.classList.remove('dragging');
    document.body.style.userSelect    = '';
    document.body.style.pointerEvents = '';
  });
}

// ── Helper UI ─────────────────────────────────────────────────────────────────
function showLoading(text) {
  els.loadingText.textContent      = text ?? 'Caricamento...';
  els.loadingOverlay.style.display = 'flex';
}
function hideLoading() {
  els.loadingOverlay.style.display = 'none';
}

let _statusTimer;
function setStatus(msg) {
  if (!els.statusBar) return;
  els.statusBar.textContent = msg;
  els.statusBar.style.opacity = '1';
  clearTimeout(_statusTimer);
  _statusTimer = setTimeout(() => {
    els.statusBar.style.opacity = '0';
    setTimeout(() => { els.statusBar.textContent = ''; els.statusBar.style.opacity = '1'; }, 300);
  }, 4000);
}

// ── Batch Mode ────────────────────────────────────────────────────────────────

const batchState = {
  files:     [],      // File[] selezionati dall'utente
  batchId:   null,    // batch_id restituito dal backend
  docs:      [],      // [{doc_id, filename, page_count, pages_done, pages_error, status}]
  pollTimer: null,
  done:      false,
};

function openBatch() {
  document.getElementById('batch-overlay').style.display = 'flex';
  if (!batchState.batchId) resetBatchToStep1();
}

function closeBatch() {
  document.getElementById('batch-overlay').style.display = 'none';
}

function resetBatchToStep1() {
  // Ferma il polling se attivo
  if (batchState.pollTimer) { clearInterval(batchState.pollTimer); batchState.pollTimer = null; }

  batchState.files   = [];
  batchState.batchId = null;
  batchState.docs    = [];
  batchState.done    = false;

  document.getElementById('batch-step-select').style.display   = 'block';
  document.getElementById('batch-step-progress').style.display = 'none';
  document.getElementById('batch-file-list').style.display     = 'none';
  document.getElementById('batch-drop-area').style.display     = 'flex';
  document.getElementById('batch-result-actions').style.display = 'none';
  const fi = document.getElementById('folder-input');
  const si = document.getElementById('files-input');
  if (fi) fi.value = '';
  if (si) si.value = '';
}

// ── Gestione selezione file batch ─────────────────────────────────────────────
// (i listener sono registrati nel DOMContentLoaded principale in cima al file)

function renderBatchFileList() {
  const files = batchState.files;
  document.getElementById('batch-drop-area').style.display  = 'none';
  document.getElementById('batch-file-list').style.display  = 'block';
  document.getElementById('batch-file-count').textContent   =
    `${files.length} file PDF selezionati`;

  const totalSize = files.reduce((s, f) => s + f.size, 0);
  let html = `<table class="batch-table">
    <thead><tr><th>#</th><th>Nome file</th><th>Dimensione</th></tr></thead><tbody>`;
  files.forEach((f, i) => {
    html += `<tr><td>${i + 1}</td><td>${escHtml(f.name)}</td><td>${fmtSize(f.size)}</td></tr>`;
  });
  html += `</tbody><tfoot><tr>
    <td colspan="2" style="text-align:right;color:var(--muted)">Totale</td>
    <td>${fmtSize(totalSize)}</td>
  </tr></tfoot></table>`;
  document.getElementById('batch-files-table-wrap').innerHTML = html;
}

function clearBatchFiles() {
  batchState.files = [];
  document.getElementById('batch-file-list').style.display = 'none';
  document.getElementById('batch-drop-area').style.display = 'flex';
  document.getElementById('folder-input').value = '';
  document.getElementById('files-input').value  = '';
}

// ── Avvio batch ───────────────────────────────────────────────────────────────

async function startBatch() {
  if (batchState.files.length === 0) return;

  const btn = document.getElementById('batch-start-btn');
  btn.disabled = true;
  btn.textContent = '⏳ Caricamento file…';

  try {
    showLoading(`Caricamento di ${batchState.files.length} file PDF e conversione pagine…`);

    const form = new FormData();
    batchState.files.forEach(f => form.append('files', f));

    const res = await fetch('/api/batch', { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();

    if (data.errors && data.errors.length > 0) {
      const errList = data.errors.map(e => `• ${e.filename}: ${e.error}`).join('\n');
      alert(`Alcuni file non sono stati elaborati:\n\n${errList}`);
    }
    if (data.docs.length === 0) {
      throw new Error('Nessun file è stato caricato correttamente.');
    }

    batchState.batchId = data.batch_id;
    batchState.docs    = data.docs;

    // Mostra pannello progresso
    document.getElementById('batch-step-select').style.display   = 'none';
    document.getElementById('batch-step-progress').style.display = 'block';
    renderBatchProgress(data.docs);

    // Avvia OCR
    const startRes = await fetch(`/api/batch/${data.batch_id}/start`, { method: 'POST' });
    if (!startRes.ok) throw new Error('Errore avvio OCR batch.');
    const startData = await startRes.json();

    document.getElementById('batch-progress-label').textContent =
      `OCR avviato su ${startData.pages_queued} pagine in background…`;

    // Polling
    batchState.pollTimer = setInterval(pollBatchStatus, 3000);

  } catch (err) {
    alert('Errore batch: ' + err.message);
    btn.disabled    = false;
    btn.textContent = '▶ Avvia Conversione Batch';
  } finally {
    hideLoading();
  }
}

async function pollBatchStatus() {
  if (!batchState.batchId) return;
  try {
    const res  = await fetch(`/api/batch/${batchState.batchId}`);
    const data = await res.json();
    batchState.docs = data.docs;
    renderBatchProgress(data.docs);

    const allFinished = data.docs.every(d => d.status === 'done' || d.status === 'error' || d.status === 'partial');
    if (allFinished) {
      clearInterval(batchState.pollTimer);
      batchState.pollTimer = null;
      batchState.done      = true;
      const nDone    = data.docs.filter(d => d.status === 'done').length;
      const nErrors  = data.docs.filter(d => d.status === 'error').length;
      const nPartial = data.docs.filter(d => d.status === 'partial').length;
      document.getElementById('batch-progress-label').textContent =
        `✓ Completato — ${nDone} OK, ${nPartial} parziali, ${nErrors} errori su ${data.docs.length} file.`;
      document.getElementById('batch-result-actions').style.display = 'flex';
    }
  } catch (_) { /* ignora errori di rete transitori */ }
}

function renderBatchProgress(docs) {
  const totalPages = docs.reduce((s, d) => s + d.page_count, 0);
  const donePages  = docs.reduce((s, d) => s + d.pages_done, 0);
  const pct = totalPages > 0 ? Math.round((donePages / totalPages) * 100) : 0;

  document.getElementById('batch-overall-fill').style.width   = pct + '%';
  document.getElementById('batch-progress-pct').textContent   = pct + '%';

  const statusLabel = {
    pending:    '○ In attesa',
    processing: '⟳ Elaborazione',
    done:       '✓ Completato',
    partial:    '⚠ Parziale',
    error:      '✗ Errore',
  };
  const statusCls = {
    pending: '', processing: 'batch-proc', done: 'batch-ok', partial: 'batch-warn', error: 'batch-err',
  };

  let html = `<table class="batch-table">
    <thead>
      <tr>
        <th>#</th><th>File</th><th>Pagine</th>
        <th>Elaborate</th><th>Errori</th><th>Stato</th>
      </tr>
    </thead><tbody>`;
  docs.forEach((d, i) => {
    const cls   = statusCls[d.status] ?? '';
    const label = statusLabel[d.status] ?? d.status;
    html += `<tr class="${cls}">
      <td>${i + 1}</td>
      <td>${escHtml(d.filename)}</td>
      <td>${d.page_count}</td>
      <td>${d.pages_done}</td>
      <td>${d.pages_error}</td>
      <td>${label}</td>
    </tr>`;
  });
  html += '</tbody></table>';
  document.getElementById('batch-progress-table-wrap').innerHTML = html;
}

// ── Download report e ZIP ─────────────────────────────────────────────────────

async function downloadBatchReport() {
  if (!batchState.batchId) return;
  try {
    const res  = await fetch(`/api/batch/${batchState.batchId}/report`);
    const data = await res.json();
    const blob = new Blob([data.report], { type: 'text/markdown;charset=utf-8' });
    const url  = URL.createObjectURL(blob);
    Object.assign(document.createElement('a'), { href: url, download: data.filename }).click();
    URL.revokeObjectURL(url);
    setStatus('📄 Report scaricato.');
  } catch (e) {
    alert('Errore download report: ' + e.message);
  }
}

function downloadBatchZip() {
  if (!batchState.batchId) return;
  const a = document.createElement('a');
  a.href = `/api/batch/${batchState.batchId}/export`;
  a.click();
  setStatus('⬇ Download ZIP avviato…');
}

// ── Utility ───────────────────────────────────────────────────────────────────

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function fmtSize(bytes) {
  if (bytes < 1024)        return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
}
