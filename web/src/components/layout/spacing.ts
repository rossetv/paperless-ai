/**
 * The spacing scale shared by the layout primitives.
 *
 * Stack and Grid both expose a `gap` prop whose value maps 1:1 to the
 * `--spacing-N` tokens in tokens.css. The union lived twice — once as
 * `StackGap`, once as `GridGap` — so it is defined once here and both import
 * it (CODE_GUIDELINES §1.3). The matching CSS classes are in ./gap.module.css.
 */

/**
 * A step on the design-token spacing scale.
 * 1 = --spacing-1 (2px) … 14 = --spacing-14 (24px).
 */
export type SpacingScale = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14;
