# Website

A website's pages on a board, live from its local dev server: you comment on sections and elements, pick between versions of a section in place, and approve. Each comment tells the agent which source file to edit. App screens and dashboards you design from scratch are a [design](design.md).

![The acme-site board: the Home mockup at 1440 px with its hero's A/B/C versions over it, the Blog live from the dev server at 390 px with a pin on a post title, the Pages panel listing each section with its source hints, and the comment in the Comments panel](../media/website-hero.webp)

## Features

- **Live pages.** A page with a `url` on `localhost` shows the running dev server (Astro, Vite, Next, anything on a loopback port), hot reload included. The bluedoc server proxies it on a port of its own, so the site's links, modules and WebSocket work as they do in a browser tab, and injects the inspector that names what you point at. Only loopback URLs are accepted; the doc can't make the server fetch anything else.
- **Mockup pages.** A page without `url` is an HTML screen file, as on a design board: for a page that doesn't exist yet. A board can mix both.
- **Breakpoints.** The toolbar's **Desktop**, **Tablet** and **Mobile** (`board.breakpoints`, default 1440, 768 and 390 px) or a typed width resize every page; the icons in a page's title bar resize that page only. The page reflows at that width, since it really is that wide.
- **Full page.** Each page grows to its whole height on the board, as in Framer: nothing scrolls inside it, you pan and zoom over it. Its viewport stays the device's (900 px tall at 1440, 1024 at 768, 844 at 390; `board.viewport` changes them): the proxy rewrites the site's `vh`, `svh`, `dvh`, `vmin`… into multiples of that height and the inspector answers `innerHeight` with it, so a `100vh` hero is as tall as in a real window. Sticky and fixed elements stay at the top. The **Viewport** key next to it shows each page in a window of the device's height that scrolls, for sticky bars and scroll-driven effects; the choice is kept per doc. A page that keeps growing with its frame shows in Viewport with a warning. Present shows Viewport.
- **Snapshots of each revision.** A live page shows the site as it is now, so bluedoc keeps a static copy of it per revision and width, beside the doc in `<name>.bluedoc.snapshots/`. The copy has no scripts; its styles, images and fonts are inlined. The page records one when you send answers, request changes or approve, and when a page first loads at a revision that has none. An earlier revision (`?rev=`) shows its snapshot, labelled **Snapshot · rev N** in the page bar, never the live site posing as old; a revision without one says so. `serve.py snapshot` records them from the command line, and with `--url` from a checkout of an older revision on another port.
- **Compare side by side.** In compare (`?diff=`), each page shows the older revision to the left of the newer one, labelled **Rev N** and **Rev M**, at the same width and height; zoom and pan move both, and in Viewport they scroll together. A section whose content changed is outlined on both pages and marked in the Pages panel. The compare tray's **Single** key goes back to one page.
- **Open in new tab.** The toolbar's external-link key opens the selected page (else the one nearest the middle of the view) in a tab of its own, to try it for real: a live page at its dev server's own URL (hot reload, devtools), not the proxy; a mockup at its screen route. The same key in a page's title bar opens that page.
- **Sections with their source.** Each page lists its sections (`sel`, a CSS selector) with where they live in the repo: `src/content/site.ts#hero`, `src/components/Hero.astro`, `src/pages/index.astro:12`. The **Pages** panel shows them; a click takes the board to that section. With `board.root` the build checks that each file exists, each `#symbol` is named in it and each `:line` is inside it.
- **Comments that point at the code.** In Point mode, click anything in a page. The comment carries the element's selector, its section, the source hints and the width you were looking at, so the change request reads:

  ```text
  1. **Board › Blog › Subscribe › h2** (pin) `el:blog/#subscribe>div:nth-of-type(1)>h2:nth-of-type(1)` (cmv5njui2sleg)
     > Get the weekly note
     At: 1440 px wide
     Source: `src/components/Subscribe.astro`
     Change: Say what the weekly note holds: one workout, one member story.
  ```

  `build.py patch <doc> <key>` prints the page, the selector and the source hints: the section's when the selector names it, else every section's.
- **Versions in place.** A section tied to a brief decision gets a bracket in the board's margin beside the page, along the section, with **A B C** keys at its top, the recommendation starred; pointing at them outlines the section on the page. Each version is a short list of text or HTML edits the page applies inside that section, so you compare headlines or pricing tables in the real layout. In **Request changes** and **Approve website**, each pick comes with a `Shown in: Home › Hero · Source: …` line.
- **Approve website.** As on plans and designs: the agent waits for **Approve website** on the current revision, then writes the picks into the source. The approval covers the doc and any mockup files; the live site keeps changing under hot reload.
- **Isolation.** The proxy answers only requests addressed to itself (no DNS rebinding), drops bluedoc's key cookie before forwarding, and lets only this server's pages frame it. The live page runs on the proxy's origin, never the doc page's, so the site's scripts can't read the doc page or the key it keeps.

## How an agent makes one

```sh
npm run dev                                                                # the site's dev server, e.g. on :4321
python3 <skill>/scripts/build.py new website docs/site.bluedoc.json --title "Acme Fit site" --url http://localhost:4321/
python3 <skill>/scripts/build.py docs/site.bluedoc.json                    # validate, check the source hints
python3 <skill>/scripts/serve.py open docs/site.bluedoc.json               # the board, live
python3 <skill>/scripts/serve.py wait docs/site.bluedoc.json --kind any
```

The agent reads the site's pages and components, adds one artboard per page with its sections, selectors and source hints, and a brief decision for each section with versions. It answers each comment by editing the file the comment names, then records the revision with `build.py patch <doc> <key> --change "…" --resolves <comment id>`.

## Example and guide

- Example: [`acme-site.bluedoc.json`](../../skills/bluedoc/examples/acme-site.bluedoc.json), the Acme Fit marketing site: the home page as a hi-fi mockup ([`acme-site.design/home.html`](../../skills/bluedoc/examples/acme-site.design/home.html)) with hero and pricing versions, and the blog live from `localhost:4321/blog/`.
- Agent guide: [`skills/bluedoc/types/website.md`](../../skills/bluedoc/types/website.md). Fields: `### Website` in [`skills/bluedoc/references/schema.md`](../../skills/bluedoc/references/schema.md).
