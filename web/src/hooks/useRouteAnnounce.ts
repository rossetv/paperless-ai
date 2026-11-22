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

/**
 * Keeps `document.title` in step with the route and, when the pathname changes
 * after the first render, moves focus to the page heading (or `<main>`) so a
 * screen reader announces the new page. Pages with neither get `fallback`. A query-string change leaves focus alone.
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
    const target = document.querySelector<HTMLElement>('h1') ?? document.querySelector<HTMLElement>('main') ?? fallback.current;
    if (target === null) return;
    if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
    target.focus();
  }, [pathname, fallback]);
}
