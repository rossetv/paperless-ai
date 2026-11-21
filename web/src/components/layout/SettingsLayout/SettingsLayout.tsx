import React from 'react';
import { cn } from '../../../lib/cn';
import { SettingsSideNav } from '../SettingsSideNav/SettingsSideNav';
import type { SettingsNavGroup } from '../SettingsSideNav/SettingsSideNav';
import styles from './SettingsLayout.module.css';

/**
 * The settings nav groups. "Pipeline" and "Operations" items are in-page anchors
 * on `/settings` (`/settings#<anchor>`); "Access control" items are routed pages.
 * Icons are assigned here so SettingsSideNav stays presentational.
 */
const SETTINGS_NAV_GROUPS: SettingsNavGroup[] = [
  {
    title: 'Pipeline',
    items: [
      { id: 'connections', label: 'Connections', to: '/settings#connections', icon: 'link' },
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
   * Optional top-right primary action, used by the access-control screens
   * (Users, API Keys). The settings screen uses the sticky SaveBar instead.
   */
  actions?: React.ReactNode;
  /** The page body, rendered in the scrollable content region. */
  children: React.ReactNode;
  className?: string;
}

/**
 * Shell of the settings and access-control area: the {@link SettingsSideNav}
 * rail beside a content column with a page header above `children`.
 *
 * Does not render the app nav bar; the hosting page wraps it in `AppNavBar`.
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
