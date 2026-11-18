"""A project file read as written and written back the same way. Git checks files out with CRLF on
Windows, and ``read_text`` turns those into LF while ``write_text`` writes the OS's own, so a file
read and written that way comes back with other bytes: undo cannot put it back, and the hash the
editor read no longer matches (amywork777/studio#12)."""

from __future__ import annotations

from pathlib import Path


def newline_of(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def read(path: Path) -> str:
    """The file's text, its line endings as they are."""
    return Path(path).read_bytes().decode("utf-8")


def write(path: Path, text: str, like: str) -> None:
    """``text`` written with the line endings of ``like`` (the file as it was read), whichever
    ``text`` itself was made with."""
    newline = newline_of(like)
    if newline != "\n":
        text = text.replace("\r\n", "\n").replace("\n", newline)
    Path(path).write_bytes(text.encode("utf-8"))
