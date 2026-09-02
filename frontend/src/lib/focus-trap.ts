const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

/**
 * Keeps Tab / Shift+Tab inside `container` while a modal surface is open.
 *
 * Without this, Tab walks straight out of a modal dialog into the page behind
 * it — which is still rendered and still interactive — so a keyboard user can
 * silently operate the obscured UI while a blocking dialog claims to be modal.
 * Returns a cleanup function.
 */
export function trapFocus(container: HTMLElement): () => void {
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key !== 'Tab') return;

    const focusable = Array.from(
      container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)
    ).filter((el) => el.offsetParent !== null || el === document.activeElement);

    if (focusable.length === 0) {
      e.preventDefault();
      return;
    }

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;

    if (!e.shiftKey && (active === last || !container.contains(active))) {
      e.preventDefault();
      first.focus();
    } else if (e.shiftKey && (active === first || !container.contains(active))) {
      e.preventDefault();
      last.focus();
    }
  };

  document.addEventListener('keydown', onKeyDown, true);
  return () => document.removeEventListener('keydown', onKeyDown, true);
}
