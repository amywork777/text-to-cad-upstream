"""Compare supported source PMI with an independent reader of the actual STEP output.

This is a bounded semantic check, not importer certification or a full AP242 validator.
Face names must be unique across the geometry; ambiguous associations fail closed.
"""
from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from pathlib import Path

from .ap242_pmi_report import report


def _near(a, b):
    return (isinstance(a, (int, float)) and isinstance(b, (int, float))
            and math.isfinite(a) and math.isfinite(b)
            and abs(a - b) <= 1e-9 * max(1, abs(a), abs(b)))


def _measure(actual, expected):
    return (isinstance(actual, dict) and isinstance(expected, dict)
            and actual.get('unit') == expected.get('unit')
            and _near(actual.get('value'), expected.get('value')))


def _matches(entry, row):
    refs = entry.get('refs') or []
    if not refs or any(not isinstance(ref.get('ref'), str) or ref.get('status', 'ok') != 'ok' for ref in refs):
        return False
    names = sorted(ref['ref'].rsplit('/', 1)[-1] for ref in refs)
    if names != sorted(feature.get('name', '') for feature in row.get('features', [])):
        return False
    if entry['kind'] == 'datum':
        letter = (entry.get('datum') or {}).get('letter')
        return bool(letter) and row.get('identification') == letter
    if entry['kind'] == 'dimension':
        dimension = entry.get('dimension') or {}
        kind = dimension.get('type')
        if kind not in ('diameter', 'distance') or row.get('name') != {'diameter': 'diameter', 'distance': 'linear distance'}[kind]:
            return False
        nominal = dimension.get('nominal')
        if not _measure(row.get('nominal'), nominal):
            return False
        # A basic dimension carries AP242's 'theoretical' note (CAx-IF 5.3), and nothing else does.
        if bool(dimension.get('basic')) != (['dimensional note', 'theoretical'] in (row.get('notes') or [])):
            return False
        tolerance, actual = dimension.get('tolerance'), row.get('tolerance')
        if tolerance is None:
            return actual is None
        return (tolerance.get('type') == 'plus_minus' and isinstance(actual, dict)
                and actual.get('unit') == nominal.get('unit')
                and _near(actual.get('lower'), tolerance.get('lower'))
                and _near(actual.get('upper'), tolerance.get('upper')))
    if entry['kind'] != 'geometric_tolerance':
        return False
    tolerance = entry.get('geometric_tolerance') or {}
    characteristic = tolerance.get('characteristic')
    # The reader does not establish material modifiers or more general zone semantics.
    if characteristic not in ('flatness', 'position') or tolerance.get('modifier') or tolerance.get('zone') not in (None, '', 'diameter'):
        return False
    return (row.get('entity') == characteristic.upper() + '_TOLERANCE'
            and _measure(row.get('magnitude'), tolerance)
            and row.get('datums', []) == tolerance.get('datums', [])
            and row.get('zone') == ('cylindrical or circular' if tolerance.get('zone') == 'diameter' else None))


def compare(entries: list[dict], parsed: dict) -> dict:
    problems = list(parsed.get('problems') or [])
    if not entries:
        problems.append('The model has no PMI to verify.')
    if not str(parsed.get('schema', '')).startswith('AP242_'):
        problems.append('The file does not declare AP242.')
    refs = defaultdict(set)
    for entry in entries:
        for ref in entry.get('refs', []):
            if isinstance(ref.get('ref'), str):
                refs[ref['ref'].rsplit('/', 1)[-1]].add(ref['ref'])
    if any(len(values) > 1 for values in refs.values()):
        problems.append('Different model parts reuse a face name; their exported associations cannot be verified.')
    ambiguous = parsed.get('ambiguousFaceNames')
    if not isinstance(ambiguous, list):
        problems.append('The reader did not establish whether exported face names are unique.')
    elif any(name in refs for name in ambiguous):
        problems.append('An exported face name is ambiguous across the geometry; its association cannot be verified.')
    letters = [datum.get('identification') for datum in parsed.get('datums', [])]
    if len(set(letters)) != len(letters):
        problems.append('Exported datum letters are repeated; their references cannot be verified.')
    result = dict(matched=0, total=len(entries), problems=problems)
    if problems:
        return result
    remaining = list(parsed.get('datums', [])) + list(parsed.get('dimensions', [])) + list(parsed.get('tolerances', []))
    for entry in entries:
        match = next((i for i, row in enumerate(remaining) if entry.get('status') == 'ok' and _matches(entry, row)), None)
        if match is None:
            problems.append(f"{entry.get('label') or entry.get('id')}: values, units, datum order or face association could not be verified.")
        else:
            remaining.pop(match)
            result['matched'] += 1
    if remaining:
        problems.append(f'{len(remaining)} exported annotations did not match the model.')
    return result


def verify(entries: list[dict], target: Path) -> dict:
    """Verification stays attached to this artifact, even after the viewer changes files."""
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    try:
        result = compare(entries, report(target))
    except Exception as error:
        result = dict(matched=0, total=len(entries), problems=[f'The STEP reader could not complete the check: {error}'])
    return {**result, 'sha256': digest}
