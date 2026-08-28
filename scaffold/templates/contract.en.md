---
# Machine-readable part of the compile contract: skill identity + subject-family path
# templates. path_templates declares the library's directory layout, one entry per subject
# family in section 1 below. Editing this edits the library's skeleton (future compiles
# only; documents already in the canon are never rewritten).
skill_id: {{SKILL_ID}}
# Bump the version after rewriting the contract; registration takes effect under the new
# version — existing documents are not migrated, only future compiles are governed.
version: app-v1
path_templates:
  - memory/profile.md
---

# Compile contract: what this library remembers for you

<!-- This contract is your library's constitution: it teaches the compile model to judge —
     in YOUR domain, what deserves long-term memory, and on which page. The body enters the
     compile model's system prompt; HTML comments like this one are stripped at
     registration and exist only for you, the editor.

     Mechanism-level rules do not belong here — the framework enforces them: every canonical
     claim must carry a traceable [cite] reference, anchors are immutable once assigned,
     frozen archive volumes are read-only. The contract holds judgement only.

     Each section has guiding questions (HTML comments). Wherever you see TODO, read your
     own material first, then replace the marker with your own answer — do not imitate
     anyone's example: somebody else's domain judgement cannot know what counts as
     high-value versus noise in yours.

     The full practice behind this template (type → implied-usage derivation, subject
     granularity, admission criteria, the acceptance loop) lives in the framework
     repository's docs/guides/compile-contract.md — that document is the sole authority;
     this file is just the skeleton you fill in. -->

## 0. Whose library is this, and what for

<!-- Ask yourself: who owns this material? Six months from now, what will they come back
     to look up — what happened? who owns it? when? how did it change? Two or three
     sentences. -->

TODO: describe the owner and what they will come back to look up.

## 1. Subject families: what gets a page of its own

<!-- Declare your subject families — what evolves independently over the long term in your
     domain? One independently-evolving thing = one document; one basket for everything
     crushes the library. For each family answer: what does it collect? which path template
     in the frontmatter does it map to? when does a new subject deserve a new page (first
     appearance? only on recurrence?). Then make the frontmatter's path_templates match
     this section one-to-one.

     If you enable the `people` component over one of these families (engine.yaml's
     components / people_family), that family owes one more judgement: what counts as a way
     of addressing a person in your domain. The framework supplies the evidence — under each
     source it lists the terms the library keeps using for the people present — and requires
     each one to be decided in the round: record it among the page's `aliases` if the material
     confirms it names this person, or call decline_alias with a reason if it does not (that
     answer is this round's only; nothing is stored, and once the page is written the same
     term is not asked again). A title carrying a surname — what anyone in that seat would be
     called — is usually not an alias; a nickname often is. See
     docs/guides/compile-contract.md §7 for how to word it. -->

TODO: list your subject families — one line each: what it collects, its path template, when a new page opens.

## 2. What deserves admission

<!-- Ask one question at a time: will this piece of information ever be used for action,
     judgement, explanation, collaboration, or review? Yes — admit it; no — the verbatim
     source and search layers keep it (nothing is lost). One level deeper: each kind of
     knowledge implies its own future use — events imply a timeline, projects imply an
     ongoing progress record, collaborators imply an ever-growing working log. Do not
     preset a checklist; derive these uses from your data and let them evolve with it.
     Facts those uses depend on must be first-class citizens — an unadmitted fact cannot
     answer anything. The same reasoning applies to names: in everyday material one person
     or project carries nicknames, titles, abbreviations, codenames — a subject appearing
     under several names implies an alias record ("also known as X") on its page, or the
     subject's story splits across names and future retrieval cannot reunite it. -->

TODO: write the two or three most typical "worth it" and "not worth it" cases in your domain.

## 3. Evidence and calibers

<!-- In your material, whose words are binding? How do you tell relays, proposals, and
     model/tool output apart from decisions the owner actually made? (Relaying ≠ agreeing,
     proposing ≠ deciding, running ≠ accepted.) -->

TODO: write down where "it counts" ends and "just talk" begins in your domain.

## 4. Time

<!-- Relative time ("next Monday") must be anchored to the material's own occurrence date
     with the original wording kept. Resolve exact dates or spans only under an unambiguous
     calendar convention; otherwise retain the anchored expression instead of inventing
     endpoints. What other time calibers should the compiler watch for in your domain? -->

TODO: write your time calibers.

## 5. Privacy and non-admission

<!-- What must never enter long-term memory? (Passwords, tokens, ID numbers are framework
     red lines; what do you add — third parties' private matters? speculation about health
     or finances?) -->

TODO: write your non-admission list.
