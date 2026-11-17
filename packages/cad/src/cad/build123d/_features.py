"""Custom features: a function of the project's own, declared as one feature of the design tree.

Onshape's FeatureScript showed what a feature-based modeller gains when a feature is code the user can
write: a feature is a function with a name and typed parameters, the tree shows each call of it as one
row with those parameters as its inputs, and the same feature is used again in any part. This is that
for build123d::

    from cad.build123d import Count, Length, feature

    @feature("Bolt Circle", diameter=Length(min=0), count=Count(min=1), hole=Length(min=0))
    def bolt_circle(body, diameter, count, hole, depth=5):
        ...
        return body - holes

    @model
    def flange():
        body = Cylinder(40, 8)
        body = bolt_circle(body, diameter=60, count=6, hole=6.6)   # one row: "Bolt Circle"
        return body

A call is a plain call, so the part builds the same with or without the edit tracer. While the tracer
records, every operation made inside the call is told which call it was in (``active``), so the row
that holds the call reads as the feature by its name, its inputs the declared parameters, named by
their labels, each still the number as written where it was written (``cad.edit.tracer``).

A parameter's spec is FeatureScript's precondition: a value outside it stops the build with the
feature's name and the parameter's, before any geometry is made (``FeatureError``).
"""

from __future__ import annotations

import contextvars
import functools
import inspect
import itertools
from collections.abc import Callable
from dataclasses import dataclass, field
from numbers import Real
from typing import Any


class FeatureError(ValueError):
    """A feature called with a parameter its spec refuses."""


@dataclass(frozen=True)
class Param:
    """A declared parameter of a feature: what it is (``kind``: length, angle, count or number), the
    label the tree shows, and the least and greatest values it takes."""

    kind: str = "number"
    label: str | None = None
    min: float | None = None
    max: float | None = None

    def check(self, feature: str, name: str, value: Any) -> None:
        if not isinstance(value, Real) or isinstance(value, bool):
            raise FeatureError(f"{feature}: {name} must be a number (was {value!r})")
        if self.kind == "count" and float(value) != int(value):
            raise FeatureError(f"{feature}: {name} must be a whole number (was {value})")
        if self.min is not None and value < self.min:
            raise FeatureError(f"{feature}: {name} must be at least {self.min:g} (was {float(value):g})")
        if self.max is not None and value > self.max:
            raise FeatureError(f"{feature}: {name} must be at most {self.max:g} (was {float(value):g})")

    def describe(self, name: str) -> dict:
        return {"name": name, "kind": self.kind, "label": self.label or _label(name), "min": self.min, "max": self.max}


def Length(*, label: str | None = None, min: float | None = None, max: float | None = None) -> Param:
    """A length, in the part's units."""
    return Param("length", label, min, max)


def Angle(*, label: str | None = None, min: float | None = None, max: float | None = None) -> Param:
    """An angle, in degrees."""
    return Param("angle", label, min, max)


def Count(*, label: str | None = None, min: float | None = None, max: float | None = None) -> Param:
    """A whole number of things."""
    return Param("count", label, min, max)


def Number(*, label: str | None = None, min: float | None = None, max: float | None = None) -> Param:
    """A number with no unit."""
    return Param("number", label, min, max)


def _label(name: str) -> str:
    return name.replace("_", " ").capitalize()


@dataclass(frozen=True)
class FeatureDefinition:
    """A feature as declared: its name, its function and its parameters, in the function's order."""

    name: str
    fn: Callable
    params: dict[str, Param] = field(default_factory=dict)

    def describe(self) -> dict:
        """What the feature is, as plain data: for a library listing, and for an agent to call it."""
        return {
            "name": self.name,
            "function": f"{self.fn.__module__}.{self.fn.__qualname__}",
            "doc": inspect.getdoc(self.fn) or "",
            "params": [spec.describe(name) for name, spec in self.params.items()],
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


def feature(name: str | None = None, **params: Param) -> Callable[[Callable], Callable]:
    """Declare a function a feature named ``name`` (its own name, as a label, when not given), with
    ``params`` the specs of its numeric parameters, each by the function's own parameter name."""

    def declare(fn: Callable) -> Callable:
        signature = inspect.signature(fn)
        unknown = [key for key in params if key not in signature.parameters]
        if unknown:
            raise TypeError(f"@feature on {fn.__qualname__}: no parameter named {', '.join(unknown)}")
        ordered = {key: params[key] for key in signature.parameters if key in params}
        definition = FeatureDefinition(name or _label(fn.__name__), fn, ordered)

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
    return getattr(fn, "feature", None) if isinstance(getattr(fn, "feature", None), FeatureDefinition) else None


def library(module: Any) -> list[dict]:
    """Every feature a module declares, described, in the order the module defines them: a feature
    library as the agent and the toolbox read it (``describe``)."""
    found = [value for value in vars(module).values() if definition_of(value) is not None]
    return [definition_of(fn).describe() for fn in found]  # type: ignore[union-attr]
