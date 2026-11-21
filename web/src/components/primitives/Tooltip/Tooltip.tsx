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
 * Shows a short label on hover and keyboard focus of its child; Escape dismisses
 * it. The tooltip is only rendered while visible, and its trigger handlers are
 * merged with the child's own (the child's fires first).
 */
export function Tooltip({ content, children }: TooltipProps): React.ReactElement {
  const [visible, setVisible] = useState(false);
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

  // aria-describedby is set only while visible: when hidden the tooltip is not
  // in the DOM, so the reference would dangle.
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
