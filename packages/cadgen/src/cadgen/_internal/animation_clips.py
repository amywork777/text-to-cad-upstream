"""The clip ids a copied ``.anim.js`` module declares, read WITHOUT running it.

A snapshot's ``animation`` request names a clip, and the sidecar carries the
choreography as module TEXT — the browser runtime compiles it, and only the
runtime can. But a typo'd clip name should fail as a clean CLI error naming the
clips the model does have, the way a typo'd pose name fails against the
declared poses, not as a stack trace out of the page. So the CLI reads the
declaration the contract requires — ``export const clips = { id: {...}, ... }``
— and collects the object literal's top-level keys, skipping over nested
braces, strings, template literals and comments.

This is a PRE-FLIGHT, not a parser: a module that builds its clips some other
way (``export const clips = build()``) yields ``None``, and the runtime's own
check — which has the compiled clips in hand — is the authority that refuses
the name with the declared set. The two never disagree on a literal, because
the runtime's ids are exactly these keys.
"""

from __future__ import annotations

import re

_CLIPS_DECLARATION = re.compile(r"\bexport\s+const\s+clips\s*=\s*\{")
_IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]*")
_OPENERS = {"{": "}", "[": "]", "(": ")"}


def _skip_string(text: str, index: int) -> int:
    """``index`` just past the string literal opening at ``text[index]``."""
    quote = text[index]
    index += 1
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == quote:
            return index + 1
        if quote == "`" and char == "$" and text.startswith("${", index):
            # A template expression may itself nest braces and quotes: skip it
            # as a balanced group and resume the literal after it.
            index = _skip_group(text, index + 1)
            continue
        index += 1
    raise ValueError("unterminated string")


def _skip_comment(text: str, index: int) -> int | None:
    """``index`` past the comment opening at ``text[index]``, or ``None`` if
    the ``/`` is not a comment (division, or a regex literal we cannot tell
    apart — treated as an ordinary character)."""
    if text.startswith("//", index):
        end = text.find("\n", index)
        return len(text) if end < 0 else end + 1
    if text.startswith("/*", index):
        end = text.find("*/", index + 2)
        if end < 0:
            raise ValueError("unterminated comment")
        return end + 2
    return None


def _skip_group(text: str, index: int) -> int:
    """``index`` just past the bracket group opening at ``text[index]``."""
    closer = _OPENERS[text[index]]
    index += 1
    while index < len(text):
        char = text[index]
        if char == closer:
            return index + 1
        if char in _OPENERS:
            index = _skip_group(text, index)
            continue
        if char in "\"'`":
            index = _skip_string(text, index)
            continue
        if char == "/":
            skipped = _skip_comment(text, index)
            if skipped is not None:
                index = skipped
                continue
        if char in "}])":
            raise ValueError("unbalanced brackets")
        index += 1
    raise ValueError("unterminated group")


def _skip_value(text: str, index: int) -> int:
    """``index`` at the ``,`` or ``}`` that ends the property value starting at
    ``text[index]``."""
    while index < len(text):
        char = text[index]
        if char in ",}":
            return index
        if char in _OPENERS:
            index = _skip_group(text, index)
            continue
        if char in "\"'`":
            index = _skip_string(text, index)
            continue
        if char == "/":
            skipped = _skip_comment(text, index)
            if skipped is not None:
                index = skipped
                continue
        if char in "])":
            raise ValueError("unbalanced brackets")
        index += 1
    raise ValueError("unterminated object")


def _skip_blank(text: str, index: int) -> int:
    while index < len(text):
        if text[index].isspace():
            index += 1
            continue
        if text[index] == "/":
            skipped = _skip_comment(text, index)
            if skipped is not None:
                index = skipped
                continue
        break
    return index


def declared_clip_ids(module_text: str) -> list[str] | None:
    """The top-level keys of the module's ``export const clips = {...}`` literal,
    in declaration order — or ``None`` when the text declares its clips some
    other way and only the runtime can say what they are."""
    text = str(module_text or "")
    match = _CLIPS_DECLARATION.search(text)
    if match is None:
        return None
    ids: list[str] = []
    index = match.end()
    try:
        while True:
            index = _skip_blank(text, index)
            if index >= len(text):
                raise ValueError("unterminated object")
            char = text[index]
            if char == "}":
                return ids
            if char == ",":
                index += 1
                continue
            if char in "\"'":
                end = _skip_string(text, index)
                key = text[index + 1 : end - 1]
            else:
                identifier = _IDENTIFIER.match(text, index)
                if identifier is None:
                    # A computed key, a spread, or something else outside the
                    # contract's literal form: defer to the runtime.
                    return None
                key = identifier.group(0)
                end = identifier.end()
            index = _skip_blank(text, end)
            if index >= len(text) or text[index] != ":":
                # Method shorthand or a bare identifier is not a clip entry the
                # runtime would keep either (a clip is an object with update()).
                return None
            index = _skip_value(text, index + 1)
            ids.append(key)
    except ValueError:
        return None
