/**
 * Application root.
 *
 * Renders the `AppRoutes` table, which switches between `LoginPage` and
 * `SearchPage` based on `useAuth().authenticated`. Providers (`QueryClient`,
 * `AuthProvider`, `BrowserRouter`) are wired in `main.tsx` so this file
 * stays a thin composition root.
 *
 * Intentionally exempt from `eslint-plugin-boundaries` (see
 * `boundaries/ignore` in eslint.config.js).
 */

import { AppRoutes } from './routes';

export default function App(): React.ReactElement {
  return <AppRoutes />;
}
