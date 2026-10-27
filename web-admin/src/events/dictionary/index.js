// One module per locale for the friendly task-log vocabulary (field names,
// enumerated values, sentence templates). It is far larger than the UI chrome, so
// each language gets its own file instead of one table that keeps growing;
// ``en.js`` is the source and a new language is a copy of it with the same keys.
//
// Locales are keyed exactly like ``src/locales/*.json`` so the language picker and
// the event view can never disagree about which language is showing.

import { resolveLocale } from "../../i18n.js"
import de from "./de.js"
import en from "./en.js"
import fr from "./fr.js"
import ru from "./ru.js"
import zhCN from "./zh-CN.js"
import zhTW from "./zh-TW.js"

export const DICTIONARIES = {
  en,
  "zh-CN": zhCN,
  "zh-TW": zhTW,
  fr,
  de,
  ru,
}

/** The vocabulary for ``locale``; anything unknown falls back to English. */
export function dictionaryForLocale(locale) {
  const key = resolveLocale(locale) || "en"
  return { locale: key, ...(DICTIONARIES[key] || DICTIONARIES.en) }
}
