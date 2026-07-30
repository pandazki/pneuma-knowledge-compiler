/**
 * The dictionary primitive. Every message file in this directory is one bundle declared
 * through `defineMessages`, which is what makes zh/en key parity a COMPILE-TIME fact:
 * `K` is inferred from both members, so a key present in one language and missing in the
 * other fails `tsc -b` (the runtime parity test in tests/i18n.test.mjs is the second net,
 * covering duplicate keys across bundles too).
 *
 * v1 ships zh + en only. Adding a third language is a matter of widening `Locale` and this
 * interface — no call site changes, because everything downstream goes through `t()`.
 */

export type Locale = "zh" | "en";

/** Declaration order = the order the header toggle walks. */
export const LOCALES: readonly Locale[] = ["zh", "en"];

export interface MessageBundle<K extends string> {
  zh: Record<K, string>;
  en: Record<K, string>;
}

export function defineMessages<K extends string>(bundle: MessageBundle<K>): MessageBundle<K> {
  return bundle;
}
