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
 * `SectionCard`. Access-control items are their own routed pages.
 */
const SETTINGS_NAV_GROUPS: SettingsNavGroup[] = [
  {
    title: 'Configuration',
    items: [
      { id: 'paperless', label: 'Paperless Connection', to: '/settings#paperless' },
      { id: 'llm', label: 'LLM Provider', to: '/settings#llm' },
      { id: 'search', label: 'Search Server', to: '/settings#search' },
      { id: 'embed', label: 'Embeddings & Index', to: '/settings#embed' },
      { id: 'ocr', label: 'OCR', to: '/settings#ocr' },
      { id: 'classify', label: 'Classification', to: '/settings#classify' },
      { id: 'tags', label: 'Pipeline Tags', to: '/settings#tags' },
      { id: 'perf', label: 'Performance', to: '/settings#perf' },
      { id: 'logs', label: 'Logging', to: '/settings#logs' },
    ],
  },
  {
    title: 'Access Control',
    items: [
      { id: 'users', label: 'Users', to: '/settings/users' },
      { id: 'keys', label: 'API Keys', to: '/settings/keys' },
    ],
  },
];

export interface SettingsLayoutProps {
  /** The page title — rendered as the `<h1>`. */
  title: string;
  /** Optional one-line description shown under the title. */
  subtitle?: string;
  /** Header actions slot — buttons, a search field — rendered top-right. */
  actions?: React.ReactNode;
  /** The page body, rendered in the scrollable content region. */
  children: React.ReactNode;
  /** Additional class names to merge onto the layout root. */
  className?: string;
}

/**
 * The shared shell of the settings / access-control area.
 *
 * Renders the {@link SettingsSideNav} rail beside a content column. The
 * content column has a page header (title, optional subtitle, an actions
 * slot) above a scrollable body that holds `children`.
 *
 * It deliberately does NOT render the app nav bar — the hosting page wraps
 * `SettingsLayout` in `AppNavBar`, exactly as every other authenticated page
 * does. Keeping the app shell out of here keeps this component in the
 * `layout` tier (a layout component may not import a feature).
 *
 * Tier: components/layout (CODE_GUIDELINES §12.3). Allowed deps: lib/,
 * other layout components.
 */
export function SettingsLayout({
  title,
  subtitle,
  actions,
  children,
  className,
}: SettingsLayoutProps): React.ReactElement {
  return (
    <div className={cn(styles['layout'], className)}>
      <SettingsSideNav groups={SETTINGS_NAV_GROUPS} />
      <div className={styles['content']}>
        <header className={styles['header']}>
          <div className={styles['header-text']}>
            <h1 className={styles['title']}>{title}</h1>
            {subtitle !== undefined && (
              <p className={styles['subtitle']}>{subtitle}</p>
            )}
          </div>
          {actions !== undefined && (
            <div className={styles['actions']}>{actions}</div>
          )}
        </header>
        <div className={styles['body']}>{children}</div>
      </div>
    </div>
  );
}
