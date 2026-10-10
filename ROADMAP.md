# Source workspace roadmap

The Linux source workflow has been reviewed and approved. Stage 1 is now enabled on Linux, Windows, and macOS. Stages 2 and 3 remain planned work.

## Stage 1 — Open and keep a shared source

- [x] Add an address bar for opening an HTTP/HTTPS page independently of table links.
- [x] Add a pin button to keep the current page when moving between rows.
- [x] Continue searching the pinned page using the current row's selected search column.
- [x] Support back, forward, reload, redirects, and opening the current address in an external browser.
- [x] Keep row links usable: explicitly choosing a link replaces the current source.
- [x] Reset the source and pin when changing the document or sheet.
- [x] Check HTML and PDF, English/Russian, light/dark themes, unsaved edits, and invalid addresses.
- [x] Build an updated Linux archive for hands-on review.

Automated browser checks passed for HTML and PDF, pinning, row searches, redirects, reload, history, row links, document changes, drafts, localization, toolbar layout, and the dismissible no-match notice. Linux hands-on review is complete.

Acceptance: a table with no URL column can be checked against one shared page; switching rows preserves that page and updates the search. Existing per-row links continue to work.

## Stage 2 — Copy evidence into cells

- Select text in an HTML source and place it in a chosen editable cell.
- Show the destination clearly and preserve ordinary saving and confirmation.
- Handle dropdown values and read-only columns explicitly.
- Decide how to record the source URL for a value without modifying the original table unexpectedly.

Acceptance: the user can transfer a visible source value into the intended cell and review it before saving.

## Stage 3 — Organize review work

- Add row notes and review statuses such as verified, not found, discrepancy, and needs clarification.
- Store review metadata separately from the original table.
- Add filters and a review queue based on empty fields and statuses.
- Add an explicit web-search action using the selected field.

Acceptance: users can find unfinished work and understand why a row needs attention after reopening the application.

## Platform rollout — approved for Stage 1

The user approved the Linux workflow and requested the same source interface on Windows and macOS before proceeding to Stages 2 and 3.

- [x] Enable the shared interface on all three platforms.
- [x] Verify Windows/macOS adapters, pinning, row searches, toolbar layout, and the no-match notice in browser checks.
- [x] Update the English user documentation.
- Delivery: rebuild the Linux, Windows, and macOS portable archives from the same sources.
- Delivery: build and test the Windows EXE in GitHub Actions.
- Native validation: run settings/launcher checks and API editing/source tests on macOS in GitHub Actions.

