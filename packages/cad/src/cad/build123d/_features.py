"""Custom features: a function of the project's own, declared as one feature of the design tree.

Onshape's FeatureScript showed what a feature-based modeller gains when a feature is code the user can
write: a feature is a function with a name and typed parameters, the tree shows each call of it as one
row with those parameters as its inputs, and the same feature is used again in any part. This is that
for build123d::

    from cad.build123d import Bool, Count, Enum, Faces, Length, feature

    @feature("Bolt Circle", diameter=Length(min=0), count=Count(min=1, max=24),
             hole=Length(label="Hole Diameter", min=0),
             end=Enum({"through": "Through All", "blind": "Blind"}, group="End"),
             depth=Length(min=0, group="End"), chamfer=Bool(group="Options"))
    def bolt_circle(body, diameter, count, hole, end="through", depth=10, chamfer=False):
        ...
        return body - holes

    @model
    def flange():
        body = Cylinder(40, 8)
        body = bolt_circle(body, diameter=60, count=6, hole=6.6)   # one row: "Bolt Circle"
        return body

What FeatureScript's precondition says, a spec says here, one per parameter, by the function's own
parameter name: what it is (a ``Length``, ``Angle``, ``Count``, ``Number``, ``Bool``, ``Enum``, or the
``Faces`` or ``Edges`` it acts on, picked on the model), its label, its bounds, its choices and the group
its dialog shows it in. A parameter's default is the function's own, as written in its signature: the
value a new call starts with. A feature's first parameter is the body it changes, and it returns that
body changed.

A call is a plain call, so the part builds the same with or without the edit tracer. While the tracer
records, every operation made inside the call is told which call it was in (``active``), so the row
that holds the call reads as the feature by its name, its inputs the declared parameters, each still the
value as written where it was written (``cad.edit.tracer``).

A value outside a spec stops the build before any geometry is made, with the feature's words and the
parameter it is about (``FeatureError``, FeatureScript's ``regenError`` with its faulty parameter): the
feature's dialog says those words and marks that parameter.
"""

from __future__ import annotations

import contextvars
import functools
import inspect
import itertools
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from numbers import Real
from typing import Any

# What each kind of parameter is, as a value: a number (with or without a unit), a switch, one of a
# list, or the faces or edges of the body it is given.
NUMBERS = ("length", "angle", "count", "number")
PICKS = ("faces", "edges")


class FeatureError(ValueError):
    """A feature that cannot be made as asked, in its own words (FeatureScript's ``regenError``):
    ``feature``, its name, and ``param``, the parameter the words are about, which its dialog marks."""

    def __init__(self, message: str, *, feature: str | None = None, param: str | None = None):
        super().__init__(message)
        self.feature = feature
        self.param = param


@dataclass(frozen=True)
class Param:
    """A declared parameter of a feature: what it is (``kind``, one of ``NUMBERS``, ``bool``, ``enum`` or
    one of ``PICKS``), the label its dialog and the tree show, its bounds, its choices (an enum's, each
    value with its label), how many faces or edges it takes at most, and the group its dialog shows it in."""

    kind: str = "number"
    label: str | None = None
    min: float | None = None
    max: float | None = None
    group: str | None = None
    choices: tuple[tuple[str, str], ...] = ()

    def check(self, feature: str, name: str, value: Any) -> None:
        def refuse(words: str) -> FeatureError:
            return FeatureError(f"{feature}: {name} {words}", feature=feature, param=name)

        if self.kind == "bool":
            if not isinstance(value, bool):
                raise refuse(f"must be True or False (was {value!r})")
            return
        if self.kind == "enum":
            allowed = [each for each, _ in self.choices]
            if value not in allowed:
                raise refuse(f"must be one of {', '.join(repr(each) for each in allowed)} (was {value!r})")
            return
        if self.kind in PICKS:
            picked = _picked(value, self.kind)
            if picked is None:
                raise refuse(f"must be {self.kind} of the body (was {type(value).__name__})")
            if not picked:
                raise refuse(f"needs at least one of the body's {self.kind}")
            if self.max is not None and picked > self.max:
                raise refuse(f"takes at most {self.max:g} {self.kind} (was {picked})")
            return
        if not isinstance(value, Real) or isinstance(value, bool):
            raise refuse(f"must be a number (was {value!r})")
        if self.kind == "count" and float(value) != int(value):
            raise refuse(f"must be a whole number (was {value})")
        if self.min is not None and value < self.min:
            raise refuse(f"must be at least {self.min:g} (was {float(value):g})")
        if self.max is not None and value > self.max:
            raise refuse(f"must be at most {self.max:g} (was {float(value):g})")

    def describe(self, name: str, default: Any = inspect.Parameter.empty) -> dict:
        described = {"name": name, "kind": self.kind, "label": self.label or _label(name), "min": self.min, "max": self.max,
                     "group": self.group, "required": default is inspect.Parameter.empty}
        if self.choices:
            described["choices"] = [{"value": value, "label": label} for value, label in self.choices]
        if default is not inspect.Parameter.empty and isinstance(default, (bool, int, float, str)):
            described["default"] = default
        return described


def _picked(value: Any, kind: str) -> int | None:
    """How many faces or edges ``value`` is (one, or a list of them), or None when it is not those."""
    import build123d as bd

    wanted = bd.Face if kind == "faces" else bd.Edge
    if isinstance(value, wanted):
        return 1
    try:
        items = list(value)
    except TypeError:
        return None
    return len(items) if all(isinstance(item, wanted) for item in items) else None


def Length(*, label: str | None = None, min: float | None = None, max: float | None = None, group: str | None = None) -> Param:
    """A length, in the part's units (FeatureScript's ``isLength``)."""
    return Param("length", label, min, max, group)


def Angle(*, label: str | None = None, min: float | None = None, max: float | None = None, group: str | None = None) -> Param:
    """An angle, in degrees (``isAngle``)."""
    return Param("angle", label, min, max, group)


def Count(*, label: str | None = None, min: float | None = None, max: float | None = None, group: str | None = None) -> Param:
    """A whole number of things (``isInteger``)."""
    return Param("count", label, min, max, group)


def Number(*, label: str | None = None, min: float | None = None, max: float | None = None, group: str | None = None) -> Param:
    """A number with no unit (``isReal``)."""
    return Param("number", label, min, max, group)


def Bool(*, label: str | None = None, group: str | None = None) -> Param:
    """A switch, a check box in the dialog (FeatureScript's ``is boolean``)."""
    return Param("bool", label, group=group)


def Enum(choices: Mapping[str, str] | list[str] | tuple[str, ...], *, label: str | None = None, group: str | None = None) -> Param:
    """One of a list (FeatureScript's ``enum``): ``choices``, each value written in the call with the
    label its dialog shows (a list of values labels each by itself)."""
    pairs = tuple(choices.items()) if isinstance(choices, Mapping) else tuple((each, _label(each)) for each in choices)
    if not pairs or not all(isinstance(value, str) for value, _ in pairs):
        raise TypeError("Enum takes its choices as strings: a list, or a mapping of each to its label")
    return Param("enum", label, group=group, choices=pairs)


def Faces(*, label: str | None = None, max: int | None = None, group: str | None = None) -> Param:
    """Faces of the body, picked on the model (FeatureScript's ``Query`` filtered to faces): written in
    the call as build123d's selectors by where they are, as the ribbon's commands write theirs. ``max``:
    at most so many (1 for a feature that takes one face)."""
    return Param("faces", label, max=max, group=group)


def Edges(*, label: str | None = None, max: int | None = None, group: str | None = None) -> Param:
    """Edges of the body, picked on the model (a ``Query`` filtered to edges)."""
    return Param("edges", label, max=max, group=group)


def _label(name: str) -> str:
    return name.replace("_", " ").capitalize()


@dataclass(frozen=True)
class FeatureDefinition:
    """A feature as declared: its name, its function, its parameters in the function's order, and the
    groups its dialog shows folded until opened (FeatureScript's "Collapsed By Default")."""

    name: str
    fn: Callable
    params: dict[str, Param] = field(default_factory=dict)
    collapsed: tuple[str, ...] = ()

    @property
    def function(self) -> str:
        return f"{self.fn.__module__}.{self.fn.__qualname__}"

    def describe(self) -> dict:
        """What the feature is, as plain data: for its dialog, the toolbar and the agent."""
        signature = inspect.signature(self.fn)
        return {
            "name": self.name,
            "function": self.function,
            "doc": inspect.getdoc(self.fn) or "",
            "params": [spec.describe(name, signature.parameters[name].default) for name, spec in self.params.items()],
            "collapsed": list(self.collapsed),
        }


@dataclass(frozen=True)
class FeatureCall:
    """One call of a feature: which, its arguments as given (bound to the function's names, so a
    traced number keeps where it was written) and a number of its own in this process."""

    definition: FeatureDefinition
    arguments: dict[str, Any]
    id: int


_ACTIVE: contextvars.ContextVar[tuple[FeatureCall, ...]] = contextvars.ContextVar("cad_feature_calls", default=())
_IDS = itertools.count(1)


def active() -> FeatureCall | None:
    """The outermost feature call running now: the one the design's own line made (a feature built
    of other features is still the one feature the line called), or None outside any."""
    calls = _ACTIVE.get()
    return calls[0] if calls else None


def feature(name: str | None = None, *, collapsed: tuple[str, ...] | list[str] = (), **params: Param) -> Callable[[Callable], Callable]:
    """Declare a function a feature named ``name`` (its own name, as a label, when not given), with
    ``params`` the specs of its parameters, each by the function's own parameter name, and
    ``collapsed`` the groups its dialog shows folded."""

    def declare(fn: Callable) -> Callable:
        signature = inspect.signature(fn)
        unknown = [key for key in params if key not in signature.parameters]
        if unknown:
            raise TypeError(f"@feature on {fn.__qualname__}: no parameter named {', '.join(unknown)}")
        first = next(iter(signature.parameters), None)
        if first in params:
            raise TypeError(f"@feature on {fn.__qualname__}: its first parameter, {first}, is the body it changes")
        groups = {spec.group for spec in params.values() if spec.group}
        missing = [each for each in collapsed if each not in groups]
        if missing:
            raise TypeError(f"@feature on {fn.__qualname__}: no group named {', '.join(missing)}")
        ordered = {key: params[key] for key in signature.parameters if key in params}
        definition = FeatureDefinition(name or _label(fn.__name__), fn, ordered, tuple(collapsed))

        @functools.wraps(fn)
        def call(*args: Any, **kwargs: Any) -> Any:
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            for key, spec in ordered.items():
                spec.check(definition.name, key, bound.arguments[key])
            token = _ACTIVE.set((*_ACTIVE.get(), FeatureCall(definition, dict(bound.arguments), next(_IDS))))
            try:
                return fn(*args, **kwargs)
            finally:
                _ACTIVE.reset(token)

        call.feature = definition  # type: ignore[attr-defined]
        return call

    return declare


def definition_of(fn: Any) -> FeatureDefinition | None:
    """The feature a function was declared as, or None for a plain function."""
    found = getattr(fn, "feature", None)
    return found if isinstance(found, FeatureDefinition) else None


def library(module: Any) -> list[dict]:
    """Every feature a module declares, described, in the order the module defines them: a feature
    library as the toolbar and the agent read it (``describe``). A feature another module declares and
    this one imports is that module's, not this one's."""
    found = [value for value in vars(module).values()
             if (definition := definition_of(value)) is not None and value.__module__ == module.__name__]
    return [definition_of(fn).describe() for fn in found]  # type: ignore[union-attr]
