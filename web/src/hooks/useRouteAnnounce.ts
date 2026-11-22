import { useEffect, useRef, type RefObject } from 'react';
import { useLocation } from 'react-router-dom';

const SUFFIX = 'Paperless AI Search';

/** Page names match the nav labels; an unknown path keeps the document's own title. */
export function pageName(pathname: string): string | undefined {
  if (pathname === '/') return 'Search';
  if (pathname === '/login') return 'Sign in';
  if (pathname === '/setup') return 'Set up';
  if (pathname === '/library') return 'Library';
  if (pathname === '/index') return 'Index';
  if (pathname === '/settings') return 'Settings';
  if (pathname === '/settings/users') return 'Users';
  if (pathname === '/settings/keys') return 'API Keys';
  if (/^\/(library\/)?document\/[^/]+$/.test(pathname)) return 'Document';
  return undefined;
}

const WATCH_MS = 2000;

function focusQuietly(el: HTMLElement): void {
  if (!el.hasAttribute('tabindex')) el.setAttribute('tabindex', '-1');
  // Focus here is a reading position, not a control, so it gets no ring; a later Tab back keeps its normal one.
  const before = el.style.outline;
  el.style.outline = 'none';
  el.addEventListener('blur', () => { el.style.outline = before; }, { once: true });
  el.focus();
}

/**
 * Keeps `document.title` in step with the route and, when the pathname changes
 * after the first render, moves focus to the page heading (or `<main>`) so a
 * screen reader announces the new page. Pages with neither get `fallback`. A query-string change leaves focus alone.
 *
 * A heading that renders late, or is replaced after it took focus, is
 * focused when it appears. That wait ends after a couple of seconds, on the
 * first key or pointer press, or once focus sits on something the hook did not put there.
 */
export function useRouteAnnounce(fallback: RefObject<HTMLElement | null>): void {
  const { pathname } = useLocation();
  const baseTitle = useRef(document.title);
  const previous = useRef(pathname);

  useEffect(() => {
    const name = pageName(pathname);
    document.title = name === undefined ? baseTitle.current : `${name} · ${SUFFIX}`;

    if (previous.current === pathname) return;
    previous.current = pathname;

    let focused: HTMLElement | null = null;
    const focusTarget = (): void => {
      const target = document.querySelector<HTMLElement>('h1') ?? document.querySelector<HTMLElement>('main') ?? fallback.current;
      if (target === null || target === document.activeElement) return;
      focusQuietly(target);
      focused = target;
    };
    focusTarget();

    const root = fallback.current ?? document.body;
    const stop = (): void => {
      observer.disconnect();
      window.clearTimeout(timer);
      document.removeEventListener('keydown', stop, true);
      document.removeEventListener('pointerdown', stop, true);
    };
    const observer = new MutationObserver(() => {
      const active = document.activeElement;
      if (active !== document.body && active !== fallback.current && active !== focused) {
        stop();
        return;
      }
      const heading = document.querySelector<HTMLElement>('h1');
      if (heading !== null && heading !== active) focusTarget();
    });
    // Suspense hides and reveals the wrapper's children with an inline style.
    observer.observe(root, { childList: true, subtree: true, attributes: true, attributeFilter: ['style'] });
    const timer = window.setTimeout(stop, WATCH_MS);
    document.addEventListener('keydown', stop, true);
    document.addEventListener('pointerdown', stop, true);
    return stop;
  }, [pathname, fallback]);
}
