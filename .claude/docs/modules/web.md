<!-- Claude-maintained; humans never edit. Registered in .claude/INDEX.md — an
unregistered KB file is a defect. Every path, command, and constant below must
be verified against the code before writing; on contradiction, fix here at
once. Unknown fact → omit the section, never guess. -->
↑ [INDEX](../../INDEX.md)

# Module: web

## Purpose

The React 18 + Vite + TypeScript SPA — the only UI for paperless-ai. Built to `web/dist` in the Node stage of the root `Dockerfile` and served same-origin at `/` by the Python search server (`src/search/spa.py`), whose deep-link catch-all lets client-router paths survive a hard refresh. Covers first-run setup, login, agentic search (live NDJSON stream with a per-phase trace), library browsing, document detail/edit, the index-health dashboard, settings, user admin and API-key admin.

Its stated non-negotiable goal (CODE_GUIDELINES §12) is zero design drift: one token file, one component library, a mechanically-enforced layer stack.

**Entrypoint:** `web/src/main.tsx` mounts `<React.StrictMode><ErrorBoundary><QueryClientProvider><BrowserRouter><App/>`; `App.tsx` renders `AppRoutes` from `routes.tsx`, which owns the route table and the setup/auth/admin guards. Dev entry is `web/index.html` (Vite on :3000, `/api` proxied to `http://localhost:8080`).

## Key files

| File | Role |
|------|------|
| `web/src/main.tsx` | Entry point. Provider stack (QueryClient → BrowserRouter); global QueryClient defaults `staleTime 60_000`, `retry 1`, `refetchOnWindowFocus: false` (the LLM-backed `/api/search` is expensive). Imports `global.css` and only the FontAwesome base + solid CSS. |
| `web/src/routes.tsx` | Route table + all guards: `BootstrapGate` (setup-status → `/setup` or `/login`), `ProtectedRoute` (`useMe` → `/login`), `RequireAdmin`/`AdminGate` (role → `/`). Eager: Search, Login, Setup. `React.lazy`: Index, Users, Keys, Settings, Library, LibraryDocument, Document. `ErrorBoundary` resets on `location.pathname`. |
| `web/src/App.tsx` | Thin composition root — renders `<AppRoutes/>` and nothing else. |
| `web/eslint.config.js` | ESLint 9 flat config; **the law-enforcement file**. Encodes the §12.3 layer stack as `eslint-plugin-boundaries` element types with `default: 'disallow'` + a per-layer allow matrix. Also `@typescript-eslint/no-explicit-any: error`, `react-hooks/exhaustive-deps: error`. |
| `web/.stylelintrc.json` | Enforces §12.4 — a `declaration-property-value-disallowed-list` rejecting hex/rgb/hsl colours, raw `px`/`rem`/`em` sizes, raw `ms`/`s` durations, numeric `z-index` and literal font stacks in any CSS file. Nulled only for `src/styles/{tokens,themes,global}.css`. |
| `web/src/styles/tokens.css` | 675 lines — the single source of every design value (colours, SF Pro type scale, 8px spacing scale, radius ladder, shadows, breakpoints). Light values sit on `:root`. |
| `web/src/styles/themes.css` | Dark palette, defined exactly once under `[data-theme="dark"]`. No `@media (prefers-color-scheme)` duplicate. |
| `web/src/styles/global.css` | `@import`s `tokens.css` + `themes.css`, then resets (`box-sizing`) and base element styles. Ships NO `@font-face` rule — SF Pro comes from the system font stack, so no web font is ever downloaded. |
| `web/index.html` | Vite shell. Carries ONE inline `<script>` — the pre-paint theme bootstrap stamping `data-theme` from `prefers-color-scheme`. That script is why the server CSP allows `script-src 'unsafe-inline'`. |
| `web/src/api/client/core.ts` | The fetch primitive. `BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''`; `request<T>()` always sends `credentials: 'include'`, throws `Unauthenticated` on 401 and `ApiError(status)` on any other non-2xx, returns `undefined` for 202/204/empty bodies, and converts a non-JSON 2xx body into a typed `ApiError`. |
| `web/src/api/client.ts` | Barrel re-exporting the nine modules under `api/client/` (core, auth, search, searchStream, access, settings, library, index, taxonomy). `./api/client` resolves to **this file**, not the directory. |
| `web/src/api/client/searchStream.ts` | `streamSearch()` POSTs `/api/search/stream`, throwing the same typed errors as `request` on a non-OK initial response. `parseNdjson()` is an async generator: streaming `TextDecoder`, buffers partial lines across chunk boundaries, throws `StreamError` on a malformed frame. |
| `web/src/api/hooks/keys.ts` | The `queryKeys` factory — single source of truth for every TanStack Query key (18 entries). Also exports `ME_QUERY_KEY` (`['auth','me']`, the same tuple `queryKeys.me()` returns); its only non-test importer is `pages/SearchPage.tsx`'s 401 handler. |
| `web/src/api/hooks/auth.ts` | `useMe` / `useSetupStatus` (`staleTime: 0`, `retry: false`), `usePublicStats`, `useLogin`, `useSetup`, `useLogout` (calls `queryClient.clear()` in `onSettled`). |
| `web/src/api/hooks.ts` | Barrel over the eight hook modules (keys, search, auth, access, settings, index-ops, library, taxonomy). |
| `web/src/api/types.ts` | Barrel over `api/types/{auth,access,search,settings,library,index}.ts` — TS mirrors of the FastAPI Pydantic wire shapes in the `src/search/wire/` package. Divergence is a bug. |
| `web/src/features/search/useStreamingSearch.ts` | The search engine of the UI: a `useReducer` over the NDJSON lifecycle (`start`/`phaseStart`/`phaseDone`/`result`/`error`). Each `run()` aborts the prior stream via `AbortController` and bumps a monotonic run-id, so superseded or post-unmount frames are dropped. |
| `web/src/pages/SearchPage.tsx` | The primary route. Pure orchestrator: reads query+filters from the URL, fires `run()` on change, selects the screen — Idle / Loading (live phase rail) / IndexNotReady (503) / SearchError / NoResults (`clarify`\|`no_match`) / Results. A 401 invalidates `ME_QUERY_KEY` so `ProtectedRoute` redirects. |
| `web/src/features/search/useSearchUrlState.ts` | URL ↔ `{query, filters}` binding — the URL is the single source of truth for what search shows. Param names (`q`, `type`, `corr`, `tag`, `from`, `to`) are symmetric with `features/library/LibraryScreen/useLibraryUrlState.ts`, so filter URLs are shareable across both screens. |
| `web/src/lib/parseSearchParams.ts` | Shared URL-param → `FilterRequest` parser. Lives in `lib/` (not `features/search`) because `features/document` also needs it and cross-feature imports violate §12.3. |
| `web/src/hooks/useAuth.tsx` | Read-only derivation over `useMe` → `{user, role, isAuthenticated, isLoading}`. Owns no state; the server session is the source of truth. Login/logout are mutations in `api/hooks/auth.ts`. |
| `web/src/components/layout/ErrorBoundary/ErrorBoundary.tsx` | The only class component in the codebase. Sits in `components/layout` (not `patterns`) because the `app` tier's allow-list includes components-layout only. `resetKeys` lets `routes.tsx` reset it on navigation. |
| `web/src/components/primitives/Icon/Icon.tsx` | Closed `IconName` union → FontAwesome 7 Free Solid `FA_CLASS` map. The only sanctioned icon surface. |
| `web/src/features/settings/fieldModel.ts` | Barrel over `fieldModel/{types,sections,helpers}.ts` — the declarative `SETTINGS_SECTIONS` schema driving the whole Settings screen; paired with `useUnsavedSettings.ts`, which diffs a draft against the saved baseline and sends only changed keys. |
| `web/vite.config.ts` | `outDir: dist`, `target: es2022`, `sourcemap: false`; dev server on :3000 with `/api` → `localhost:8080`. |
| `web/vitest.config.ts` | jsdom, `globals: true`, `pool: 'threads'` (~27% faster than forks). Coverage thresholds: statements 91 / branches 83 / functions 91 / lines 91 — a regression floor 2–3 points below the measured baseline. |
| `web/tsconfig.json` | `strict` + `noUncheckedIndexedAccess` + `noImplicitReturns` + `noFallthroughCasesInSwitch` + `exactOptionalPropertyTypes` + `noPropertyAccessFromIndexSignature`. |
| `web/src/vite-env.d.ts` | Ambient types. Documents that `vite/client` alone types `*.module.css` (no per-file cast) and that only `VITE_`-prefixed vars reach the bundle — `VITE_API_BASE_URL` is the only one. |
| `web/package.json` | Scripts: `dev`, `build` (`tsc -p tsconfig.json --noEmit && vite build`), `typecheck`, `lint` (`eslint . && stylelint "src/**/*.css" --allow-empty-input`), `test`, `test:coverage`, `storybook`, `build-storybook`. `overrides` pin handlebars/uuid/esbuild/js-yaml for CVEs. |

## Invariants

- **The layer stack is mechanically enforced.** `web/eslint.config.js` declares ten boundary element types with `default: 'disallow'`; a violating import fails CI.

  | From | May import |
  |------|-----------|
  | `app` (`App.tsx`, `routes.tsx`, `main.tsx`) | app, pages, features, components-layout, api, hooks, styles, lib |
  | `pages` | pages, features, components-layout, api, hooks, lib |
  | `features` | features, all three component tiers, api, hooks, styles, lib |
  | `components-patterns` | patterns, layout, primitives, hooks, styles, lib, **api** |
  | `components-layout` | layout, primitives, hooks, styles, lib |
  | `components-primitives` | primitives, hooks, styles, lib |
  | `hooks` | hooks, api, lib |
  | `api` | api, lib |
  | `lib` | api (type-only) |
  | `styles` | — (nothing) |

- **A page may NOT import a primitive or a pattern** — only features + `components/layout`. This is the structural guarantee against per-page design drift (§12.3). A missing visual must become a feature or a library component; it is never solved on the page.
- **`pages/*.module.css` is prohibited** (§12.5) — verified: no page ships a CSS module. `features/` may ship a `.module.css` for screen-level layout only, and every value in it must be a token.
- **Every design value comes from `src/styles/tokens.css`.** Stylelint fails a hex/rgb/hsl colour, a raw `px`/`rem`/`em` size, a raw `ms`/`s` duration, a numeric `z-index` or a literal font stack anywhere outside `src/styles/{tokens,themes,global}.css`.
- **Token identifiers use British spelling**: `--colour-accent`, never `--color-*`.
- **Dark mode is keyed on a single `[data-theme="dark"]` selector** in `themes.css`. The pre-paint inline script in `index.html` always sets `data-theme`, so there is no `@media` duplicate to keep in sync.
- **`src/api/` is the only place the frontend touches the backend.** A component or page calling `fetch` directly is a review-blocker. Every request carries `credentials: 'include'`; 401 → `Unauthenticated`, any other non-2xx → `ApiError(status)`.
- **No credential ever reaches the bundle.** Vite exposes only `VITE_`-prefixed env vars, and `VITE_API_BASE_URL` is the only one declared. Secrets (Paperless token, OpenAI key) live in `app.db` and are never prefixed.
- **Server state is TanStack Query's, exclusively** — no hand-rolled loading/error/cache state. Every key comes from the `queryKeys` factory in `api/hooks/keys.ts`; no file hard-codes a key array.
- **Auth queries deliberately override the global 60 s `staleTime`** with `staleTime: 0, retry: false`, so a login or logout flips state on the very next mount. `useLogout` calls `queryClient.clear()` in `onSettled` (not `onSuccess`) — fail-closed: a sign-out click always lands signed out locally and wipes every other user's cached data.
- **Every library component is a typed-props function component** (exported `interface`, no `React.FC`, no `any`) shipping a `.module.css`, a `.test.tsx` and a `.stories.tsx` beside it. The single exception is `ErrorBoundary`, which has no `.stories.tsx` (it is the codebase's only class component). Census: 42 primitives, 12 patterns, 15 layout components (plus the shared `spacing.ts` + `gap.module.css` used by `Stack`/`Grid`); across `src/`: 150 test files, 100 stories, 113 CSS modules.
- **Backend endpoints consumed** (verified in `api/client/`): `/api/auth/{login,logout,me}`, `/api/setup`, `/api/setup/status`, `/api/stats`, `/api/stats/public`, `/api/search`, `/api/search/stream`, `/api/facets`, `/api/healthz`, `/api/reconcile`, `/api/recent-searches`, `/api/documents` (+ `/{id}`, `/{id}/pdf`, `/{id}/thumb`, `/{id}/reclassify`, `/{id}/retranscribe`), `/api/index/{status,activity,failed,rebuild}`, `/api/settings` (+ `/test-connection`), `/api/users` (+ `/{id}`), `/api/api-keys` (+ `/{id}`), `/api/correspondents`, `/api/document-types`, `/api/tags`.
- **The frontend CI lane** (`frontend` job in `.github/workflows/ci.yml`, `working-directory: web`, Node 22) runs in order: `npm ci` → `npm audit --omit=dev --audit-level=high` → `npm run typecheck` → `npm run lint` → `npm run test:coverage` → `npm run build`. The `docker` job `needs:` it, so the image build is gated on it.

## Gotchas

- **Barrel-vs-directory name collision.** `api/client.ts` is the BARREL; `api/client/index.ts` is the index-OPERATIONS module (daemon status, activity, failed docs, rebuild) — not a barrel. Same trap for `api/types.ts` (barrel) vs `api/types/index.ts` (index-ops wire types). Node/TS resolves `from './api/client'` to the file, so imports work — but never assume `client/index.ts` re-exports anything. (The hooks side dodged it by naming the module `hooks/index-ops.ts`.)
- **`index.html` must keep exactly ONE inline `<script>`.** `src/search/security_headers.py` ships `script-src 'self' 'unsafe-inline'` with NO nonce (a `StaticFiles` mount cannot stamp one) precisely to admit the theme bootstrap. `'unsafe-eval'` is deliberately withheld — introducing `eval`/`new Function` into the bundle (e.g. via a new dependency) breaks the app under CSP. `connect-src 'self'` also means no third-party API can ever be called from the browser.
- **Known cross-feature imports.** `eslint-plugin-boundaries` only checks LAYER types, so it does not catch feature→sibling-feature imports and CI stays green. Live violations of the §12.3 sibling rule:
  | Importer | Imports |
  |----------|---------|
  | `features/index/IndexScreen/IndexScreen.tsx:20` | `DocumentPreviewScreen` from `features/search` — named in CODE_GUIDELINES §12.3 as "a live violation to fix on next touch" |
  | `features/search/SourceCard/SourceCard.tsx:6` | `DocumentMeta` from `features/document` |
  | `features/search/DocumentPreviewScreen/DocumentPreviewScreen.tsx:12` | `DocumentMeta` from `features/document` |

  The prescribed fix is promotion to `components/`, not a wider allow-list.
- **Do NOT add `isolate: false` to `vitest.config.ts`.** The comment there records that per-file isolation is load-bearing: without it the suite fails on cross-file global/DOM pollution. `pool: 'threads'` is the sanctioned speed-up.
- **`pages/SearchPage.tsx` disables `react-hooks/exhaustive-deps`** on the search-trigger effect and depends on `JSON.stringify(filters)` instead of the object. Intentional — a fresh-but-equal filters object identity must not retrigger a (billed) LLM search. Do not "fix" the lint by adding `filters` to the deps.
- **The "stale answer" guard.** SearchPage compares `state.query === query.trim()` before trusting a terminal `done`/`error` state, because between a URL change and the effect firing the reducer still holds the previous query's result. Removing that check flashes the old answer under the new query.
- **`main.tsx` imports only `fontawesome.min.css` + `solid.min.css`.** Importing the full FontAwesome CSS pulls ~130 KB of unused woff2 into the bundle. New icons must be Free Solid glyphs registered in the `FA_CLASS` map in `components/primitives/Icon/Icon.tsx`.
- **`web/.npmrc` pins the public npm registry** with an explicit comment: do not repoint it at an internal/corporate registry — the Docker build and external contributors depend on it.
- **`noPropertyAccessFromIndexSignature` is on**, so CSS-module classes are accessed with bracket notation (`styles['button']`). Do not add per-file `as Record<string, string>` casts — `vite/client` already types the import (see `src/vite-env.d.ts`).
- **Deep links only work because of the Python side.** `src/search/spa.py` serves real files from `web/dist` and falls back to `index.html` for any GET that is not an `/api` or `/mcp` path (so an unknown `/api` path still 404s honestly). Changing the route table needs no backend change — but removing that catch-all breaks every hard refresh.
- **`npm run build` runs `tsc -p tsconfig.json --noEmit` BEFORE `vite build`** — a type error fails the build, not just the typecheck lane. Production sourcemaps are off (`sourcemap: false`), so a prod stack trace is unsymbolicated by design.
- **The `app` boundary element type is exactly `src/App.tsx`, `src/routes.tsx`, `src/main.tsx`** (the pattern list in `eslint.config.js`). Adding a fourth composition-root file without registering it there leaves it unclassified and silently unchecked.
- **`components-patterns → api` is an explicit narrow exception** in the allow matrix — added in commit `1b7fe18` when `FilterControls` was promoted to `components/patterns` (shared by library + search), and documented in `eslint.config.js` as mirroring the earlier `hooks → api` allowance (`eefa1a8`). It is not a licence for every pattern to fetch; primitives and layout still cannot reach `api`.
- **`ErrorBoundary` sits in `components/layout/`, not `components/patterns/`,** purely because the `app` tier's allow-list contains components-layout and not components-patterns. Moving it breaks `routes.tsx`/`main.tsx` at lint time.

## Extension points

| To add… | Do this |
|---------|---------|
| A design value | Add a token to `src/styles/tokens.css` (British name, `--colour-*`) and its dark counterpart to `themes.css`. Never a literal in a component's CSS module — stylelint fails it. |
| A backend call | Add the typed function to the matching `src/api/client/<domain>.ts`, the wire type to `src/api/types/<domain>.ts` (mirroring the matching module in `src/search/wire/`), a key to the `queryKeys` factory, and the hook to `src/api/hooks/<domain>.ts`. Never `fetch` from a component. |
| A route | Add a `<Route>` in `src/routes.tsx` wrapped in `ProtectedRoute` or `RequireAdmin`; `React.lazy` it unless it is on the load path. No backend change is needed — `spa.py`'s catch-all already serves it. |
| A page | `src/pages/<Name>Page.tsx`, composed from features + `components/layout` only, and with no CSS module (§12.5). |
| A UI element | Put it in the lowest tier that fits (`components/primitives` → `layout` → `patterns`) with a `.module.css`, a `.test.tsx` and a `.stories.tsx`. Reuse before creating: 42 primitives already exist. |
| An icon | Extend the `IconName` union and the `FA_CLASS` map in `components/primitives/Icon/Icon.tsx` in lockstep, using a FontAwesome 7 Free **Solid** glyph. |
| A setting | Add the field to `SETTINGS_SECTIONS` in `features/settings/fieldModel/sections.ts` — the Settings screen is data-driven; no screen code changes. |
| A composition-root file | Register its path in the `app` element-type pattern list in `eslint.config.js`, or its imports go unchecked. |

## Related

- Modules: [search-api](search-api.md) — serves `web/dist` (`src/search/spa.py`), owns the CSP the SPA must stay compatible with (`src/search/security_headers.py`), emits the NDJSON frames the SPA decodes (`src/search/routes.py` + `src/search/wire/stream.py`), and defines the wire shapes (`src/search/wire/`) that `src/api/types/` mirrors. [search-pipeline](search-pipeline.md) — the phases the live rail and trace panel render; the `SearchPhase` union in `src/api/types/search.ts` (`plan` · `resolve` · `retrieve` · `gate` · `judge` · `synthesise` · `replan` · `refine` · `cache`) must track the strings the pipeline emits.
- Law: `CODE_GUIDELINES.md` §12 (Frontend Architecture) — §12.3 the layer stack, §12.4 tokens, §12.5 CSS-module ownership, §12.6 the typed API layer, §12.7–12.8 component standards, §12.10 build and CI.
- Stack: react 18.3 + react-dom, react-router-dom 6.30, @tanstack/react-query 5.56, @fortawesome/fontawesome-free 7.2 (Free Solid only, self-hosted — `font-src 'self'`), vite 6.4.3 + @vitejs/plugin-react, typescript 5.6, eslint 9 + eslint-plugin-boundaries 5, stylelint 16, prettier 3, vitest 4 + @testing-library/* + jsdom 25, storybook 8.3 (`.storybook/` is excluded from ESLint).
