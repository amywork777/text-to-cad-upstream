"""cadgen._internal.animation_clips: the clip ids a copied .anim.js declares.

The snapshot CLI refuses a typo'd `--animation` clip with the clips the model
has, and the only place they are written down is the module TEXT in the sidecar.
This reader collects the top-level keys of the contract's declaration form
(`export const clips = { id: {...} }`) without executing anything; a module that
builds its clips some other way yields None, deferring to the runtime.
"""

from __future__ import annotations

import unittest

from tests.python.support.paths import add_repo_path

add_repo_path("packages/cadgen/src")

from cadgen._internal.animation_clips import declared_clip_ids  # noqa: E402


class DeclaredClipIdsTests(unittest.TestCase):
    def test_reads_the_contract_form_in_declaration_order(self) -> None:
        text = """
        // arm.anim.js
        export const clips = {
          demo: { label: "Demo", duration: 8, loop: true, update(t, m) { m.get("forearm").rotate([0, 0, 1], t); } },
          teardown: { duration: 5, update: (t, m) => { m.get("lid").opacity(1 - t / 5); } },
        };
        """
        self.assertEqual(["demo", "teardown"], declared_clip_ids(text))

    def test_nested_braces_strings_templates_and_comments_do_not_split_an_entry(self) -> None:
        text = (
            "export const clips = {\n"
            "  demo: { label: 'Demo }', duration: 8, update(t, m) {\n"
            "    if (t > 1) { m.get(`part-${Math.floor(t)}`).rotate([0, 0, 1], 90); } // not a key: }\n"
            "    /* nor this: spin: { */\n"
            "  } },\n"
            "  'spin-fast': { duration: 2, update() {} },\n"
            '  "hold": { duration: 1, update() {} }\n'
            "};\n"
        )
        self.assertEqual(["demo", "spin-fast", "hold"], declared_clip_ids(text))

    def test_helpers_declared_before_the_clips_are_not_mistaken_for_clips(self) -> None:
        text = """
        const TARGETS = { arm: "o1.2", lid: "o1.3" };
        function swing(m, t) { m.get(TARGETS.arm).rotate([0, 1, 0], 30 * t); }
        export const clips = { swingLoop: { duration: 4, update(t, m) { swing(m, t); } } };
        """
        self.assertEqual(["swingLoop"], declared_clip_ids(text))

    def test_an_empty_literal_declares_no_clips(self) -> None:
        self.assertEqual([], declared_clip_ids("export const clips = {};"))

    def test_anything_but_the_literal_form_defers_to_the_runtime(self) -> None:
        for text in (
            "",
            "export default { demo: { update() {} } };",
            "export const clips = build();",
            "export const clips = { ...base, extra: { update() {} } };",
            "export const clips = { [computed]: { update() {} } };",
            "export const clips = { demo: { update() {} }",  # unterminated
        ):
            with self.subTest(text=text):
                self.assertIsNone(declared_clip_ids(text))


if __name__ == "__main__":
    unittest.main()
