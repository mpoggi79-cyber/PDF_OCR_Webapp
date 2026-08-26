'use strict';

// ── Stato applicazione ────────────────────────────────────────────────────────
const state = {
  docId:       null,
  currentPage: 0,
  totalPages:  0,
  filename:    '',
  sourceType:  null,
  documentJob: null,
  documentJobPoll: null,
  /** @type {Object.<number, string>} page → markdown */
  ocrResults:  {},
  /** @type {Object.<number, Object|null>} page → dettaglio errore OCR */
  ocrErrors:   {},
  /** @type {Object.<number, Object|null>} page → payload OCR strutturato opzionale */
  ocrStructured: {},
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
let _batchUploadTimer = null;
let _batchUploadStartedAt = 0;
const PDF_EXTENSIONS = ['.pdf'];
const IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg'];
const PROMPT_PROFILE_LABELS = {
  default: 'Generico',
  structured_document: 'Documento strutturato',
  structured_document_no_html: 'Strutturato, solo Markdown',
  web_article: 'Articolo web',
};

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

function startBatchUploadTimer() {
  stopBatchUploadTimer();
  _batchUploadStartedAt = Date.now();
  _batchUploadTimer = setInterval(() => {
    const elapsed = Math.floor((Date.now() - _batchUploadStartedAt) / 1000);
    const count = batchState.files.length;
    const message = `Preparazione di ${count} PDF in corso… (${fmtElapsed(elapsed)})`;
    const button = document.getElementById('batch-start-btn');
    if (button?.disabled) button.textContent = `⏳ ${message}`;
    const status = document.getElementById('batch-preparation-status');
    if (status) {
      status.dataset.elapsed = fmtElapsed(elapsed);
      renderBatchPreparation(batchState.preparation, batchState.errors);
    }
  }, 1000);
}

function stopBatchUploadTimer() {
  if (_batchUploadTimer) {
    clearInterval(_batchUploadTimer);
    _batchUploadTimer = null;
  }
}

/** Formatta secondi in mm:ss */
function fmtElapsed(sec) {
  const m = String(Math.floor(sec / 60)).padStart(2, '0');
  const s = String(sec % 60).padStart(2, '0');
  return `${m}:${s}`;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function buildOcrErrorHtml(error) {
  if (!error) return null;

  const sourceLabel = error.source === 'ollama' ? 'Ollama / modello' : 'Backend';
  const retryLabel  = error.retryable ? 'Sì' : 'No';
  const interpretation = escapeHtml(error.interpretation || 'Nessuna interpretazione disponibile.');
  const detail = escapeHtml(error.detail || 'Nessun dettaglio tecnico disponibile.');
  const label = escapeHtml(error.label || 'Errore OCR');
  const type = escapeHtml(error.type || 'unknown');

  return `
    <div class="ocr-error-card">
      <div class="ocr-error-header">
        <span class="ocr-error-icon">❌</span>
        <div>
          <div class="ocr-error-title">${label}</div>
          <div class="ocr-error-meta">${escapeHtml(sourceLabel)} · <code>${type}</code></div>
        </div>
      </div>
      <div class="ocr-error-section">
        <div class="ocr-error-label">Interpretazione</div>
        <p>${interpretation}</p>
      </div>
      <div class="ocr-error-section">
        <div class="ocr-error-label">Riprova consigliata</div>
        <p>${escapeHtml(retryLabel)}</p>
      </div>
      <div class="ocr-error-section">
        <div class="ocr-error-label">Dettaglio tecnico</div>
        <pre class="ocr-error-detail">${detail}</pre>
      </div>
    </div>`;
}

function extractStructuredOcrPayload(data) {
  if (!data || typeof data !== 'object') return null;

  const payload = {
    provider: data.provider ?? null,
    model: data.model ?? null,
    layoutVisualization: data.layout_visualization ?? null,
    cropRegions: data.crop_regions ?? null,
    tableRegions: data.table_regions ?? null,
    formulaRegions: data.formula_regions ?? null,
    confidence: data.confidence ?? null,
    structureMetadata: data.structure_metadata ?? null,
    rawProviderPayload: data.raw_provider_payload ?? null,
  };

  const hasStructuredContent = Object.entries(payload)
    .some(([, value]) => value !== null && value !== undefined);

  return hasStructuredContent ? payload : null;
}

function applyOcrPayload(page, data) {
  state.ocrStatuses[page] = data.status;

  if (data.markdown != null) {
    state.ocrResults[page] = data.markdown;
  }

  state.ocrErrors[page] = data.error ?? null;

  const structuredPayload = extractStructuredOcrPayload(data);
  if (structuredPayload) {
    state.ocrStructured[page] = structuredPayload;
  } else {
    delete state.ocrStructured[page];
  }

  if (page === state.currentPage) renderOcrOverlay();
}

// ── Riferimenti DOM ───────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);

const els = {
  uploadOverlay:  $('upload-overlay'),
  pdfUploadArea:  $('pdf-upload-area'),
  imageUploadArea:$('image-upload-area'),
  mainContainer:  $('main-container'),
  loadingOverlay: $('loading-overlay'),
  loadingText:    $('loading-text'),
  docInfo:        $('doc-info'),
  docFilename:    $('doc-filename'),
  docPages:       $('doc-pages'),
  pageImage:      $('page-image'),
  ocrOverlay:     $('ocr-overlay'),
  ocrOverlayStatus:$('ocr-overlay-status'),
  ocrOverlayToggle:$('ocr-overlay-toggle'),
  ocrOverlayFilters:$('ocr-overlay-filters'),
  ocrOverlayText: $('ocr-overlay-text'),
  ocrOverlayImage:$('ocr-overlay-image'),
  ocrOverlayTable:$('ocr-overlay-table'),
  ocrOverlayFormula:$('ocr-overlay-formula'),
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
  promptProfileSelect: $('prompt-profile-select'),
  batchPromptProfileSelect: $('batch-prompt-profile-select'),
  pdfInput:       $('pdf-input'),
  pdfInputOverlay:$('pdf-input-overlay'),
  imageInput:     $('image-input'),
  imageInputOverlay:$('image-input-overlay'),
};

// ── Inizializzazione ──────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  preventBrowserFileDrop();

  els.pageImage.addEventListener('load', renderOcrOverlay);
  window.addEventListener('resize', renderOcrOverlay);

  // Input file header e overlay
  els.pdfInput.addEventListener('change', e => handleFile(e.target.files[0], 'pdf'));
  els.pdfInputOverlay.addEventListener('change', e => handleFile(e.target.files[0], 'pdf'));
  els.imageInput.addEventListener('change', e => handleFile(e.target.files[0], 'image'));
  els.imageInputOverlay.addEventListener('change', e => handleFile(e.target.files[0], 'image'));

  setupUploadArea(els.pdfUploadArea, 'pdf');
  setupUploadArea(els.imageUploadArea, 'image');

  [els.promptProfileSelect, els.batchPromptProfileSelect].forEach(select => {
    select?.addEventListener('change', () => syncPromptProfileSelectors(select));
  });

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
    resetDropAreaState(dropArea);

    dropArea.addEventListener('dragenter', event => {
      event.preventDefault();
      incrementDropAreaState(dropArea);
    });

    dropArea.addEventListener('dragover', event => {
      event.preventDefault();
      dropArea.classList.add('drag-over');
    });

    dropArea.addEventListener('dragleave', event => {
      event.preventDefault();
      decrementDropAreaState(dropArea);
    });

    dropArea.addEventListener('drop', event => {
      event.preventDefault();
      resetDropAreaState(dropArea);

      const pdfs = Array.from(event.dataTransfer.files).filter(f => f.name.toLowerCase().endsWith('.pdf'));
      if (pdfs.length === 0) { alert('Nessun file PDF trovato nel trascinamento.'); return; }
      batchState.files = pdfs;
      renderBatchFileList();
    });
  }
});

// ── Controllo Ollama ──────────────────────────────────────────────────────────
async function checkOllama() {
  try {
    const res  = await fetch('/api/health');
    const data = await res.json();
    populatePromptProfiles(data.prompt_profiles, data.default_prompt_profile);

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

function populatePromptProfiles(profiles, defaultProfile) {
  const selects = [els.promptProfileSelect, els.batchPromptProfileSelect].filter(Boolean);
  if (!Array.isArray(profiles) || profiles.length === 0 || selects.length === 0) return;

  const currentProfile = els.promptProfileSelect?.value || defaultProfile;
  selects.forEach(select => {
    select.replaceChildren(...profiles.map(profile => {
      const option = document.createElement('option');
      option.value = profile;
      option.textContent = PROMPT_PROFILE_LABELS[profile] || profile;
      return option;
    }));
  });

  const selectedProfile = profiles.includes(currentProfile)
    ? currentProfile
    : (profiles.includes(defaultProfile) ? defaultProfile : profiles[0]);
  selects.forEach(select => { select.value = selectedProfile; });
}

function syncPromptProfileSelectors(source) {
  if (!source?.value) return;
  [els.promptProfileSelect, els.batchPromptProfileSelect]
    .filter(select => select && select !== source)
    .forEach(select => { select.value = source.value; });
}

function getPromptProfile() {
  const batchOverlay = document.getElementById('batch-overlay');
  if (batchOverlay?.style.display === 'flex' && els.batchPromptProfileSelect) {
    return els.batchPromptProfileSelect.value || 'structured_document_no_html';
  }
  return els.promptProfileSelect?.value || 'structured_document_no_html';
}

function withPromptProfile(path, profile = getPromptProfile()) {
  const params = new URLSearchParams({ prompt_profile: profile });
  return `${path}?${params.toString()}`;
}

function setBadge(type, text) {
  els.ollamaBadge.textContent = text;
  els.ollamaBadge.className   = `badge badge-${type}`;
}

// ── Upload PDF ────────────────────────────────────────────────────────────────
function getFileExtension(filename = '') {
  const dotIndex = filename.lastIndexOf('.');
  return dotIndex >= 0 ? filename.slice(dotIndex).toLowerCase() : '';
}

function getFileKind(file) {
  const extension = getFileExtension(file?.name || '');
  if (PDF_EXTENSIONS.includes(extension)) return 'pdf';
  if (IMAGE_EXTENSIONS.includes(extension)) return 'image';
  return null;
}

function eventHasFiles(event) {
  return Array.from(event.dataTransfer?.types || []).includes('Files');
}

function getDropZones() {
  return [
    els.pdfUploadArea,
    els.imageUploadArea,
    document.getElementById('batch-drop-area'),
  ].filter(Boolean);
}

function clearAllDropZoneHighlights() {
  getDropZones().forEach(resetDropAreaState);
}

function getHoveredDropZone(event) {
  const hoveredElement = document.elementFromPoint(event.clientX, event.clientY);
  return hoveredElement?.closest?.('.upload-area, .batch-drop-area') || null;
}

function syncFileDragHover(event) {
  if (!eventHasFiles(event)) {
    clearAllDropZoneHighlights();
    return;
  }

  const hoveredDropZone = getHoveredDropZone(event);
  getDropZones().forEach(zone => {
    if (zone === hoveredDropZone) {
      zone.classList.add('drag-over');
    } else {
      resetDropAreaState(zone);
    }
  });
}

function preventBrowserFileDrop() {
  ['dragenter', 'dragover', 'drop'].forEach(eventName =>
    window.addEventListener(eventName, event => {
      if (!eventHasFiles(event)) return;
      event.preventDefault();
      syncFileDragHover(event);
      if (eventName === 'dragover') {
        event.dataTransfer.dropEffect = 'copy';
      }
      if (eventName === 'drop') {
        clearAllDropZoneHighlights();
      }
    })
  );

  window.addEventListener('dragleave', clearAllDropZoneHighlights);
  window.addEventListener('dragend', clearAllDropZoneHighlights);
}

function resetDropAreaState(area) {
  area.dataset.dragDepth = '0';
  area.classList.remove('drag-over');
}

function incrementDropAreaState(area) {
  const nextDepth = Number(area.dataset.dragDepth || '0') + 1;
  area.dataset.dragDepth = String(nextDepth);
  area.classList.add('drag-over');
}

function decrementDropAreaState(area) {
  const nextDepth = Math.max(0, Number(area.dataset.dragDepth || '0') - 1);
  area.dataset.dragDepth = String(nextDepth);
  if (nextDepth === 0) {
    area.classList.remove('drag-over');
  }
}

function setupUploadArea(area, expectedKind) {
  if (!area) return;

  resetDropAreaState(area);

  area.addEventListener('dragenter', event => {
    event.preventDefault();
    incrementDropAreaState(area);
  });

  area.addEventListener('dragover', event => {
    event.preventDefault();
    area.classList.add('drag-over');
  });

  area.addEventListener('dragleave', event => {
    event.preventDefault();
    decrementDropAreaState(area);
  });

  area.addEventListener('drop', event => {
    event.preventDefault();
    resetDropAreaState(area);
    handleFile(event.dataTransfer.files[0], expectedKind);
  });
}

function handleFile(file, expectedKind = null) {
  if (!file) return;

  const kind = getFileKind(file);
  if (!kind || (expectedKind && kind !== expectedKind)) {
    if (expectedKind === 'pdf') {
      alert('Seleziona un file PDF (.pdf).');
    } else if (expectedKind === 'image') {
      alert('Seleziona un file immagine PNG o JPG.');
    } else {
      alert('Seleziona un PDF oppure un file PNG/JPG.');
    }
    return;
  }

  uploadDocument(file, kind);
}

async function uploadDocument(file, kind) {
  showLoading(kind === 'pdf' ? 'Caricamento e conversione pagine PDF...' : 'Caricamento immagine...');
  try {
    const form = new FormData();
    form.append('file', file);

    const res = await fetch(withPromptProfile('/api/upload'), { method: 'POST', body: form });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();

    // Ferma eventuali polling e timer in corso
    Object.values(state.polls).forEach(clearInterval);
    stopDocumentJobPolling();
    stopDisplayTimer();

    // Aggiorna stato
    Object.assign(state, {
      docId:          data.doc_id,
      currentPage:    0,
      totalPages:     data.page_count,
      filename:       data.filename,
      sourceType:     data.source_type,
      documentJob:    null,
      documentJobPoll:null,
      ocrResults:     {},
      ocrErrors:      {},
      ocrStructured:  {},
      ocrStatuses:    {},
      polls:          {},
      ocrStartTimes:  {},
      ocrDurations:   [],
    });

    // Aggiorna UI
    els.docFilename.textContent = data.filename;
    els.docPages.textContent = data.source_type === 'image'
      ? '— immagine singola'
      : `— ${data.page_count} ${data.page_count === 1 ? 'pagina' : 'pagine'}`;
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
    els.imageInput.value = '';
    els.imageInputOverlay.value = '';
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
  els.pageImage.alt = state.sourceType === 'image' ? 'Immagine originale' : `Pagina ${n + 1} del documento`;
  renderOcrOverlay();

  updateAllThumbs();
  renderOcrPanel();
}

function changePage(delta) {
  const n = state.currentPage + delta;
  if (n >= 0 && n < state.totalPages) loadPage(n);
}

function getOcrOverlayRegions(page) {
  const structured = state.ocrStructured[page];
  const sourceRegions = structured?.structureMetadata?.regions;
  if (!Array.isArray(sourceRegions)) return [];

  const supportedKinds = new Set(['text', 'image', 'table', 'formula', 'display_formula', 'inline_formula']);
  const regions = [];

  for (const region of sourceRegions) {
    const rawKind = String(region?.label || '').toLowerCase();
    const kind = rawKind.includes('formula') ? 'formula' : rawKind;
    const bbox = region?.bbox;
    if (
      !supportedKinds.has(rawKind) ||
      !Array.isArray(bbox) ||
      bbox.length !== 4 ||
      !bbox.every(Number.isFinite)
    ) continue;

    const [left, top, right, bottom] = bbox;
    if (right <= left || bottom <= top) continue;
    regions.push({ kind, index: region.index, left, top, right, bottom });
  }
  return regions;
}

function renderOcrOverlay() {
  const overlayEnabled = els.ocrOverlayToggle?.checked;
  const imageReady = els.pageImage.naturalWidth > 0 && els.pageImage.naturalHeight > 0;
  const availableRegions = getOcrOverlayRegions(state.currentPage);
  const enabledKinds = new Set([
    els.ocrOverlayText?.checked && 'text',
    els.ocrOverlayImage?.checked && 'image',
    els.ocrOverlayTable?.checked && 'table',
    els.ocrOverlayFormula?.checked && 'formula',
  ].filter(Boolean));
  const regions = availableRegions.filter(region => enabledKinds.has(region.kind));

  els.ocrOverlay.classList.toggle('is-visible', Boolean(overlayEnabled && imageReady));
  els.ocrOverlayFilters.disabled = !overlayEnabled;
  els.ocrOverlayStatus.hidden = true;
  els.ocrOverlay.replaceChildren();

  if (!overlayEnabled) return;
  if (!imageReady) return;

  els.ocrOverlay.setAttribute(
    'viewBox',
    `0 0 ${els.pageImage.naturalWidth} ${els.pageImage.naturalHeight}`,
  );

  if (availableRegions.length === 0) {
    els.ocrOverlayStatus.textContent = 'Nessuna geometria restituita dal provider per questa pagina.';
    els.ocrOverlayStatus.hidden = false;
    return;
  }

  if (regions.length === 0) {
    els.ocrOverlayStatus.textContent = `Nessuna regione visibile: attiva almeno un filtro layout (${availableRegions.length} disponibili).`;
    els.ocrOverlayStatus.hidden = false;
    return;
  }

  const countByKind = regions.reduce((counts, region) => {
    counts[region.kind] = (counts[region.kind] || 0) + 1;
    return counts;
  }, {});
  const regionSummary = [
    ['text', 'testo'],
    ['image', 'immagine'],
    ['table', 'tabella'],
    ['formula', 'formula'],
  ].map(([kind, label]) => {
    const count = countByKind[kind] || 0;
    return count ? `${count} ${label}${count === 1 ? '' : 'e'}` : null;
  }).filter(Boolean).join(', ');
  els.ocrOverlayStatus.textContent = `Layout visibile: ${regions.length}/${availableRegions.length} regioni (${regionSummary}). I riquadri possono essere parziali.`;
  els.ocrOverlayStatus.hidden = false;

  const namespace = 'http://www.w3.org/2000/svg';
  for (const region of regions) {
    const width = region.right - region.left;
    const height = region.bottom - region.top;
    const labels = {
      text: 'Testo rilevato',
      image: 'Immagine rilevata',
      table: 'Tabella rilevata',
      formula: 'Formula rilevata',
    };
    const label = labels[region.kind];
    const classSuffix = region.kind;
    const labelWidth = Math.max(label.length * 8 + 10, 72);

    const rectangle = document.createElementNS(namespace, 'rect');
    rectangle.setAttribute('class', `ocr-region ocr-region-${classSuffix}`);
    rectangle.setAttribute('x', String(region.left));
    rectangle.setAttribute('y', String(region.top));
    rectangle.setAttribute('width', String(width));
    rectangle.setAttribute('height', String(height));

    const regionTitle = document.createElementNS(namespace, 'title');
    regionTitle.textContent = `Regione provider ${region.index + 1}: ${label.toLowerCase()}.`;

    els.ocrOverlay.append(rectangle, regionTitle);

    if (region.kind === 'table' || region.kind === 'formula') {
      const labelBackground = document.createElementNS(namespace, 'rect');
      labelBackground.setAttribute('class', `ocr-region-label-bg-${classSuffix}`);
      labelBackground.setAttribute('x', String(region.left));
      labelBackground.setAttribute('y', String(region.top));
      labelBackground.setAttribute('width', String(labelWidth));
      labelBackground.setAttribute('height', '20');

      const labelText = document.createElementNS(namespace, 'text');
      labelText.setAttribute('class', 'ocr-region-label');
      labelText.setAttribute('x', String(region.left + 5));
      labelText.setAttribute('y', String(region.top + 14));
      labelText.textContent = label;

      els.ocrOverlay.append(labelBackground, labelText);
    }
  }
}

function toggleOcrOverlay() {
  renderOcrOverlay();
}

function toggleOcrOverlayFilter() {
  renderOcrOverlay();
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
  const error   = state.ocrErrors[page] ?? null;
  const showRaw = els.rawToggle.checked;

  // Reset
  els.ocrPlaceholder.style.display = 'none';
  els.ocrRendered.style.display    = 'none';
  els.ocrRaw.style.display         = 'none';
  els.copyBtn.disabled             = true;
  els.ocrBtn.disabled              = false;

  if (status === 'error' && !showRaw) {
    els.ocrPlaceholder.style.display = 'flex';
    const errorHtml = buildOcrErrorHtml(error);
    els.ocrPlaceholder.innerHTML = errorHtml || '❌ Errore OCR. Riprova.';
    els.ocrBtn.textContent = '🔄 Riprova OCR';
    els.ocrBtn.disabled    = false;

  } else if (md !== undefined) {
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
  try {
    const res  = await fetch(withPromptProfile(`/api/ocr-job/${state.docId}`), { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);

    state.documentJob = data;
    updateOcrAllButton();
    await syncDocumentStatuses();
    startDocumentJobPolling();
    setStatus(`OCR documento avviato a blocchi da ${data.block_size || 10} pagine.`);
  } catch (e) {
    alert('Errore avvio OCR completo: ' + e.message);
  }
  renderOcrPanel();
  updateAllThumbs();
}

async function triggerOcr(page) {
  if (state.ocrStatuses[page] === 'processing') return;
  state.ocrStatuses[page]   = 'processing';
  delete state.ocrErrors[page];
  delete state.ocrStructured[page];
  state.ocrStartTimes[page] = Date.now();   // registra inizio
  if (page === state.currentPage) { renderOcrPanel(); startDisplayTimer(); }
  updateAllThumbs();

  try {
    const res  = await fetch(withPromptProfile(`/api/ocr/${state.docId}/${page}`), { method: 'POST' });
    const data = await res.json();

    if (data.status === 'done' && data.markdown != null) {
      applyOcrPayload(page, data);
      if (page === state.currentPage) renderOcrPanel();
      updateAllThumbs();
    } else if (data.status === 'error') {
      applyOcrPayload(page, data);
      if (page === state.currentPage) renderOcrPanel();
      updateAllThumbs();
    } else {
      // Il backend sta elaborando in background: avvia polling
      startPolling(page);
    }
  } catch (e) {
    state.ocrStatuses[page] = 'error';
    delete state.ocrStructured[page];
    state.ocrErrors[page] = {
      source: 'frontend',
      type: 'request_error',
      label: 'Errore di richiesta dal browser',
      interpretation: 'La richiesta OCR non è stata completata dal browser o dal server HTTP prima di ricevere una risposta valida.',
      detail: e.message || String(e),
      retryable: true,
    };
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
        applyOcrPayload(page, data);
        clearInterval(state.polls[page]);
        delete state.polls[page];
        const sec = state.ocrStartTimes[page]
          ? Math.round((Date.now() - state.ocrStartTimes[page]) / 1000)
          : null;
        setStatus(`✓ Pagina ${page + 1} completata${sec !== null ? ` in ${fmtElapsed(sec)}` : ''}.`);
        if (page === state.currentPage) { stopDisplayTimer(); renderOcrPanel(); }
        updateAllThumbs();

      } else if (data.status === 'error') {
        applyOcrPayload(page, data);
        clearInterval(state.polls[page]);
        delete state.polls[page];
        setStatus(`✗ Pagina ${page + 1} fallita: ${data.error?.label || 'Errore OCR'}.`);
        if (page === state.currentPage) { stopDisplayTimer(); renderOcrPanel(); }
        updateAllThumbs();
      }
    } catch (_) { /* ignora errori di rete transitori */ }
  }, 2500);
}

function updateOcrAllButton() {
  const job = state.documentJob;
  if (!job || !state.docId) {
    els.ocrAllBtn.disabled = false;
    els.ocrAllBtn.textContent = '⚡ Tutto';
    return;
  }

  if (job.status === 'queued' || job.status === 'processing') {
    const completed = (job.done_pages || 0) + (job.error_pages || 0);
    let label = `⏳ Tutto ${completed}/${job.total_pages}`;
    if (job.current_block) {
      label += ` · ${job.current_block.start_page}-${job.current_block.end_page}`;
    }
    els.ocrAllBtn.disabled = true;
    els.ocrAllBtn.textContent = label;
    return;
  }

  els.ocrAllBtn.disabled = false;
  els.ocrAllBtn.textContent = '⚡ Tutto';
}

function stopDocumentJobPolling() {
  if (state.documentJobPoll) {
    clearInterval(state.documentJobPoll);
    state.documentJobPoll = null;
  }
  state.documentJob = null;
  updateOcrAllButton();
}

function startDocumentJobPolling() {
  if (state.documentJobPoll || !state.docId) return;
  state.documentJobPoll = setInterval(() => {
    pollDocumentJob().catch(() => {});
  }, 2500);
}

async function loadOcrResult(page) {
  const res  = await fetch(`/api/ocr/${state.docId}/${page}`);
  const data = await res.json();

  applyOcrPayload(page, data);

  if (page === state.currentPage) {
    if (data.status !== 'processing') stopDisplayTimer();
    renderOcrPanel();
  }
  updateAllThumbs();
}

async function syncDocumentStatuses() {
  if (!state.docId) return;

  const res  = await fetch(`/api/documents/${state.docId}`);
  const data = await res.json();
  const nextStatuses = data.ocr_status || {};

  for (const [pageKey, status] of Object.entries(nextStatuses)) {
    const page = Number(pageKey);
    const previous = state.ocrStatuses[page];
    state.ocrStatuses[page] = status;

    if (status === 'processing' && previous !== 'processing') {
      state.ocrStartTimes[page] = Date.now();
      if (page === state.currentPage) startDisplayTimer();
    }

    if ((status === 'done' || status === 'error') && previous === 'processing' && state.ocrStartTimes[page]) {
      const duration = Date.now() - state.ocrStartTimes[page];
      if (duration > 0) {
        state.ocrDurations.push(duration);
        if (state.ocrDurations.length > 6) state.ocrDurations.shift();
      }
    }

    if ((status === 'done' || status === 'error') && state.ocrResults[page] === undefined) {
      await loadOcrResult(page);
    }
  }

  if (state.ocrStatuses[state.currentPage] !== 'processing') stopDisplayTimer();
  renderOcrPanel();
  updateAllThumbs();
}

async function pollDocumentJob() {
  if (!state.docId) return;

  const res  = await fetch(`/api/ocr-job/${state.docId}`);
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);

  state.documentJob = data;
  updateOcrAllButton();
  await syncDocumentStatuses();

  if (['done', 'partial', 'error', 'pending'].includes(data.status)) {
    stopDocumentJobPolling();
    setStatus(`OCR documento terminato: ${data.done_pages}/${data.total_pages} pagine OK, ${data.error_pages} errori.`);
  }
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
  preparation: null,  // stato di preparazione file restituito dal backend
  errors:    [],       // errori di preparazione per singolo file
  pollTimer: null,
  done:      false,
  promptProfile: null,
};

function openBatch() {
  syncPromptProfileSelectors(els.promptProfileSelect);
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
  batchState.preparation = null;
  batchState.errors = [];
  batchState.done    = false;
  batchState.promptProfile = null;

  document.getElementById('batch-step-select').style.display   = 'block';
  document.getElementById('batch-step-progress').style.display = 'none';
  document.getElementById('batch-file-list').style.display     = 'none';
  document.getElementById('batch-drop-area').style.display     = 'flex';
  document.getElementById('batch-result-actions').style.display = 'none';
  document.getElementById('batch-preparation-status').textContent = '';
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
  renderBatchPreparation(batchState.preparation, batchState.errors);
}

function clearBatchFiles() {
  batchState.files = [];
  document.getElementById('batch-file-list').style.display = 'none';
  document.getElementById('batch-drop-area').style.display = 'flex';
  document.getElementById('batch-preparation-status').textContent = '';
  document.getElementById('folder-input').value = '';
  document.getElementById('files-input').value  = '';
}

// ── Avvio batch ───────────────────────────────────────────────────────────────

function renderBatchPreparation(preparation, errors = []) {
  const status = document.getElementById('batch-preparation-status');
  if (!status || !preparation) return;

  const total = Number(preparation.total_files || batchState.files.length);
  const prepared = Number(preparation.prepared_files || 0);
  const failed = Number(preparation.failed_files || 0);
  const current = preparation.current_filename;
  const elapsed = status.dataset.elapsed;
  const stateLabel = preparation.status === 'ready' ? 'Preparazione completata' : 'Preparazione in corso';
  const currentLabel = current ? ` · File corrente: ${escHtml(current)}` : '';
  const elapsedLabel = elapsed ? ` · Tempo: ${elapsed}` : '';
  const errorLabel = failed ? ` · Errori: ${failed}` : '';
  const details = errors.length ? `<div class="batch-preparation-errors">${errors
    .map(error => `${escHtml(error.filename || 'File')} : ${escHtml(error.error || 'errore')}`)
    .join('<br>')}</div>` : '';

  status.innerHTML = `<strong>${stateLabel}: ${prepared}/${total} PDF preparati</strong>${currentLabel}${errorLabel}${elapsedLabel}${details}`;
}

async function startBatch() {
  if (batchState.files.length === 0) return;

  const btn = document.getElementById('batch-start-btn');
  batchState.promptProfile = getPromptProfile();
  btn.disabled = true;
  btn.setAttribute('aria-busy', 'true');
  btn.textContent = `⏳ Preparazione di ${batchState.files.length} PDF…`;
  startBatchUploadTimer();

  try {
    const initRes = await fetch('/api/batch/init', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        filenames: batchState.files.map(file => file.name),
        sizes: batchState.files.map(file => file.size),
      }),
    });
    if (!initRes.ok) {
      const err = await initRes.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${initRes.status}`);
    }
    const initData = await initRes.json();
    batchState.batchId = initData.batch_id;
    batchState.preparation = initData.preparation;
    renderBatchPreparation(batchState.preparation, batchState.errors);

    for (const [index, file] of batchState.files.entries()) {
      batchState.preparation.current_filename = file.name;
      renderBatchPreparation(batchState.preparation, batchState.errors);
      const form = new FormData();
      form.append('index', String(index));
      form.append('file', file);
      const res = await fetch(withPromptProfile(`/api/batch/${batchState.batchId}/files`, batchState.promptProfile), { method: 'POST', body: form });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      const data = await res.json();
      batchState.preparation = data.preparation;
      batchState.docs = data.prepared_files || batchState.docs;
      batchState.errors = data.errors || batchState.errors;
      renderBatchPreparation(batchState.preparation, batchState.errors);
    }

    const completeRes = await fetch(`/api/batch/${batchState.batchId}/complete`, { method: 'POST' });
    if (!completeRes.ok) {
      const err = await completeRes.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${completeRes.status}`);
    }
    const completeData = await completeRes.json();
    batchState.preparation = completeData.preparation;
    batchState.docs = completeData.prepared_files || batchState.docs;
    batchState.errors = completeData.errors || batchState.errors;
    renderBatchPreparation(batchState.preparation, batchState.errors);

    const data = { batch_id: batchState.batchId, docs: batchState.docs, errors: batchState.errors };

    if (data.errors && data.errors.length > 0) {
      const errList = data.errors.map(e => `• ${e.filename}: ${e.error}`).join('\n');
      alert(`Alcuni file non sono stati elaborati:\n\n${errList}`);
    }
    if (data.docs.length === 0) {
      throw new Error('Nessun file è stato caricato correttamente.');
    }

    batchState.docs    = data.docs;

    // Mostra pannello progresso
    document.getElementById('batch-step-select').style.display   = 'none';
    document.getElementById('batch-step-progress').style.display = 'block';
    renderBatchProgress(data.docs);

    // Avvia OCR
    const startRes = await fetch(withPromptProfile(`/api/batch/${data.batch_id}/start`, batchState.promptProfile), { method: 'POST' });
    if (!startRes.ok) throw new Error('Errore avvio OCR batch.');
    const startData = await startRes.json();

    document.getElementById('batch-progress-label').textContent =
      `OCR avviato per ${startData.jobs_started || data.docs.length} documenti, blocchi da ${startData.block_size || 10} pagine.`;

    // Polling
    batchState.pollTimer = setInterval(pollBatchStatus, 3000);

  } catch (err) {
    alert('Errore batch: ' + err.message);
    btn.disabled    = false;
    btn.removeAttribute('aria-busy');
    btn.textContent = '▶ Avvia Conversione Batch';
  } finally {
    stopBatchUploadTimer();
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

// ── Funzione EXIT ────────────────────────────────────────────────────────────

async function exitApp() {
  if (!confirm('Chiudere il server e uscire?')) return;
  setStatus('Chiusura server in corso…');
  try {
    const res = await fetch('/api/shutdown', { method: 'POST' });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `HTTP ${res.status}`);
    }

    setStatus('Server arrestato. Chiusura pagina…');
    setTimeout(() => { window.location.replace('about:blank'); }, 400);
  } catch (err) {
    alert('Impossibile arrestare il server: ' + err.message);
    setStatus('Arresto server fallito.');
  }
}
