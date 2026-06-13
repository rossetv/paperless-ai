import React from 'react';
import { cn } from '../../../lib/cn';
import { SettingsSideNav } from '../SettingsSideNav/SettingsSideNav';
import type { SettingsNavGroup } from '../SettingsSideNav/SettingsSideNav';
import styles from './SettingsLayout.module.css';

/**
 * The settings nav groups.
 *
 * Three groups:
 *   "Pipeline" — the pipeline config sections (Connections, AI providers, OCR,
 *     Classification, Indexing, Search), each an in-page anchor on the
 *     `/settings` route (links are `/settings#<anchor>`).
 *   "Operations" — automation/daemons and logging, also in-page anchors.
 *   "Access control" — Users and API Keys, each their own routed page.
 *
 * Icons are assigned here because this component owns the nav-group shape;
 * SettingsSideNav is purely presentational.
 */
const SETTINGS_NAV_GROUPS: SettingsNavGroup[] = [
  {
    title: 'Pipeline',
    items: [
      { id: 'connections', label: 'Connections', to: '/settings#connections', icon: 'link' },
      { id: 'providers', label: 'AI providers', to: '/settings#providers', icon: 'sparkle' },
      { id: 'ocr', label: 'OCR', to: '/settings#ocr', icon: 'eye' },
      { id: 'classification', label: 'Classification', to: '/settings#classification', icon: 'tags' },
      { id: 'indexing', label: 'Indexing', to: '/settings#indexing', icon: 'index' },
      { id: 'search', label: 'Search', to: '/settings#search', icon: 'search' },
    ],
  },
  {
    title: 'Operations',
    items: [
      { id: 'automation', label: 'Automation & Daemons', to: '/settings#automation', icon: 'gears' },
      { id: 'logging', label: 'Logging', to: '/settings#logging', icon: 'document' },
    ],
  },
  {
    title: 'Access control',
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
  /**
   * Optional top-right header slot — a primary CTA used by the access-control
   * screens (Users, API Keys) where the page has a single dominant action.
   * The settings screen does NOT use this slot — the sticky SaveBar carries
   * Discard / Save instead.
   */
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
 * content column has a page header (title, optional subtitle, optional
 * top-right actions slot) above a body that holds `children`.
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
  actions,
  children,
  className,
}: SettingsLayoutProps): React.ReactElement {
  return (
    <div className={cn(styles['layout'], className)}>
      <SettingsSideNav groups={SETTINGS_NAV_GROUPS} eyebrow="Settings" />
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
