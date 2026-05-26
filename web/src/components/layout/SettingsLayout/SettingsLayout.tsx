import React from 'react';
import { cn } from '../../../lib/cn';
import { SettingsSideNav } from '../SettingsSideNav/SettingsSideNav';
import type { SettingsNavGroup } from '../SettingsSideNav/SettingsSideNav';
import styles from './SettingsLayout.module.css';

/**
 * The settings nav groups.
 *
 * Two groups: "Configuration" (the nine config sections — Wave 4) and
 * "Access Control" (Users, API Keys — Wave 3). The Configuration items are
 * in-page anchors: every section renders on the single `/settings` route, so
 * each link is `/settings#<anchor>` and the hash scrolls to that
 * `SettingsBlock`. Access-control items are their own routed pages.
 *
 * Icons are assigned here because this component owns the nav-group shape;
 * SettingsSideNav is purely presentational.
 */
const SETTINGS_NAV_GROUPS: SettingsNavGroup[] = [
  {
    title: 'Configuration',
    items: [
      { id: 'paperless', label: 'Paperless Connection', to: '/settings#paperless', icon: 'link' },
      { id: 'llm', label: 'LLM Provider', to: '/settings#llm', icon: 'sparkle' },
      { id: 'search', label: 'Search Server', to: '/settings#search', icon: 'search' },
      { id: 'embed', label: 'Embeddings & Index', to: '/settings#embed', icon: 'waves' },
      { id: 'ocr', label: 'OCR', to: '/settings#ocr', icon: 'eye' },
      { id: 'classify', label: 'Classification', to: '/settings#classify', icon: 'paragraph' },
      { id: 'tags', label: 'Pipeline Tags', to: '/settings#tags', icon: 'tag' },
      { id: 'perf', label: 'Performance', to: '/settings#perf', icon: 'lightning' },
      { id: 'logs', label: 'Logging', to: '/settings#logs', icon: 'list-lines' },
    ],
  },
  {
    title: 'Access Control',
    items: [
      { id: 'users', label: 'Users', to: '/settings/users', icon: 'users' },
      { id: 'keys', label: 'API Keys', to: '/settings/keys', icon: 'key' },
    ],
  },
];

export interface SettingsLayoutProps {
  /** The page title — rendered as the `<h1>`. */
  title: string;
  /** Optional one-line description shown under the title. */
  subtitle?: string;
  /** The page body, rendered in the scrollable content region. */
  children: React.ReactNode;
  /** Additional class names to merge onto the layout root. */
  className?: string;
}

/**
 * The shared shell of the settings / access-control area.
 *
 * Renders the {@link SettingsSideNav} rail beside a content column. The
 * content column has a page header (title, optional subtitle) above a
 * scrollable body that holds `children`. The old `actions` header slot is
 * gone — the sticky SaveBar takes that responsibility in the settings screen.
 *
 * It deliberately does NOT render the app nav bar — the hosting page wraps
 * `SettingsLayout` in `AppNavBar`, exactly as every other authenticated page
 * does.
 *
 * Tier: components/layout (CODE_GUIDELINES §12.3). Allowed deps: lib/,
 * components/primitives, other layout components.
 */
export function SettingsLayout({
  title,
  subtitle,
  children,
  className,
}: SettingsLayoutProps): React.ReactElement {
  return (
    <div className={cn(styles['layout'], className)}>
      <SettingsSideNav groups={SETTINGS_NAV_GROUPS} eyebrow="Settings" />
      <div className={styles['content']}>
        <header className={styles['header']}>
          <h1 className={styles['title']}>{title}</h1>
          {subtitle !== undefined && (
            <p className={styles['subtitle']}>{subtitle}</p>
          )}
        </header>
        <div className={styles['body']}>{children}</div>
      </div>
    </div>
  );
}
