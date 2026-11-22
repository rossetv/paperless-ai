import React, { useId, useRef, useState } from 'react';
import { cn } from '../../../lib/cn';
import styles from './Tabs.module.css';

/** A single tab definition — id, label, and the content it reveals. */
export interface TabItem {
  /** Unique identifier for the tab, used for ARIA wiring and defaultActiveId. */
  id: string;
  label: string;
  /** Content rendered in the tab panel when this tab is active. */
  content: React.ReactNode;
}

export interface TabsProps {
  /** Ordered list of tabs. Must contain at least one entry. */
  tabs: TabItem[];
  /** Id of the tab that should be active on first render. Defaults to the first tab. */
  defaultActiveId?: string;
  className?: string;
}

/**
 * Accessible tabs (WAI-ARIA Tabs pattern) with automatic activation: arrow keys
 * move focus, wrap at the ends, Home/End jump to the ends, and activate the focused tab.
 *
 * Only the active panel is mounted, so inactive panels do not keep state such as
 * scroll position.
 */
export function Tabs({
  tabs,
  defaultActiveId,
  className,
}: TabsProps): React.ReactElement {
  const baseId = useId();
  const firstId = tabs[0]?.id ?? '';
  const [activeId, setActiveId] = useState(
    defaultActiveId !== undefined ? defaultActiveId : firstId,
  );

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
      case 'Home':
      case 'End': {
        event.preventDefault();
        const edgeIndex = event.key === 'Home' ? 0 : count - 1;
        focusTab(edgeIndex);
        const edgeTab = tabs[edgeIndex];
        if (edgeTab !== undefined) activateTab(edgeTab.id);
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
  const tabDomId = (id: string): string => `${baseId}-tab-${id}`;
  const panelId = `${baseId}-panel-${activeTab?.id ?? ''}`;

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
              id={tabDomId(tab.id)}
              type="button"
              role="tab"
              aria-selected={isActive}
              // Only the active panel is mounted, so only it can be referenced.
              {...(tab.id === activeTab?.id ? { 'aria-controls': panelId } : {})}
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
          aria-labelledby={tabDomId(activeTab.id)}
          className={styles['panel']}
          tabIndex={0}
        >
          {activeTab.content}
        </div>
      )}
    </div>
  );
}
