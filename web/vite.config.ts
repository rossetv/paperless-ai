import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Vite config for paperless-ai Web UI.
// The built output is served by the Python search server at '/'.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    // Source maps omitted from the production image — keeps the container lean
    // and avoids publishing readable source. Use 'hidden' here if you need
    // symbolicated error traces from a private Sentry project.
    sourcemap: false,
    // Target the actual runtime (self-hosted M4 Mac Mini, single browser
    // family). Matches tsconfig's ES2022 and avoids needless down-level
    // polyfill helpers that Vite would otherwise emit for es2020-baseline.
    target: 'es2022',
  },
  server: {
    port: 3000,
    proxy: {
      '/api': 'http://localhost:8080',
    },
  },
});
