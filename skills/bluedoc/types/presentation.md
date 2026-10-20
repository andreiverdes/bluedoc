# Presentation

**When:** the user wants slides: a deck, a talk, a review or pitch to present. Screens for an app or site are a `design`. Save it as `docs/decks/<topic>.bluedoc.json`.

```sh
python3 <skill>/scripts/build.py new presentation docs/decks/<topic>.bluedoc.json --title "…"
```

This writes the brief, a board of three slides (`title`, `content`, `closing`) and their stub files in `<topic>.design/<id>.html`. The page is a design page: the board, the brief in the right panel's Brief tab, **Present**, **Request changes** and **Approve presentation**.

**Home card:** the slides as 16:9 frames. **Required:** exactly one `board` block of at least one artboard, every one `device: "slide"`; a phone or any other device is an error (use a design doc for screens).

## Layout

| Section | Holds |
|---|---|
| Goal (`tldr`) | What the deck says, in how many slides, and which picks the reader makes. |
| Brief (`brief`) | A `text` block: audience, where they see it, the story in order. The checklist `brief` (`numbered: false`): `framework` (recommend `plain`), `theme` (ids = `themes[].id`), any open question. Every option's `md` says in 1–3 sentences how the slides come out with it and what it costs; the build fails without it. |
| Slides | One `board` block: `targets: ["presentation"]`, `framework`, `themes`, `artboards`. |

## Slides

- One artboard per slide, `device: "slide"` (1920 × 1080; another ratio: `w`, `h`), listed in deck order without `x`/`y`: the board stacks them in one column, and **Present** plays them top to bottom.
- Speaker notes go in the artboard's `notes` (md, ≤ 2 KB, an error above), never on the slide. Present shows them under it (`N`).
- To share the deck: `build.py <doc> --deck <out>.html` writes one HTML file that plays offline; `--deck <out>.pdf` a PDF, one 16:9 page per slide, no notes (needs Chrome or Chromium, found in the usual places or named by `BLUEDOC_CHROME`, as `serve.py snapshot` does). The reader's **Export to…** menu, in the toolbar and Present, downloads the same files; its **Include unapplied edits** puts the reader's pending text edits and deletions in them, which `--deck` never does (no reader state).
- A slide's element drafts (text edits and deletions from **Edit**) come under `## Board drafts` with `File: <stem>.design/<slide>.html` and a `patch el:` command each, as on designs: run them.
- One point per slide, readable from the back of the room. Build each in the plain kit's slide classes: `grep -n -A20 '^## Slides' <skill>/references/kits.md`. Colours from the theme tokens (`var(--accent)`).
- The screen-file rules of `types/design.md` hold: a body fragment, no network, `data-bd` on what a reader may point at, ≤ 24 KB.

## Revisions and approval

As in `types/design.md`: rev A is wireframes (`fidelity: "wireframe"`), hi-fi after the reader's picks; edit a slide file in place, then `build.py patch <doc> artboard:<id> --change "…" --resolves <comment id>`. A new slide: append an artboard with `build.py patch <doc> block:slides/0 --append '{…}'` and write its file. Approval covers the JSON and every slide file; any edit to a slide asks for approval again.
