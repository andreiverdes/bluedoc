# Other

Any page that is not a system doc, a plan, a review or a design: a status page, an incident report, an inventory, meeting notes, a comparison.

![The acme-status page: Acme shop status for week 41, with the TL;DR and the week-over-week numbers table](../media/other-hero.webp)

## Features

- **Free layout.** A TL;DR, then one section per question the reader brings. The same blocks as every type: text, tables, callouts, cards, code, terms, media, compare and checklists.
- **Hero stat.** One number sums the page up (`18,420` orders placed, `99.95%` uptime) with an icon and a label; the home page shows it on the doc's card.
- **Free kind label.** `meta.kind` names the page ("Status", "Report", "Inventory") above the title and on the home card.
- **Checklists and decisions.** Tasks are checklists whose ticks the local server keeps. Questions show options as pills with the agent's recommendation starred; **Accept recommended** takes every starred option, and **Send answers** sends picks, ticks and item comments to the agent.
- **Comments.** Point at any element, select a passage or draw on the page; notes collect in the **Comments** tab and go to the agent with **Request changes**. A comment the agent lists in a revision's `resolves` turns Resolved.
- **Revisions.** The **Revisions** tab lists each build of the page; compare two to see what changed since last week's update.

## How an agent makes one

```sh
python3 <skill>/scripts/build.py new other docs/status/week-41.bluedoc.json --title "Acme shop status, week 41" --kind Status
python3 <skill>/scripts/build.py docs/status/week-41.bluedoc.json        # validate, record the revision
python3 <skill>/scripts/serve.py open docs/status/week-41.bluedoc.json   # print the URL
```

The agent fills the skeleton's `<<…>>` fields, including the `hero` stat, between the first two commands.

## Example and guide

- Example: [`acme-status.bluedoc.json`](../../skills/bluedoc/examples/acme-status.bluedoc.json), the Acme shop's week 41 status: orders, uptime, one incident and the next week's tasks with one open decision. Built page: [`acme-status.html`](../examples/acme-status.html) (download it, then open it).
- Agent guide: [`skills/bluedoc/types/other.md`](../../skills/bluedoc/types/other.md).
