import React, { useRef, useState } from 'react';
import { cn } from '../../../lib/cn';
import styles from './Tabs.module.css';

/** A single tab definition — id, label, and the content it reveals. */
export interface TabItem {
  /** Unique identifier for the tab, used for ARIA wiring and defaultActiveId. */
  id: string;
  /** Visible label text on the tab. */
  label: string;
  /** Content rendered in the tab panel when this tab is active. */
  content: React.ReactNode;
}

export interface TabsProps {
  /** Ordered list of tabs. Must contain at least one entry. */
  tabs: TabItem[];
  /** Id of the tab that should be active on first render. Defaults to the first tab. */
  defaultActiveId?: string;
  /** Additional class names to merge onto the root element. */
  className?: string;
}

/**
 * Accessible tabbed interface.
 *
 * Implements the ARIA Tabs pattern (WAI-ARIA 1.2):
 * - role="tablist" on the tab container
 * - role="tab" + aria-selected on each tab button
 * - role="tabpanel" + aria-labelledby on each panel
 *
 * Keyboard support (automatic activation model — focus change activates):
 * - ArrowRight / ArrowLeft — move focus between tabs and activate
 * - ArrowRight at the last tab wraps to the first
 * - ArrowLeft at the first tab wraps to the last
 * - Enter / Space on a focused tab — activate it
 *
 * Only the active panel is mounted (not just hidden); this is a common
 * trade-off that keeps the DOM lean. Use CSS-hidden panels if unmounting
 * loses important state (e.g. scroll position) — comment if changed.
 *
 * App-agnostic — does not know about search, documents, or any domain concept.
 */
export function Tabs({
  tabs,
  defaultActiveId,
  className,
}: TabsProps): React.ReactElement {
  const firstId = tabs[0]?.id ?? '';
  const [activeId, setActiveId] = useState(
    defaultActiveId !== undefined ? defaultActiveId : firstId,
  );

  // Keep refs to each tab button for programmatic focus management
  const tabRefs = useRef<Array<HTMLButtonElement | null>>(
    Array.from({ length: tabs.length }, () => null),
  );

  function activateTab(id: string): void {
    setActiveId(id);
  }

  function focusTab(index: number): void {
    tabRefs.current[index]?.focus();
  }

  function handleKeyDown(
    event: React.KeyboardEvent<HTMLButtonElement>,
    currentIndex: number,
  ): void {
    const count = tabs.length;
    switch (event.key) {
      case 'ArrowRight': {
        event.preventDefault();
        const nextIndex = (currentIndex + 1) % count;
        focusTab(nextIndex);
        // Automatic activation — focusing a tab activates it
        const nextTab = tabs[nextIndex];
        if (nextTab !== undefined) activateTab(nextTab.id);
        break;
      }
      case 'ArrowLeft': {
        event.preventDefault();
        const prevIndex = (currentIndex - 1 + count) % count;
        focusTab(prevIndex);
        const prevTab = tabs[prevIndex];
        if (prevTab !== undefined) activateTab(prevTab.id);
        break;
      }
      case 'Enter':
      case ' ': {
        event.preventDefault();
        const currentTab = tabs[currentIndex];
        if (currentTab !== undefined) activateTab(currentTab.id);
        break;
      }
      default:
        break;
    }
  }

  const activeTab = tabs.find((t) => t.id === activeId) ?? tabs[0];
  const panelId = `tabpanel-${activeTab?.id ?? ''}`;

  const rootClasses = cn(styles['tabs'], className);

  return (
    <div className={rootClasses}>
      <div role="tablist" className={styles['tablist']}>
        {tabs.map((tab, index) => {
          const isActive = tab.id === activeId;
          return (
            <button
              key={tab.id}
              ref={(el) => {
                tabRefs.current[index] = el;
              }}
              id={`tab-${tab.id}`}
              type="button"
              role="tab"
              aria-selected={isActive}
              aria-controls={`tabpanel-${tab.id}`}
              // Roving tabindex: only the active tab is in the natural tab order.
              // Arrow keys move focus between tabs; Tab moves focus out of the tablist.
              tabIndex={isActive ? 0 : -1}
              className={cn(styles['tab'], isActive ? styles['active'] : undefined)}
              onClick={() => activateTab(tab.id)}
              onKeyDown={(event) => handleKeyDown(event, index)}
            >
              {tab.label}
            </button>
          );
        })}
      </div>

      {activeTab !== undefined && (
        <div
          id={panelId}
          role="tabpanel"
          aria-labelledby={`tab-${activeTab.id}`}
          className={styles['panel']}
          tabIndex={0}
        >
          {activeTab.content}
        </div>
      )}
    </div>
  );
}
