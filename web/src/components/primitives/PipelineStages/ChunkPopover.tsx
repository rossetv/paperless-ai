/**
 * ChunkPopover — a single shared hover/focus popover for retrieve-phase chunk
 * snippets.
 *
 * When a `.chunk-snip` element is hovered or keyboard-focused, this fixed-
 * position popover appears near the cursor (hover) or anchored below the
 * element (focus), showing the chunk's full text (title + score + body).
 *
 * Positioning: clamped to the viewport (flips left/up near edges); max-height
 * with internal scroll for long text. Dismissed on mouseleave / blur / Escape.
 *
 * Animation respects `prefers-reduced-motion`.
 *
 * Tier: components/primitives (CODE_GUIDELINES §12.3).
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import styles from './ChunkPopover.module.css';

export interface ChunkData {
  title: string;
  score: string;
  fullText: string;
}

interface PopoverState {
  visible: boolean;
  x: number;
  y: number;
  chunk: ChunkData | null;
}

interface ChunkPopoverProps {
  /** Container ref — the popover listens for mouseenter/focus on .chunk-snip descendants. */
  containerRef: React.RefObject<HTMLElement | null>;
}

/**
 * A single shared popover driven by `.chunk-snip[data-title][data-score][data-full]`
 * elements inside `containerRef`. Mounts once alongside the retrieve body.
 */
export function ChunkPopover({ containerRef }: ChunkPopoverProps): React.ReactElement {
  const [state, setState] = useState<PopoverState>({ visible: false, x: 0, y: 0, chunk: null });
  const popRef = useRef<HTMLDivElement>(null);
  const hideTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearHideTimer = useCallback(() => {
    if (hideTimerRef.current !== null) {
      clearTimeout(hideTimerRef.current);
      hideTimerRef.current = null;
    }
  }, []);

  const hidePop = useCallback(() => {
    clearHideTimer();
    hideTimerRef.current = setTimeout(() => {
      setState((prev) => ({ ...prev, visible: false }));
    }, 80);
  }, [clearHideTimer]);

  const showPop = useCallback((el: HTMLElement, x: number, y: number) => {
    clearHideTimer();
    setState({
      visible: true,
      x,
      y,
      chunk: {
        title: el.dataset['title'] ?? '',
        score: el.dataset['score'] ?? '',
        fullText: el.dataset['full'] ?? '',
      },
    });
  }, [clearHideTimer]);

  // Position the popover: clamp to viewport, flip left/up near edges.
  useEffect(() => {
    if (!state.visible || popRef.current === null) {
      return;
    }
    const pop = popRef.current;
    const margin = 12;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const w = pop.offsetWidth;
    const h = pop.offsetHeight;
    let left = state.x + 16;
    if (left + w + margin > vw) {
      left = state.x - w - 16;
    }
    if (left < margin) {
      left = margin;
    }
    let top = state.y + 16;
    if (top + h + margin > vh) {
      top = state.y - h - 16;
    }
    if (top < margin) {
      top = margin;
    }
    pop.style.left = `${left}px`;
    pop.style.top = `${top}px`;
  }, [state.visible, state.x, state.y, state.chunk]);

  // Bind event listeners onto the container's .chunk-snip elements.
  useEffect(() => {
    const container = containerRef.current;
    if (container === null) {
      return;
    }

    function onMouseEnter(e: MouseEvent): void {
      const el = (e.target as HTMLElement).closest('[data-full]') as HTMLElement | null;
      if (el !== null) {
        showPop(el, e.clientX, e.clientY);
      }
    }
    function onMouseMove(e: MouseEvent): void {
      const el = (e.target as HTMLElement).closest('[data-full]') as HTMLElement | null;
      if (el === null) return;
      // Use the functional setState form so the handler never closes over a
      // stale `state.visible` value — the effect dependency array previously
      // included `state.visible`, causing the handler to lag a render behind.
      setState((prev) => prev.visible ? { ...prev, x: e.clientX, y: e.clientY } : prev);
    }
    function onMouseLeave(e: MouseEvent): void {
      const el = (e.target as HTMLElement).closest('[data-full]') as HTMLElement | null;
      if (el !== null) {
        hidePop();
      }
    }
    function onFocus(e: FocusEvent): void {
      const el = (e.target as HTMLElement).closest('[data-full]') as HTMLElement | null;
      if (el !== null) {
        const rect = el.getBoundingClientRect();
        showPop(el, rect.left, rect.bottom);
      }
    }
    function onBlur(e: FocusEvent): void {
      const el = (e.target as HTMLElement).closest('[data-full]') as HTMLElement | null;
      if (el !== null) {
        hidePop();
      }
    }

    container.addEventListener('mouseenter', onMouseEnter, true);
    container.addEventListener('mousemove', onMouseMove, true);
    container.addEventListener('mouseleave', onMouseLeave, true);
    container.addEventListener('focus', onFocus, true);
    container.addEventListener('blur', onBlur, true);

    return () => {
      container.removeEventListener('mouseenter', onMouseEnter, true);
      container.removeEventListener('mousemove', onMouseMove, true);
      container.removeEventListener('mouseleave', onMouseLeave, true);
      container.removeEventListener('focus', onFocus, true);
      container.removeEventListener('blur', onBlur, true);
    };
    // `state.visible` is intentionally omitted — onMouseMove now uses the
    // functional setState form, so it no longer needs the closure value.
  }, [containerRef, showPop, hidePop]);

  // Dismiss on Escape key.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent): void {
      if (e.key === 'Escape') {
        hidePop();
      }
    }
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [hidePop]);

  return (
    <div
      ref={popRef}
      className={styles['popover']}
      data-visible={state.visible}
      role="tooltip"
      aria-hidden={!state.visible}
    >
      {state.chunk !== null && (
        <>
          <div className={styles['pophead']}>
            <span className={styles['pop-title']}>{state.chunk.title}</span>
            <span className={styles['pop-score']}>{state.chunk.score}</span>
          </div>
          <p className={styles['pop-body']}>{state.chunk.fullText}</p>
        </>
      )}
    </div>
  );
}
