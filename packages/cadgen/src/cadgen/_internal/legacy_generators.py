"""Teaching errors for the retired magic-name generator contract.

There is deliberately NO backwards compatibility (design/library-first-
generation.md): a legacy source fails hard with a message that routes the
reader — usually an agent — straight to the migration doc. The whole
migration story is: hit this error, read that doc, run the codemod.
"""

from __future__ import annotations

from pathlib import Path

MIGRATION_DOC = "skills/cad/references/migrating-generators.md"


class LegacyGeneratorError(ValueError):
    """A source still using the retired gen_step()/gen_dxf() contract or the
    retired .step.py/.dxf.py naming."""


class InvalidModelScriptError(ValueError):
    """A script whose model DECLARATION is malformed in a way directory
    discovery should skip-with-a-note rather than abort on (e.g. two models in
    one file). Contract violations inside a single model (bad envelope fields,
    bad decorator arguments) stay plain ValueErrors and DO abort, because an
    explicitly-targeted build must fail loudly."""


def _display(script_path: Path) -> str:
    resolved = Path(script_path).resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def legacy_generator_message(script_path: Path, names: tuple[str, ...]) -> str:
    joined = "/".join(f"{name}()" for name in names) or "gen_step()"
    return (
        f"{_display(script_path)} is a legacy generator ({joined} magic names are "
        f"retired) — migrate to the @step/@dxf decorators: see {MIGRATION_DOC} "
        "(one-liner: python -m cadgen.migrate <file>)"
    )


def legacy_naming_message(script_path: Path) -> str:
    return (
        f"{_display(script_path)} uses the retired .step.py/.dxf.py naming — model "
        f"scripts are plain .py files now; see {MIGRATION_DOC} "
        "(one-liner: python -m cadgen.migrate <file>)"
    )
