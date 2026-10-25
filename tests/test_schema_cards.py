"""`build.py schema`: a card for every block type, part and doc type, generated from build.SCHEMA_CARDS; every field the
validator reads for a block is on its card (or a part card it names); each block's example validates, and dropping one
of its required fields is an error naming it; the types guides send agents to these cards, not to grep schema.md."""
from __future__ import annotations

import copy
import inspect
import json
import re
import subprocess
import sys
import unittest

from _support import SCRIPTS, SKILL

import build
import listing

PARTS_OF_SCOPE = ("node", "edge", "flow")
DOC_TYPE_FOR = {"board": "design", "listing": "storelisting"}


def card(name: str) -> str:
    text = build.schema_card(name)
    assert text is not None, name
    return text


def card_with_parts(*names: str) -> str:
    """The cards plus every part card they name (`schema <part>`), transitively, as an agent would read them."""
    seen, todo, texts = set(), list(names), []
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        texts.append(card(name))
        todo += sorted(set(re.findall(r"schema (\w+)", texts[-1])) & set(build.SCHEMA_CARDS))
    return "\n".join(texts)


def shape_keys(spec, scope_seen: bool = False) -> set[str]:
    """Every key BLOCK_SHAPES names at any depth (SCOPE stands for nodes, edges and flows, expanded once)."""
    if spec == build.SCOPE:
        if scope_seen:
            return set()
        spec, scope_seen = build.SCOPE_SHAPE, True
    if isinstance(spec, dict):
        return set(spec) | {k for v in spec.values() for k in shape_keys(v, scope_seen)}
    if isinstance(spec, list) and spec:
        return shape_keys(spec[0], scope_seen)
    return set()


def read_keys(src: str, names: str) -> set[str]:
    """The keys read in src as <name>.get("k") or <name>["k"], for the given variable names."""
    return set(re.findall(rf'\b(?:{names})(?:\.get\(|\[)"(\w+)"', src))


def branches() -> list[tuple[tuple[str, ...], str]]:
    """check_block's source per branch: the block types an `if t ==` / `elif t ==` / `t in (…)` names, and its text."""
    src = inspect.getsource(build._validate)
    body = src[src.index("    def check_block"):]
    body = body[:re.search(r"\n    \S", body[1:]).start() + 1]
    parts = re.split(r"\n\s+(?:el)?if (t == \"\w+\"|t in \([^)]*\)):", body)
    return [(tuple(re.findall(r'"(\w+)"', head)), text) for head, text in zip(parts[1::2], parts[2::2])]


def wrap(block: dict) -> dict:
    """A doc holding block, of the type that may hold it; no meta.rev, so contracts only warn."""
    return {"id": "acme-card", "title": "Card example", "meta": {"type": DOC_TYPE_FOR.get(block["type"], "other")},
            "sections": [{"id": "main", "title": "Main", "blocks": [block]}]}


def errors(doc: dict) -> list[str]:
    """The doc's errors, less a storelisting's store-rule findings (no shots yet: the page still draws)."""
    rep = build.validate(doc, None, write_cache=False)
    return [e for e in rep.errors if e not in rep.store]


class Cards(unittest.TestCase):
    def test_every_block_type_part_and_doc_type_has_a_card(self) -> None:
        self.assertLessEqual(build.BLOCK_TYPES, set(build.SCHEMA_CARDS))
        for name in list(build.SCHEMA_CARDS) + sorted(build.DOC_TYPES):
            with self.subTest(name=name):
                text = card(name)
                self.assertTrue(text.startswith(f"{name}: "), text)
        self.assertIsNone(build.schema_card("nope"))

    def test_a_block_card_has_a_row_per_field_and_a_minified_example(self) -> None:
        for t in build.BLOCK_TYPES:
            with self.subTest(block=t):
                lines = card(t).splitlines()
                self.assertTrue(lines[-1].startswith("e.g. {"), lines[-1])
                ex = lines[-1][len("e.g. "):]
                self.assertEqual(json.dumps(json.loads(ex), ensure_ascii=False, separators=(",", ":")), ex)
                for name, *_ in build.SCHEMA_CARDS[t][1]:
                    self.assertTrue(any(line.startswith(name + "  ") for line in lines[1:-1]), name)

    def test_index_lists_every_block_type_and_the_doc_types(self) -> None:
        text = build.schema_index()
        for t in build.BLOCK_TYPES:
            self.assertRegex(text, rf"(?m)^  {t} +\S")
        for t in build.DOC_TYPES:
            self.assertIn(t, text.splitlines()[-1])


class FieldsOnCards(unittest.TestCase):
    def assert_on_card(self, names, keys: set[str]) -> None:
        names = (names,) if isinstance(names, str) else names
        text = card_with_parts(*names)
        missing = sorted(k for k in keys if not re.search(rf"(?<![\w-]){re.escape(k)}(?![\w-])", text))
        self.assertEqual(missing, [], f"fields the validator reads but `build.py schema {' / '.join(names)}` doesn't show")

    def test_every_field_in_the_type_shapes_is_on_its_card(self) -> None:
        for t, spec in build.BLOCK_SHAPES.items():
            with self.subTest(block=t):
                self.assert_on_card(t, shape_keys(spec))

    def test_every_field_check_block_reads_is_on_its_card(self) -> None:
        got = branches()
        self.assertLessEqual(build.BLOCK_TYPES - {"board", "listing"}, {t for names, _ in got for t in names})
        for names, src in got:
            with self.subTest(blocks=names):
                self.assert_on_card(names, read_keys(src, r"b|it|f|sd|c") - {"type"})

    def test_every_field_the_canvas_board_and_listing_validators_read_is_on_a_card(self) -> None:
        self.assert_on_card("canvas", read_keys(inspect.getsource(build.validate_scope), r"n|e|f|st|scope"))
        self.assert_on_card("board", read_keys(inspect.getsource(build.validate_board), r"b|a|fw|th"))
        self.assert_on_card("listing", read_keys(inspect.getsource(listing), r"lb"))

    def test_enums_come_from_the_validator(self) -> None:
        self.assertIn("|".join(sorted(build.CALLOUT_KINDS)), card("callout"))
        self.assertIn("|".join(sorted(build.FILE_ACTIONS)), card("files"))
        self.assertIn("|".join(sorted(build.NODE_KINDS)), card("node"))
        self.assertIn("|".join(build.FIDELITIES), card("artboard"))
        self.assertIn("|".join(p["id"] for p in listing.load_rules()["platforms"]), card("listing"))


class Examples(unittest.TestCase):
    def test_each_block_example_validates(self) -> None:
        for t in build.BLOCK_TYPES:
            with self.subTest(block=t):
                self.assertEqual(errors(wrap(copy.deepcopy(build.SCHEMA_CARDS[t][2]))), [])

    def test_dropping_a_required_field_is_an_error_naming_it(self) -> None:
        for t in build.BLOCK_TYPES:
            for field in build.BLOCK_REQUIRED[t]:
                with self.subTest(block=t, field=field):
                    block = copy.deepcopy(build.SCHEMA_CARDS[t][2])
                    del block[field]
                    self.assertTrue(any(field in e for e in errors(wrap(block))), field)

    def test_the_item_and_doc_examples_validate(self) -> None:
        item = copy.deepcopy(build.SCHEMA_CARDS["item"][2])
        self.assertEqual(errors(wrap({"type": "checklist", "id": "q", "title": "Questions", "items": [item]})), [])
        self.assertEqual(errors(copy.deepcopy(build.SCHEMA_CARDS["doc"][2])), [])

    def test_required_fields_feed_the_validator(self) -> None:
        self.assertEqual(build.BLOCK_REQUIRED["checklist"], ("id", "title", "items"))
        self.assertEqual(build.BLOCK_REQUIRED["diff"], ("id", "title"))
        self.assertEqual(build.DOC_REQUIRED, ("id", "title", "sections"))


class DocTypes(unittest.TestCase):
    def test_plan_card_names_its_contract_and_skeleton_sections(self) -> None:
        text = card("plan")
        self.assertIn("steps block", text)
        self.assertIn("files block", text)
        self.assertIn("steps · Steps · steps plan", text)
        self.assertLessEqual(len(text.splitlines()), 14)

    def test_board_types_name_the_artboard_rules(self) -> None:
        self.assertIn("at least one artboard", card("design"))
        self.assertIn('device "slide"', card("presentation"))
        self.assertIn("shot|asset|icons", card("storelisting"))
        self.assertIn("blocker|major|minor|nit", card("review"))
        self.assertIn("--shape area", card("review"))


class Command(unittest.TestCase):
    def run_schema(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(SCRIPTS / "build.py"), "schema", *args], capture_output=True, text=True,
                              timeout=30)

    def test_schema_prints_cards(self) -> None:
        for name in ("checklist", "canvas", "plan", ""):
            with self.subTest(name=name):
                r = self.run_schema(*([name] if name else []))
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertEqual(r.stdout.strip(), card(name) if name else build.schema_index())

    def test_an_unknown_name_exits_2_listing_the_names(self) -> None:
        r = self.run_schema("nope")
        self.assertEqual(r.returncode, 2)
        self.assertIn("checklist", r.stderr)


class Guides(unittest.TestCase):
    def test_types_guides_point_at_schema_cards_not_grep(self) -> None:
        for f in sorted((SKILL / "types").glob("*.md")):
            with self.subTest(guide=f.name):
                text = f.read_text(encoding="utf-8")
                self.assertNotRegex(text, r"grep[^\n]*schema\.md")
                self.assertNotIn("Field details: grep", text)


if __name__ == "__main__":
    unittest.main()
