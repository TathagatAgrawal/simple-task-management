# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Three colleagues at a Chartered Accountant (CA) firm who trust each other and share one board. They work mostly in a desktop browser (Chrome or Edge, 1280px or wider) over Tailscale, and often on a phone through the same page's mobile layout (many add it to the Home Screen). There is no IT person; one flag, `is_admin`, lets someone add and remove people and manage updates. Their job is to keep client work moving and never miss a deadline.

## Product Purpose

A one-page task board where deadlines are the point. Each task has a title, notes, one or more assignees, a due date, an optional repeat schedule and a thread of updates. Three columns (To do, Doing, Done) hold cards moved by drag-and-drop on a computer, by swipe or press-and-hold on a phone, or from the keyboard, and a strip across the top shows what is overdue, due today and due in the next three days. Success is that the firm never misses a due date and the app keeps running for years with nobody technical looking after it.

## Positioning

Deliberately small: no projects, labels, priorities, sub-tasks or attachments. The due date is the priority, columns sort by due date, and every change is logged in the task's thread so the history is complete and trustworthy for compliance work. Notifications are kept to what a shared board needs: when someone else changes a task you are on or created, you hear about it, in a bell and, if you turn it on per device, as a phone or computer alert even when the board is closed. A general-purpose tracker could not truthfully claim that simplicity.

## Operating Context

Runs on one always-on Windows 10 PC in the office, reached over Tailscale only (task titles contain client names, so no public access). "Today" is computed in IST (`Asia/Kolkata`). Backups run nightly; migrations run at startup; admins can turn on a nightly automatic update, and `update.ps1` backs up and rolls back if a new version won't start. The page is a TypeScript client (Preact) built with Node into one committed file, so the PC never needs Node. It talks to a FastAPI JSON API under `/api` and learns of changes through Server-Sent Events. Phone and desktop alerts are sent through Apple, Google or Mozilla's push services, which needs only outbound internet from the PC. The user manual at `/help` is server-rendered.

## Capabilities and Constraints

- Statuses move freely; anyone can edit any task; only two roles (admin, not-admin).
- Every task change writes an `event` row in the same transaction. People are deactivated, never deleted.
- A person is notified of other people's changes to a task they are on or created, never their own. Each person chooses, for everything or per kind of change, Alert and bell, Bell only or Nothing.
- Few dependencies: the server's are FastAPI, Uvicorn, Jinja2, tzdata and pywebpush; the client's are Preact and Preact Signals. No CSS framework. See `docs/philosophy.md`.
- One responsive page (a `max-width: 640px` block in `app.css` with a bottom tab bar, plus the phone gestures in `gestures.ts`); light and dark themes.
- Destructive actions ask in the page's own dialog (never the browser's pop-up), and a move offers Undo for a few seconds.
- UI error messages are written for an accountant, not a developer.
- Deliberately not built: roles beyond admin, projects/labels/priorities, manual card ordering, attachments, email, and reminders for due dates.

## Brand Commitments

None. This is an internal tool with no logo, brand colors or voice rules. The one voice commitment is plain English that a non-technical accountant understands.

## Evidence on Hand

Developer docs in `docs/`, an illustrated user manual at `/help` (screenshots in `src/simple_task_management/static/help/`, retaken by `web/scripts/help-screenshots.mjs`, with a keyboard shortcuts table), a UX critique and design notes in `docs/design/`, and demo data via `seed-demo`. There are no testimonials, customers or metrics, and none should be invented.

## Product Principles

1. Keep it clean and simple: if the firm would not notice it missing, do not build it.
2. Deadlines first: dates are correct, visible and the main way tasks are ordered.
3. History is never lost: every change is recorded and attributable.
4. Nobody gets blocked: no workflow enforcement among trusted colleagues.
5. Runs unattended for years: fewer moving parts beat nicer features.
