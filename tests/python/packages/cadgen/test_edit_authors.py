"""Who made each feature of a part (``cadgen.edit.authors``): yours when a hand edit wrote the
first line of its statement, the agent's when a turn's checkpoint made since Studio began keeping
track holds it, and nobody's otherwise: a line from before then, and one no checkpoint holds yet.

They drive the edit service end to end, as the viewer's server does, on a small part in a fresh git
repository a Studio chat has run in. A checkpoint is made as Studio's server makes one: the folder
staged in an index of its own, committed and kept under a hidden ref, the branch left where it is.
Builds are not started.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from cadgen.edit import authors
from cadgen.edit import service as edit


def setUpModule():
    """An engine of this file's own (its folders, and a free port), which every process the edit
    service starts inherits: the rollback bar's body is handed to it (``tracer._bar_document``)."""
    from unittest import mock

    from tests.python.support import engine_daemon

    engine_daemon.isolate(unittest.addModuleCleanup)
    patch = mock.patch.dict(os.environ, {"CADGEN_ENGINE_PORT": "0"})
    patch.start()
    unittest.addModuleCleanup(patch.stop)

GIT_ENV = {
    "GIT_AUTHOR_NAME": "T3 Code",
    "GIT_AUTHOR_EMAIL": "t3@example.com",
    "GIT_COMMITTER_NAME": "T3 Code",
    "GIT_COMMITTER_EMAIL": "t3@example.com",
}
# A turn that ended long before Studio began keeping track.
LONG_AGO = "@1700000000 +0000"

# A block the agent made before Studio kept track, its body returned outright.
BLOCK = """
    from build123d import Box
    from cadgen import model


    @model
    def block():
        return Box(20, 10, 4)
"""
# The same block after a turn of the agent's: its top edges chamfered.
CHAMFERED = """
    from build123d import Axis, Box, chamfer
    from cadgen import model


    @model
    def block():
        part = Box(20, 10, 4)
        part = chamfer(part.edges().group_by(Axis.Z)[-1], length=0.5)
        return part
"""
# The chamfered block with a fillet put in by hand, then a hole a later turn drills.
FILLETED = """
    from build123d import Axis, Box, Cylinder, chamfer, fillet
    from cadgen import model


    @model
    def block():
        part = Box(20, 10, 4)
        part = chamfer(part.edges().group_by(Axis.Z)[-1], length=0.5)
        part = fillet(part.edges().group_by(Axis.Z)[0], radius=0.5)
        return part
"""
DRILLED = FILLETED.replace("        return part", "        part -= Cylinder(1, 20)\n        return part")
# The block with its bottom edges rounded where CHAMFERED's top edges are chamfered: line 8 of its script is a fillet.
ROUNDED = CHAMFERED.replace("chamfer", "fillet").replace("[-1], length=0.5", "[0], radius=0.5")
HOLE = "part -= Cylinder(1, 20)"
# A part of a library the project keeps in a folder of its own.
WIDGET = """
    from build123d import Cylinder
    from cadgen import model


    @model
    def widget():
        return Cylinder(5, 12)
"""
BOX, BOX_HELD = "return Box(20, 10, 4)", "part = Box(20, 10, 4)"
AGENT_CHAMFER = "part = chamfer(part.edges().group_by(Axis.Z)[-1], length=0.5)"
# The block's top edges, as the viewer reads them.
TOP_EDGES = [{"selector": selector, "type": "line", "center": list(center), "size": size}
             for selector, center, size in (("e1", (0, -5, 2), 20), ("e2", (0, 5, 2), 20), ("e3", (-10, 0, 2), 10), ("e4", (10, 0, 2), 10))]


def git(repo: Path, *args: str, env: dict | None = None) -> str:
    ran = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True, env={**os.environ, **GIT_ENV, **(env or {})})
    return ran.stdout.strip()


def checkpoint(repo: Path, ordinal: int, when: str | None = None, scope: str = "t") -> str:
    """A chat's checkpoint, as Studio's server makes one at the end of each turn, and as its first
    run starts (ordinal 0)."""
    index = repo / ".git" / "checkpoint-index"
    staged = {"GIT_INDEX_FILE": str(index)}
    git(repo, "add", "-A", env=staged)
    tree = git(repo, "write-tree", env=staged)
    index.unlink()
    ref = f"refs/t3/orchestration-v2/checkpoints/{scope}/ordinal/{ordinal}"
    dated = {"GIT_COMMITTER_DATE": when, "GIT_AUTHOR_DATE": when} if when else {}
    commit = git(repo, "commit-tree", tree, "-m", f"t3 checkpoint ref={ref}", env=dated)
    git(repo, "update-ref", ref, commit)
    return commit


def made_by(reply: dict) -> dict[str, str]:
    """Who made each feature, by the first line of its statement."""
    text = {feature["key"]: feature["text"] for feature in reply["features"]}
    return {text[key]: author for key, author in reply["authors"].items()}


def key_of(reply: dict, line: str) -> str:
    return next(feature["key"] for feature in reply["features"] if feature["text"] == line)


class Authors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = edit.EditService(build=False)

    @classmethod
    def tearDownClass(cls):
        cls.service.close()

    def project(self, *, repository: bool = True, chat: bool = True) -> tuple[Path, str]:
        """The block in a fresh folder: a git repository a chat has run in (its first run's checkpoint), unless not."""
        root = Path(tempfile.mkdtemp(prefix="cadgen-edit-authors-")).resolve()
        self.addCleanup(shutil.rmtree, root, True)
        if repository:
            git(root, "init", "-q")
        self.write(root, BLOCK)
        if repository and chat:
            checkpoint(root, 0)
        return root, str(root / "block.step")

    @staticmethod
    def write(root: Path, text: str) -> None:
        (root / "block.py").write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")

    def read(self, file: str, files: dict | None = None) -> dict:
        reply = self.service.state(file, files)
        self.assertTrue(reply["ok"], reply.get("error"))
        return reply

    def change(self, file: str, state: dict, **change) -> dict:
        reply = self.service.change({"file": file, "files": state["files"], **change})
        self.assertTrue(reply["ok"], reply.get("error"))
        return reply

    def fillet(self, file: str, state: dict) -> dict:
        return self.change(file, state, command={"command": "fillet", "selection": TOP_EDGES, "inputs": {"radius": "1"}})

    def test_marks_nothing_from_before_tracking_began(self):
        root, file = self.project()
        checkpoint(root, 1, LONG_AGO)
        state = self.read(file)
        self.assertEqual(state["authors"], {})
        # Recording began with the project's scripts as they were.
        start = json.loads((root / authors.LEDGER).read_text(encoding="utf-8").splitlines()[0])
        self.assertIn(BOX, start["baseline"]["block.py"])
        # A turn since that left the part alone holds its lines too: they are still nobody's.
        made = checkpoint(root, 2)
        self.assertEqual(self.read(file)["authors"], {})
        self.assertEqual(self.read(file, state["files"]).get("authors"), {})
        # The record is never in a checkpoint.
        self.assertNotIn(".studio", git(root, "ls-tree", "-r", "--name-only", made))

    def test_marks_a_hand_edit_as_yours(self):
        root, file = self.project()
        filleted = self.fillet(file, self.read(file))
        fillet = next(feature["text"] for feature in filleted["features"] if feature["kind"] == "Fillet")
        # The block, held in a name for the fillet to go on from, is still from before Studio kept track.
        self.assertIn(BOX_HELD, (root / "block.py").read_text(encoding="utf-8"))
        self.assertEqual(made_by(filleted), {fillet: "you"})
        # A turn's checkpoint holds it too, and it stays yours.
        checkpoint(root, 1)
        self.assertEqual(made_by(self.read(file)), {fillet: "you"})

    def test_marks_an_agent_turns_feature_as_the_agents(self):
        root, file = self.project()
        self.read(file)
        self.write(root, CHAMFERED)
        checkpoint(root, 1)
        # The block the turn held in a name is still from before.
        self.assertEqual(made_by(self.read(file)), {AGENT_CHAMFER: "agent"})

    def test_marks_nothing_a_turn_has_not_finished(self):
        root, file = self.project()
        # A turn long before Studio kept track chamfered the block, and the chamfer was taken out again.
        self.write(root, CHAMFERED)
        checkpoint(root, 1, LONG_AGO)
        self.write(root, BLOCK)
        self.read(file)
        self.write(root, CHAMFERED)
        running = self.read(file)
        self.assertIn(AGENT_CHAMFER, [feature["text"] for feature in running["features"]])
        self.assertEqual(running["authors"], {})
        # The turn ends: the part reads the same, and its marks are brought up to date.
        checkpoint(root, 2)
        again = self.read(file, running["files"])
        self.assertTrue(again["unchanged"])
        self.assertEqual(again["authors"], {key_of(running, AGENT_CHAMFER): "agent"})

    def test_never_starts_outside_a_git_folder(self):
        root, file = self.project(repository=False)
        filleted = self.fillet(file, self.read(file))
        self.assertEqual(filleted["authors"], {})
        self.assertFalse((root / ".studio").exists())
        # Nor where a folder named .git is no repository.
        (root / ".git").mkdir()
        self.assertEqual(self.read(file)["authors"], {})
        self.assertFalse((root / ".studio").exists())

    def test_undo_puts_back_whose_line_it_was_and_redo_whose_it_became(self):
        root, file = self.project()
        self.read(file)
        self.write(root, CHAMFERED)
        checkpoint(root, 1)
        state = self.read(file)
        chamfer = next(feature for feature in state["features"] if feature["text"] == AGENT_CHAMFER)
        edited = self.change(file, state, command={"command": "chamfer", "inputs": {"distance": "1"}, "replace": {"row": chamfer["key"]}})
        mine = next(feature["text"] for feature in edited["features"] if feature["kind"] == "Chamfer")
        self.assertEqual(made_by(edited), {mine: "you"})
        undone = self.change(file, edited, splice=edited["change"]["undo"])
        self.assertEqual(made_by(undone), {AGENT_CHAMFER: "agent"})
        # A size typed in the chamfer's row makes its line yours; Undo, the number written back, makes it the agent's again.
        row = next(row for row in undone["rows"] if row["kind"] == "Chamfer")
        typed = self.change(file, undone, input={"row": row["key"], "index": 0}, text="0.7")
        self.assertEqual(made_by(typed), {AGENT_CHAMFER.replace("0.5", "0.7"): "you"})
        back = self.change(file, typed, literal=typed["change"]["literal"], text=typed["change"]["from"])
        self.assertEqual(made_by(back), {AGENT_CHAMFER: "agent"})
        redone = self.change(file, back, splice=edited["change"]["redo"])
        self.assertEqual(made_by(redone), {mine: "you"})

    def test_a_git_command_that_fails_leaves_no_marks_and_the_part_still_reads(self):
        root, file = self.project()
        filleted = self.fillet(file, self.read(file))
        self.assertEqual(list(made_by(filleted).values()), ["you"])
        checkpoint(root, 1)
        # The repository broken under the project, then a hand edit to judge against the turn: the part still
        # reads, with no marks.
        (root / ".git" / "HEAD").rename(root / ".git" / "HEAD.moved")
        self.addCleanup(lambda: (root / ".git" / "HEAD.moved").rename(root / ".git" / "HEAD"))
        named = self.change(file, filleted, parameter={"name": "WALL", "value": "2"})
        self.assertEqual(named["authors"], {})
        self.assertEqual(self.read(file)["authors"], {})
        # No git at all: nothing is recorded, and nothing raises.
        other, _ = self.project()
        with mock.patch.dict(os.environ, {"PATH": str(other / "no-git-here")}):
            authors.start(other)
        self.assertFalse((other / ".studio").exists())

    def test_records_nothing_where_no_chat_has_run(self):
        # The viewer used on its own in a git folder: nothing written in it, nor in its git.
        root, file = self.project(chat=False)
        filleted = self.fillet(file, self.read(file))
        self.assertEqual(filleted["authors"], {})
        self.assertFalse((root / ".studio").exists())
        exclude = root / ".git" / "info" / "exclude"
        self.assertNotIn(b".studio", exclude.read_bytes() if exclude.exists() else b"")

    def test_a_chat_starting_is_no_turn_of_the_agents(self):
        root, file = self.project()
        self.read(file)
        # A line written outside Studio, then another chat's first run, whose checkpoint is taken before its agent writes.
        self.write(root, CHAMFERED)
        checkpoint(root, 0, scope="u")
        self.assertEqual(self.read(file)["authors"], {})

    def test_a_moved_script_keeps_whose_lines_they_were(self):
        root, file = self.project()
        filleted = self.fillet(file, self.read(file))
        fillet = next(feature["text"] for feature in filleted["features"] if feature["kind"] == "Fillet")
        # A turn that only moves the script into a folder: the block is still from before, the fillet still yours.
        (root / "parts").mkdir()
        (root / "block.py").rename(root / "parts" / "block.py")
        checkpoint(root, 1)
        self.assertEqual(made_by(self.read(str(root / "parts" / "block.step"))), {fillet: "you"})

    def test_a_turn_ending_in_the_same_second_as_another_counts(self):
        root, file = self.project()
        self.read(file)
        # Two chats' turns end in one second; the later one sorts first, by its ordinal, so the newest stays the other's.
        second = f"@{int(time.time()) + 2} +0000"
        checkpoint(root, 5, second, scope="a")
        self.write(root, CHAMFERED)
        running = self.read(file)
        # The view's poll judges the part between the two.
        self.assertEqual(self.read(file, running["files"])["authors"], {})
        checkpoint(root, 1, second, scope="b")
        again = self.read(file, running["files"])
        self.assertTrue(again["unchanged"])
        self.assertEqual(again["authors"], {key_of(running, AGENT_CHAMFER): "agent"})

    def test_a_view_of_another_version_is_never_given_this_ones_marks(self):
        root, file = self.project()
        # One view reads the block with its bottom edges rounded: line 8 of the script, the fillet, is nobody's.
        self.write(root, ROUNDED)
        rounded = self.read(file)
        self.assertEqual(rounded["authors"], {})
        # The agent's turn makes line 8 a chamfer instead, and a second view reads that.
        self.write(root, CHAMFERED)
        checkpoint(root, 1)
        self.assertEqual(made_by(self.read(file)), {AGENT_CHAMFER: "agent"})
        # The script put back as the first view read it: its poll finds its files as they were, and its fillet, keyed
        # by the chamfer's line, is not marked the agent's.
        self.write(root, ROUNDED)
        again = self.read(file, rounded["files"])
        self.assertTrue(again["unchanged"])
        self.assertEqual(again.get("authors", {}), {})

    def test_a_rename_keeps_who_made_it(self):
        root, file = self.project()
        self.read(file)
        self.write(root, CHAMFERED)
        checkpoint(root, 1)
        state = self.read(file)
        renamed = self.change(file, state, rename={"feature": key_of(state, AGENT_CHAMFER), "title": "Chamfer1", "name": "Lid edge # 2"})
        self.assertEqual(made_by(renamed), {f"{AGENT_CHAMFER}  # Lid edge # 2": "agent"})

    def test_a_project_holding_a_virtual_environment_is_recorded_without_it(self):
        # Its baseline read from the newest checkpoint: a chat's first run's, or a turn's end.
        for ordinal in (0, 1):
            root, file = self.project(chat=False)
            for name in ("venv/pyvenv.cfg", "venv/lib/python3.13/site-packages/pkg/__init__.py", "venv/bin/activate_this.py",
                         "node_modules/gyp/gyp.py", ".venv/lib/mod.py", "parts/sizes.py"):
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text("WALL = 2\n", encoding="utf-8")
            checkpoint(root, ordinal)
            self.read(file)
            start = json.loads((root / authors.LEDGER).read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(sorted(start["baseline"]), ["block.py", "parts/sizes.py"], ordinal)
        # A project too big to record is found so once, not read again on every trace.
        big, _ = self.project()
        with mock.patch.object(authors, "BASELINE_LIMIT", 8):
            authors.start(big)
            with mock.patch.object(authors.versions, "_git", wraps=authors.versions._git) as ran:
                authors.start(big)
        ran.assert_not_called()
        self.assertFalse((big / authors.LEDGER).exists())

    def test_the_turn_under_way_as_the_record_begins_is_the_agents_and_one_ended_before_is_nobodys(self):
        # Read before any chat; then a chat's first run, the agent writing, the part read while it does, and its turn ending.
        root, file = self.project(chat=False)
        self.read(file)
        checkpoint(root, 0)
        self.write(root, CHAMFERED)
        running = self.read(file)
        self.assertEqual(running["authors"], {})
        checkpoint(root, 1)
        self.assertEqual(self.read(file, running["files"])["authors"], {key_of(running, AGENT_CHAMFER): "agent"})
        # First read only once that turn had ended: the turn is in the record's baseline, and has no marks.
        other, other_file = self.project(chat=False)
        checkpoint(other, 0)
        self.write(other, CHAMFERED)
        checkpoint(other, 1)
        self.assertEqual(self.read(other_file)["authors"], {})

    def test_a_projects_history_from_before_the_record_has_no_marks(self):
        root, file = self.project(chat=False)
        now = int(time.time())
        checkpoint(root, 0, f"@{now - 300} +0000")
        # A turn chamfers the block; a fillet is put in by hand, unrecorded as an older Studio left it; another turn ends.
        self.write(root, CHAMFERED)
        checkpoint(root, 1, f"@{now - 200} +0000")
        self.write(root, FILLETED)
        last = checkpoint(root, 2, f"@{now - 100} +0000")
        # The record begins from the newest checkpoint, dated then: whatever the project holds then is nobody's.
        self.assertEqual(self.read(file)["authors"], {})
        start = json.loads((root / authors.LEDGER).read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(start["checkpoint"], last)
        self.assertEqual(datetime.fromisoformat(start["start"]).timestamp(), int(git(root, "show", "-s", "--format=%ct", last)))
        # A turn after that drills a hole: only it is the agent's.
        self.write(root, DRILLED)
        checkpoint(root, 3)
        self.assertEqual(made_by(self.read(file)), {HOLE: "agent"})

    def test_a_script_in_a_folder_recording_leaves_out_has_no_marks(self):
        root, _ = self.project(chat=False)
        (root / "vendor").mkdir()
        (root / "vendor" / "widget.py").write_text(textwrap.dedent(WIDGET).lstrip(), encoding="utf-8")
        checkpoint(root, 0)
        widget = str(root / "vendor" / "widget.step")
        self.read(widget)
        checkpoint(root, 1)
        self.assertEqual(self.read(widget)["authors"], {})

    def test_a_repository_with_linked_worktrees_records_nothing_and_marks_nothing(self):
        # The agent's turn marked, in a repository of one checkout.
        root, file = self.project()
        self.read(file)
        self.write(root, CHAMFERED)
        made = checkpoint(root, 1)
        self.assertEqual(made_by(self.read(file)), {AGENT_CHAMFER: "agent"})
        # A worktree linked to it, as T3 Code makes one for a chat: every checkout's checkpoints are under the same refs,
        # so whose a turn was cannot be told. The record begun before marks nothing from then on, the poll included.
        elsewhere = Path(tempfile.mkdtemp(prefix="cadgen-edit-authors-linked-")).resolve()
        self.addCleanup(shutil.rmtree, elsewhere, True)
        git(root, "worktree", "add", "--detach", str(elsewhere / "chat"), made)
        state = self.read(file)
        self.assertEqual(state["authors"], {})
        self.assertEqual(self.read(file, state["files"]).get("authors"), {})
        # A worktree taken away by hand leaves its entry until git prunes it: still none.
        shutil.rmtree(elsewhere / "chat")
        self.assertEqual(self.read(file)["authors"], {})
        # Nor is a record begun in such a repository.
        other, other_file = self.project()
        git(other, "worktree", "add", "--detach", str(elsewhere / "other"), checkpoint(other, 1))
        self.assertEqual(self.read(other_file)["authors"], {})
        self.assertFalse((other / authors.LEDGER).exists())

    def test_a_git_exclude_file_in_utf16_leaves_the_part_readable(self):
        root, file = self.project()
        # A line appended as Windows PowerShell 5.1's `>>` appends one.
        exclude = root / ".git" / "info" / "exclude"
        exclude.parent.mkdir(exist_ok=True)
        with exclude.open("ab") as handle:
            handle.write("build/\r\n".encode("utf-16"))
        kept = exclude.read_bytes()
        for _ in range(2):
            self.assertEqual(self.read(file)["authors"], {})
        self.assertFalse((root / ".studio").exists())
        self.assertEqual(exclude.read_bytes(), kept)


if __name__ == "__main__":
    unittest.main()
