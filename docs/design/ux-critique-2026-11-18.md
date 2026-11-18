# UX critique, 18 Nov 2026

A design critique of the board page (`index.html` and its partials, `app.css`, `board.js`), run with `/impeccable critique`, plus the decisions made about what to fix. The findings below describe the app as it was on 18 Nov 2026 (before the move to the TypeScript client); [Status](#status) says what has been done since. The short machine-readable snapshots of the runs are in `.impeccable/critique/`.

Method: two isolated assessments, a design review (A) and detector plus browser evidence (B). Mode: Operate. Product context: [PRODUCT.md](../../PRODUCT.md).

Limits of the review: the phone layout (`app.css:270-439`) was assessed from source only, because the browser tool could not resize the viewport to 390px. Dark theme was seen only on the login screen. The filter dropdown and empty states were read from templates, not exercised live.

## Score: 28/40 (Good)

| # | Heuristic | Score | Key issue |
|---|---|---|---|
| 1 | Visibility of system status | 3 | The board refreshes every 60s and on focus, but drawer edits save silently on `change` (`_panel.html:8-19, 57-77`) with no "Saved" cue |
| 2 | Match system and real world | 4 | "1 day late", "Due today", "Done 15 Nov" are accountant language |
| 3 | User control and freedom | 3 | Esc closes the drawer and delete is confirmed, but a mistyped due date takes effect at once with no undo |
| 4 | Consistency and standards | 3 | Today is omitted in the strip but shown on the card (`_summary.html:19`); date formats are mixed ("Tue 15 Dec", "13/11/2026", "15 Nov, 12:44 pm") |
| 5 | Error prevention | 2 | Nothing warns when a due date moves into the past or an overdue task is completed; phone swipe actions are easy to trigger by accident |
| 6 | Recognition rather than recall | 3 | "My tasks" does not say it also scopes the summary strip; there is no search |
| 7 | Flexibility and efficiency | 2 | No search, no keyboard way to move a card, no shortcut for New task; cards have `tabindex=0` but Enter only opens the drawer (`_card.html:4-5`) |
| 8 | Aesthetic and minimalist design | 3 | The strip takes about 90px to say "Nothing due" in two of three tiles; Done takes a full third of the width |
| 9 | Error recovery | 2 | Errors go to one fixed top-centre banner (`app.css:115-119`), not next to the field that failed |
| 10 | Help and documentation | 3 | `/help` exists and is linked, but on the phone it is buried under Me |

## Design specificity

Mostly interchangeable, with a few authored moments. It reads as a calm "Trello lite", which suits "no brand, keep it simple", but nothing visual says this is a deadline tool for a CA firm.

- Authored: the warm bone surfaces with a deep green accent (`app.css:5-19`), the deadline strip, the relative date labels, and the event thread that doubles as an audit log.
- Generic: one 14px system font, uniform white cards, three equal columns, pills for everything.
- Gap against the product: "Deadlines first" is only half expressed. A card a day late and a card due in February 2027 look the same apart from a small chip.

## What works

1. Deadline language and tone: "1 day late", "Today", "Done 15 Nov", with red, amber and green tones, make due status scannable (`_card.html:9`, `_summary.html`).
2. The thread as audit log: system events and comments are interleaved and de-emphasised (`app.css:245-250`), so history is complete without a separate screen.
3. A disciplined system: tokenised light and dark palettes, `:focus-visible` rings (`app.css:49-51`), `prefers-reduced-motion` honoured (`app.css:440`), and a considered phone layout with bottom tabs and 16px inputs.

## Detector results

13 warnings in the templates (`index.html` 8, `help.html` 5), every one reported at `line: 0`. The injected scan of the rendered live page found nothing (`[impeccable] No anti-patterns found`). Judgement on each, not yet verified against the CSS:

| File | Finding | Judgement |
|---|---|---|
| `index.html` | Low contrast, `#000000` on `#1e1e1b` and the hover variant on `#282824` | Probably false positive: unresolved theme variables |
| `index.html` | Low contrast, `#a3a199` on `#ffffff` at 2.6:1 | Worth checking: muted text on a light surface |
| `index.html` | 10px avatar initials (`{{ user.name \| initials }}`) | Real, and the design review found it independently (`app.css:100-104`) |
| `index.html` | Cramped padding on two `<dialog>` elements | Probably false positive: the inner form supplies the padding |
| `index.html` | `<h1>` "Me" followed by `<h3>` "Appearance" | Probably real, in the hidden dialog |
| `help.html` | Two 3px `border-left` side-tab accents | A taste call, not a bug |
| `help.html` | `#ecebe6` on `#ffffff` at 1.2:1 | Probably a border misread as text |
| `help.html` | `#ffffff` on `#d97706` at 3.2:1 | Plausibly real: white text on an amber badge |
| `help.html` | Line height 1.19x | Plausibly real |

## Priority issues and the decisions

Scope decision: **all five issues**, in the order below, **including `/help`** (the board, drawer and phone layout are all in scope). Start with issue 1.

### 1. [P1] Silent autosave in the drawer

Title, notes, due date, repeat and assignees post on `change` with `hx-swap="none"`. Nobody can tell whether a date change took effect, and a failed save only shows in a banner elsewhere. For compliance work a wrong deadline nobody noticed is the worst failure.

Fix: a small "Saving… / Saved" status in the panel header, inline errors beside the field, and a gentle confirmation when a due date moves into the past or an overdue task is completed. Also move the drawer's `autofocus` from Close (`_panel.html:12`) to the title. Command: `/impeccable harden`.

### 2. [P1] The strip duplicates the board and dilutes "deadlines first"

The same task appears in the strip and in its column, and the strip spends prime space on "Nothing due". Urgency is carried only by sort order and a small chip.

Fix: give overdue and due-today cards visual weight on the board (an edge, a bolder date line), make the due chip the strongest element on the card, and collapse the strip to one slim "All clear" row when counts are zero. Commands: `/impeccable layout`, then `/impeccable bolder`.

### 3. [P2] Chips and small text are too weak for a deadline tool

Chips are 11px with 1px/8px padding (`app.css:82-85`), red and amber differ mostly by colour, avatar initials are 10px, and `.thread .when` is 11px (`app.css:248`).

Fix: 12px chips at weight 600, a leading icon for late and today, avatar initials at least 11px, tabular figures for dates and counts, and the `help.html` line-height. Do not add web fonts. Commands: `/impeccable typeset`, then `/impeccable audit`.

### 4. [P2] Power-user ceiling and keyboard-only status changes

Titles hold client names and "Show older" is the only way to find history. Drag is the only way to change status from the board, which excludes keyboard users.

Fix: one client-side title filter in the top bar and a "Move to" action on the card, nothing heavier. This is new behaviour, so settle the minimum scope with `/impeccable shape` first, then build with `/impeccable harden`. Check it against [philosophy.md](../philosophy.md) before building.

### 5. [P2] Error, empty-state and filter-scope gaps

Errors surface in one global banner. "Nothing here." and "Nothing due." are flat. The default "My tasks" filter hides a colleague's overdue work from the person most responsible for deadlines.

Fix: inline errors, warmer and specific empty states, and a filter-independent overdue count so "My tasks" can never hide late work. Command: `/impeccable clarify`.

## Planned order

1. `/impeccable harden` for issue 1.
2. `/impeccable layout` and `/impeccable bolder` for issue 2.
3. `/impeccable typeset` for issue 3, including `help.html`.
4. `/impeccable shape` then `/impeccable harden` for issue 4.
5. `/impeccable clarify` for issue 5.
6. `/impeccable audit`: contrast for every chip colour pair in both themes, the `help.html` white-on-amber flag, the `h1` to `h3` skip in the Me dialog, and the phone layout viewed live (it was not in this review).
7. `/impeccable polish` as the final pass, including the `help.html` side-tab borders.

Re-run `/impeccable critique` afterwards to compare against 28/40.

## Persona red flags

- Alex (power user): no text search, no shortcut for New task (`index.html:65`), cards cannot be moved without a pointer, no bulk actions, the "Showing" filter cannot combine two people.
- Sam (accessibility): drag-only status change, 11px chips, red versus amber told apart mainly by colour, autosaved fields announce nothing to a screen reader, the banner is `role="alert"` with no focus handling, `.sum-go` is `opacity:0` until hover on desktop.
- Casey (mobile, from source only): swipe actions can fire while scrolling (`app.css:339`), Help and the user menu sit under Me (`app.css:286`), `#who` is capped at `max-width: 42vw` so the scope label can truncate, the date edit target is 40px.
- Meera (filing clerk working a client queue): cannot see all tasks for one client, and a completed recurring return silently creates the next one, mentioned only in the thread.
- Asha (admin and firm owner, who must never miss a deadline): "My tasks" hides colleagues' overdue work, there is no firm-wide overdue count independent of the filter, and "Manage people" is two clicks deep.

## Minor observations

- The page title is just "Tasks"; a count such as "(1) Tasks" would help an open tab.
- The Done heading "DONE (LAST 14 DAYS)" is long and noisy in uppercase.
- The drawer's `#1` task number sits far from the title (`app.css:228`).
- The due chip vanishes on Done tasks, so the original due date is only in the field.
- Desktop cards have no hover affordance beyond a border change and no visible drag cue.

## Questions the review raised

1. If the due date is the priority, why is it a small grey chip? What would a date-first card look like, with status secondary?
2. Is a full-width Done column worth a third of the screen when nobody opens it?
3. Anyone can edit anything and saves are silent. Where should the app slow the user down: a past due date, a delete, completing something overdue?

## Status

Implemented on the `feat/ux-critique-fixes` branch.

| Issue | State |
|---|---|
| 1. Silent autosave | Done: "Saving… / Saved ✓" in the drawer header, the server's reason under the field that failed, a confirmation before saving a past due date, and the drawer opens with focus on the panel instead of Close. **Not done on purpose:** a confirmation when completing an overdue task, because a native dialog on every completion is not gentle. The thread already records it. |
| 2. Strip duplicates the board | Done: the deadline chip leads every card and is solid for overdue and due-today, those cards are tinted, and the strip collapses to one "All clear" row when empty. |
| 3. Chips and small text | Done: 12px chips at weight 600 with an icon for late and due-today, 11px avatar initials, tabular figures for dates and counts, 12px thread times. `/help`: tip boxes use a plain border, pins use a darker amber, `kbd` keeps its leading. Two detector findings on `/help` remain (a `#ecebe6` on white pair that is probably the dark theme's text colour compared with the screenshot frame's white, and a 1.19x line height whose source I could not find). |
| 4. Search and keyboard | Done, smaller than "Move to": a title search box (`/` focuses it) that also finds older Done tasks, `[` and `]` to move a focused card, and `n` for New task. No phone search box and no "Move to" menu on desktop. |
| 5. Errors, empty states, filter scope | Done: errors sit beside the field (drawer) or stay in the banner until dismissed, warmer empty copy, and "N more overdue across the firm" when "Showing" hides other people's overdue work. |
| Audit items | Done: the `h1` to `h3` skip in Me is fixed, the phone targets were measured and raised, the tab bar marks the current tab. The phone layout was checked in a 390px frame. |

## Second critique: the notification surfaces (27/40)

Run on the bell, panel, messages, settings and Alerts tab after they were built.

| Issue | Decision |
|---|---|
| [P1] A notification could be silently lost: one `localStorage` marker shared by all tabs, advanced even when nothing was shown | Fixed: each tab remembers what it has shown in memory, a hidden tab waits, and desktop alerts use their own shared marker that only moves when an alert was sent or the page was in view |
| [P1] The message was bottom-right, faded after 15 seconds, and treated a due-date change like a comment | Fixed: top right under the bell, above the panel. Assignments, due-date changes, removals and deletions stay until dismissed (`sticky` in the API), the rest fade. They show the new date and a View button, and a burst becomes one "N changes" message |
| [P2] Settings: 18 radios, unclear wording, "Saved" out of sight | Kept all six kinds (per-kind choice was asked for). Modes are now "Pop up and bell / Bell only / Nothing", explained once at the top, "Saved ✓" beside the changed row, the dialog is named, and desktop alerts have their own row |
| [P2] Panel: no sticky tools, permanent setup strip, repeated titles | Fixed: sticky title and tools, scroll resets on open, the setup strip shows only when there is something to do, consecutive changes to a task are one row, first eight rows then "Show older" |
| [P2] Accessibility | Fixed: 44px targets on the phone, `aria-current` on the tab bar, row buttons name their task, `aria-expanded` on the bell, focus returns to the opener (or the next row after a dismiss), the badge cap is "99+" everywhere |
| Undo for Dismiss and Clear read | **Your decision: confirm Clear read only.** Single dismissals stay instant and permanent |
