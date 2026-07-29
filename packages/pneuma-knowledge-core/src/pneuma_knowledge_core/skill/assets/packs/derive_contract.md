You are judging, for one owner of a personal knowledge workbench, whether their occupation produces a class of high-value information that is **clearly distinct from the generic people/topics families and stable in shape**, worth reserving a dedicated filing location for.

The input is the free text from the owner's registration profile: occupation, bio, and the interests list. The output is 0 to 3 additional topic families (each one path template shaped `memory/<family>/{slug}.md`), each with one line of reasoning grounded in the profile.

## Criteria

- **The empty set is the default.** Only propose a family when the occupation clearly implies a recurring, structurally stable class of information that generic people/topics cannot hold. If you cannot see that stable shape, or can only guess, return the empty set — a missing family can be added by later evidence, whereas a wrongly created empty family misleads filing for a long time.
- **Fewer rather than more.** Even if you can think of three, prefer to keep only the one or two you are most confident about. Thin and accurate is the product requirement.
- **Do not invent families that duplicate the built-in matrix.** projects, tech-notes, accounts, deals, products, research, design-work, campaigns, audiences, shifts and handoffs are already covered by the role × industry matrix; do not re-propose them just because a similar word appears in the bio. What you add is the occupation-specific shape the matrix does not cover.
- **Do not compete with the base families.** people (individuals), topics (work / life topics), profile (the owner's own picture and preferences) and materials (externalized bodies) are the generic foundation; do not set up a family for meaning these already hold.
- **Interests are not a filing requirement.** A hobby by itself does not produce a stable filing shape, unless the bio makes clear that it is a serious commitment (professionalized, producing output, worth tracking long term). "Likes photography" does not justify a `memory/photos/` family; "independent photographer, taking commercial work continuously" might.
- Name families in English kebab-case, consistent with the existing people/topics; each family's single line of reasoning must point back to concrete evidence in the profile, never generic filler.

## few-shot

**Example 1 (one family produced)**
occupation: "practising lawyer, mainly commercial contracts"; bio: "five years in independent practice, following the contracts and disputes of a dozen or so corporate clients"; interests: ["hiking", "wine"].
→ Output: `memory/matters/{slug}.md`, reasoning: "the owner tracks work in units of cases/matters over long periods; each matter has its own parties, timeline and state evolution, and generic topics cannot carry that stable case lifecycle." (The hiking and wine in interests produce no family.)

**Example 2 (empty set produced)**
occupation: "freelancer"; bio: "likes travelling around, picks up odd jobs now and then"; interests: ["travel", "coffee", "photography"].
→ Output: the empty set. Reasoning: the profile shows no stable, recurring information shape distinct from generic people/topics; travel and photography are interests rather than serious commitments, and the base families carry them adequately.
