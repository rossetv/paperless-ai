import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Vite config for paperless-ai Web UI.
// The built output is served by the Python search server at '/'.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
  server: {
    port: 3000,
    proxy: {
      '/api': 'http://localhost:8080',
    },
  },
});
