# Store listing

An app's listing on Google Play and the App Store: the screenshots for every device, the icon and feature graphic, the store text in each locale, A/B tests, custom pages and ads. You check it against the stores' rules, comment on any shot or field, approve it, and get the fastlane folders to upload. The app's own screens are a [design](design.md).

![The acme-fit-listing App Store page in es-ES: the left panel's Text, Style, Colors and Checks tabs with Checks listing the store-rule warnings, the iPhone 6.9" and 6.3" sets of captured shots with Spanish captions, and Brief, Comments and Revisions on the right](../media/storelisting-hero.webp)

## Features

- **Two platform pages.** The toolbar's **Google Play | App Store** switch shows each store's page: a Shared section (icon, feature graphic, preview video), then a section per device row (watch, phone, tablet), each set with its count against the store's maximum (`8 / 8` on Play, `10 / 10` on the App Store), its sizes and whether it is required. Optional rows (TV, desktop, XR, car) sit as off strips that turn on with a draft.
- **One file, every set.** A shot is an HTML file in the shot kit: a caption, a device frame or card, and the app's UI. The page renders the same file at each set's size (Play phone 1080×1920, iPhone 6.9" 1320×2868, iPad 2064×2752, Wear OS, Apple Watch), so a change lands everywhere at once. Watch sets show the UI alone, as the stores require.
- **Real screenshots.** A shot shows a mock-up until it has a capture or an upload, and says so (**mock UI**, **capture**, **stale**, **upload**). `capture.py` runs each shot's recipe on the iOS and watchOS simulators, an Android or Wear OS emulator, or headless Chrome against a design doc's screens or a local dev server, with a 9:41 status bar. Drop a PNG on a set's slot to upload one; the page and the server check its size and alpha first.
- **Re-shoot from a comment.** A pin on a capture names the shot, its screen, the recipe and the `capture.py` command, so the agent fixes the app or the recipe and re-shoots; compare shows the old capture beside the new one.
- **Edit the text in place.** The left panel's **Text** tab lists the platform's store text and the captions for the locale, each editable with its counter (red past the store's limit). **Save** (⌘S) turns the changed fields into drafts, one undo step per Save (**Undo**, **Redo**, ⌘Z); **Request changes** sends each with the `build.py patch … field:…` command that writes it, and **Approve** waits until the agent has.
- **Styles, font and colors.** The **Style** tab picks a caption style (M1–M5) and a layout (L1–L5) per platform, each with its evidence; every shot re-renders live. The caption font, at the bottom of **Text**, comes from the fonts installed on your machine. The **Colors** tab sets the palette, by hand or extracted from an image, with a contrast check on each text pair.
- **Locales and MT.** The locale menu switches text, captions and captures; each entry counts missing and machine-translated strings. MT strings carry an **MT** badge until accepted; **Accept MT** sends the agent the command that clears them. A missing string falls back to the default locale and is flagged where it shows.
- **Store checks.** `build.py` checks the listing against a dated rules file with a source for each rule: text limits (Apple's keywords in bytes), set counts and required sets, exact sizes, alpha, Wear's UI-only rule, the Apple Watch's one size, locales that fall back, mock-up UI, contrast and variants. The left panel's **Checks** tab lists each page's findings and counts them on the tab; a rule marked unverified only warns. The right panel holds **Brief**, **Comments** and **Revisions**, as on every design page.
- **Variants and ads.** A tab per custom product page or A/B test (App Store CPP and PPO, Play custom listings and experiments) shows what it changes against the default page, with **Compare to default** side by side. The **Store preview** draws the product and search pages as a mock; the **Ads** view holds Google App campaign text and images and Apple Ads' variations and search asset.
- **Export to…** the fastlane ZIP (`supply` and `deliver` folders, every PNG re-encoded as 24-bit RGB with no alpha, variants and ads beside them, a `manifest.json` with each file's sha256, the MT strings and the fonts), a PDF or an HTML file for review.
- **Approve listing.** As on plans and designs. The dialog counts the unaccepted MT strings and the shots with mock-up UI, and names the variants it covers; the style picks travel under `## Decisions`. On the home page a listing's card shows a column per store with a dot per section, coloured by its worst check.

## How an agent makes one

```sh
python3 <skill>/scripts/build.py new storelisting docs/store/acme-fit.bluedoc.json --title "Acme Fit: store listing"
python3 <skill>/scripts/capture.py docs/store/acme-fit.bluedoc.json --dry-run      # then without --dry-run
python3 <skill>/scripts/build.py docs/store/acme-fit.bluedoc.json                  # store checks, record the revision
python3 <skill>/scripts/build.py l10n docs/store/acme-fit.bluedoc.json --export es-ES   # what to translate, with limits
python3 <skill>/scripts/serve.py open docs/store/acme-fit.bluedoc.json
python3 <skill>/scripts/build.py docs/store/acme-fit.bluedoc.json --listing acme-fit.zip   # after approval
```

The agent writes one shot file per screenshot, the text per store and locale, and the captions as strings; it never types a size or limit, since those live in `assets/store-rules.json`. It imports translations with `--import es-ES <file> --mt`, answers comments with `build.py patch`, and hands over the ZIP once you approve. It never uploads to a store for you.

## Example and guide

- Example: [`acme-fit-listing.bluedoc.json`](../../skills/bluedoc/examples/acme-fit-listing.bluedoc.json), the Acme Fit 3.0 listing at the store maximums: 10 shots per App Store set and 8 per Play set for watch, phone and tablet, in en-US and es-ES (Spanish machine-translated, two strings accepted), a Runners custom page, two lifestyle B treatments and ads. The phone shots Today, Activity, Workouts, Workout and Profile are captured from the [design example](../../skills/bluedoc/examples/acme-fit-design.bluedoc.json)'s screens; the rest show their mock-up. Its full export is about 150 PNGs for the default pages and 294 with the variants (40 MB). Shots in [`acme-fit-listing.design/`](../../skills/bluedoc/examples/acme-fit-listing.design/). Open it with `python3 <skill>/scripts/serve.py open skills/bluedoc/examples/acme-fit-listing.bluedoc.json`.
- Agent guide: [`skills/bluedoc/types/storelisting.md`](../../skills/bluedoc/types/storelisting.md). Fields, sets and checks: `## Listing` in [`skills/bluedoc/references/schema.md`](../../skills/bluedoc/references/schema.md); the shot kit: `## Store shots` in [`skills/bluedoc/references/kits.md`](../../skills/bluedoc/references/kits.md).
