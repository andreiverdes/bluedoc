#!/usr/bin/env python3
"""Build a bluedoc HTML page from a JSON document.

Usage:
  build.py doc.json -o out.html     validate, lint, write HTML
  build.py doc.json --check         validate and lint only
  build.py doc.json -o out.html --strict   treat lint warnings as errors

Exit codes: 0 ok, 1 validation errors (or warnings with --strict), 2 usage/IO error.
Python 3.9+ standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "assets" / "template.html"

BLOCK_TYPES = {"text", "callout", "table", "code", "terms", "cards", "checklist", "canvas", "diff"}
FILE_STATUSES = {"added", "modified", "deleted", "renamed", "context"}
ITEM_BLOCK_TYPES = {"text", "callout", "table", "code", "terms", "cards", "checklist"}
MAX_TITLE, MAX_SUB = 90, 120   # characters that fit the collapsed checklist row
MAX_CHOICES, MAX_CHOICE_LABEL = 6, 28
PLACEHOLDER = re.compile(r"<<[^<>\n]{1,120}>>")
CALLOUT_KINDS = {"note", "caution", "warning", "risk", "decision"}
STATE_KINDS = {"ok", "warn", "risk", "info", "todo"}
NODE_KINDS = {"service", "process", "function", "store", "db", "cache", "stream", "queue", "device", "hardware",
              "actor", "user", "person", "client", "app", "ui", "external", "cloud", "note", "port"}
NODE_STATES = {"live", "local", "proposed", "unverified", "removed", "replaced"}
EDGE_KINDS = {"data", "control", "async", "power", "dep", "replaced"}
PORTS = {"@left", "@right", "@top", "@bottom"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

# Mechanical CRISP checks. They catch common slips; they do not replace the CRISP pass.
FILLER = ["very", "really", "just", "simply", "basically", "actually", "quite", "extremely", "incredibly",
          "robust", "seamless", "seamlessly", "leverage", "utilize", "powerful", "comprehensive", "delve",
          "crucial", "cutting-edge", "game-changer", "in order to", "it's worth noting", "it is worth noting",
          "please note", "note that", "feel free", "let me know", "as mentioned", "needless to say",
          "at the end of the day", "in conclusion", "to summarize", "in summary"]
VAGUE = ["soon", "usually", "often", "sometimes", "appropriate", "appropriately", "various", "a number of",
         "as needed", "if necessary", "etc", "and so on", "some time", "a while", "fast enough", "properly"]
NON_IMPERATIVE_START = {"the", "a", "an", "this", "it", "you", "we", "there", "make sure", "ensure that", "should"}
MAX_WORDS = 32


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, where: str, msg: str) -> None:
        self.errors.append(f"ERROR {where}: {msg}")

    def warn(self, where: str, msg: str) -> None:
        self.warnings.append(f"WARN  {where}: {msg}")


def lint_text(rep: Report, where: str, text: str | None, *, imperative: bool = False) -> None:
    if not text:
        return
    plain = re.sub(r"`[^`]*`", "", text)
    plain = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", plain)
    low = " " + plain.lower() + " "
    for w in FILLER:
        if re.search(r"(?<![\w-])" + re.escape(w) + r"(?![\w-])", low):
            rep.warn(where, f"filler/ceremony word '{w}' (CRISP rule 3/9)")
    for w in VAGUE:
        if re.search(r"(?<![\w-])" + re.escape(w) + r"(?![\w-])", low):
            rep.warn(where, f"vague word '{w}': use a number, name, condition, or 'unknown' (CRISP rule 6)")
    for sentence in re.split(r"(?<=[.!?])\s+|\n", plain):
        n = len(sentence.split())
        if n > MAX_WORDS:
            rep.warn(where, f"sentence has {n} words (> {MAX_WORDS}): split it")
    if imperative:
        first = plain.strip().lower()
        for bad in NON_IMPERATIVE_START:
            if first.startswith(bad + " "):
                rep.warn(where, f"checklist item starts with '{bad}': start with a verb (\"Run …\", \"Open …\")")
                break
        if first.endswith("?"):
            rep.warn(where, "checklist item is a question: write one action")


def need(rep: Report, where: str, obj: dict, *keys: str) -> bool:
    ok = True
    for k in keys:
        if k not in obj or obj[k] in (None, "", []):
            rep.err(where, f"missing required field '{k}'")
            ok = False
    return ok


def check_id(rep: Report, where: str, value) -> None:
    if not isinstance(value, str) or not ID_RE.match(value):
        rep.err(where, f"id {value!r} must match {ID_RE.pattern} (stable ids keep checklist progress)")


def validate_scope(rep: Report, where: str, scope: dict, depth: int, node_keys: set[str], prefix: str,
                   is_child: bool) -> None:
    nodes = scope.get("nodes") or []
    edges = scope.get("edges") or []
    flows = scope.get("flows") or []
    if not nodes:
        rep.err(where, "scope has no nodes")
    if len(nodes) > 12:
        rep.warn(where, f"{len(nodes)} nodes in one level: group them into systems with children (aim for <= 9)")
    if depth > 4:
        rep.warn(where, "nesting deeper than 4 levels is hard to navigate")
    ids: set[str] = set()
    for i, n in enumerate(nodes):
        w = f"{where}.nodes[{i}]"
        if not need(rep, w, n, "id", "label"):
            continue
        check_id(rep, w, n["id"])
        if n["id"] in ids:
            rep.err(w, f"duplicate node id '{n['id']}' in this scope")
        ids.add(n["id"])
        key = f"{prefix}{n['id']}"
        node_keys.add(key)
        if n.get("kind") and n["kind"] not in NODE_KINDS:
            rep.err(w, f"kind '{n['kind']}' not in {sorted(NODE_KINDS)}")
        if n.get("state") and n["state"] not in NODE_STATES:
            rep.err(w, f"state '{n['state']}' not in {sorted(NODE_STATES)}")
        has_pos = ("x" in n and "y" in n) or ("col" in n or "row" in n)
        if not has_pos:
            rep.err(w, "node needs a position: x and y (centre), or col and row")
        if len(n.get("label", "")) > 40:
            rep.warn(w, "label longer than 40 characters: move detail to 'sub' or 'md'")
        lint_text(rep, w + ".md", n.get("md"))
        if n.get("children"):
            validate_scope(rep, w + ".children", n["children"], depth + 1, node_keys, key + "/", True)
    # overlap check (centre-based boxes)
    boxes = []
    for n in nodes:
        if "id" not in n:
            continue
        sys_ = bool(n.get("children", {}).get("nodes"))
        w_ = n.get("w") or (240 if sys_ else 180)
        h_ = n.get("h") or (140 if sys_ else 80)
        cx = n["x"] if "x" in n else n.get("col", 0) * 250
        cy = n["y"] if "y" in n else n.get("row", 0) * 160
        boxes.append((n["id"], cx - w_ / 2, cy - h_ / 2, cx + w_ / 2, cy + h_ / 2))
    for a in range(len(boxes)):
        for b in range(a + 1, len(boxes)):
            A, B = boxes[a], boxes[b]
            if A[1] < B[3] and B[1] < A[3] and A[2] < B[4] and B[2] < A[4]:
                rep.err(where, f"nodes '{A[0]}' and '{B[0]}' overlap: move one (col/row grid is 250 x 160)")
    edge_ids: set[str] = set()
    for i, e in enumerate(edges):
        w = f"{where}.edges[{i}]"
        if not need(rep, w, e, "from", "to"):
            continue
        for end in ("from", "to"):
            v = e[end]
            if v in PORTS:
                if not is_child:
                    rep.err(w, f"{end}='{v}': ports exist only inside a node's children")
            elif v not in ids:
                rep.err(w, f"{end}='{v}' is not a node id in this scope")
        eid = e.get("id") or f"{e['from']}->{e['to']}"
        if eid in edge_ids:
            rep.err(w, f"duplicate edge id '{eid}': give parallel edges explicit ids")
        edge_ids.add(eid)
        if e.get("kind") and e["kind"] not in EDGE_KINDS:
            rep.err(w, f"kind '{e['kind']}' not in {sorted(EDGE_KINDS)}")
        if e.get("label") and len(e["label"]) > 28:
            rep.warn(w, "edge label longer than 28 characters")
    for i, f in enumerate(flows):
        w = f"{where}.flows[{i}]"
        if not need(rep, w, f, "id", "label", "steps"):
            continue
        for j, st in enumerate(f.get("steps") or []):
            sw = f"{w}.steps[{j}]"
            refs = st.get("edges") or ([st["edge"]] if st.get("edge") else [])
            if not refs:
                rep.err(sw, "step needs 'edge' or 'edges'")
            for r in refs:
                if r not in edge_ids:
                    rep.err(sw, f"edge '{r}' not found in this scope (edge id defaults to 'from->to')")
            if not st.get("label"):
                rep.warn(sw, "step has no label: the caption bar will be empty")
            lint_text(rep, sw + ".label", st.get("label"))


def diff_lines(f: dict) -> tuple[set[int], set[int]]:
    """Line numbers a file's hunks display, per side (old, new)."""
    old: set[int] = set()
    new: set[int] = set()
    for h in f.get("hunks") or []:
        o, n = h.get("old", 1), h.get("new", 1)
        for l in h.get("lines") or []:
            if l[:1] != "+":
                old.add(o)
                o += 1
            if l[:1] != "-":
                new.add(n)
                n += 1
    return old, new


def validate_diff(rep: Report, where: str, b: dict) -> dict[str, tuple[set[int], set[int]]]:
    files: dict[str, tuple[set[int], set[int]]] = {}
    for fi, f in enumerate(b.get("files") or []):
        fw = f"{where}.files[{fi}]"
        if not need(rep, fw, f, "path"):
            continue
        if f["path"] in files:
            rep.err(fw, f"duplicate file '{f['path']}'")
        if f.get("status", "modified") not in FILE_STATUSES:
            rep.err(fw, f"status '{f.get('status')}' not in {sorted(FILE_STATUSES)}")
        for hi, h in enumerate(f.get("hunks") or []):
            if not isinstance(h.get("lines"), list) or not all(isinstance(l, str) and l[:1] in ("+", "-", " ") for l in h["lines"]):
                rep.err(f"{fw}.hunks[{hi}]", "every line must be a string starting with '+', '-' or ' '")
        files[f["path"]] = diff_lines(f)
    return files


def validate(doc: dict) -> Report:
    rep = Report()
    need(rep, "doc", doc, "id", "title", "sections")
    if "id" in doc:
        check_id(rep, "doc", doc["id"])
    lint_text(rep, "doc.subtitle", doc.get("subtitle"))
    lint_text(rep, "doc.tldr", doc.get("tldr"))
    for i, s in enumerate(doc.get("state") or []):
        if s.get("kind") and s["kind"] not in STATE_KINDS:
            rep.err(f"doc.state[{i}]", f"kind '{s['kind']}' not in {sorted(STATE_KINDS)}")
    sec_ids: set[str] = set()
    titles: set[str] = set()
    checklist_ids: set[str] = set()
    canvas_nodes: dict[str, set[str]] = {}
    refs_to_check: list[tuple[str, str]] = []
    checklist_items: dict[str, set[str]] = {}
    diffs: dict[str, dict[str, tuple[set[int], set[int]]]] = {}
    comments_to_check: list[tuple[str, str, dict]] = []

    def check_block(bw: str, b: dict, depth: int) -> None:
        """depth 0 = section block, 1 = inside a checklist item, 2 = inside a nested checklist's item."""
        t = b.get("type")
        if t not in BLOCK_TYPES:
            rep.err(bw, f"type {t!r} not in {sorted(BLOCK_TYPES)}")
            return
        if depth and t not in ITEM_BLOCK_TYPES:
            rep.err(bw, f"type {t!r} can't sit inside a checklist item; use one of {sorted(ITEM_BLOCK_TYPES)}")
            return
        if depth >= 2 and t == "checklist":
            rep.err(bw, "checklists nest one level only: a nested checklist's items can't hold another checklist")
            return
        if t in ("text", "callout"):
            need(rep, bw, b, "md")
            lint_text(rep, bw, b.get("md"))
            if t == "callout" and b.get("kind", "note") not in CALLOUT_KINDS:
                rep.err(bw, f"callout kind '{b.get('kind')}' not in {sorted(CALLOUT_KINDS)}")
        elif t == "table":
            if need(rep, bw, b, "columns", "rows"):
                for ri, row in enumerate(b["rows"]):
                    if len(row) != len(b["columns"]):
                        rep.err(f"{bw}.rows[{ri}]", f"{len(row)} cells, {len(b['columns'])} columns")
        elif t == "code":
            need(rep, bw, b, "code")
        elif t == "terms":
            for ti, it in enumerate(b.get("items") or []):
                need(rep, f"{bw}.items[{ti}]", it, "term", "md")
                lint_text(rep, f"{bw}.items[{ti}]", it.get("md"))
        elif t == "cards":
            for ci, it in enumerate(b.get("items") or []):
                need(rep, f"{bw}.items[{ci}]", it, "title", "md")
                lint_text(rep, f"{bw}.items[{ci}]", it.get("md"))
        elif t == "checklist":
            if not need(rep, bw, b, "id", "title", "items"):
                return
            check_id(rep, bw, b["id"])
            if b["id"] in checklist_ids:
                rep.err(bw, f"duplicate checklist id '{b['id']}'")
            checklist_ids.add(b["id"])
            checklist_items[b["id"]] = {it.get("id") for it in b["items"]}
            item_ids: set[str] = set()
            for ii, it in enumerate(b["items"]):
                iw = f"{bw}.items[{ii}]"
                if not need(rep, iw, it, "id", "text"):
                    continue
                check_id(rep, iw, it["id"])
                if it["id"] in item_ids:
                    rep.err(iw, f"duplicate item id '{it['id']}'")
                item_ids.add(it["id"])
                choices = it.get("choices")
                # a decision item's title names the question or finding, so it need not be imperative
                lint_text(rep, iw + ".text", it.get("text"), imperative=not choices)
                if choices is not None:
                    if not isinstance(choices, list) or not 2 <= len(choices) <= MAX_CHOICES:
                        rep.err(iw + ".choices", f"give 2 to {MAX_CHOICES} options, each {{id, label}}")
                    else:
                        cids: set[str] = set()
                        for ci, c in enumerate(choices):
                            cw = f"{iw}.choices[{ci}]"
                            if not isinstance(c, dict) or not need(rep, cw, c, "id", "label"):
                                continue
                            check_id(rep, cw, c["id"])
                            if c["id"] in cids:
                                rep.err(cw, f"duplicate option id '{c['id']}'")
                            cids.add(c["id"])
                            if len(re.sub(r"`", "", c["label"])) > MAX_CHOICE_LABEL:
                                rep.warn(cw, f"option label over {MAX_CHOICE_LABEL} characters: options are pills; put the explanation in 'md'")
                            lint_text(rep, cw + ".md", c.get("md"))
                        for field in ("recommend", "choice"):
                            if it.get(field) is not None and it[field] not in cids:
                                rep.err(f"{iw}.{field}", f"'{it[field]}' is not one of the option ids {sorted(cids)}")
                    if it.get("done"):
                        rep.err(iw + ".done", "a decision item is answered by 'choice', not 'done'")
                elif it.get("recommend") or it.get("choice"):
                    rep.err(iw, "'recommend' and 'choice' need 'choices'")
                title = re.sub(r"`([^`]*)`", r"\1", it.get("text", ""))
                if len(title) > MAX_TITLE:
                    rep.warn(iw + ".text", f"{len(title)} characters: the collapsed row shows one line (about {MAX_TITLE}); "
                             "keep the action there and move the rest to 'sub', 'detail' or 'blocks'")
                if "\n" in (it.get("sub") or "") or len(it.get("sub") or "") > MAX_SUB:
                    rep.warn(iw + ".sub", f"the subtitle shows one line (about {MAX_SUB} characters); move the rest to 'detail'")
                lint_text(rep, iw + ".sub", it.get("sub"))
                lint_text(rep, iw + ".detail", it.get("detail"))
                for r in it.get("refs") or []:
                    refs_to_check.append((iw, r))
                for ki, kb in enumerate(it.get("blocks") or []):
                    check_block(f"{iw}.blocks[{ki}]", kb, depth + 1)
        elif t == "canvas":
            if not need(rep, bw, b, "id", "title", "nodes"):
                return
            check_id(rep, bw, b["id"])
            if b["id"] in canvas_nodes:
                rep.err(bw, f"duplicate canvas id '{b['id']}'")
            keys: set[str] = set()
            validate_scope(rep, bw, b, 0, keys, "", False)
            canvas_nodes[b["id"]] = keys
            lint_text(rep, bw + ".caption", b.get("caption"))
        elif t == "diff":
            if not need(rep, bw, b, "id", "title", "files"):
                return
            check_id(rep, bw, b["id"])
            if b["id"] in diffs:
                rep.err(bw, f"duplicate diff id '{b['id']}'")
            diffs[b["id"]] = validate_diff(rep, bw, b)
            lint_text(rep, bw + ".note", b.get("note"))
            for ci, c in enumerate(b.get("comments") or []):
                comments_to_check.append((f"{bw}.comments[{ci}]", b["id"], c))

    for si, sec in enumerate(doc.get("sections") or []):
        sw = f"sections[{si}]"
        if not need(rep, sw, sec, "id", "title"):
            continue
        check_id(rep, sw, sec["id"])
        if sec["id"] in sec_ids:
            rep.err(sw, f"duplicate section id '{sec['id']}'")
        sec_ids.add(sec["id"])
        if sec["title"].lower() in titles:
            rep.warn(sw, f"duplicate section title '{sec['title']}'")
        titles.add(sec["title"].lower())
        lint_text(rep, sw + ".lead", sec.get("lead"))
        blocks = sec.get("blocks") or []
        if not blocks:
            rep.warn(sw, "section has no blocks")
        for bi, b in enumerate(blocks):
            check_block(f"{sw}.blocks[{bi}]", b, 0)

    for where, r in refs_to_check:
        cid, _, key = r.partition("/")
        if cid not in canvas_nodes:
            rep.err(where, f"ref '{r}': no canvas '{cid}'")
        elif key not in canvas_nodes[cid] and not any(k.split("/")[-1] == key for k in canvas_nodes[cid]):
            rep.err(where, f"ref '{r}': no node '{key}' in canvas '{cid}' (use 'canvas/parent/child' for inner nodes)")
    for where, did, c in comments_to_check:
        files = diffs[did]
        if c.get("item"):
            cid, _, iid = c["item"].partition("/")
            if iid not in checklist_items.get(cid, set()):
                rep.err(where, f"item '{c['item']}' is not a checklist item ('checklist-id/item-id')")
        elif not (c.get("md") or c.get("title")):
            rep.err(where, "comment needs 'item', or 'title'/'md'")
        lint_text(rep, where + ".md", c.get("md"))
        if not c.get("file"):
            if c.get("line"):
                rep.err(where, "a comment with 'line' needs 'file'")
            continue
        if c["file"] not in files:
            rep.err(where, f"file '{c['file']}' is not in diff '{did}'")
            continue
        if c.get("line"):
            side = c.get("side", "new")
            shown = files[c["file"]][0 if side == "old" else 1]
            end = c.get("end", c["line"])
            if end not in shown:
                rep.err(where, f"line {end} ({side} side) of '{c['file']}' is not shown in the diff: add an excerpt hunk (gitdiff.py does)")
    for did, path, line in re.findall(r"#code:([\w-]+)(?:/([^\s)\"]+?))?(?::(\d+))?(?=[)\"\s])", json.dumps(doc)):
        if did not in diffs:
            rep.err("links", f"#code:{did} points to no diff block")
        elif path and path not in diffs[did]:
            rep.err("links", f"#code:{did}/{path} points to no file in that diff")
    md_links = re.findall(r"#node:([\w-]+)/([\w/-]+)", json.dumps(doc))
    for cid, key in md_links:
        if cid not in canvas_nodes or (key not in canvas_nodes[cid] and not any(k.split('/')[-1] == key for k in canvas_nodes[cid])):
            rep.err("links", f"#node:{cid}/{key} points to no node")
    item_anchors = {f"item-{cid}-{iid}" for cid, iids in checklist_items.items() for iid in iids}
    for anchor in re.findall(r"\]\(#(item-[\w-]+)\)", json.dumps(doc)):
        if anchor not in item_anchors:
            rep.err("links", f"#{anchor} points to no checklist item (#item-<checklist>-<item>)")

    def placeholders(node, where: str) -> None:
        # ghthreads.py stubs carry <<...>> where the author's verdict and reasoning go;
        # code (diff files, code blocks) is quoted source and may legitimately contain << >>
        if isinstance(node, dict):
            for k, v in node.items():
                if k not in ("files", "code"):
                    placeholders(v, f"{where}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                placeholders(v, f"{where}[{i}]")
        elif isinstance(node, str):
            for m in PLACEHOLDER.findall(node):
                rep.err(where, f"unfilled placeholder {m}: write the verdict, reasoning, fix and check")
    placeholders(doc.get("sections") or [], "sections")
    return rep


def build(doc: dict, template: str) -> str:
    payload = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("</", "<\\/").replace("<!--", "<\\!--")
    title = (doc.get("title") or "bluedoc").replace("&", "&amp;").replace("<", "&lt;")
    if "__BLUEDOC_DOC__" not in template:
        raise SystemExit("template is missing the __BLUEDOC_DOC__ placeholder")
    return template.replace("__BLUEDOC_TITLE__", title).replace("__BLUEDOC_DOC__", payload)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("doc", type=Path)
    ap.add_argument("-o", "--out", type=Path)
    ap.add_argument("--check", action="store_true", help="validate and lint only")
    ap.add_argument("--strict", action="store_true", help="fail on lint warnings")
    ap.add_argument("--template", type=Path, default=TEMPLATE)
    a = ap.parse_args()
    try:
        doc = json.loads(a.doc.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"cannot read {a.doc}: {e}", file=sys.stderr)
        return 2
    rep = validate(doc)
    for line in rep.errors + rep.warnings:
        print(line, file=sys.stderr)
    print(f"{len(rep.errors)} error(s), {len(rep.warnings)} warning(s)", file=sys.stderr)
    if rep.errors or (a.strict and rep.warnings):
        return 1
    if a.check:
        return 0
    if not a.out:
        print("pass -o OUT.html or --check", file=sys.stderr)
        return 2
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(build(doc, a.template.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"wrote {a.out} ({a.out.stat().st_size // 1024} KB)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
