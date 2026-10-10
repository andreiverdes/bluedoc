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

## data-bd

Name every element a reader may comment on: `data-bd="submit"` (letters, digits, `-`, `_`), unique in the screen.
A comment on it arrives as `el:<artboard>/submit`; a repeated name gets its named ancestors (`el:login/form/submit`);
an unnamed element gets a CSS path from the nearest named one (`el:login/[data-bd="brand"]>h1:nth-of-type(1)`).
`build.py patch` prints the file and selector. Edit that element in place; don't rewrite the screen.

## Frameworks

A board names its own in `frameworks[]`:

- `{"id": "acme-web", "label": "Acme web CSS", "files": ["../web/dist/app.css"]}`: files relative to the doc, under
  a registered folder, `.css`/`.js`/`.mjs`. The server sends only declared files and the files their CSS names with
  `url()` (fonts, icons).
- `{"id": "heroui", "label": "Tailwind + HeroUI", "store": "heroui"}`: a copy the reader made once with
  `serve.py add-framework <name> [path|url]`, kept in `~/.bluedoc/frameworks/<name>/`. Presets (pinned URLs, sha256
  checked): `tailwind`, `heroui` (HeroUI's CSS classes, e.g. `button button--primary`, `card`, `input`, plus Tailwind
  utilities; no React components), `daisyui` (`btn btn-primary`, `card`… plus Tailwind utilities). Any path or URL
  works too; `--load FILE` picks the files screens load, `--source FILE --tailwind` compiles a Tailwind source in
  the frame.

When the project has its own framework (`package.json`, built CSS), declare those files. Else recommend: web and
desktop `heroui`, mobile `heroui`, watch and presentation the plain kit, with the `add-framework` command in the
brief item's detail.
A missing file or store copy renders the plain kit with a notice bar; the build warns with the path.
