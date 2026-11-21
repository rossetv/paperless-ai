/// <reference types="vite/client" />

/*
 * `vite/client` types `*.module.css` imports as `CSSModuleClasses`, so no
 * per-file cast is needed; index with brackets (`styles['button']`) because of
 * `noPropertyAccessFromIndexSignature`.
 */

/**
 * Typed `import.meta.env` variables. Only `VITE_`-prefixed variables reach the
 * bundle; secrets live server-side in `app.db` and are never prefixed.
 */
interface ImportMetaEnv {
  /** Base URL for all API calls; absent (same-origin) in production. */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
