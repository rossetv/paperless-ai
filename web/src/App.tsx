/** Application root. Providers (`QueryClient`, `BrowserRouter`) are wired in `main.tsx`. */

import { AppRoutes } from './routes';

export default function App(): React.ReactElement {
  return <AppRoutes />;
}
