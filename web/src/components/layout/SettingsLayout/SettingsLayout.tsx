import React from 'react';
import { cn } from '../../../lib/cn';
import { SettingsSideNav } from '../SettingsSideNav/SettingsSideNav';
import type { SettingsNavGroup } from '../SettingsSideNav/SettingsSideNav';
import styles from './SettingsLayout.module.css';

/**
 * The settings nav groups.
 *
 * Wave 3 ships exactly one group — Access Control. Wave 4 (Settings / config)
 * prepends a "Configuration" group; that is a Wave 4 change to this constant.
 * It lives here, not in the page, so the rail is identical on every settings
 * screen.
 */
const SETTINGS_NAV_GROUPS: SettingsNavGroup[] = [
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
          <div className={styles['headerText']}>
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
