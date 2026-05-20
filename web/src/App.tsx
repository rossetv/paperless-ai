import { Routes, Route } from 'react-router-dom';

/**
 * Application root. Wires top-level routes.
 * Pages and features are added here as the product grows.
 * Placeholder until SearchPage and LoginPage are implemented (T6.2+).
 */
export default function App(): React.ReactElement {
  return (
    <Routes>
      <Route
        path="/"
        element={
          <main style={{ fontFamily: 'system-ui, sans-serif', padding: '2rem' }}>
            <h1>Paperless AI Search</h1>
            <p>Index initialising — search will be available once the indexer has run.</p>
          </main>
        }
      />
    </Routes>
  );
}
