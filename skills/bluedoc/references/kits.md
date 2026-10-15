# Design kits

A screen file (`<stem>.design/<artboard>.html`) is a body fragment. `serve.py` wraps it in `assets/kits/shell.html`
with the artboard's framework, its fidelity, the device's safe area, the theme and motion tokens and the inspector.
Never write `<html>`, `<head>`, network URLs or `<base>`/`<iframe>`/`<meta http-equiv>`. Grep the section you need.

## Plain kit

`framework: "plain"` (the default). Variables on `:root`: `--accent --accent-fg --bg --surface --fg --muted --border
--ok --warn --risk --radius --font --mono` (the board's theme tokens set them by name: token `accent` → `--accent`),
`--dur-fast --dur-base --dur-slow --ease` (zeroed under reduced motion), `--safe-top/right/bottom/left`,
`--safe-inset` (round watch: inset of the inscribed square), `--screen-w --screen-h`.

- Layout: `.screen` (fills the frame) `.safe` (pads by the safe area + 16px) `.round` (circle clip, watch-round;
  `.round.safe` pads by `--safe-inset`) `.stack` `.row` `.wrap` `.grid` `.cols-2/3/4` `.gap-1`…`.gap-6`
  (4 8 12 16 24 32 px) `.center` `.between` `.end` `.grow` `.p-2/4/6` `.scroll`
- Type: `.display` `.title` `.headline` `.body` `.caption` `.muted` `.label` `.mono` `.num`
- Components: `.btn` (+ `.primary .ghost .danger .block .sm .icon`) `.field` (input, textarea) `.select` `.check`
  `.switch` (checkbox) `.card` `.list > .item` `.divider` `.badge` (+ `.ok .warn .risk`) `.chip(.active)` `.avatar`
  `.topbar` `.tabbar > .tab(.active)` `.sidebar > .nav-item(.active)` `.progress > span[style="--v:.6"]`
  `.ring[style="--v:.72"]` (put a label inside) `.table` `.kpi > .label + .num` `.sheet` `.toast`

```html
<main class="screen safe stack gap-4" data-bd="login">
  <h1 class="title">Welcome back</h1>
  <input class="field" placeholder="Email" data-bd="email">
  <button class="btn primary block" data-bd="submit">Sign in</button>
</main>
```

## Wireframe

Loaded with the plain kit and for every `wireframe` or `sketch` artboard. Those fidelities grey the kit's colours.
`.wf-box[data-label="Map"]` (dashed box, label inside) `.wf-img` (box with a cross) `.wf-text[style="--lines:3"]`
(text bars) `.wf-line` `.wf-circle` `.wf-icon`. The toolbar's Sketch adds a hand font and a wobble over any screen:
don't write a second low-fi file.
Inside a `.slide` the placeholders grow to slide scale; wireframe and sketch slides dash the quote bar and the foot.

## Slides

Plain kit, for `device: "slide"` (1920 × 1080; another aspect ratio: `w` and `h`). One file per slide; speaker notes
go in the artboard's `notes`, not the slide. Colours come from the theme tokens, so the theme pills and Sketch work.
`.slide` (the canvas: column, 96/128 px padding; add `.center` for a title or closing slide) `.slide-kicker` (eyebrow)
`.slide-title` `.slide-body` (36 px text; its `ul`/`ol` get accent bullets) `.slide-cols` (equal columns, one per
child) `.slide-big` (a big number) `.slide-quote` `.slide-foot[data-n="2"]` (footer text, page number right).

```html
<section class="slide" data-bd="growth">
  <p class="slide-kicker">Q3 review</p>
  <h2 class="slide-title" data-bd="headline">Acme Fit doubled weekly actives</h2>
  <div class="slide-cols grow">
    <ul class="slide-body" data-bd="points"><li>Passkey sign-in: 2× faster</li><li>Streaks keep 61 % at week 4</li></ul>
    <div class="stack gap-2" data-bd="kpi"><span class="slide-big">2.1×</span><span class="muted">weekly actives</span></div>
  </div>
  <footer class="slide-foot" data-n="2" data-bd="foot">Acme · Q3 review</footer>
</section>
```

## HorizonUI

`framework: "horizon"` loads `react.js`, `horizon-ui.js` and `horizon-ui.css` before the fragment; the globals are
`React`, `ReactDOM` and `HorizonUI`. Mount into a `data-bd` element; put `data-bd` on plain elements you create,
since components may not forward it.

```html
<div id="root" data-bd="dashboard"></div>
<script>
const e = React.createElement, { HorizonProvider, Card, Button } = HorizonUI;
ReactDOM.createRoot(document.getElementById('root')).render(
  e(HorizonProvider, { theme: 'light' }, e('div', { 'data-bd': 'kpis' }, e(Card, null, 'Steps'))));
</script>
```

## HeroUI

`framework: "heroui"` loads HeroUI's CSS (`@heroui/styles` 3.2.6) and Tailwind's browser build (4.3.3), which
compiles the fragment's Tailwind utilities in the frame. Use HeroUI's classes, BEM style: `button button--primary`
(`--secondary --tertiary --outline --ghost --danger --sm --lg --full-width`), `card` with `card__header card__title
card__description card__content card__footer`, `input`, `label`, `chip chip--success`, `alert alert--warning`,
`tabs`, `switch`, `separator`, `avatar`, `link`. Its React components don't run. The plain kit isn't loaded (no
`screen`, `safe`): pad with the safe-area variables. The theme's `accent` token re-skins HeroUI's `--accent`; other
tokens reach Tailwind as `bg-[var(--bg)]`. `framework: "tailwind"` loads Tailwind's browser build alone.

```html
<main class="min-h-screen flex flex-col gap-4 px-4 pb-4 pt-[calc(var(--safe-top)+16px)]" data-bd="home">
  <div class="card" data-bd="today">
    <div class="card__header"><h2 class="card__title">Today</h2></div>
    <div class="card__content text-3xl font-semibold">8,412 steps</div>
  </div>
  <button class="button button--primary button--full-width" data-bd="start">Start workout</button>
</main>
```

## data-bd

Name every element a reader may comment on: `data-bd="submit"` (letters, digits, `-`, `_`), unique in the screen.
A comment on it arrives as `el:<artboard>/submit`; a repeated name gets its named ancestors (`el:login/form/submit`);
an unnamed element gets a CSS path from the nearest named one (`el:login/[data-bd="brand"]>h1:nth-of-type(1)`).
`build.py patch` prints the file and selector. Edit that element in place; don't rewrite the screen.

## Frameworks

A board names the ones it brings in `frameworks[]`:

- `{"id": "acme-web", "label": "Acme web CSS", "files": ["../web/dist/app.css"]}`: files relative to the doc, under
  a registered folder, `.css`/`.js`/`.mjs`. The server sends only declared files and the files their CSS names with
  `url()` (fonts, icons).
- `{"id": "acme-tw", "label": "Acme Tailwind", "store": "acme-tw"}`: a copy the reader made once with
  `serve.py add-framework <name> [path|url]`, kept in `~/.bluedoc/frameworks/<name>/`. Preset (pinned URLs, sha256
  checked): `daisyui` (`btn btn-primary`, `card`… plus Tailwind utilities). Any path or URL works too; `--load FILE`
  picks the files screens load, `--source FILE --tailwind` compiles a Tailwind source in the frame.

`plain`, `horizon`, `heroui` and `tailwind` ship with bluedoc: name them in `framework`, with no `frameworks[]` entry
and no download. A doc from before HeroUI shipped may still carry `{"id": "heroui", "store": "heroui"}`: it loads the
shipped copy.

When the project has its own framework (`package.json`, built CSS), declare those files. Else recommend: web,
desktop and mobile `heroui`, watch and presentation the plain kit.
A missing file or store copy renders the plain kit with a notice bar; the build warns with the path.

## Navigation

A link is `data-nav` on the element a tap follows; the element needs a unique `data-bd`. The board draws an arrow
from it, **Present** follows the tap. `data-nav-label` names the action for the arrow and Present's hints.

```html
<nav class="tabbar" data-bd="tabs">
  <button data-bd="tab-today" aria-current="page">Today</button>
  <button data-bd="tab-activity" data-nav="tab:activity">Activity</button>
</nav>
<button class="btn primary" data-bd="start" data-nav="workout" data-nav-label="Tap Start workout">Start</button>
<button data-bd="back" data-nav="back">Back</button>
<i hidden data-bd="swipe-left" data-nav="tab:activity" data-nav-label="Swipe left"></i>
```

Kinds: `workout` (push), `modal:`, `tab:` (tab bars; the current tab has none), `replace:` (sign-in, onboarding:
clears the stack), `back`. A gesture is a hidden element with a label. Set `board.entry` to the first screen; with
`"layout": "flow"` unplaced screens line up by depth. The build errors on an unknown target and warns on a screen
no entry reaches. A reader's link edit arrives as `link:<screen>/<name>` with its `patch` command.

## App icons

`build.py new design … --icons` adds `{"id": "app-icon", "device": "icons", "icon": {"bg": "#2563eb", "name": "…"}}`
and stub layers in `<stem>.design/app-icon/`. Draw on a 108 × 108 viewBox:

- `fg.svg` (required): the mark, transparent around it, inside the centre circle r 33 (54, 54); leave a margin.
- `mono.svg`: the same mark in one colour (themed and tinted icons).
- background: `icon.bg`, or `bg.svg` for a gradient; optional `ios-dark.svg`, `ios-tinted.svg`, `play.svg`.

Shapes and paths only: no `<text>` (convert to paths), `<image>` links, scripts or `<foreignObject>`. The board
shows every mask, variant and size; Export writes the iOS and Android PNG sets. A comment on a tile arrives as
`el:app-icon/<tile>`: `patch` prints the layers it is drawn from.

## Store shots

A storelisting's `shot` and `asset` screen files use the shot kit (`kits/shot.css`, `kits/shot-styles.css`,
`kits/shot.js`) on top of the plain kit. The page renders one file at each of its sets' frames, so size everything in
container units (`cqw`, `cqh`), never px.

```html
<main class="shot" data-bd="today">
  <h1 class="shot-cap" data-bd="cap" data-l10n="today.title">See your week at a glance</h1>
  <p class="shot-sub" data-l10n="today.sub">…</p>
  <div class="shot-frame" data-bd="frame">
    <div class="shot-ui" data-bd="ui"><main class="screen safe stack gap-4">…the app's UI, plain kit…</main></div>
  </div>
</main>
```

- `.shot-cap`, `.shot-sub`: the caption and its line; `data-l10n="<shot>.<name>"` fills them from `listing.strings` for
  the shown locale (else the default). The text in the file is only the fallback.
- `.shot-ui`: the app's UI at the set's UI viewport (412 × 915 Play phone, 440 × 956 iPhone 6.9", …), scaled into the
  frame with the row's safe area. A capture, when there is a fresh one, replaces it. Raw sets (watch) show only this.
- An asset (`device: "asset"`, feature graphic) is `.asset` > `.asset-title`, `.asset-sub`; keep text inside the
  guide the page draws.
- Brand tokens: `--brand-bg`, `--brand-surface`, `--brand-accent`, `--brand-text`, `--brand-caption`,
  `--bd-font-caption`, `--bd-weight-caption`. The plain kit's `--accent` stays the app's own.

## Shot styles

`listing.style` (`listing.style.<platform>` for one store's page, or a shot's `style`) picks a message style and a
layout style; `kits/shot-styles.css` draws both from the brand tokens, so a pick restyles every shot without new HTML.
The page's Style tab shows them with thumbnails (`kits/style-thumbs.svg`).

| Message | Caption |   | Layout | Image |
|---|---|---|---|---|
| `m1` | benefit headline, 3-6 words (default) | | `l1` | device frame (App Store) / UI card (Play) on brand colour (default) |
| `m2` | story sequence: numbered steps of one journey | | `l2` | panoramic: one band of art across shots 1-3 |
| `m3` | zoomed callout of the element marked `data-callout` | | `l3` | frameless full-bleed UI under a slim caption band |
| `m4` | social proof on shot 1, from the string `<shot>.proof` (App Store; Play: use-case first) | | `l4` | dark hero |
| `m5` | video-first: a play button over shot 1 | | `l5` | lifestyle: a person beside the UI; a photo is `<img class="shot-photo">`, its rights in the shot's `credits` |

Grades and sources: `assets/store-rules.json` `styles`. Text sits on brand colours in four pairs, which the build
checks at 4.5:1 (`store-rules.json` `brand.contrast`): caption and subtitle on `--brand-bg` (L1–L3), `--brand-bg` on
`--brand-surface` (L5) and on `--brand-caption` (M2's step chip). Keep text on other colours off the brand tokens.
