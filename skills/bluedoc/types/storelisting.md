# Store listing

**When:** an app's listing on Google Play and the App Store: screenshots per device, the feature graphic, store text, locales. Screens of the app itself are a `design`. Save it as `docs/store/<app>.bluedoc.json`.

```sh
python3 <skill>/scripts/build.py new storelisting docs/store/<app>.bluedoc.json --title "…"
```

This writes the `listing` block, a board with one shot (`first`), an icon artboard and their files in `<app>.design/`. The page shows the board as two platform pages (Google Play, App Store) with a locale menu, and a left panel of tabs beside them: Text, Style, Colors and Checks. The right panel holds Brief, Comments and Revisions, as on every design page.

**Home card:** a column per platform with a dot per section, coloured by its worst check. **Required:** one `listing` block and one `board` of `shot`, `asset` and `icons` artboards. Fields: `build.py schema listing` and `build.py schema artboard`; sets and checks: `## Listing` in `references/schema.md`.

## Rules

- Never type a size, limit or count: they live in `assets/store-rules.json` (`sets`, `assets`, `text`). `build.py <doc>` checks the doc against it; a rule marked `unverified` only warns.
- One artboard is one shot; its `sets` list every set it renders in (`play/phone`, `appstore/iphone-69`, `appstore/iphone`, …). The page renders the one file at each set's frame.
- Captions are strings, not text in the file: `data-l10n="<shot>.title"` in the shot, the text in `listing.strings[locale]`. Mark machine translations in `listing.mt` (the page badges them **MT**).
- Build each shot in the shot kit: `grep -n -A30 '^## Store shots' <skill>/references/kits.md`. Colours and the caption font from the brand vars (`var(--brand-bg)`, `var(--bd-font-caption)`), never hard-coded.
- The screen-file rules of `types/design.md` hold: a body fragment, no network, `data-bd` on what a reader may point at, ≤ 24 KB.

## Real screenshots

Stores want the app in use: a shot shows a mock-up only until it has a capture or an upload (the page tags it **mock UI**).

- **Captures:** give the shot a `recipe` (`{route, appearance, settle, targets, locales}`) and `listing.capture` its `devices` and `apps`, then run `python3 <skill>/scripts/capture.py <doc>` (`--dry-run` first; `--shot/--target/--locale` narrow it). It drives `xcrun simctl`, `adb`/`emulator` and headless Chrome, writes `<stem>.listing/captures/`, then `build.py <doc>` records them. Exit 3 means a tool or device is missing: say which. A `web` capture fills only the sets of its aspect (a phone capture leaves tablets their mock-up). Fields: `build.py schema listing` (`capture`); targets: `### Uploads and captures` in `references/schema.md`.
- **Uploads:** the reader drops PNGs on the page; each is a draft until you run the `## Uploaded shots` command from the reply. Never write into `<stem>.listing/<platform>/` yourself.
- After a recipe change the capture is **stale**: re-shoot with the command `build.py` prints.

## Text, style and brand

The reader edits text and picks styles and the brand on the page; you record them.

- **Text edits** arrive under `## Text edits`, a `build.py patch <doc> field:<locale>/<group>/<field> --set <field>=<text>` command each: run them as given (it also clears an MT mark). Approve waits until you do. `patch` refuses a text over its store limit (the page lets the reader save one, in red): say so in your reply and offer a shorter one.
- **Style picks** arrive under `## Decisions` (`style-<platform>-<variant>-message`/`-layout`) with a `## Style picks` command that writes `listing.style.<platform>`. A pick marked *needs the agent* also needs its hook: `data-callout` (M3), the string `<shot>.proof` (M4), a video (M5), a photo with `credits` (L5).
- **Brand drafts** (the Colors tab's palette, the caption font at the top of Text) arrive under `## Brand drafts` with a `build.py patch <doc> brand:main --json …` command: run it as given. Approve waits until you do. The build warns on a contrast pair under 4.5:1 and on a font a PDF can't embed: say so in your reply.

## Variants and ads

- **Variants** (`listing.variants`): custom pages (`cpp`, `csl`) and A/B tests (`ppo`, `sle`), a tab each on their platform page. A variant changes only what its kind may: `swap` a shot for its own (`variantOf`), `order` a set, `style`, and `text` (CPP: promo and keywords; SLE: short and full, in its `locale` only; PPO: none, and never the watch). B treatments are L5 lifestyle unless they name a layout. Fields: `build.py schema listing` (`variants`); each kind's: `### Variants, preview and ads` in `references/schema.md`.
- **Ads:** Google Ads headlines and descriptions in `text.<locale>.play.adHeadlines`/`adDescriptions`; ad images and the App Store search asset as `asset` artboards (`play/ad-*`, `appstore/search`) or the reader's uploads. Give a CPP an `adGroup` for Apple Ads.
- Variant order drafts come with a `variant:<id>` command; run it as given. The **Store preview** is a mock: never quote it as how the store looks.

## Revisions

Edit a shot file in place, then `build.py patch <doc> artboard:<id> --change "…" --resolves <id>`. A text or caption comment has a `field:` key: `build.py patch <doc> field:es-ES/play/short --set short="…"`. Reorder and section drafts come with their `block:` command; run it as given.

A pin on a capture comes with the shot's capture, recipe and a `Re-shoot:` command. Fix the app, its demo data or the recipe, run that command, then `build.py patch <doc> artboard:<id> --change "Re-shot …" --resolves <id>`: the new capture joins the revision and compare shows the old one beside it. A pin on an upload has no recipe: ask for a new PNG, or add a recipe.

## Checks, translation, export and approval

- **Checks:** `build.py <doc>` runs every store rule (`### Checks` in `references/schema.md`). A store-rule error exits 1 but the page still draws; fix each one, or say why it stays.
- **Translation:** `build.py l10n <doc> --export es-ES` prints what to translate with each limit; translate within it, then `--import es-ES <file.json> --mt`. An over-limit string refuses the file: shorten it. Run the `## Accepted MT` command from a reply as given.
- **Export:** `build.py <doc> --listing out.zip` writes the fastlane folders; add `--format folders` for plain folders by store, language and device with a README (`--listing out.pdf` or `.html` for review). The reader uploads it with fastlane or by hand; never upload for them. Mention the `WARN --listing` lines.
- **Approval:** an approved listing is final at that rev: export it and hand over the ZIP. The reader can approve with unaccepted MT strings; say so.
