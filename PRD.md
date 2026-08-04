# PRD: Vocabulary Memorization Webapp

## Problem Statement

I read English books and regularly hit words I don't know. Today I break my
reading flow to look them up somewhere, and then I forget both the word and its
meaning almost immediately because nothing captures it or drills it back into my
memory. I want a single tool that lets me look a word up in one gesture while
reading, instantly see what it means, quietly remember that I didn't know it, and
later drill those exact words back into long-term memory using spaced repetition.

## Solution

A single-user, self-hosted webapp with two core modes:

1. **Lookup mode** - a focused search box. I type an unknown English word, get its
   full English definition (all senses) instantly, and the word is automatically
   added to my personal vocabulary list with a one-tap undo.
2. **Review mode** - a spaced-repetition flashcard flow (SM-2) that shows me the
   English word, lets me recall the meaning, reveals the definition, and schedules
   the card based on how well I knew it (Again / Hard / Good / Easy).

Supporting screens: a browse/manage list of all captured words and a stats
dashboard. The app runs in a Docker container on my homelab and is reached from my
phone or laptop over the browser via Tailscale.

## User Stories

1. As a reader, I want a single always-focused search box on the lookup screen, so that I can look up a word without any navigation friction.
2. As a reader, I want to type an English word and press enter, so that I immediately see its meaning.
3. As a reader, I want the lookup to show all senses of the word (definitions, part of speech, examples, synonyms), so that I can find the sense that matches my book.
4. As a reader, I want a looked-up word to be automatically added to my vocabulary list, so that I don't have to take a separate "save" action while reading.
5. As a reader, I want a quick undo/remove affordance right after a lookup, so that a word I actually knew doesn't clutter my review deck.
6. As a reader, I want repeated lookups of the same word to surface the existing entry rather than create a duplicate, so that my list stays clean.
7. As a reader, I want the app to count how many times I've looked a word up, so that frequently-forgotten words are visible.
8. As a reader, I want words to be matched case-insensitively and trimmed of whitespace, so that "Run", "run " and "run" are treated as the same entry.
9. As a reader, I want a clear "not found" message when a word has no dictionary entry, so that I know the lookup failed.
10. As a reader, I want words that return no dictionary entry to NOT be added to my list, so that typos and proper nouns don't create junk entries.
11. As a learner, I want a review mode that shows me words that are due today, so that I only study what spaced repetition says I should.
12. As a learner, I want each card to show the English word on the front, so that I practise recalling the meaning myself.
13. As a learner, I want to flip the card to reveal the definition, example and synonyms, so that I can check my recall.
14. As a learner, I want to grade my recall with Again / Hard / Good / Easy, so that the scheduler can space the card appropriately.
15. As a learner, I want the SM-2 algorithm to compute the next due date from my grade, so that difficult words come back sooner and easy ones later.
16. As a learner, I want newly looked-up words to be reviewable the same day, so that I can drill something I just learned.
17. As a learner, I want a configurable daily limit on how many new words enter review (default 20), so that a big reading session doesn't bury me in reviews later.
18. As a learner, I want to review all due cards in one session with no artificial cap, so that I decide when to stop.
19. As a learner, I want due cards ordered by due date ascending and then randomised within the same due bucket, so that the oldest-due words come first without a fixed rote order.
20. As a learner, I want to see how many cards are due today before I start, so that I know the size of my session.
21. As a user, I want a browse/manage screen listing all my words, so that I can see everything I've captured.
22. As a user, I want to search my word list, so that I can find a specific entry quickly.
23. As a user, I want to sort my word list by date added, due date, or SM-2 maturity, so that I can view it the way I need.
24. As a user, I want to edit an entry inline, so that I can fix or annotate a card.
25. As a user, I want to delete an entry, so that I can prune words I no longer care about.
26. As a user, I want a stats screen showing my total number of words, so that I can see the size of my vocabulary.
27. As a user, I want the stats screen to show how many cards are due today, so that I can gauge my review load.
28. As a user, I want a maturity breakdown (new / learning / mature), so that I can see how much of my vocabulary is well-established.
29. As a user, I want a bar chart of reviews done per day over the last 30 days, so that I can see my recent study activity.
30. As a user, I want an accuracy rate (% of Good + Easy grades), so that I can gauge how well I'm retaining words.
31. As a homelab user, I want the whole app to run as a single Docker container with SQLite on a mounted volume, so that deployment and persistence are trivial.
32. As a mobile user, I want the UI to be responsive and usable on my phone, so that I can look up and review words comfortably from either device.

## Implementation Decisions

### Architecture

- Single-user, self-hosted; no authentication (access is gated by Tailscale).
- One Docker container running FastAPI + Uvicorn.
- SQLite datastore on a mounted volume.
- Frontend is server-rendered Jinja templates + HTMX with plain responsive CSS.
  No JavaScript build step, no SPA.

### Modules

The system is decomposed into deep, independently testable modules behind the thin
FastAPI/HTMX layer:

- **scheduler (SM-2)** - a pure module with no I/O. Given a card's scheduling state
  (ease factor, interval, repetitions) and a grade (Again / Hard / Good / Easy),
  it returns the new scheduling state and next due date. This is the deepest and
  highest-value module: small interface, well-specified behaviour, rarely changes.
- **dictionary_client** - wraps the Free Dictionary API (dictionaryapi.dev). Input:
  a raw word. Output: a normalized lookup result containing all senses, or an
  explicit NotFound. Encapsulates HTTP, response parsing and the 404 case behind a
  simple interface.
- **vocab_store** - persistence boundary over SQLite. Responsibilities: create an
  entry (storing the full dictionary JSON payload plus SM-2 fields), dedupe on the
  normalized word, increment lookup count, query due cards, update scheduling state
  after a review, browse/search/sort, edit, delete, and append review-log rows.
- **stats** - a pure aggregation module. Input: entries and review-log rows. Output:
  total words, due-today count, maturity breakdown, reviews-per-day series, accuracy
  rate. No I/O; fed by data the store retrieves.

### Lookup behaviour

- Source: Free Dictionary API (EN→EN), no API key.
- The full API JSON payload is stored per entry; cards render the primary sense by
  default and can be expanded to show the rest.
- Words are normalized (lowercase, trimmed) for dedupe and matching.
- Auto-add on successful lookup with quick undo/remove.
- On 404 / not found: display "not found" and do NOT add the word.

### Scheduling behaviour

- Algorithm: SM-2 with four grades (Again / Hard / Good / Easy).
- Card front: the English word; back: definition, example, synonyms.
- New words become due the same day they are added.
- Configurable daily new-card limit (default 20).
- Review sessions include all due cards with no cap; ordering is due-date ascending,
  then randomised within the same due bucket.

### Maturity thresholds (for stats)

- **new** = never reviewed.
- **learning** = current interval < 21 days.
- **mature** = current interval >= 21 days.

### Data model

- **Entry**: normalized word, full dictionary JSON payload, added_at, lookup_count,
  SM-2 fields (ease factor, interval, repetitions, due date, state).
- **Review log**: reference to entry, graded_at timestamp, grade. Backs the
  reviews-per-day chart and the accuracy rate.

## Testing Decisions

Good tests here verify external, observable behaviour of a module through its public
interface, not internal implementation details. They should survive refactors of the
internals.

Modules to test:

- **scheduler (SM-2)** - primary test target. Pure function, so tests are simple and
  deterministic: given a starting state and a grade, assert the resulting ease,
  interval, repetitions and due date. Cover each grade, the first-review case, the
  lapse (Again) case that resets progress, and boundary intervals around the
  new/learning/mature thresholds.
- **vocab_store** - test against a temporary/in-memory SQLite database: dedupe on
  normalized word, lookup-count increment on repeat, due-card querying, scheduling
  update after a review, and browse/search/sort/edit/delete. Assert via the store's
  public methods.
- **stats** - pure aggregation: feed fixed sets of entries and review-log rows and
  assert the computed totals, maturity buckets, per-day series and accuracy rate.
- **dictionary_client** - test with mocked HTTP responses: a well-formed multi-sense
  payload parses into the normalized result, and a 404 maps to NotFound. No live
  network calls in tests.

There is no prior art in this fresh repo; these tests establish the pattern.

## Out of Scope

- Authentication / multi-user support.
- LLM-based lookup or explanations.
- German (EN→DE) or any non-English translation. EN→EN only for now.
- DeepL, LibreTranslate, or any translation provider.
- Source/book tagging; the vocabulary list is one flat global pile.
- Review streaks and gamification.
- In-app or automated backups (relying on existing homelab backup regime).
- Native mobile apps; the mobile experience is the responsive web UI.
- Capturing surrounding sentence/context (optional, deferred; not built now).

## Further Notes

- 500k-character caps and API keys are irrelevant given the free, keyless Free
  Dictionary API; if lookup quality or availability disappoints later, swapping the
  `dictionary_client` implementation is the only change needed.
- The `scheduler` and `stats` modules are intentionally pure so the interesting
  logic is testable without touching HTTP or the database.
- German translation (EN→DE via DeepL Free or self-hosted LibreTranslate) was
  discussed and explicitly deferred; the architecture keeps `dictionary_client`
  isolated so an additional translation source could be added later without
  reworking the rest of the app.
