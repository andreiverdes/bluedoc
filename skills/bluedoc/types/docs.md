# Docs

**When:** explaining a system that exists or a change to it: architecture page, walkthrough ("how X works"), runbook, setup or onboarding guide, change proposal. Pass the kind to `build.py new docs <doc> --kind <Kind>`; `meta.kind` is the label above the title and on the home card.

**Home card:** the doc's root drawing, one flow animating on hover, the kind and the level count under it.
**Required** (an error on a new rev, a warning on older ones): a `canvas` block, or a top-level `hero` stat (`{icon, value, label}`, see `types/other.md`) when the doc has no drawing.

## Layout per kind

| `meta.kind` | Sections, in order |
|---|---|
| Architecture | TL;DR → canvas (the system) → terms → components (cards or table) → decisions (`decision` callouts) → known issues and risks |
| Walkthrough | TL;DR → canvas with one flow per scenario → step-by-step explanation per flow → edge cases |
| Runbook, Setup | TL;DR → prerequisites checklist → canvas (what you are building) → procedure checklists → verification → troubleshooting table → teardown checklist |
| Change | TL;DR → canvas with `state` (`proposed`, `removed`) → what changes (table) → rollout checklist → risks |

Anything you'd hand over for approval before implementing is a plan (`types/plan.md`), not a Change doc.

## Canvas rules

- **One canvas per system boundary.** Put depth in `children`, not in more canvases. ≤ 9 nodes per level, ≤ 3 levels.
- **Children explain the parent:** its real parts (modules, classes, threads, pins). `@left`/`@right`/`@top`/`@bottom` ports show where the parent's outer edges enter and leave.
- **One flow per question** ("How does a request get served?"). Each step is one edge and one sentence (actor, action, object), with an optional `payload` naming what moves. Every scope with edges has at least one flow.
- **Kinds carry meaning.** Edges: `data` payloads, `control` calls and starts, `async` queues and events, `power` hardware supply, `dep` build or runtime dependencies. Node shapes follow the node `kind` (grep `### Node` in the schema).
- **State is visible.** Use node `state` and doc `state` chips for anything not live or not verified; never draw a proposed part as if it exists.
- **A drawing explains; it does not prove.** Say so in doc `state` when a reader could take it for runtime evidence.
- Nodes must not overlap (the build checks). Labels ≤ 40 chars, edge labels ≤ 28; detail goes in `sub` or `md`, source anchors in `refs`.

## Checklists

Every procedure is a checklist. A row shows two lines: `text` is the action (imperative verb first, ≤ 90 characters), `sub` one line of why or what it unblocks. The open row holds the rest: `detail`, `code` for the command, `verify` for the observable result (required when failure is silent), `blocks` for tables or one nested checklist. Link items to the drawing with `refs` (`"<canvasId>/<nodeKey>"`) so readers jump from a step to the part it touches. Pre-tick (`done: true`) only steps you ran and verified.

## Fragment

```json
{ "type": "canvas", "id": "arch", "title": "Order path", "rootLabel": "acme-shop", "height": 520,
  "nodes": [
    { "id": "web", "label": "web", "kind": "client", "col": 0, "row": 0 },
    { "id": "api", "label": "orders-api", "sub": "Node 20", "col": 1, "row": 0, "refs": ["`services/orders-api/src/server.ts:12`"],
      "children": { "nodes": [ { "id": "router", "label": "router", "col": 0, "row": 0 }, { "id": "pricing", "label": "pricing", "kind": "function", "col": 1, "row": 0 } ],
                    "edges": [ { "from": "@left", "to": "router", "kind": "data" }, { "from": "router", "to": "pricing", "kind": "control", "label": "price(cart)" } ],
                    "flows": [ { "id": "price", "label": "Price a cart", "steps": [ { "edge": "@left->router", "label": "A request enters the router." }, { "edge": "router->pricing", "label": "The router calls pricing." } ] } ] } },
    { "id": "db", "label": "orders", "kind": "db", "col": 2, "row": 0 } ],
  "edges": [ { "from": "web", "to": "api", "kind": "data", "label": "POST /orders" }, { "from": "api", "to": "db", "kind": "data", "label": "INSERT order" } ],
  "flows": [ { "id": "order", "label": "Place an order", "steps": [
    { "edge": "web->api", "label": "The web app posts the cart.", "payload": "cart" },
    { "edge": "api->db", "label": "orders-api stores the order." } ] } ] }
```

Field details: grep `## Canvas`, `### Node`, `### Edge`, `### Flow`, `## Checklist` in `references/schema.md`.
