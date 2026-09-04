/**
 * A document's frontmatter, prepared for a READER.
 *
 * Frontmatter is machine text and renders verbatim — that is the rule, and it is why the meta
 * strip prints keys and values as they stand on disk. Two spellings break it, and both belong
 * to one file: a CLOSED VOLUME (`<doc>/aNN.md`). Rollover stamps it with the open volume it
 * was cut out of under the legacy key `archived_from`, and with a `type` that falls back to
 * `archive` when the open volume declares none (core `compile/rollover.py`). Neither can move:
 * they are written into every user's git library already, so renaming them on disk would make
 * two spellings of one fact.
 *
 * But the console is the one place a HUMAN reads them as words, and a closed volume is not an
 * archive. The archive is where an owner puts what should leave every default retrieval
 * (`docs/design/archive.md`); a closed volume is live knowledge every lane reads — a work in
 * several volumes, the page itself being the open one. Rendering `ARCHIVED_FROM` on a volume
 * hands the reader the one word the design reserves for something else. So the two legacy
 * spellings are given their decided words HERE, at the render face, and nowhere else: no byte
 * on disk changes, no other key is touched, and the value keeps its own text.
 *
 * Import-free by design, so it transpiles standalone for its test.
 */

/** The legacy on-disk key a closed volume carries: the open volume it was cut out of. */
export const VOLUME_OF_KEY = "archived_from";

/** The `type` a closed volume falls back to when its open volume declares none of its own. */
export const LEGACY_VOLUME_TYPE = "archive";

/**
 * Frontmatter keys a component fills with a LIST written as a comma-separated string — the
 * `people` component's `identities` / `aliases`. One value per chip reads as the set it is,
 * where one long line reads as a sentence that happens to contain commas.
 */
export const CHIP_FRONTMATTER_KEYS = new Set(["identities", "aliases"]);

/** Keys whose value names another canonical document by path, so it can be a door. */
export const PATH_FRONTMATTER_KEYS = new Set([VOLUME_OF_KEY]);

/** The address key, printed apart from the facts: it says nothing about the subject. */
export const DOC_ID_KEY = "doc_id";

/** A chip list from either spelling: a comma-separated string, or an already-split list. */
export function frontmatterChips(value: unknown): string[] {
  const parts = Array.isArray(value)
    ? value
    : typeof value === "string"
      ? value.split(",")
      : [];
  return parts.map((part) => String(part).trim()).filter(Boolean);
}

/** A frontmatter value as one line: objects and lists collapse to their JSON form. */
export function frontmatterValue(value: unknown): string {
  return typeof value === "object" && value !== null ? JSON.stringify(value) : String(value);
}

/**
 * The same value for the pinned masthead, where the strip's JSON would be noise: a list reads
 * as its members. Objects still collapse to JSON — there is no shorter honest spelling.
 */
export function frontmatterInline(value: unknown): string {
  return Array.isArray(value) ? value.join(", ") : frontmatterValue(value);
}

/** How the meta strip is to draw one entry. */
export type FrontmatterFieldKind = "chips" | "path" | "plain";

/**
 * The two message keys this module can ask for, spelled as literals rather than imported:
 * the module stays import-free (so it transpiles standalone for its test), and `tsc` still
 * checks them against the dictionary at every call site that passes one to `t()`.
 */
export type FrontmatterLabelKey = "library.frontmatter.volumeOf";
export type FrontmatterValueKey = "library.frontmatter.closedVolume";

/** One frontmatter entry, resolved to what the page should show for it. */
export interface FrontmatterField {
  /** The raw key, unchanged — it is still the render key and the value's identity. */
  key: string;
  kind: FrontmatterFieldKind;
  /**
   * i18n key of the label to print INSTEAD of the raw key, or null when the key is its own
   * label. Only a legacy spelling earns one.
   */
  labelKey: FrontmatterLabelKey | null;
  /** kind `chips`: one value per chip. Empty for the other kinds. */
  chips: string[];
  /** kind `path` / `plain`: the value as one line. Empty for `chips`. */
  text: string;
  /** The value as it stands, for a surface that spells a list differently than the strip. */
  value: unknown;
  /**
   * i18n key that REPLACES `text` — a legacy value given its decided word — or null when the
   * value is the document's own data and renders verbatim.
   */
  textKey: FrontmatterValueKey | null;
}

/**
 * One entry, resolved. The two exceptions are named by key so that everything else keeps
 * falling through to the verbatim rendering it had before this module existed.
 */
export function frontmatterField(key: string, value: unknown): FrontmatterField {
  const chips = CHIP_FRONTMATTER_KEYS.has(key) ? frontmatterChips(value) : [];
  const labelKey: FrontmatterLabelKey | null =
    key === VOLUME_OF_KEY ? "library.frontmatter.volumeOf" : null;
  if (chips.length > 0) {
    return { key, kind: "chips", labelKey, chips, text: "", textKey: null, value };
  }
  const text = frontmatterValue(value);
  // `type: archive` is the volume's fallback and ONLY that: a page that declares its own type
  // carries that word instead, and any other value is the library's own data.
  const textKey: FrontmatterValueKey | null =
    key === "type" && text === LEGACY_VOLUME_TYPE ? "library.frontmatter.closedVolume" : null;
  const kind: FrontmatterFieldKind =
    PATH_FRONTMATTER_KEYS.has(key) && text.trim() ? "path" : "plain";
  return { key, kind, labelKey, chips: [], text, textKey, value };
}

/**
 * Every entry but `doc_id`, in the order the document wrote them. The address is left out
 * because the strip prints it apart, last and quietest.
 */
export function frontmatterFields(entries: [string, unknown][]): FrontmatterField[] {
  return entries
    .filter(([key]) => key !== DOC_ID_KEY)
    .map(([key, value]) => frontmatterField(key, value));
}
