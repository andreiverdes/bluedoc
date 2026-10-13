# Website

**When:** the user wants to review or change a website's pages (a marketing site, landing page, docs site, blog) with you: comment on sections, pick between versions, approve. App screens and dashboards are a `design`. Save it as `docs/site.bluedoc.json` in the site's repo.

```sh
python3 <skill>/scripts/build.py new website docs/site.bluedoc.json --title "…" --url http://localhost:4321/
```

`--url` makes the home page **live**: the page shows the running dev server through the bluedoc server's proxy, so it shows the site's real code and hot reload. Only loopback URLs (`localhost`, `127.x.y.z`, `::1`) work. Without `--url` the home page is a mockup: a stub screen file in `<stem>.design/home.html`, written by the rules of `types/design.md`. `board.root` is set to the repo folder.

**Home card:** the pages with their sections. **Required:** exactly one `board` block of at least one artboard, every one `device: "page"`.

## Layout

| Section | Holds |
|---|---|
| Goal (`tldr`) | Which pages and sections the reader judges, and which picks they make. |
| Brief (`brief`) | A `text` block: who visits, what each page must get them to do, where the copy and layout live. The checklist `brief` (`numbered: false`): one decision item per section with versions. |
| Pages | One `board` block: `targets: ["web"]`, `root`, `breakpoints`, `artboards`. |

## Pages

- One artboard per page: `{id, title, device: "page", fidelity, url | (screen file), source, sections}`. A live page has `url` and no screen file. A mockup page needs one and may set `framework` like a design.
- `breakpoints` (default `[1440, 768, 390]`): the widths the reader switches every page to. Check that each section holds at each width. `viewport` (`{"1440": 900}`) overrides a width's design viewport height (default 900, 1024, 844).
- The board shows each page at its full height (**Full page**, the default), viewport heights pinned to the design viewport, so a `100vh` hero looks as in a real window. A height media query, or a height a script reads from somewhere else, still follows the tall frame; if a page keeps growing it falls back to **Viewport** (the scrolling frame). Sticky and fixed elements sit at the top in Full page; ask the reader to check them, and scroll effects, in Viewport.
- The reader can open a page in a tab of its own (the toolbar's or its title bar's external-link key): a live page at its `url`, a mockup at its screen route. Ask them to try links, forms and scroll there.
- `source`: where the page lives in the repo, as `path`, `path#symbol` or `path:line`, up to 3. With `root`, the build warns on a missing file, a symbol the file never names, a line past the end.
- `sections`: `{id, title, sel, source}` per section, in page order. `sel` is a CSS selector that finds the section in the page (`section.hero`, `#faq`); read the page's components to get it right. `source` names the copy first (`src/content/site.ts#hero`), then the component.
- Versions: a section with `decision: "<brief item id>"` and `variants: {<choice id>: [{sel?, text | html}]}`. Each edit replaces the text or the inner HTML of `sel` inside the section (the section itself without `sel`). The current version's list is `[]`. Offer 2 or 3. The page shows the pick in place, with A/B/C keys in a bracket beside the page, along the section.

## Change requests

| Key | Do |
|---|---|
| `el:<page>/<css path>` | The comment's `Source: …` line names its section's files and `At: <width> px wide` the width it was made at: edit there. `build.py patch <doc> <key>` prints the page (live URL or screen file), the selector and source hints (every section's when the selector alone can't tell the section). Then patch the key with `--change`. |
| `artboard:<page>` | The whole page: same as above, without a selector. |
| `item:brief/<item>` | A pick: write the chosen version into the source. The reply's `Shown in:` line names the section and its source. |
| `frame:page@<x>,<y>` | A requested new page: patch it with `--set id=… --set title=…`, then add `url` (a live route) or write its screen file. |

A live page has no screen file to diff: after editing the source, record the change with `build.py patch <doc> artboard:<page> --change "…" --resolves <id>` so the reader sees a new rev.

**Snapshots.** A live page always shows today's site, so each revision keeps a static snapshot of it in `<name>.bluedoc.snapshots/` (commit it with the doc). The page records one when the reader sends feedback or first views a revision. `?rev=` shows the snapshot, and `?diff=` puts the earlier page beside the current one with the changed sections outlined. If `patch` warns that the revision it replaces has no snapshot, run `serve.py snapshot <doc>` *before* editing the site for the next change. To back-fill an older revision, check it out on another port and run `serve.py snapshot <doc> --rev R --url http://localhost:<port>`.

## Approval loop

As in `types/design.md`. **Approve website** means: apply the picks to the source as approved. The approval covers the JSON and mockup screen files, not the live site's code, which keeps changing under hot reload.
