/// <reference types="vite/client" />

/*
 * CSS Modules typing.
 *
 * The `vite/client` reference above is the single ambient declaration for
 * `*.module.css` imports — it types a default import as `CSSModuleClasses`
 * (a `Readonly<Record<string, string>>`). A component therefore writes a
 * plain `import styles from './X.module.css'` and indexes it with bracket
 * notation (`styles['button']`) — required by `noPropertyAccessFromIndexSignature`.
 * No per-file `as Record<string, string>` cast is needed, and adding one is a
 * §1.3 boilerplate violation.
 */

/**
 * Typed environment variables exposed to the bundle via `import.meta.env`.
 *
 * Augmenting `ImportMetaEnv` makes each `VITE_*` variable a typed property, so
 * `import.meta.env.VITE_API_BASE_URL` needs no cast at the call site.
 *
 * Only `VITE_`-prefixed variables are exposed by Vite to client code; secrets
 * (the Paperless token, the OpenAI key, the SEARCH_API_KEY) are never prefixed
 * and so never reach the bundle (§10.3).
 */
interface ImportMetaEnv {
  /**
   * Base URL for all API calls. Empty (same-origin) in production; set to the
   * dev proxy target during local development. Optional — absent in prod.
   */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
