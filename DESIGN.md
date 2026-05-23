# Design System Inspiration of Apple

## 1. Visual Theme & Atmosphere

Apple's website is a masterclass in controlled drama — vast expanses of pure black and near-white serve as cinematic backdrops for products that are photographed as if they were sculptures in a gallery. The design philosophy is reductive to its core: every pixel exists in service of the product, and the interface itself retreats until it becomes invisible. This is not minimalism as aesthetic preference; it is minimalism as reverence for the object.

The typography anchors everything. San Francisco (SF Pro Display for large sizes, SF Pro Text for body) is Apple's proprietary typeface, engineered with optical sizing that automatically adjusts letterforms depending on point size. At display sizes (56px), weight 600 with a tight line-height of 1.07 and subtle negative letter-spacing (-0.28px) creates headlines that feel machined rather than typeset — precise, confident, and unapologetically direct. At body sizes (17px), the tracking loosens slightly (-0.374px) and line-height opens to 1.47, creating a reading rhythm that is comfortable without ever feeling slack.

The color story is starkly binary. Product sections alternate between pure black (`#000000`) backgrounds with white text and light gray (`#f5f5f7`) backgrounds with near-black text (`#1d1d1f`). This creates a cinematic pacing — dark sections feel immersive and premium, light sections feel open and informational. The only chromatic accent is Apple Blue (`#0071e3`), reserved exclusively for interactive elements: links, buttons, and focus states. This singular accent color in a sea of neutrals gives every clickable element unmistakable visibility.

**Key Characteristics:**
- SF Pro Display/Text with optical sizing — letterforms adapt automatically to size context
- Binary light/dark section rhythm: black (`#000000`) alternating with light gray (`#f5f5f7`)
- Single accent color: Apple Blue (`#0071e3`) reserved exclusively for interactive elements
- Product-as-hero photography on solid color fields — no gradients, no textures, no distractions
- Extremely tight headline line-heights (1.07-1.14) creating compressed, billboard-like impact
- Full-width section layout with centered content — the viewport IS the canvas
- Pill-shaped CTAs (980px radius) creating soft, approachable action buttons
- Generous whitespace between sections allowing each product moment to breathe

## 2. Color Palette & Roles

### Primary
- **Pure Black** (`#000000`): Hero section backgrounds, immersive product showcases. The darkest canvas for the brightest products.
- **Light Gray** (`#f5f5f7`): Alternate section backgrounds, informational areas. Not white — the slight blue-gray tint prevents sterility.
- **Near Black** (`#1d1d1f`): Primary text on light backgrounds, dark button fills. Slightly warmer than pure black for comfortable reading.

### Interactive
- **Apple Blue** (`#0071e3`): `--sk-focus-color`, primary CTA backgrounds, focus rings. The ONLY chromatic color in the interface.
- **Link Blue** (`#0066cc`): `--sk-body-link-color`, inline text links. Slightly darker than Apple Blue for text-level readability.
- **Bright Blue** (`#2997ff`): Links on dark backgrounds. Higher luminance for contrast on black sections.

### Text
- **White** (`#ffffff`): Text on dark backgrounds, button text on blue/dark CTAs.
- **Near Black** (`#1d1d1f`): Primary body text on light backgrounds.
- **Black 80%** (`rgba(0, 0, 0, 0.8)`): Secondary text, nav items on light backgrounds. Slightly softened.
- **Black 48%** (`rgba(0, 0, 0, 0.48)`): Tertiary text, disabled states, carousel controls.

### Surface & Dark Variants
- **Dark Surface 1** (`#272729`): Card backgrounds in dark sections.
- **Dark Surface 2** (`#262628`): Subtle surface variation in dark contexts.
- **Dark Surface 3** (`#28282a`): Elevated cards on dark backgrounds.
- **Dark Surface 4** (`#2a2a2d`): Highest dark surface elevation.
- **Dark Surface 5** (`#242426`): Deepest dark surface tone.

### Button States
- **Button Active** (`#ededf2`): Active/pressed state for light buttons.
- **Button Default Light** (`#fafafc`): Search/filter button backgrounds.
- **Overlay** (`rgba(210, 210, 215, 0.64)`): Media control scrims, overlays.
- **White 32%** (`rgba(255, 255, 255, 0.32)`): Hover state on dark modal close buttons.

### Shadows
- **Card Shadow** (`rgba(0, 0, 0, 0.22) 3px 5px 30px 0px`): Soft, diffused elevation for product cards. Offset and wide blur create a natural, photographic shadow.

## 3. Typography Rules

### Font Family
- **Display**: `SF Pro Display`, with fallbacks: `SF Pro Icons, Helvetica Neue, Helvetica, Arial, sans-serif`
- **Body**: `SF Pro Text`, with fallbacks: `SF Pro Icons, Helvetica Neue, Helvetica, Arial, sans-serif`
- SF Pro Display is used at 20px and above; SF Pro Text is optimized for 19px and below.

### Hierarchy

| Role | Font | Size | Weight | Line Height | Letter Spacing | Notes |
|------|------|------|--------|-------------|----------------|-------|
| Display Hero | SF Pro Display | 56px (3.50rem) | 600 | 1.07 (tight) | -0.28px | Product launch headlines, maximum impact |
| Section Heading | SF Pro Display | 40px (2.50rem) | 600 | 1.10 (tight) | normal | Feature section titles |
| Tile Heading | SF Pro Display | 28px (1.75rem) | 400 | 1.14 (tight) | 0.196px | Product tile headlines |
| Card Title | SF Pro Display | 21px (1.31rem) | 700 | 1.19 (tight) | 0.231px | Bold card headings |
| Sub-heading | SF Pro Display | 21px (1.31rem) | 400 | 1.19 (tight) | 0.231px | Regular card headings |
| Nav Heading | SF Pro Text | 34px (2.13rem) | 600 | 1.47 | -0.374px | Large navigation headings |
| Sub-nav | SF Pro Text | 24px (1.50rem) | 300 | 1.50 | normal | Light sub-navigation text |
| Body | SF Pro Text | 17px (1.06rem) | 400 | 1.47 | -0.374px | Standard reading text |
| Body Emphasis | SF Pro Text | 17px (1.06rem) | 600 | 1.24 (tight) | -0.374px | Emphasized body text, labels |
| Button Large | SF Pro Text | 18px (1.13rem) | 300 | 1.00 (tight) | normal | Large button text, light weight |
| Button | SF Pro Text | 17px (1.06rem) | 400 | 2.41 (relaxed) | normal | Standard button text |
| Link | SF Pro Text | 14px (0.88rem) | 400 | 1.43 | -0.224px | Body links, "Learn more" |
| Caption | SF Pro Text | 14px (0.88rem) | 400 | 1.29 (tight) | -0.224px | Secondary text, descriptions |
| Caption Bold | SF Pro Text | 14px (0.88rem) | 600 | 1.29 (tight) | -0.224px | Emphasized captions |
| Micro | SF Pro Text | 12px (0.75rem) | 400 | 1.33 | -0.12px | Fine print, footnotes |
| Micro Bold | SF Pro Text | 12px (0.75rem) | 600 | 1.33 | -0.12px | Bold fine print |
| Nano | SF Pro Text | 10px (0.63rem) | 400 | 1.47 | -0.08px | Legal text, smallest size |

### Principles
- **Optical sizing as philosophy**: SF Pro automatically switches between Display and Text optical sizes. Display versions have wider letter spacing and thinner strokes optimized for large sizes; Text versions are tighter and sturdier for small sizes. This means the font literally changes its DNA based on context.
- **Weight restraint**: The scale spans 300 (light) to 700 (bold) but most text lives at 400 (regular) and 600 (semibold). Weight 300 appears only on large decorative text. Weight 700 is rare, used only for bold card titles.
- **Negative tracking at all sizes**: Unlike most systems that only track headlines, Apple applies subtle negative letter-spacing even at body sizes (-0.374px at 17px, -0.224px at 14px, -0.12px at 12px). This creates universally tight, efficient text.
- **Extreme line-height range**: Headlines compress to 1.07 while body text opens to 1.47, and some button contexts stretch to 2.41. This dramatic range creates clear visual hierarchy through rhythm alone.

## 4. Component Stylings

### Buttons

**Primary Blue (CTA)**
- Background: `#0071e3` (Apple Blue)
- Text: `#ffffff`
- Padding: 8px 15px
- Radius: 8px
- Border: 1px solid transparent
- Font: SF Pro Text, 17px, weight 400
- Hover: background brightens slightly
- Active: `#ededf2` background shift
- Focus: `2px solid var(--sk-focus-color, #0071E3)` outline
- Use: Primary call-to-action ("Buy", "Shop iPhone")

**Primary Dark**
- Background: `#1d1d1f`
- Text: `#ffffff`
- Padding: 8px 15px
- Radius: 8px
- Font: SF Pro Text, 17px, weight 400
- Use: Secondary CTA, dark variant

**Pill Link (Learn More / Shop)**
- Background: transparent
- Text: `#0066cc` (light bg) or `#2997ff` (dark bg)
- Radius: 980px (full pill)
- Border: 1px solid `#0066cc`
- Font: SF Pro Text, 14px-17px
- Hover: underline decoration
- Use: "Learn more" and "Shop" links — the signature Apple inline CTA

**Filter / Search Button**
- Background: `#fafafc`
- Text: `rgba(0, 0, 0, 0.8)`
- Padding: 0px 14px
- Radius: 11px
- Border: 3px solid `rgba(0, 0, 0, 0.04)`
- Focus: `2px solid var(--sk-focus-color, #0071E3)` outline
- Use: Search bars, filter controls

**Media Control**
- Background: `rgba(210, 210, 215, 0.64)`
- Text: `rgba(0, 0, 0, 0.48)`
- Radius: 50% (circular)
- Active: scale(0.9), background shifts
- Focus: `2px solid var(--sk-focus-color, #0071e3)` outline, white bg, black text
- Use: Play/pause, carousel arrows

### Cards & Containers
- Background: `#f5f5f7` (light) or `#272729`-`#2a2a2d` (dark)
- Border: none (borders are rare in Apple's system)
- Radius: 5px-8px
- Shadow: `rgba(0, 0, 0, 0.22) 3px 5px 30px 0px` for elevated product cards
- Content: centered, generous padding
- Hover: no standard hover state — cards are static, links within them are interactive

### Navigation
- Background: `rgba(0, 0, 0, 0.8)` (translucent dark) with `backdrop-filter: saturate(180%) blur(20px)`
- Height: 48px (compact)
- Text: `#ffffff` at 12px, weight 400
- Active: underline on hover
- Logo: Apple logomark (SVG) centered or left-aligned, 17x48px viewport
- Mobile: collapses to hamburger with full-screen overlay menu
- The nav floats above content, maintaining its dark translucent glass regardless of section background

### Image Treatment
- Products on solid-color fields (black or white) — no backgrounds, no context, just the object
- Full-bleed section images that span the entire viewport width
- Product photography at extremely high resolution with subtle shadows
- Lifestyle images confined to rounded-corner containers (12px+ radius)

### Distinctive Components

**Product Hero Module**
- Full-viewport-width section with solid background (black or `#f5f5f7`)
- Product name as the primary headline (SF Pro Display, 56px, weight 600)
- One-line descriptor below in lighter weight
- Two pill CTAs side by side: "Learn more" (outline) and "Buy" / "Shop" (filled)

**Product Grid Tile**
- Square or near-square card on contrasting background
- Product image dominating 60-70% of the tile
- Product name + one-line description below
- "Learn more" and "Shop" link pair at bottom

**Feature Comparison Strip**
- Horizontal scroll of product variants
- Each variant as a vertical card with image, name, and key specs
- Minimal chrome — the products speak for themselves

**Search experience (Wave 2)**
- `DocThumb` — a fixed 96×124 SVG mockup of a document page: a header block,
  a hairline, grey body line-stripes (matched rows drawn in `--colour-accent`),
  and a footer totals band for statements and invoices.
- `AnswerSurface` — the synthesised-answer card: a "Synthesised answer"
  eyebrow with a spark glyph, the answer prose in SF Pro Display, and a
  hairline-topped provenance footer (source count, latency, an optional
  "Refined once" marker).
- `CitationMark` — an inline citation chip: a 20px `--colour-accent` circle
  carrying a white numeral; a real, focus-ringed `<button>`.
- `SourceCardSurface` — the source-result card shell: a two-column grid (a
  content column and a `DocThumb` column) with a circular citation badge
  overlapping the thumbnail's top-left corner; a `highlighted` variant lifts
  the card with `--shadow-source-highlight` and an `--colour-accent-ring`
  outline.
- `SnippetText` — matched-content text; `**bold**` runs render as
  `--colour-accent-wash` highlight marks.
- `Disclosure` — a native `<details>` collapsible panel with a chevron that
  rotates a quarter-turn when open. Backs `QueryPlanSummary`.
- `PipelineStages` — the agentic-search progress rail: an ordered list of
  stages, each with a status dot (a tick when done, a pulsing core when
  active, a muted disc when pending) and an "in progress" pill on the active
  stage.
- `RecentSearchStrip`, `IndexStatusFooter` — the idle-screen recent-search
  list and index-status summary line.
- `DocumentViewerChrome`, `PdfFrame`, `ViewerSplit` — the in-app PDF viewer:
  a forced-dark chrome bar (the `--colour-dark-*` tokens), an `<iframe>` of
  the proxied PDF, and the page-area / metadata-sidebar split.

Search-screen layout uses the `SearchScreenLayout` primitive — a `centred`
single column (idle, index-not-ready, error) or a `rail` filter-rail +
content grid (loading, results, no-results).

## 5. Layout Principles

### Spacing System
- Base unit: 8px
- Scale: 2px, 4px, 5px, 6px, 7px, 8px, 9px, 10px, 11px, 14px, 15px, 17px, 20px, 24px
- Notable characteristic: the scale is dense at small sizes (2-11px) with granular 1px increments, then jumps in larger steps. This allows precise micro-adjustments for typography and icon alignment.

### Grid & Container
- Max content width: approximately 980px (the recurring "980px radius" in pill buttons echoes this width)
- Hero: full-viewport-width sections with centered content block
- Product grids: 2-3 column layouts within centered container
- Single-column for hero moments — one product, one message, full attention
- No visible grid lines or gutters — spacing creates implied structure

### Whitespace Philosophy
- **Cinematic breathing room**: Each product section occupies a full viewport height (or close to it). The whitespace between products is not empty — it is the pause between scenes in a film.
- **Vertical rhythm through color blocks**: Rather than using spacing alone to separate sections, Apple uses alternating background colors (black, `#f5f5f7`, white). Each color change signals a new "scene."
- **Compression within, expansion between**: Text blocks are tightly set (negative letter-spacing, tight line-heights) while the space surrounding them is vast. This creates a tension between density and openness.

### Border Radius Scale
- Micro (5px): Small containers, link tags
- Standard (8px): Buttons, product cards, image containers
- Comfortable (11px): Search inputs, filter buttons
- Large (12px): Feature panels, lifestyle image containers
- Full Pill (980px): CTA links ("Learn more", "Shop"), navigation pills
- Circle (50%): Media controls (play/pause, arrows)

## 6. Depth & Elevation

| Level | Treatment | Use |
|-------|-----------|-----|
| Flat (Level 0) | No shadow, solid background | Standard content sections, text blocks |
| Navigation Glass | `backdrop-filter: saturate(180%) blur(20px)` on `rgba(0,0,0,0.8)` | Sticky navigation bar — the glass effect |
| Subtle Lift (Level 1) | `rgba(0, 0, 0, 0.22) 3px 5px 30px 0px` | Product cards, floating elements |
| Media Control | `rgba(210, 210, 215, 0.64)` background with scale transforms | Play/pause buttons, carousel controls |
| Focus (Accessibility) | `2px solid #0071e3` outline | Keyboard focus on all interactive elements |

**Shadow Philosophy**: Apple uses shadow extremely sparingly. The primary shadow (`3px 5px 30px` with 0.22 opacity) is soft, wide, and offset — mimicking a diffused studio light casting a natural shadow beneath a physical object. This reinforces the "product as physical sculpture" metaphor. Most elements have NO shadow at all; elevation comes from background color contrast (dark card on darker background, or light card on slightly different gray).

### Decorative Depth
- Navigation glass: the translucent, blurred navigation bar is the most recognizable depth element, creating a sense of floating UI above scrolling content
- Section color transitions: depth is implied by the alternation between black and light gray sections rather than by shadows
- Product photography shadows: the products themselves cast shadows in their photography, so the UI doesn't need to add synthetic ones

## 7. Do's and Don'ts

### Do
- Use SF Pro Display at 20px+ and SF Pro Text below 20px — respect the optical sizing boundary
- Apply negative letter-spacing at all text sizes (not just headlines) — Apple tracks tight universally
- Use Apple Blue (`#0071e3`) ONLY for interactive elements — it must be the singular accent
- Alternate between black and light gray (`#f5f5f7`) section backgrounds for cinematic rhythm
- Use 980px pill radius for CTA links — the signature Apple link shape
- Keep product imagery on solid-color fields with no competing visual elements
- Use the translucent dark glass (`rgba(0,0,0,0.8)` + blur) for sticky navigation
- Compress headline line-heights to 1.07-1.14 — Apple headlines are famously tight

### Don't
- Don't introduce additional accent colors — the entire chromatic budget is spent on blue
- Don't use heavy shadows or multiple shadow layers — Apple's shadow system is one soft diffused shadow or nothing
- Don't use borders on cards or containers — Apple almost never uses visible borders (except on specific buttons)
- Don't apply wide letter-spacing to SF Pro — it is designed to run tight at every size
- Don't use weight 800 or 900 — the maximum is 700 (bold), and even that is rare
- Don't add textures, patterns, or gradients to backgrounds — solid colors only
- Don't make the navigation opaque — the glass blur effect is essential to the Apple UI identity
- Don't center-align body text — Apple body copy is left-aligned; only headlines center
- Don't use rounded corners larger than 12px on rectangular elements (980px is for pills only)

## 8. Responsive Behavior

### Breakpoints
| Name | Width | Key Changes |
|------|-------|-------------|
| Small Mobile | <360px | Minimum supported, single column |
| Mobile | 360-480px | Standard mobile layout |
| Mobile Large | 480-640px | Wider single column, larger images |
| Tablet Small | 640-834px | 2-column product grids begin |
| Tablet | 834-1024px | Full tablet layout, expanded nav |
| Desktop Small | 1024-1070px | Standard desktop layout begins |
| Desktop | 1070-1440px | Full layout, max content width |
| Large Desktop | >1440px | Centered with generous margins |

### Touch Targets
- Primary CTAs: 8px 15px padding creating ~44px touch height
- Navigation links: 48px height with adequate spacing
- Media controls: 50% radius circular buttons, minimum 44x44px
- "Learn more" pills: generous padding for comfortable tapping

### Collapsing Strategy
- Hero headlines: 56px Display → 40px → 28px on mobile, maintaining tight line-height proportionally
- Product grids: 3-column → 2-column → single column stacked
- Navigation: full horizontal nav → compact mobile menu (hamburger)
- Product hero modules: full-bleed maintained at all sizes, text scales down
- Section backgrounds: maintain full-width color blocks at all breakpoints — the cinematic rhythm never breaks
- Image sizing: products scale proportionally, never crop — the product silhouette is sacred

### Image Behavior
- Product photography maintains aspect ratio at all breakpoints
- Hero product images scale down but stay centered
- Full-bleed section backgrounds persist at every size
- Lifestyle images may crop on mobile but maintain their rounded corners
- Lazy loading for below-fold product images

## 9. Agent Prompt Guide

### Quick Color Reference
- Primary CTA: Apple Blue (`#0071e3`)
- Page background (light): `#f5f5f7`
- Page background (dark): `#000000`
- Heading text (light): `#1d1d1f`
- Heading text (dark): `#ffffff`
- Body text: `rgba(0, 0, 0, 0.8)` on light, `#ffffff` on dark
- Link (light bg): `#0066cc`
- Link (dark bg): `#2997ff`
- Focus ring: `#0071e3`
- Card shadow: `rgba(0, 0, 0, 0.22) 3px 5px 30px 0px`

### Example Component Prompts
- "Create a hero section on black background. Headline at 56px SF Pro Display weight 600, line-height 1.07, letter-spacing -0.28px, color white. One-line subtitle at 21px SF Pro Display weight 400, line-height 1.19, color white. Two pill CTAs: 'Learn more' (transparent bg, white text, 1px solid white border, 980px radius) and 'Buy' (Apple Blue #0071e3 bg, white text, 8px radius, 8px 15px padding)."
- "Design a product card: #f5f5f7 background, 8px border-radius, no border, no shadow. Product image top 60% of card on solid background. Title at 28px SF Pro Display weight 400, letter-spacing 0.196px, line-height 1.14. Description at 14px SF Pro Text weight 400, color rgba(0,0,0,0.8). 'Learn more' and 'Shop' links in #0066cc at 14px."
- "Build the Apple navigation: sticky, 48px height, background rgba(0,0,0,0.8) with backdrop-filter: saturate(180%) blur(20px). Links at 12px SF Pro Text weight 400, white text. Apple logo left, links centered, search and bag icons right."
- "Create an alternating section layout: first section black bg with white text and centered product image, second section #f5f5f7 bg with #1d1d1f text. Each section near full-viewport height with 56px headline and two pill CTAs below."
- "Design a 'Learn more' link: text #0066cc on light bg or #2997ff on dark bg, 14px SF Pro Text, underline on hover. After the text, include a right-arrow chevron character (>). Wrap in a container with 980px border-radius for pill shape when used as a standalone CTA."

### Iteration Guide
1. Every interactive element gets Apple Blue (`#0071e3`) — no other accent colors
2. Section backgrounds alternate: black for immersive moments, `#f5f5f7` for informational moments
3. Typography optical sizing: SF Pro Display at 20px+, SF Pro Text below — never mix
4. Negative letter-spacing at all sizes: -0.28px at 56px, -0.374px at 17px, -0.224px at 14px, -0.12px at 12px
5. The navigation glass effect (translucent dark + blur) is non-negotiable — it defines the Apple web experience
6. Products always appear on solid color fields — never on gradients, textures, or lifestyle backgrounds in hero modules
7. Shadow is rare and always soft: `3px 5px 30px 0.22 opacity` or nothing at all
8. Pill CTAs use 980px radius — this creates the signature Apple rounded-rectangle-that-looks-like-a-capsule shape

---

## 10. Implementation — Token System

Sections 1-9 above document the design inspiration. Sections 10-14 document the
**actual implementation** in `web/src/` — the components, tokens, patterns, and
architectural decisions that exist in code. This is the live, authoritative
reference for implementers.

### 10.1 Token file locations

| File | Purpose |
|------|---------|
| `web/src/styles/tokens.css` | All design tokens (CSS custom properties on `:root`) |
| `web/src/styles/themes.css` | Light and dark theme overrides of token values |
| `web/src/styles/global.css` | Resets, `@font-face`, base element styles |

**Rule:** No component may contain a hardcoded colour, size, radius, or shadow.
Every design value is a `var(--…)` reference. Stylelint enforces this — a literal
`px` size or hex colour outside `tokens.css` fails CI.

### 10.2 Token naming conventions

- British spelling: `--colour-*`, never `--color-*`.
- Semantic tokens (role-based) are preferred over literal tokens. Example:
  `--colour-text-primary` not `--colour-near-black`.
- Theme-independent tokens (forced-dark island, status colours, avatar palette,
  accent-wash) are defined once on `:root` and **not** overridden in `themes.css`.
- Theme-aware tokens are declared in `tokens.css` with light-theme fallback
  values, and overridden for dark mode in `themes.css`.

### 10.3 Token groups

| Group | Prefix | Description |
|-------|--------|-------------|
| Colour roles | `--colour-*` | Backgrounds, text, accent, borders, overlays |
| Forced-dark island | `--colour-dark-*` | Login/Setup screens — same in both themes |
| Status colours | `--colour-status-*` | Badge/pill semantic colours |
| Avatar palette | `--colour-avatar-0…5` | Deterministic per-user avatar backgrounds |
| Accent variants | `--colour-accent-wash`, `--colour-accent-ring` | Translucent accent for highlights |
| Font families | `--font-display`, `--font-text`, `--font-mono` | SF Pro stack |
| Type scale | `--font-size-*`, `--font-weight-*`, etc. | Per-role size/weight/leading/tracking |
| Spacing | `--spacing-1` … `--spacing-14` | 8px-base dense scale |
| Radii | `--radius-micro` … `--radius-pill` | The six-rung border-radius ladder |
| Shadows | `--shadow-card`, `--shadow-answer`, etc. | Soft, diffused — sparingly used |
| Motion | `--duration-*`, `--easing-*` | Transition durations and curves |
| Z-index | `--z-base` … `--z-modal` | Five-rung stacking ladder |
| Breakpoints | `--bp-*` | Reference values (use raw values in `@media` queries) |
| Dimensions | `--size-*`, `--width-*`, `--height-*` | Fixed component sizes |
| Opacities | `--opacity-disabled` | Interaction state modifiers |
| Settings controls | `--colour-toggle-*`, `--size-toggle-*`, etc. | Toggle/Segmented/NumberStepper |
| Gradients | `--gradient-avatar-default` | Default avatar background |

---

## 11. Implementation — Component Library

The component library lives under `web/src/components/` and is structured into
three sub-layers: `primitives/` (atomic), `layout/` (structural), and
`patterns/` (composed). All import directions obey CODE_GUIDELINES §12.3.

### 11.1 Layer rules

```
pages/       → features/, components/layout/, api/, hooks/
features/    → components/*, api/, hooks/
components/  → lower components/, styles/
styles/      → (nothing)
api/, hooks/ → (nothing above)
```

**Crucial:** `features/` components may import from `components/` but never
from `pages/`. A `pages/` component composes `features/` and `layout/` only —
it never writes CSS or reaches into primitives directly.

### 11.2 CSS module policy — the `features/.module.css` exception

CODE_GUIDELINES §12.5 states "only `components/` carries styling". In practice,
every `features/` sub-screen (IndexScreen, LibraryScreen, LoginScreen, etc.) ships
its own `.module.css` for layout and spacing concerns that are specific to that
screen and cannot be expressed purely by composing layout primitives.

**Decision (Wave 7):** This pattern is codified as intentional, not a bug.
The rule is refined as:

- `components/` CSS modules: component identity, visual chrome, all tokens.
- `features/` CSS modules: screen-level layout, spacing overrides, structural
  grid/flex containers. **No hardcoded design values** — every value must still
  reference a token.
- `pages/` CSS modules: **prohibited.** Pages compose; they do not style.

The boundary is: if a `features/` module is copy-pasting a component's visual
chrome (colours, radii, shadows), it should extract a new `components/` primitive
instead. Screen-level layout grids are fine to keep in `features/`.

### 11.3 Primitives catalogue

| Component | Tier | Props/Variants | Notes |
|-----------|------|----------------|-------|
| `Button` | primitives | `variant` (primary/secondary/destructive/ghost), `size` (default/small), `type`, `disabled` | Focus ring, hover, active states |
| `IconButton` | primitives | `icon`, `label` (a11y), `size`, `variant` | Circular icon-only button |
| `Input` | primitives | `label`, `type`, `surface` (light/dark), `error`, `disabled` | Dark surface for Login/Setup island |
| `TextArea` | primitives | `label`, `surface`, `error`, `disabled` | Multi-line companion to Input |
| `Link` | primitives | `href`, `variant` (default/pill), `external` | External links open in new tab, `rel="noopener"` |
| `Badge` | primitives | `variant` (neutral/accent) | Inline label chip |
| `RoleBadge` | primitives | `role` (admin/member/readonly) | Maps role to semantic colour token |
| `StatusBadge` | primitives | `tone` (ok/warn/danger/info/neutral/violet) | Leading status dot + label |
| `ScopePill` | primitives | `scope` (read/write/mcp) | API-key scope pill |
| `Chip` | primitives | `selected`, `onRemove`, `removeLabel` | Filter chip with remove × |
| `Card` | primitives | `children`, `className` | Surface container, one shadow level |
| `Icon` | primitives | `name` (closed union), `size` (small/medium/large/xlarge) | SVG icon set |
| `Spinner` | primitives | `size` (small/medium/large), `label` (a11y) | WCAG accessible; `role="status"` |
| `Skeleton` | primitives | `kind` (line/control/block/media), `width` | Loading placeholder shimmer |
| `Text` | primitives | `as` (span/p/strong/etc.), `variant` (body/caption/micro/card-title/…), `tone` (primary/secondary/tertiary) | Applies type-scale tokens |
| `Avatar` | primitives | `initials`, `colour`, `size` | Coloured initials circle |
| `Brand` | primitives | `size` | SVG paperless-ai logo mark |
| `Tooltip` | primitives | `content`, `placement` | Hover label via a positioned overlay |
| `Toggle` | primitives | `checked`, `onChange`, `label`, `disabled` | iOS-style on/off switch |
| `Segmented` | primitives | `options`, `value`, `onChange` | Multi-option tab selector |
| `NumberStepper` | primitives | `value`, `min`, `max`, `step`, `onChange`, `label` | ± stepper for numeric settings |
| `StatTile` | primitives | `value`, `label`, `accent` | Single-stat display; `accent` applies the accent colour |
| `Row` | primitives | `label`, `children`, `action`, `description`, `divider` | Settings row — two-column label/control layout |
| `SectionCard` | primitives | `icon`, `title`, `description`, `children` | Settings section card with an icon header |
| `FormField` | primitives | `label`, `id`, `error`, `hint`, `children` | Label + error wrapper for form controls |
| `SettingsTextField` | primitives | `label`, `value`, `onChange`, `disabled`, `error` | Settings-specific text input row |
| `SettingsSelectField` | primitives | `label`, `options`, `value`, `onChange`, `disabled` | Settings-specific select row |
| `Table` | primitives | `columns` (Column[]), `data`, `keyField` | Data table with typed columns |
| `SnippetText` | primitives | `text` | Renders `**bold**` runs as `<mark>` highlight chips |
| `DocThumb` | primitives | `kind` (invoice/letter/statement), `matched` (row indices) | SVG document thumbnail |
| `SourceCardSurface` | primitives | `index`, `thumbKind`, `matched`, `highlighted` | Two-column card shell (content + DocThumb + citation badge) |
| `AnswerSurface` | primitives | `answer`, `sourceCount`, `latencyMs`, `refined`, `children` | Synthesised-answer card |
| `CitationMark` | primitives | `index`, `onClick` | Inline citation chip `[n]` button |
| `PipelineStages` | primitives | `stages` (StageStatus[]) | Search progress rail |
| `Disclosure` | primitives | `summary`, `children`, `open` | `<details>` collapsible panel |
| `RecentSearchStrip` | primitives | `searches`, `onSelect`, `onClear` | Idle-screen recent-search list |
| `IndexStatusFooter` | primitives | `documentCount`, `ready` | Idle-screen index-status summary |
| `DocumentViewerChrome` | primitives | `title`, `paperlessUrl`, `downloadUrl`, `onClose`, `children` | Forced-dark viewer frame |
| `PdfFrame` | primitives | `src`, `title` | `<iframe>` PDF embed |

### 11.4 Layout catalogue

| Component | Props | Notes |
|-----------|-------|-------|
| `Page` | `children`, `className` | Root page wrapper: `--colour-bg`, `100dvh` min-height |
| `Container` | `children`, `className` | Max-width (`--width-content-max`) + centring |
| `Section` | `children`, `variant` (light/dark) | Alternating background section |
| `Stack` | `direction`, `gap`, `align`, `wrap`, `children` | Flex column/row with gap token |
| `Grid` | `columns`, `gap`, `children` | CSS grid wrapper |
| `Divider` | `orientation` | Hairline separator |
| `NavBar` | `brand`, `links`, `actions` | Glass navigation bar (`--colour-nav-bg`, `--backdrop-nav`, `--z-nav`) |
| `SearchScreenLayout` | `variant` (centred/rail), `rail`, `children` | Search/Library page layout: centred single-column or filter-rail + content |
| `SettingsLayout` | `children` | Settings page layout: left sidenav + right content pane |
| `SettingsSideNav` | `items`, `activePath` | Settings left nav (vertical tabs) |
| `ViewerSplit` | `sidebar`, `children` | Document-preview two-pane split |
| `FullPageLoading` | `label` | Full-viewport spinner placeholder |

### 11.5 Patterns catalogue

| Component | Props | Notes |
|-----------|-------|-------|
| `SearchField` | `id`, `placeholder`, `onSubmit`, `defaultValue` | Pill-shaped search input |
| `Select` | `id`, `label`, `options`, `value`, `onChange` | Custom listbox select (keyboard-navigable) |
| `FilterPanel` | `title`, `children`, `open`, `onToggle` | Collapsible filter section |
| `EmptyState` | `icon`, `message`, `description`, `action`, `className` | Empty/error placeholder with icon |
| `Modal` | `open`, `title`, `onClose`, `children` | Centred dialog with focus trap |
| `Toast` | `message`, `tone`, `onDismiss` | Transient notification |
| `Tabs` | `items`, `activeId`, `onChange` | Horizontal tab bar |
| `UserMenu` | `initials`, `displayName`, `username`, `email`, `onSignOut` | Avatar + dropdown menu |
| `SortControl` | `id`, `label`, `options`, `value`, `onChange` | Sort-by select |
| `ViewToggle` | `value` (grid/list), `onChange` | Icon-button pair for grid/list view |

---

## 12. Implementation — Screen Patterns

### 12.1 Page structure

Every authenticated page composes:

```
<Page>           ← min-height 100dvh, --colour-bg background
  <AppNavBar />  ← glass nav (AppNavBar in features/shell/)
  <ScreenComponent />
</Page>
```

Login and Setup are unauthenticated dark-island pages — they compose their own
layout and do not use `<Page>` or `<AppNavBar>`. Their screens are full-bleed
dark (`--colour-dark-bg`).

### 12.2 AppNavBar — canonical link set

The authoritative nav link list is the `NAV_LINKS` constant in
`web/src/features/shell/AppNavBar/AppNavBar.tsx`. The final link set is:

| Link | Path | Condition |
|------|------|-----------|
| Search | `/` | All authenticated users (`end` match) |
| Library | `/library` | All authenticated users |
| Index | `/index` | All authenticated users |
| Settings | `/settings` | Admin role only |

Adding, removing, or renaming a nav link requires editing only `NAV_LINKS`.

### 12.3 Document-preview pattern

Documents are opened in-app via `DocumentPreviewScreen` exclusively — not via
an external `paperless_url` deep-link. The three screens that open documents:

| Screen | How it opens a document |
|--------|------------------------|
| `SearchPage` / `ResultsScreen` | "Preview" button on `SourceCard` calls `onPreview(id)` |
| `LibraryScreen` | `LibraryCard` click calls `setPreviewDocumentId(id)` |
| `IndexScreen` / `FailedDocumentsPanel` | "Preview" button calls `onOpen(id)` |

All three set a `previewDocumentId` state, then render `DocumentPreviewScreen`
as a full-bleed overlay in place of the normal screen content. The "Open in
Paperless" external link in `SourceCard` and inside `DocumentViewerChrome` is a
**supplementary** affordance, not the primary document-open mechanism.

### 12.4 Loading / empty / error state consistency

| State | Component | Notes |
|-------|-----------|-------|
| Loading | `<Spinner size="large" label="…" />` | `role="status"` for a11y |
| Empty / no results | `<EmptyState icon="search" message="…" />` | Always with an icon and message |
| Error | `<EmptyState icon="warning" message="…" />` wrapped in `role="alert"` div | Consistent across Search, Library, Index |
| Loading placeholder | `<Skeleton kind="…" />` | Specific to layout-sensitive placeholders |

### 12.5 Dark-island treatment

`LoginScreen` and `FirstRunSetupScreen` use the forced-dark token group
(`--colour-dark-*`). These tokens are theme-independent — identical in light and
dark mode. Other screens use the standard theme-aware tokens and adapt via
`themes.css` dark-mode overrides.

---

## 13. Implementation — Feature Components

The `features/` layer contains domain-aware components that compose library
primitives. Key feature groups:

### 13.1 `features/shell`

- `AppNavBar` — the authenticated application navigation bar. Composes `NavBar`,
  `Brand`, `UserMenu`. Uses the `NAV_LINKS` data-driven definition (§12.2).

### 13.2 `features/auth`

- `LoginScreen` — dark-island two-column sign-in screen.
- `FirstRunSetupScreen` — dark-island first-admin creation screen.
- `credentials.ts` — shared username/password validation rules.

### 13.3 `features/search`

- `IdleScreen` — hero with `RecentSearchStrip` and `IndexStatusFooter`.
- `LoadingScreen` — `PipelineStages` progress rail during a search.
- `ResultsScreen` — `AnswerCard` + `FilterControls` + `SourceList`.
- `NoResultsScreen`, `SearchErrorScreen`, `IndexNotReadyScreen` — error/empty states.
- `AnswerCard` — wraps `AnswerSurface` with citation-mark interaction.
- `SourceCard` — a single search result; "Preview" opens `DocumentPreviewScreen`.
- `SourceList` — ordered list of `SourceCard`s.
- `FilterControls` — filter rail (reused in Library).
- `CitationLink` — inline `[n]` citation chip that highlights the corresponding source.
- `QueryPlanSummary` — `Disclosure` wrapping the agentic query plan.
- `DocumentPreviewScreen` — the in-app PDF viewer overlay (see §12.3).

### 13.4 `features/library`

- `LibraryScreen` — browse grid/list with search, filters, sort and pager.
- `LibraryCard` — a single document card; click opens `DocumentPreviewScreen`.

### 13.5 `features/index`

- `IndexScreen` — ops dashboard: health hero, stat tiles, daemon cards, activity, failed docs.
- `IndexHealthHero` — coloured health verdict banner.
- `StatTile` — single-stat display (reuses `StatTile` primitive).
- `DaemonCard` — per-daemon status card.
- `ActivityRow` — one reconcile-cycle row in the activity list.
- `FailedDocumentsPanel` — failed-document list; "Preview" opens `DocumentPreviewScreen`.
- `RebuildIndexCard` — admin-only destructive rebuild section.

### 13.6 `features/settings`

- `SettingsScreen` — settings form with sections; uses `SettingsLayout`.
- `SettingsSection` — one section card (uses `SectionCard` primitive).
- `SecretField` — masked secret input with reveal toggle.
- `TestConnectionRow` — Paperless API connection test action row.
- `fieldModel.ts` — typed field definitions for every settings key.
- `useUnsavedSettings.ts` — dirty-tracking hook for the settings form.

### 13.7 `features/access`

- `UsersScreen` — user table with stat tiles and invite/edit/disable actions.
- `UserEditDrawer` — drawer modal for editing a user's role and status.
- `APIKeysScreen` — API key list with create/edit/revoke actions.
- `APIKeyCreatePanel`, `APIKeyEditPanel` — slide-in panels for key management.

### 13.8 `features/document`

- `DocumentMeta` — single-line correspondent · type · date meta row.
- `DocumentSnippet` — matched snippet text with highlight marks.

---

## 14. Implementation — Architecture Decisions

### 14.1 `features/.module.css` policy

See §11.2 for the full decision. The short version: `features/` CSS modules are
permitted for screen-level layout, but must reference tokens exclusively —
no hardcoded values.

### 14.2 No `pages/` CSS

Pages compose; they never style. A `pages/` file has no `.module.css`. If a page
needs visual treatment, the treatment belongs in a `features/` or `components/`
component.

### 14.3 Settings controls are primitives, not wrappers

`SettingsTextField` and `SettingsSelectField` are primitives in `components/`.
They are not wrappers around `Input`/`Select` — they implement the Apple-style
settings row control (label column + control column) defined in the Settings
handoff. The decision not to merge them with `Input`/`Select` is intentional:
the settings layout is structurally different from a standard form input, and
merging them via a `surface` variant would add complexity with no consumer benefit
until a third use-case appears (§1.9 — three call sites before extraction).

### 14.4 `StatTile` is the sole stat-display primitive

Prior to Wave 7, `StatCard` (features) and `StatTile` (primitives) co-existed.
Wave 7 consolidation removed `StatCard`; all stat displays use `StatTile`.

### 14.5 Badge family

Three badge components serve distinct semantic roles:

| Component | Role |
|-----------|------|
| `Badge` | Generic neutral or accent label chip |
| `RoleBadge` | Admin/member/readonly role indicator |
| `StatusBadge` | Account status, health state, count indicator |
| `ScopePill` | API key scope (read/write/mcp) |

This is a documented family, not duplication — each carries distinct semantic
colour tokens and renders different information shapes.

### 14.6 Authentication model

The frontend uses a signed `HttpOnly` session cookie (set by `POST /api/auth/login`).
The `SEARCH_API_KEY` never appears in the bundle. A `401` response from any
protected endpoint triggers `me`-query invalidation → `ProtectedRoute` redirect
to `/login`. API keys (REST/MCP) are a separate credential and cannot authenticate
the browser session.

### 14.7 `DocumentPreviewScreen` interface

The `source: SourceDocument` prop carries some search-specific fields (`snippet`,
`score`) that Library and Index do not have. These are passed as harmless defaults
(empty string / 0). The `paperless_url` field is `null` from Library (which has no
deep-link URL) and `''` from Index — `DocumentViewerChrome` omits the
"Open in Paperless" action for both falsy values.
