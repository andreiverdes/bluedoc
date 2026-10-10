# Design

**When:** the user wants UI mockups, wireframes or screen designs for a watch, phone, tablet, desktop app or website, or slides for a presentation. A technical design doc is a `plan`. Save it as `docs/design/<topic>.bluedoc.json`.

```sh
python3 <skill>/scripts/build.py new design docs/design/<topic>.bluedoc.json --title "…" --target watch,mobile,web [--framework heroui]
```

This writes the brief, a board with one wireframe artboard per target, and one stub screen file each in `<topic>.design/<target>.html`; `presentation` writes three slides (`title`, `content`, `closing`). The page shows the board full width with the brief beside it, **Request changes** and **Approve design**, as on plans.

**Home card:** the board's outline. **Required:** exactly one `board` block with at least one artboard.

## Layout

| Section | Holds |
|---|---|
| Goal (`tldr`) | What the screens show, on which devices, and which picks the reader makes. |
| Brief (`brief`) | A `text` block: who uses it, on which device, what each screen must let them do. The checklist `brief` (`numbered: false`): decision item `framework` (ids: `plain`, `horizon`, `heroui`, `tailwind`, `frameworks[].id`), `theme` (ids = `themes[].id`), plus any open question (scope, navigation, motion). `sub` is "Recommend <option>: <reason>." |
| Screens | One `board` block: `targets`, `framework`, `frameworks`, `themes`, `motion`, `artboards`. |

## Pick the framework

1. **The project's own first.** Look in `package.json` (`tailwindcss`, `@heroui/*`, `daisyui`, `bootstrap`, `@mui/*`), the built CSS (`dist/*.css`, `public/*.css`) and the design tokens. Built CSS and JS files: declare them as `{"id", "label", "files": ["../../web/dist/app.css"]}`, paths from the doc's folder. A Tailwind source (`@import "tailwindcss"`, `@theme`) needs compiling: ask the reader to run `serve.py add-framework <name> <dir> --source app.css`, then use `{"id", "label", "store": "<name>"}`.
2. **No framework in the project:** recommend the default for the target and offer up to 2 others, each with why.

| Target | Default |
|---|---|
| web (sites, dashboards, CRMs) | `heroui` (Tailwind + HeroUI) |
| desktop app | `heroui` |
| mobile | `heroui`, touch sizes |
| watch | `plain` |
| presentation (slides) | `plain`, its slide classes |

`plain`, `horizon` (HorizonUI), `heroui` and `tailwind` (Tailwind utilities alone) ship with bluedoc: no download, no `frameworks` entry. Konsta UI, the usual mobile kit, ships only React, Vue and Svelte components, nothing a static screen can load, so mobile uses HeroUI too. HeroUI runs as its CSS classes (`button button--primary`, `card`, `input`) plus Tailwind utilities, compiled inside the frame; its React components don't run. `serve.py add-framework daisyui` is the other Tailwind option.

A framework that isn't on disk yet is still an option: put the `add-framework` command in the item's `detail`. Until the reader runs it, those screens show the plain kit with a notice and the build warns. Never fetch a framework yourself.

## Slides

`device: "slide"` (1920 × 1080; another ratio: `w`, `h`), one file per slide in kit classes (`## Slides` in `references/kits.md`), speaker notes in the artboard's `notes` (md, ≤ 2 KB). List the slides in deck order without `x`/`y`: the board stacks them in one column, and **Present** plays them top to bottom, with the notes under them.

## Screen files

- One file per artboard, `<stem>.design/<artboard id>.html`: a **body fragment**. No `<!doctype>`, `<html>`, `<head>`, `<body>`, `<base>`, `<iframe>`, `<object>`, `<embed>`, `<meta http-equiv>` or `<form action>`; the server adds the shell, kit, safe areas and tokens.
- **No network:** no `http:`, `https:` or `//` URLs in attributes, CSS or scripts. Images go beside the screen or in `data:` URIs; the build fails otherwise. Text may show a URL.
- **Name what a reader may point at:** `data-bd="submit"` on buttons, fields, cards, list rows, nav items. The reader's comments come back as `el:<artboard>/<name>`. Names are unique within a screen.
- **Links:** `data-nav="workout"` on what a tap follows (`modal:`, `tab:`, `replace:`, `back`), `data-nav-label="Tap Start"`; list start screens in `board.entry`. Grep `## Navigation` in kits.md.
- **App icon:** `new … --icons` adds `app-icon` (`device: "icons"`): draw `fg.svg` and `mono.svg` in `<stem>.design/app-icon/`. Grep `## App icons` in kits.md.
- **Use kit classes**, not long inline CSS: grep the section you need, e.g. `grep -n -A30 '^## Plain kit' <skill>/references/kits.md` (also `## Wireframe`, `## HorizonUI`, `## HeroUI`, `## data-bd`, `## Frameworks`). Colours come from the theme tokens as CSS variables (`var(--accent)`), so the theme pills re-skin every screen.
- ≤ 24 KB per file (a warning above). A screen that needs more is two artboards.
- Scripts may run (tabs, toggles, a carousel) inside the sandbox; they reach neither the page nor the network.

## Revisions

- **Rev A is wireframes:** `fidelity: "wireframe"`, kit wireframe classes, real labels. Write hi-fi (`fidelity: "hifi"`) after the reader picks the framework and theme.
- A variant: a new artboard with `variantOf: "<id>"` and its own file. The board places it right of its source.
- Without `x`/`y` the board lays artboards out left to right, and slides top to bottom in one column right of them; set both only to start a new row (e.g. `"x": 0, "y": 1000` for the web screens).
- **Edit screen files in place**, the lines the comment names; never rewrite a whole file for one change. Then record it: `build.py patch <doc> artboard:<id> --change "Sign in: passkey first." --resolves <comment id>`.
- Every build records each screen's text in the history file under `meta.rev`. Once the reader has seen a rev, never edit it in place: bump it (patch does). An edit to any screen file asks for approval again.

## Change requests

| Key | Do |
|---|---|
| `el:<id>/<path>` | `build.py patch <doc> <key>` prints the file and the selector (`[data-bd="submit"]`, or a CSS path). Edit that element, then patch the key with `--change`. |
| `artboard:<id>` | The whole screen, or a drawing over it: edit the file; or `--set device=…`, `--set fidelity=hifi`, `--set x=… --set y=…`. |
| `frame:<device>@<x>,<y>` | A requested new screen; the note holds the prompt and its labelled boxes. `build.py patch <doc> <key> --set id=settings --set title=Settings` adds the artboard and a stub file; write the screen there, keeping the boxes' labels as `data-bd` names. |
| `item:brief/<item>` | A pick or note on the brief: apply it to every screen it touches. |

Several patches for one reply: bump on the first, `--no-bump` on the rest. Send `<url>?diff=<previous rev>`: changed screens are marked and open side by side.

## Approval loop

As in `types/plan.md`: `serve.py open`, `wait --kind any`, revise on change requests, and build only the approved rev. The approval covers the JSON and every screen file: picks are binding; an unpicked item means your recommendation.

## Fragment

```json
{ "type": "board", "id": "main", "targets": ["mobile", "web"], "framework": "plain",
  "frameworks": [ { "id": "acme-web", "label": "Acme web CSS", "files": ["../../web/dist/app.css"] } ],
  "themes": [ { "id": "indigo", "label": "Indigo", "tokens": { "accent": "#4f46e5", "bg": "#f8fafc", "fg": "#0f172a" } } ],
  "artboards": [
    { "id": "login", "title": "Sign in", "device": "phone", "fidelity": "hifi" },
    { "id": "login-b", "title": "Sign in, passkey first", "device": "phone", "fidelity": "wireframe", "variantOf": "login" },
    { "id": "dashboard", "title": "Dashboard", "device": "browser", "fidelity": "hifi", "framework": "heroui", "x": 0, "y": 1000 } ] }
```

```html
<main class="screen safe stack gap-4" data-bd="login">
  <h1 class="title">Welcome back</h1>
  <input class="field" placeholder="Email" data-bd="email">
  <button class="btn primary block" data-bd="submit">Sign in</button>
</main>
```

Field details: grep `## Board`, `### Artboard`, `### Devices`, `### Screen files` in `references/schema.md`.
