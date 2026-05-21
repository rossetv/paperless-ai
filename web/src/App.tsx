/**
 * Application root.
 *
 * Renders the `AppRoutes` table, which switches between `LoginPage` and
 * `SearchPage` based on `useAuth().authenticated`. Providers (`QueryClient`,
 * `AuthProvider`, `BrowserRouter`) are wired in `main.tsx` so this file
 * stays a thin composition root.
 *
 * Classified as the `app` element type in `eslint-plugin-boundaries`; its
 * imports are boundary-checked against the `app` row of the allow matrix.
 */

import { AppRoutes } from './routes';

export default function App(): React.ReactElement {
  return <AppRoutes />;
}
