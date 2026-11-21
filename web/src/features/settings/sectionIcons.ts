/**
 * Side-nav icon for each settings section id (`SETTINGS_SECTIONS`) plus the Access Control
 * items `users` and `keys`.
 */

import type { IconName } from '../../components/primitives/Icon/Icon';

export const SETTINGS_SECTION_ICONS: Record<string, IconName> = {
  paperless: 'link',
  llm: 'sparkle',
  search: 'search',
  embed: 'waves',
  ocr: 'eye',
  classify: 'paragraph',
  tags: 'tag',
  perf: 'lightning',
  logs: 'list-lines',
  users: 'users',
  keys: 'key',
};
