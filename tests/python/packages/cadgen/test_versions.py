"""Studio's versions of a part (``cadgen.edit.versions``) and the solids' comparison behind What
changed (``cadgen.edit.solid_diff``, ported from Fixture's ``diff_revision.py``).

A project here is a git repository whose versions are checkpoints made the way Studio's server makes
them: the folder staged in an index of its own, written as a commit and kept under
``refs/t3/orchestration-v2/checkpoints/<scope>/ordinal/<n>``, its branch never moving.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from build123d import Box, Cylinder, Location, export_step

from cadgen.edit import solid_diff, versions

SCOPE = "YmNiZDAxNjdlNTVmODBlZGRkNjY4YTc5NjIyNzU5YzM"
# Checkpoint times are seconds after this one.
EPOCH = 1_700_000_000
GIT_ENV = {
    "GIT_AUTHOR_NAME": "T3 Code",
    "GIT_AUTHOR_EMAIL": "t3@example.com",
    "GIT_COMMITTER_NAME": "T3 Code",
    "GIT_COMMITTER_EMAIL": "t3@example.com",
}


def git(repo: Path, *args: str, env: dict | None = None) -> str:
    ran = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True, env={**os.environ, **GIT_ENV, **(env or {})}
    )
    return ran.stdout.strip()


def checkpoint(repo: Path, ordinal: int, when: int, scope: str = SCOPE) -> str:
    """A checkpoint as Studio's server makes one: every file staged in a separate index, committed
    and kept under a hidden ref, the branch left where it is."""
    index = repo / ".git" / f"checkpoint-index-{ordinal}"
    staged = {"GIT_INDEX_FILE": str(index)}
    git(repo, "add", "-A", env=staged)
    tree = git(repo, "write-tree", env=staged)
    index.unlink()
    date = {"GIT_COMMITTER_DATE": f"@{EPOCH + when} +0000", "GIT_AUTHOR_DATE": f"@{EPOCH + when} +0000"}
    ref = f"refs/t3/orchestration-v2/checkpoints/{scope}/ordinal/{ordinal}"
    commit = git(repo, "commit-tree", tree, "-m", f"t3 checkpoint ref={ref}", env=date)
    git(repo, "update-ref", ref, commit)
    return commit


def write(repo: Path, name: str, text: str) -> None:
    (repo / name).write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")


def step(repo: Path, name: str, shape) -> None:
    export_step(shape, str(repo / name))


class Project(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="studio-versions-")).resolve()
        self.addCleanup(shutil.rmtree, self.repo, True)
        git(self.repo, "init", "-q")


class Versions(Project):
    def test_one_version_each_time_the_file_changed_then_the_file_on_disk(self):
        step(self.repo, "hook.step", Box(40, 30, 10))
        first = checkpoint(self.repo, 0, 1_000)
        write(self.repo, "notes.md", "a turn that left the part alone\n")
        checkpoint(self.repo, 1, 2_000)
        step(self.repo, "hook.step", Box(48, 30, 10))
        third = checkpoint(self.repo, 2, 3_000)
        step(self.repo, "hook.step", Box(48, 30, 12))  # a hand edit since the last turn

        listed = versions.versions(str(self.repo), "hook.step")["versions"]
        self.assertEqual([version["id"] for version in listed], [first, third, "now"])
        self.assertEqual([version["time"] for version in listed[:2]], [EPOCH + 1_000, EPOCH + 3_000])
        self.assertTrue(listed[1]["ref"].endswith(f"{SCOPE}/ordinal/2"))
        self.assertIsNone(listed[2]["ref"])

    def test_a_file_starts_its_versions_when_it_first_appears(self):
        write(self.repo, "notes.md", "before the part\n")
        checkpoint(self.repo, 0, 1_000)
        step(self.repo, "hook.step", Box(40, 30, 10))
        made = checkpoint(self.repo, 1, 2_000)
        listed = versions.versions(str(self.repo), "hook.step")["versions"]
        self.assertEqual([version["id"] for version in listed], [made])

    def test_a_folder_that_is_no_repository_says_so(self):
        loose = Path(tempfile.mkdtemp(prefix="studio-loose-"))
        self.addCleanup(shutil.rmtree, loose, True)
        with self.assertRaisesRegex(versions.VersionsError, "not a git repository"):
            versions.versions(str(loose), "hook.step")


class Compare(Project):
    def setUp(self) -> None:
        super().setUp()
        write(self.repo, "hook.py", "HOOK_DEPTH = 40\nWALL = 10\n")
        step(self.repo, "hook.step", Box(40, 30, 10))
        write(self.repo, "hook.fea.json", '{"verdict": {"status": "fix"}}\n')
        self.older = checkpoint(self.repo, 0, 1_000)
        write(self.repo, "hook.py", "HOOK_DEPTH = 48\nWALL = 10\nRIB: float = 3\n")
        step(self.repo, "hook.step", Box(40, 30, 10) + Cylinder(5, 8).moved(Location((0, 0, 9))))
        write(self.repo, "hook.fea.json", '{"verdict": {"status": "ready"}}\n')
        self.newer = checkpoint(self.repo, 1, 2_000)

    def test_the_solids_sizes_and_texts_of_two_versions(self):
        result = versions.compare(str(self.repo), "hook.step", self.older, self.newer, ["hook.fea.json"], wait=True)
        shape = result["shape"]
        self.assertEqual(shape["status"], "done")
        self.assertGreater(shape["added_mm3"], 300)
        self.assertLess(shape["removed_mm3"], 1)
        self.assertFalse(shape["same"] or shape["moved"])
        self.assertEqual(shape["older"]["bodies"], 1)
        self.assertTrue((self.repo / result["files"]["diff"]).is_file())
        self.assertTrue((self.repo / result["files"]["older"]).is_file())
        self.assertEqual(
            [(size["name"], size["value"]) for size in result["script"]["newerSizes"]],
            [("HOOK_DEPTH", 48), ("WALL", 10), ("RIB", 3)],
        )
        self.assertEqual(result["script"]["olderSizes"][0], {"name": "HOOK_DEPTH", "value": 40, "line": 1})
        self.assertIn('"fix"', result["texts"]["hook.fea.json"]["older"])
        self.assertIn('"ready"', result["texts"]["hook.fea.json"]["newer"])

    def test_a_comparison_is_made_once_and_found_again(self):
        first = versions.compare(str(self.repo), "hook.step", self.older, self.newer, wait=True)
        again = versions.compare(str(self.repo), "hook.step", self.older, self.newer)
        self.assertEqual(again["key"], first["key"])
        self.assertEqual(again["shape"]["status"], "done")
        self.assertEqual(again["shape"]["added_mm3"], first["shape"]["added_mm3"])

    def test_the_file_on_disk_compares_as_now(self):
        step(self.repo, "hook.step", Box(40, 30, 6).moved(Location((0, 0, -2))))
        result = versions.compare(str(self.repo), "hook.step", self.newer, "now", wait=True)
        self.assertEqual(result["shape"]["status"], "done")
        self.assertGreater(result["shape"]["removed_mm3"], 40 * 30 * 4 - 1)

    def test_no_checkpoint_takes_a_comparison(self):
        versions.compare(str(self.repo), "hook.step", self.older, self.newer, wait=True)
        self.assertIn(".studio/", (self.repo / ".git" / "info" / "exclude").read_text().splitlines())
        later = checkpoint(self.repo, 2, 3_000)
        files = git(self.repo, "ls-tree", "-r", "--name-only", later).splitlines()
        self.assertFalse([name for name in files if name.startswith(".studio")])

    def test_a_version_without_the_file_is_refused(self):
        write(self.repo, "other.md", "x\n")
        with self.assertRaisesRegex(versions.VersionsError, "not in one of the two versions"):
            versions.compare(str(self.repo), "missing.step", self.older, self.newer)


class Restore(Project):
    """Going back to a version, as Google Docs' Restore this version does: the part's file and its
    script as that version had them, what was on disk kept as a version first."""

    def setUp(self) -> None:
        super().setUp()
        write(self.repo, "hook.py", "HOOK_DEPTH = 40\n")
        write(self.repo, "hook.step", "ISO-10303-21; depth 40\n")
        self.first = checkpoint(self.repo, 0, 1_000)
        write(self.repo, "hook.py", "HOOK_DEPTH = 48\n")
        write(self.repo, "hook.step", "ISO-10303-21; depth 48\n")
        self.second = checkpoint(self.repo, 1, 2_000)

    def listed(self) -> list[str]:
        return [version["id"] for version in versions.versions(str(self.repo), "hook.step")["versions"]]

    def test_going_back_keeps_what_was_on_disk_as_a_version_first(self):
        write(self.repo, "hook.py", "HOOK_DEPTH = 52\n")  # a hand edit since the last turn
        write(self.repo, "hook.step", "ISO-10303-21; depth 52\n")
        result = versions.restore(str(self.repo), "hook.step", self.first)
        self.assertEqual(sorted(result["restored"]), ["hook.py", "hook.step"])
        self.assertEqual((self.repo / "hook.py").read_text(), "HOOK_DEPTH = 40\n")
        self.assertEqual((self.repo / "hook.step").read_text(), "ISO-10303-21; depth 40\n")
        kept = result["kept"]
        self.assertEqual(git(self.repo, "show", f"{kept}:hook.py"), "HOOK_DEPTH = 52")
        self.assertEqual(self.listed(), [self.first, self.second, kept, "now"])
        listed = versions.versions(str(self.repo), "hook.step")["versions"]
        self.assertTrue(listed[2]["ref"].startswith("refs/studio/kept/"))
        self.assertEqual(listed[3]["blob"], listed[0]["blob"])
        # The folder's own index and branch are left alone: the kept version has an index of its own.
        self.assertFalse((self.repo / ".git" / "index").exists())

    def test_going_back_from_a_version_keeps_nothing_new(self):
        result = versions.restore(str(self.repo), "hook.step", self.first)
        self.assertIsNone(result["kept"])
        self.assertEqual(git(self.repo, "for-each-ref", "refs/studio/"), "")
        self.assertEqual(self.listed(), [self.first, self.second, "now"])

    def test_going_back_and_forth_keeps_each_state_once(self):
        versions.restore(str(self.repo), "hook.step", self.first)
        again = versions.restore(str(self.repo), "hook.step", self.second)
        self.assertIsNone(again["kept"])
        self.assertEqual((self.repo / "hook.py").read_text(), "HOOK_DEPTH = 48\n")
        self.assertEqual(self.listed(), [self.first, self.second])

    def test_going_back_to_the_file_on_disk_or_to_no_version_is_refused(self):
        with self.assertRaisesRegex(versions.VersionsError, "on disk"):
            versions.restore(str(self.repo), "hook.step", "now")
        with self.assertRaisesRegex(versions.VersionsError, "no such version"):
            versions.restore(str(self.repo), "hook.step", "--output=elsewhere")
        with self.assertRaisesRegex(versions.VersionsError, "not in that version"):
            versions.restore(str(self.repo), "missing.step", self.first)


class NamedSizes(unittest.TestCase):
    def test_numbers_named_as_written_but_units(self):
        source = "INCH = 25.4\nLENGTH = 2.8\nOFFSET = -3\ndef part():\n    depth: float = 12.5\n    flag = True\n    __version__ = 2\n"
        self.assertEqual(
            [(size["name"], size["value"]) for size in versions.named_sizes(source)],
            [("LENGTH", 2.8), ("OFFSET", -3), ("depth", 12.5)],
        )

    def test_no_script_or_a_broken_one_has_none(self):
        self.assertIsNone(versions.named_sizes(None))
        self.assertIsNone(versions.named_sizes("WIDTH = (\n"))


class SolidDiff(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="studio-solid-diff-"))
        self.addCleanup(shutil.rmtree, self.folder, True)

    def run_diff(self, older, newer) -> dict:
        export_step(older, str(self.folder / "older.step"))
        export_step(newer, str(self.folder / "newer.step"))
        out = self.folder / "out"
        code = solid_diff.main([str(self.folder / "older.step"), str(self.folder / "newer.step"), str(out)])
        result = json.loads((out / "result.json").read_text())
        self.assertEqual(code, 1 if "error" in result else 0)
        return result

    def test_a_thinner_wall_is_removed_material_with_a_diff_to_show(self):
        result = self.run_diff(Box(40, 30, 10), Box(40, 30, 6).moved(Location((0, 0, -2))))
        self.assertAlmostEqual(result["removed_mm3"], 40 * 30 * 4, delta=1)
        self.assertLess(result["added_mm3"], 1)
        self.assertEqual(result["diff"], "what-changed.step")
        self.assertTrue((self.folder / "out" / "what-changed.step").is_file())
        self.assertEqual([round(v) for v in result["newer"]["bbox"]["max"]], [20, 15, 1])

    def test_the_same_shape_is_the_same_and_has_no_diff(self):
        result = self.run_diff(Box(20, 20, 20), Box(20, 20, 20))
        self.assertTrue(result["same"])
        self.assertIsNone(result["diff"])

    def test_a_part_that_only_moved_says_so(self):
        result = self.run_diff(Box(20, 20, 20), Box(20, 20, 20).moved(Location((100, 0, 0))))
        self.assertTrue(result["moved"])
        self.assertIsNone(result["diff"])

    def test_a_file_that_is_no_step_fails_in_the_result(self):
        (self.folder / "older.step").write_text("not a step file")
        (self.folder / "newer.step").write_text("not a step file")
        out = self.folder / "out"
        self.assertEqual(solid_diff.main([str(self.folder / "older.step"), str(self.folder / "newer.step"), str(out)]), 1)
        self.assertIn("error", json.loads((out / "result.json").read_text()))


if __name__ == "__main__":
    unittest.main()
