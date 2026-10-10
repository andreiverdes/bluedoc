# Other

**When:** a page that is not a plan, a review or a system doc: a status page, an incident report, an inventory, meeting notes, a comparison. `build.py new other <doc> --kind <Kind>` sets `meta.type: "other"`; `meta.kind` is your free label ("Status", "Report").

**Home card:** an icon and one big stat with its label, from the top-level `hero`. Without `hero` the card shows the `doc` icon and the section count.
**Required:** nothing; set `hero` whenever one number sums the doc up.

## Layout

Free. Start with a `tldr` that states the answer, then one section per question the reader brings, most urgent first. Pick blocks by the shape of the content: a table for 2+ items sharing 2+ attributes, a checklist for anything to do, decision items for anything to choose, `cards` for options side by side, callouts for risk.

## `hero`

| Field | Rule |
|---|---|
| `icon` | One of `chart`, `doc`, `flag`, `bolt`, `clock`, `users`, `bug`, `box`, `check`, `globe`, `lock`, `list`. |
| `value` | The stat, ≤ 8 characters: `"99.95%"`, `"12"`, `"3 d"`. |
| `label` | What it counts, ≤ 28 characters: `"uptime, last 30 days"`. |

Pick the number the reader would ask for first, and make the `tldr` agree with it. A docs page without a canvas uses the same field.

## Fragment

```json
{ "id": "acme-checkout-uptime", "title": "Checkout uptime, September",
  "meta": { "org": "Acme Corp", "kind": "Status", "type": "other", "rev": "1", "date": "2026-10-01" },
  "hero": { "icon": "chart", "value": "99.95%", "label": "uptime, last 30 days" },
  "tldr": "Checkout met its 99.9% target; the one 21-minute outage came from an expired PayCo certificate.",
  "sections": [ { "id": "outages", "title": "Outages", "lead": "One outage, 21 minutes, on 14 September.",
    "blocks": [ { "type": "table", "columns": ["Date", "Duration", "Cause"], "rows": [["14 Sep", "21 min", "Expired PayCo certificate"]] } ] } ] }
```

Field details: grep `## Document` and `## Blocks` in `references/schema.md`.
