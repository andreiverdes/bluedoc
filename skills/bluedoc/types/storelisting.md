# Store listing

**When:** an app's listing on Google Play and the App Store: screenshots per device, the feature graphic, store text, locales. Screens of the app itself are a `design`. Save it as `docs/store/<app>.bluedoc.json`.

```sh
python3 <skill>/scripts/build.py new storelisting docs/store/<app>.bluedoc.json --title "…"
```

This writes the `listing` block, a board with one shot (`first`), an icon artboard and their files in `<app>.design/`. The page shows the board as two platform pages (Google Play, App Store) with a locale menu, the Text tab beside them, and Style, Brand and Checks on the right.

**Home card:** each platform's sections with their shot counts. **Required:** one `listing` block and one `board` of `shot`, `asset` and `icons` artboards. The fields, sets and checks: `grep -n -A60 '^## Listing' <skill>/references/schema.md`.

## Rules

- Never type a size, limit or count: they live in `assets/store-rules.json` (`sets`, `assets`, `text`). `build.py <doc>` checks the doc against it; a rule marked `unverified` only warns.
- One artboard is one shot; its `sets` list every set it renders in (`play/phone`, `appstore/iphone-69`, `appstore/iphone`, …). The page renders the one file at each set's frame.
- Captions are strings, not text in the file: `data-l10n="<shot>.title"` in the shot, the text in `listing.strings[locale]`. Mark machine translations in `listing.mt` (the page badges them **MT**).
- Build each shot in the shot kit: `grep -n -A30 '^## Store shots' <skill>/references/kits.md`. Colours and the caption font from the brand vars (`var(--brand-bg)`, `var(--bd-font-caption)`), never hard-coded.
- The screen-file rules of `types/design.md` hold: a body fragment, no network, `data-bd` on what a reader may point at, ≤ 24 KB.

## Revisions

Edit a shot file in place, then `build.py patch <doc> artboard:<id> --change "…" --resolves <id>`. A text or caption comment has a `field:` key: `build.py patch <doc> field:es-ES/play/short --set short="…"`. Reorder and section drafts come with their `block:` command; run it as given.
