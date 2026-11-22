import React from 'react';

/** How long an armed button waits before it disarms itself. */
const DISARM_AFTER_MS = 4000;
/** Taps this soon after arming are ignored, so a double tap cannot confirm. */
const IGNORE_TAPS_FOR_MS = 600;

export interface ArmedConfirm<Key> {
  /** The key currently armed, or null. */
  armed: Key | null;
  /** Arm a key; the first tap of a destructive action. */
  arm: (key: Key) => void;
  /** Disarm without confirming. */
  disarm: () => void;
  /** True once an armed key may be confirmed (not within the double-tap window). */
  canConfirm: () => boolean;
  /** Props for the element wrapping the button: Escape and focus leaving disarm it. */
  armedProps: {
    onBlur: (event: React.FocusEvent) => void;
    onKeyDown: (event: React.KeyboardEvent) => void;
  };
}

/**
 * State for an in-place "tap again to confirm" button: it disarms on Escape,
 * on blur and after a few seconds, and ignores a confirm tap right after arming.
 */
export function useArmedConfirm<Key>(): ArmedConfirm<Key> {
  const [armed, setArmed] = React.useState<Key | null>(null);
  const armedAt = React.useRef(0);

  React.useEffect(() => {
    if (armed === null) return undefined;
    const timer = setTimeout(() => setArmed(null), DISARM_AFTER_MS);
    return () => clearTimeout(timer);
  }, [armed]);

  const disarm = React.useCallback(() => setArmed(null), []);

  return {
    armed,
    arm: (key) => {
      armedAt.current = Date.now();
      setArmed(key);
    },
    disarm,
    canConfirm: () => Date.now() - armedAt.current >= IGNORE_TAPS_FOR_MS,
    armedProps: {
      onBlur: (event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) disarm();
      },
      onKeyDown: (event) => {
        if (event.key !== 'Escape' || armed === null) return;
        // Handled here, so a surrounding dialog does not also close on this Escape.
        event.preventDefault();
        disarm();
      },
    },
  };
}
