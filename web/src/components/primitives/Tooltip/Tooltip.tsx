import React, { useState, useId, useCallback } from 'react';
import styles from './Tooltip.module.css';

export interface TooltipProps {
  /**
   * The label text to display in the tooltip.
   * Keep it short — a tooltip is a supplementary label, not a paragraph.
   */
  content: string;
  /**
   * The element that triggers the tooltip.
   * Must be a single interactive or focusable element so aria-describedby
   * can be wired correctly.
   */
  children: React.ReactElement;
}

/**
 * Shows a short label on hover and keyboard focus of its child element.
 *
 * Accessibility behaviour:
 * - The tooltip element has role="tooltip".
 * - aria-describedby on the trigger is set to the tooltip's id when visible.
 * - Dismissed with Escape (per ARIA APG tooltip pattern).
 * - Hidden via conditional rendering (not just visibility) so screen readers
 *   do not encounter it when it is not triggered.
 *
 * All five trigger handlers (onMouseEnter, onMouseLeave, onFocus, onBlur,
 * onKeyDown) are merged with the child's existing handlers — the child's
 * handler fires first, then the tooltip's. No child handler is overwritten.
 */
export function Tooltip({ content, children }: TooltipProps): React.ReactElement {
  const [visible, setVisible] = useState(false);
  // useId produces a stable, unique id per component instance.
  const tooltipId = useId();

  const show = useCallback(() => setVisible(true), []);
  const hide = useCallback(() => setVisible(false), []);

  // Helpers that call the child's existing handler (if any) then the tooltip's.
  type MouseHandler = (e: React.MouseEvent) => void;
  type FocusHandler = (e: React.FocusEvent) => void;

  const handleMouseEnter = useCallback(
    (event: React.MouseEvent) => {
      (children.props.onMouseEnter as MouseHandler | undefined)?.(event);
      show();
    },
    [children.props.onMouseEnter, show],
  );

  const handleMouseLeave = useCallback(
    (event: React.MouseEvent) => {
      (children.props.onMouseLeave as MouseHandler | undefined)?.(event);
      hide();
    },
    [children.props.onMouseLeave, hide],
  );

  const handleFocus = useCallback(
    (event: React.FocusEvent) => {
      (children.props.onFocus as FocusHandler | undefined)?.(event);
      show();
    },
    [children.props.onFocus, show],
  );

  const handleBlur = useCallback(
    (event: React.FocusEvent) => {
      (children.props.onBlur as FocusHandler | undefined)?.(event);
      hide();
    },
    [children.props.onBlur, hide],
  );

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      // Forward to any existing onKeyDown on the child first.
      const existingHandler = children.props.onKeyDown as
        | ((e: React.KeyboardEvent) => void)
        | undefined;
      existingHandler?.(event);
      if (event.key === 'Escape') {
        setVisible(false);
      }
    },
    [children.props.onKeyDown],
  );

  // Merge tooltip trigger handlers with the child's existing handlers.
  // aria-describedby is only set when the tooltip is visible — when hidden
  // the tooltip element is not in the DOM so the reference would dangle.
  const triggerProps: Record<string, unknown> = {
    onMouseEnter: handleMouseEnter,
    onMouseLeave: handleMouseLeave,
    onFocus: handleFocus,
    onBlur: handleBlur,
    onKeyDown: handleKeyDown,
    ...(visible ? { 'aria-describedby': tooltipId } : {}),
  };

  const trigger = React.cloneElement(children, triggerProps);

  return (
    <span className={styles['wrapper']}>
      {trigger}
      {visible && (
        <span
          id={tooltipId}
          role="tooltip"
          className={styles['tooltip']}
        >
          {content}
        </span>
      )}
    </span>
  );
}
