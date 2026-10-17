"""A Markdown plan (Claude Code's plan mode, or any plan written as Markdown) as a bluedoc `plan` doc.

    from_markdown(text, *, stem, project_dir, org, plan_file=None) -> dict

The first `#` heading is the title and the first paragraph the tldr; a plan without one (omp's start at `##`) is titled
from its file's name, else the doc's name (stem: what the gate names it, an omp `local://` plan's name), else the first
`##` heading that isn't a generic one like Context or Summary. Each `##` heading is a section. The steps block
comes from the numbered list under a heading named like Steps or Implementation, else the first top-level numbered
list; a plan without one makes each `##` section that isn't context, risks or verification a step. Backticked paths
become the files block (`edit` when the path exists under project_dir, else `add`). Everything else stays text,
tables and code, so no line of the plan is lost. `build.py from-md` writes the result and builds it.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

MAX_STEP_TITLE = 90
STEPS_HEADING = re.compile(r"\b(steps?|implementation|tasks?|plan|changes|work|order|phases?)\b", re.I)
KEEP_AS_SECTION = re.compile(r"\b(context|summary|overview|background|goals?|why|risks?|verification|verify|testing|"
                             r"tests?|questions?|files?|notes?|out of scope|non-goals?|rollback)\b", re.I)
NUMBERED = re.compile(r"^(\d+)[.)]\s+(.*)$")
BULLET = re.compile(r"^[-*+]\s+(.*)$")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE = re.compile(r"^(```+|~~~+)\s*([\w+#.-]*)")
TABLE_SEP = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
CODE_SPAN = re.compile(r"`([^`\s]+)`")
PATH_LIKE = re.compile(r"^(?:\.{0,2}/|~/)?[\w.@+-]+(?:/[\w.@+-]+)*(?:\.[A-Za-z0-9]{1,8}|/)$")
UNSAFE_LINK = re.compile(r"\[([^\]]+)\]\((?!https?:|mailto:|#|\.{0,2}/|[\w-]+\.)[^)]*\)", re.I)
# Names that say nothing about the plan: never its title. Matched whole, after deslugging; a dedupe suffix (plan-2) too.
GENERIC_TITLE = re.compile(r"(context|summary|overview|background|goals?|approach|introduction|intro|tl;?dr|problem|"
                           r"motivation|notes?|steps|(implementation )?plan|readme|inline [0-9a-f]{12})( \d+)?", re.I)


def slug(text: str, fallback: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48].strip("-")
    return s or fallback


def title_from_name(name: str) -> str | None:
    """A file or doc name as a title (hello-txt-plan -> Hello txt plan), or None when it is generic."""
    words = re.sub(r"[-_\s]+", " ", name).strip()
    if not words or GENERIC_TITLE.fullmatch(words):
        return None
    return words[0].upper() + words[1:]


def unique(base: str, used: set[str]) -> str:
    s, n = base, 2
    while s in used:
        s, n = f"{base}-{n}", n + 1
    used.add(s)
    return s


def inline(text: str) -> str:
    """Markdown the page's inline renderer takes: links with an unsafe scheme lose the link, keep their text."""
    return UNSAFE_LINK.sub(r"\1", text.strip())


# ---------- Markdown → a tree of headings and their lines ----------

def split_sections(lines: list[str]) -> tuple[str | None, list[str], list[tuple[str, list[str]]]]:
    """(title, lines before the first ##, [(## heading, its lines)]). Headings inside code fences don't count."""
    title, intro, sections, cur = None, [], [], None
    fence = None
    for line in lines:
        f = FENCE.match(line.strip())
        if f and (fence is None or line.strip().startswith(fence)):
            fence = None if fence else f.group(1)
        h = None if fence or f else HEADING.match(line)
        if h and len(h.group(1)) == 1 and title is None and cur is None and not any(x.strip() for x in intro):
            title = h.group(2)
        elif h and len(h.group(1)) <= 2:
            cur = (h.group(2), [])
            sections.append(cur)
        else:
            (cur[1] if cur else intro).append(line)
    return title, intro, sections


def blocks_of(lines: list[str]) -> list[dict]:
    """Text, table and code blocks, in order. ### headings become bold lines; nested list items keep their marker."""
    out: list[dict] = []
    para: list[str] = []

    def flush() -> None:
        md = "\n".join(para).strip()
        para.clear()
        if md:
            out.append({"type": "text", "md": inline(md)})

    i = 0
    while i < len(lines):
        raw = lines[i]
        s = raw.strip()
        f = FENCE.match(s)
        if f:
            flush()
            body, i = [], i + 1
            while i < len(lines) and not lines[i].strip().startswith(f.group(1)):
                body.append(lines[i])
                i += 1
            block = {"type": "code", "code": "\n".join(body)}
            if f.group(2):
                block["lang"] = f.group(2)
            out.append(block)
            i += 1
            continue
        if s.startswith("|") and i + 1 < len(lines) and TABLE_SEP.match(lines[i + 1].strip()):
            flush()
            cols = [c.strip() for c in s.strip("|").split("|")]
            rows, i = [], i + 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [inline(c) for c in lines[i].strip().strip("|").split("|")]
                rows.append((cells + [""] * len(cols))[:len(cols)])
                i += 1
            out.append({"type": "table", "columns": cols, "rows": rows})
            continue
        h = HEADING.match(s)
        if h:
            flush()
            para.append(f"**{h.group(2)}**")
            flush()
        elif not s:
            flush()
        else:
            # a nested list item keeps its marker at the left; a quote loses its '>'
            para.append(re.sub(r"^>\s?", "", s))
        i += 1
    flush()
    return out


def numbered_items(lines: list[str]) -> tuple[list[tuple[str, list[str]]], int, int] | None:
    """The first top-level numbered list: [(item text, its continuation lines)], start index, end index. Indented
    lines, blank lines and indented code fences continue an item; any other line at the left margin ends the list."""
    fence, start, items = None, None, []
    for i, line in enumerate(lines):
        f = FENCE.match(line.strip())
        if fence:
            if f and line.strip().startswith(fence):
                fence = None
            if items:
                items[-1][1].append(line)
            continue
        if f:
            if items and line[:1].isspace():
                fence = f.group(1)
                items[-1][1].append(line)
                continue
            if items:
                return items, start, i
            fence = f.group(1)   # a fence before the list: skip it whole
            continue
        m = NUMBERED.match(line) if not line[:1].isspace() else None
        if m:
            start = i if start is None else start
            items.append((m.group(2), []))
        elif items and (line[:1].isspace() or not line.strip()):
            items[-1][1].append(line)
        elif items:
            return items, start, i
    return (items, start, len(lines)) if items else None


def step_of(text: str, body: list[str], used: set[str]) -> dict:
    """One step: the item's first sentence (≤ 90 characters) as the title, everything else as md."""
    text = text.strip()
    title, rest = text, ""
    plain = re.sub(r"[*_`]", "", text)
    if len(plain) > MAX_STEP_TITLE:
        cut = re.search(r"^(.{20,%d}?[.:;])\s" % MAX_STEP_TITLE, text)
        if cut:
            title, rest = cut.group(1).rstrip(".:;"), text[cut.end():]
        else:
            words, title = text.split(), ""
            while words and len(title) + len(words[0]) + 1 <= MAX_STEP_TITLE - 1:
                title = f"{title} {words.pop(0)}".strip()
            title, rest = title + "…", "…" + " ".join(words)
    body_md = "\n".join(re.sub(r"^\s{2,}", "", l).rstrip() for l in body).strip()
    md = "\n\n".join(x for x in (rest.strip(), body_md) if x)
    step = {"id": unique(slug(re.sub(r"[*_`]", "", title), "step"), used), "title": inline(title), "status": "todo"}
    if md:
        step["md"] = inline(md)
    return step


# ---------- files ----------

def paths_in(text: str, project_dir: Path) -> list[str]:
    """Backticked file paths in text, as paths from project_dir, in order of first mention."""
    out: list[str] = []
    for m in CODE_SPAN.finditer(text):
        p = re.sub(r":\d+(?:-\d+)?$", "", m.group(1)).rstrip(".,;:")
        if "://" in p or p.startswith("-") or not PATH_LIKE.match(p) or ("/" not in p and "." not in p.strip(".")):
            continue
        q = Path(p).expanduser()
        if q.is_absolute():
            try:
                p = str(q.resolve().relative_to(project_dir.resolve()))
            except ValueError:
                pass
        p = p.removeprefix("./")
        if p and p not in out:
            out.append(p)
    return out


# ---------- the doc ----------

def from_markdown(text: str, *, stem: str, project_dir: Path, org: str, plan_file: str | None = None) -> dict:
    """The plan doc for a Markdown plan. stem names the doc (its id); plan_file is the Markdown's own path, listed as
    the one file when the plan names none."""
    lines = text.replace("\r\n", "\n").split("\n")
    title, intro, raw_sections = split_sections(lines)
    if not title:   # no `#` heading: the plan file's name, the doc's, a telling `##` heading, else the doc's name as is
        title = (title_from_name(Path(plan_file).stem) if plan_file else None) or title_from_name(stem) \
            or next((h for h, _ in raw_sections if not GENERIC_TITLE.fullmatch(h.strip())), None) \
            or stem.replace("-", " ").capitalize()

    used_sections: set[str] = set()
    used_steps: set[str] = set()
    sections: list[dict] = []
    steps: list[dict] = []
    steps_at: int | None = None   # the index in `sections` the steps section takes

    # the steps: the numbered list under a steps-like heading, else under any heading that isn't context, questions,
    # risks or verification, else before the first ##
    named = sorted((k for k, (h, _) in enumerate(raw_sections) if STEPS_HEADING.search(h)),
                   key=lambda k: bool(KEEP_AS_SECTION.search(raw_sections[k][0])))   # "Steps" before "Verification steps"
    others = [k for k, (h, _) in enumerate(raw_sections) if k not in named and not KEEP_AS_SECTION.search(h)]
    found = None
    for k in [*named, *others, "intro"]:
        hit = numbered_items(intro if k == "intro" else raw_sections[k][1])
        if hit and (k != "intro" or len(hit[0]) >= 2):
            found = (k, hit)
            break

    intro_lines = intro
    steps_section = None   # the raw section index whose numbered list became the steps
    if found:
        k, (items, a, b) = found
        steps = [step_of(t, body, used_steps) for t, body in items]
        if k == "intro":
            intro_lines = intro[:a] + intro[b:]
        else:
            h, body = raw_sections[k]
            raw_sections[k] = (h, body[:a] + body[b:])
            steps_section = k

    # tldr: the first paragraph before the first ##, else of the first section
    def first_para(ls: list[str]) -> tuple[str, list[str]]:
        joined, i = [], 0
        while i < len(ls) and not ls[i].strip():
            i += 1
        while i < len(ls) and ls[i].strip() and not HEADING.match(ls[i]) and not FENCE.match(ls[i].strip()) \
                and not ls[i].lstrip().startswith("|") and not NUMBERED.match(ls[i]) and not BULLET.match(ls[i]):
            joined.append(ls[i].strip())
            i += 1
        return " ".join(joined), ls[i:]

    tldr, intro_rest = first_para(intro_lines)
    if not tldr and raw_sections:
        tldr = first_para(raw_sections[0][1])[0]

    intro_blocks = blocks_of(intro_rest)
    if intro_blocks:
        sections.append({"id": unique("overview", used_sections), "title": "Overview", "blocks": intro_blocks})

    for k, (heading, body) in enumerate(raw_sections):
        blocks = blocks_of(body)
        if not found and not KEEP_AS_SECTION.search(heading):
            # no numbered list: this section is a step, and the steps section sits where the first one was
            if steps_at is None:
                steps_at = len(sections)
            md = "\n\n".join(x["md"] if x["type"] == "text" else (f"`{x['code'].strip()}`" if x["type"] == "code" else
                             "\n".join("- " + " · ".join(r) for r in x["rows"])) for x in blocks)
            steps.append(step_of(heading, md.split("\n") if md else [], used_steps))
            continue
        if not blocks and k != steps_section:
            continue   # a heading with nothing under it
        sec = {"id": unique(slug(heading, "section"), used_sections), "title": inline(heading), "blocks": blocks}
        if k == steps_section:
            sec["blocks"] = [{"type": "steps", "id": "plan", "title": "Implementation order", "items": steps}] + blocks
        sections.append(sec)

    if not steps:
        steps = [{"id": "implement", "title": "Implement the plan", "status": "todo",
                  "md": "The plan has no numbered steps; its sections above say what to do."}]
    if steps_section is None:
        steps_sec = {"id": unique("steps", used_sections), "title": "Steps",
                     "blocks": [{"type": "steps", "id": "plan", "title": "Implementation order", "items": steps}]}
        sections.insert(len(sections) if steps_at is None else steps_at, steps_sec)

    # files: every backticked path; each step lists the ones its own text names
    all_text = text
    paths = paths_in(all_text, project_dir)
    rows = []
    for st in steps:
        mine = [p for p in paths_in(f"{st['title']}\n{st.get('md', '')}", project_dir) if p in paths]
        if mine:
            st["files"] = mine
    first_step = {p: next((st["id"] for st in steps if p in st.get("files", [])), None) for p in paths}
    for p in paths:
        row = {"path": p, "action": "edit" if (project_dir / p).exists() else "add",
               "why": "Named in the plan." if (project_dir / p).exists() else "Named in the plan; not in the project yet."}
        if first_step[p]:
            row["step"] = first_step[p]
        rows.append(row)
    if not rows:
        rows = [{"path": plan_file or f"{stem}.md", "action": "add", "why": "The plan itself; it names no files."}]
    sections.append({"id": unique("files", used_sections), "title": "Files", "blocks": [{"type": "files", "title": "Files named in the plan", "items": rows}]})

    return {
        "id": slug(stem, "plan"),
        "title": inline(re.sub(r"^(plan|implementation plan)\s*[:—-]\s*", "", title, flags=re.I)) or "Plan",
        "meta": {"org": org, "kind": "Plan", "type": "plan", "rev": "1", "date": dt.date.today().isoformat()},
        "state": [{"label": "imported from a Markdown plan", "kind": "info"}],
        **({"tldr": inline(tldr)} if tldr else {}),
        "sections": sections,
    }
