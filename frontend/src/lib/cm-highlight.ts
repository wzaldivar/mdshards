/*
 * Catppuccin syntax highlight for the markdown editor. Tag mappings follow the
 * upstream catppuccin/obsidian theme (sapphire bold, green italic, blue link,
 * teal external link / strong-em, maroon strikethrough, lavender headings,
 * pink/green/yellow/sapphire/mauve/red/peach for fenced-code-block tokens).
 *
 * Colors reference CSS custom properties so the @media prefers-color-scheme
 * swap in style.css flips Latte ↔ Mocha without us re-running anything here.
 */

import { HighlightStyle } from '@codemirror/language'
import { tags as t } from '@lezer/highlight'

export const catppuccinHighlight = HighlightStyle.define([
  // Markdown structural ----------------------------------------------------
  { tag: [t.heading1, t.heading2, t.heading3, t.heading4, t.heading5, t.heading6], color: 'var(--heading-color)', fontWeight: '700' },
  { tag: t.heading, color: 'var(--heading-color)', fontWeight: '700' },
  { tag: t.strong, color: 'var(--bold-color)', fontWeight: '700' },
  { tag: t.emphasis, color: 'var(--italic-color)', fontStyle: 'italic' },
  { tag: t.strikethrough, color: 'var(--strike-color)', textDecoration: 'line-through' },
  { tag: t.link, color: 'var(--link-color)', textDecoration: 'underline' },
  { tag: t.url, color: 'var(--link-external-color)' },
  { tag: t.quote, color: 'var(--blockquote-color)', fontStyle: 'italic' },
  { tag: t.contentSeparator, color: 'var(--hr-color)' },
  { tag: t.list, color: 'var(--list-marker-color)' },
  { tag: t.monospace, color: 'var(--code-property)', fontFamily: 'ui-monospace, monospace' },

  // Generic code-block tokens (the fenced-code parser inherits from this when
  // no language is set or the language parser falls through to defaults) -----
  { tag: t.keyword, color: 'var(--code-keyword)' },
  { tag: [t.string, t.special(t.string)], color: 'var(--code-string)' },
  { tag: [t.function(t.variableName), t.function(t.propertyName)], color: 'var(--code-function)' },
  { tag: [t.propertyName, t.attributeName], color: 'var(--code-property)' },
  { tag: [t.literal, t.number, t.bool, t.null], color: 'var(--code-value)' },
  { tag: [t.tagName, t.angleBracket], color: 'var(--code-tag)' },
  { tag: [t.atom, t.self], color: 'var(--code-important)' },
  { tag: t.comment, color: 'var(--code-comment)', fontStyle: 'italic' },
  { tag: [t.punctuation, t.bracket, t.brace, t.paren], color: 'var(--code-punctuation)' },
  { tag: t.variableName, color: 'var(--code-normal)' },
  { tag: t.typeName, color: 'var(--code-property)' },
  { tag: t.operator, color: 'var(--code-keyword)' },
  { tag: t.regexp, color: 'var(--code-string)' },
  { tag: t.escape, color: 'var(--code-important)' },
  { tag: t.meta, color: 'var(--code-comment)' },
  { tag: t.invalid, color: 'var(--danger-color)' },
])
