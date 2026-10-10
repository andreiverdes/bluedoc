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
