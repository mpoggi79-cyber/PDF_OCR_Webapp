'use strict';
/**
 * Tooltip personalizzato — legge l'attributo data-tooltip su qualsiasi elemento.
 * La prima riga del testo viene trattata come "titolo" (colore accento).
 * Le righe successive sono la descrizione.
 * Supporta \n per andare a capo nel valore HTML.
 */

(function () {
  const DELAY_IN  = 280;   // ms prima di mostrare
  const DELAY_OUT = 120;   // ms prima di nascondere
  const MARGIN    = 10;    // px di distanza dall'elemento

  let box           = null;
  let timerIn       = null;
  let timerOut      = null;
  let current       = null;   // elemento con tooltip visibile
  let pendingTarget = null;   // elemento per cui timerIn è in attesa

  // ── Crea il nodo tooltip una sola volta ──────────────────────────────────
  function createBox() {
    box = document.createElement('div');
    box.id = 'tt-box';
    box.setAttribute('role', 'tooltip');
    box.setAttribute('aria-hidden', 'true');
    document.body.appendChild(box);
  }

  // ── Risale il DOM cercando data-tooltip ──────────────────────────────────
  function findTarget(node) {
    while (node && node !== document.body) {
      if (node.hasAttribute && node.hasAttribute('data-tooltip')) return node;
      node = node.parentNode;
    }
    return null;
  }

  // ── Posizionamento ────────────────────────────────────────────────────────
  function position(target) {
    const rect       = target.getBoundingClientRect();
    const bw         = box.offsetWidth;
    const bh         = box.offsetHeight;
    const vw         = window.innerWidth;
    const vh         = window.innerHeight;
    const spaceBelow = vh - rect.bottom;
    const below      = spaceBelow >= bh + MARGIN || spaceBelow >= rect.top;

    let top, left;
    if (below) {
      top = rect.bottom + MARGIN;
      box.classList.add('tt-below');
      box.classList.remove('tt-above');
    } else {
      top = rect.top - bh - MARGIN;
      box.classList.add('tt-above');
      box.classList.remove('tt-below');
    }

    left = rect.left;
    if (left + bw > vw - 8) left = vw - bw - 8;
    if (left < 8) left = 8;

    box.style.top  = `${top}px`;
    box.style.left = `${left}px`;
  }

  // ── Contenuto del tooltip ─────────────────────────────────────────────────
  function setContent(text) {
    const lines = text.split('\n');
    const title = lines[0];
    const body  = lines.slice(1).join('\n').trim();
    box.innerHTML =
      `<span class="tt-title">${escHtml(title)}</span>` +
      (body ? escHtml(body) : '');
  }

  function escHtml(s) {
    return s
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  // ── Mostra / nasconde ────────────────────────────────────────────────────
  function show(target) {
    if (!box) createBox();
    const text = target.getAttribute('data-tooltip');
    if (!text) return;

    current       = target;
    pendingTarget = null;
    setContent(text);

    // NON usare stili inline per opacity/transform: verrebbero sovrapposti
    // alle regole CSS della classe .tt-visible e il tooltip resterebbe invisibile.
    box.classList.remove('tt-visible');   // reset transizione per nuova apertura
    box.style.display = 'block';          // render nel DOM per avere dimensioni

    requestAnimationFrame(() => {
      position(target);                   // posiziona mentre ancora invisible
      box.classList.add('tt-visible');    // attiva transizione CSS → opacity 1
    });
  }

  function hide() {
    if (!box) return;
    box.classList.remove('tt-visible');
    current = null;
    setTimeout(() => {
      if (!box.classList.contains('tt-visible')) {
        box.style.display = 'none';
      }
    }, 200);
  }

  function cancelPending() {
    clearTimeout(timerIn);
    pendingTarget = null;
  }

  // ── mouseover ─────────────────────────────────────────────────────────────
  // NOTA: mouseover bolle, ma e.target è sempre l'elemento più profondo.
  // Usiamo un flag pendingTarget per sapere per quale elemento stiamo
  // aspettando, così mouseout non cancella timerIn per errore.
  document.addEventListener('mouseover', e => {
    const target = findTarget(e.target);

    clearTimeout(timerOut);   // annulla eventuale hide in attesa

    if (!target) {
      // Entrati in zona senza tooltip: cancella pending e programma hide
      if (current || pendingTarget) {
        cancelPending();
        timerOut = setTimeout(hide, DELAY_OUT);
      }
      return;
    }

    // Stesso elemento già visibile o già in coda: nulla da fare
    if (target === current || target === pendingTarget) return;

    // Nuovo elemento con tooltip: riprogramma show
    cancelPending();
    pendingTarget = target;
    timerIn = setTimeout(() => show(target), DELAY_IN);
  });

  // ── mouseout ──────────────────────────────────────────────────────────────
  // FIX del bug originale: NON cancellare timerIn se il mouse sta andando
  // verso un elemento che ha data-tooltip (il mouseover successivo lo gestirà).
  document.addEventListener('mouseout', e => {
    const related        = e.relatedTarget;
    const relatedTooltip = related ? findTarget(related) : null;

    // Il mouse sta entrando in un elemento con tooltip → lascia fare a mouseover
    if (relatedTooltip) return;

    // Il mouse esce dalla "zona tooltip" → cancella tutto e programa hide
    cancelPending();
    timerOut = setTimeout(hide, DELAY_OUT);
  });

  // ── Nasconde al click ────────────────────────────────────────────────────
  document.addEventListener('mousedown', () => {
    cancelPending();
    clearTimeout(timerOut);
    hide();
  });

  // ── Nasconde su scroll / resize / Escape ─────────────────────────────────
  window.addEventListener('scroll',  () => { cancelPending(); hide(); }, true);
  window.addEventListener('resize',  () => { cancelPending(); hide(); });
  window.addEventListener('keydown', e => {
    if (e.key === 'Escape') { cancelPending(); hide(); }
  });
})();
