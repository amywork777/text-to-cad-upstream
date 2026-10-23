"""An exported file's requirements must match its source, without guessing identities."""
import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cadgen._internal.pmi_verification import compare, verify


def fixtures():
    entries = [
        dict(id='A', kind='datum', status='ok', refs=[dict(ref='part/f:base')], datum=dict(letter='A')),
        dict(id='bore', kind='dimension', status='ok', refs=[dict(ref='part/f:bore')],
             dimension=dict(type='diameter', nominal=dict(value=10, unit='mm'), tolerance=dict(type='plus_minus', lower=0, upper=.05))),
        dict(id='position', kind='geometric_tolerance', status='ok', refs=[dict(ref='part/f:bore')],
             geometric_tolerance=dict(characteristic='position', value=.1, unit='mm', zone='diameter', datums=['A'])),
    ]
    report = dict(schema='AP242_TEST', problems=[], ambiguousFaceNames=[],
                  datums=[dict(identification='A', features=[dict(name='f:base')])],
                  dimensions=[dict(name='diameter', features=[dict(name='f:bore')], nominal=dict(value=10, unit='mm'), tolerance=dict(lower=0, upper=.05, unit='mm'))],
                  tolerances=[dict(entity='POSITION_TOLERANCE', features=[dict(name='f:bore')], magnitude=dict(value=.1, unit='mm'), zone='cylindrical or circular', datums=['A'])])
    return entries, report


class VerificationTest(unittest.TestCase):
    def test_reader_refuses_unchecked_exported_tolerance_extensions(self):
        from cadgen._internal.ap242_pmi_report import Report, parse_builtin
        fixture = Path(__file__).resolve().parents[5] / 'docs/pmi/pmi_plate.step'
        records = parse_builtin(fixture.read_text(encoding="utf-8"))
        number = next(n for n, parts in records.items() if any(name == 'POSITION_TOLERANCE' for name, _ in parts))
        for extension in ('GEOMETRIC_TOLERANCE_WITH_MODIFIERS', 'GEOMETRIC_TOLERANCE_WITH_MAXIMUM_TOLERANCE'):
            altered = copy.deepcopy(records)
            altered[number].append((extension, (('MAXIMUM_MATERIAL_REQUIREMENT',),)))
            reader = Report(altered)
            reader.tolerances()
            self.assertTrue(any(extension in problem for problem in reader.problems), reader.problems)

    def test_matches_and_detects_changed_values_units_faces_datums_and_extras(self):
        entries, report = fixtures()
        self.assertEqual(compare(entries, report), dict(matched=3, total=3, problems=[]))
        for collection, field, value in [('dimensions', 'tolerance', dict(lower=0, upper=.5, unit='mm')),
                                          ('tolerances', 'magnitude', dict(value=.1, unit='m')),
                                          ('datums', 'features', [dict(name='f:wrong')]),
                                          ('tolerances', 'datums', ['B'])]:
            changed = copy.deepcopy(report)
            changed[collection][0][field] = value
            self.assertTrue(compare(entries, changed)['problems'])
        report['dimensions'] *= 2
        self.assertTrue(compare(entries, report)['problems'])

    def test_ambiguous_associations_fail_closed(self):
        entries, report = fixtures()
        for altered in [{**report, 'ambiguousFaceNames': ['f:bore']},
                        {k: v for k, v in report.items() if k != 'ambiguousFaceNames'},
                        {**report, 'datums': report['datums'] * 2},
                        {**report, 'problems': ['Mixed deviation units']},
                        {**report, 'schema': 'AUTOMOTIVE_DESIGN'}]:
            self.assertEqual(compare(entries, altered)['matched'], 0)
        other = copy.deepcopy(entries[1]); other['refs'][0]['ref'] = 'other/f:bore'
        self.assertEqual(compare(entries + [other], report)['matched'], 0)

    def test_unsupported_modifiers_and_empty_pmi_never_claim_success(self):
        entries, report = fixtures()
        entries[2]['geometric_tolerance']['modifier'] = 'maximum_material_condition'
        self.assertEqual(compare(entries, report)['matched'], 2)
        self.assertTrue(compare([], {**report, 'datums': [], 'dimensions': [], 'tolerances': []})['problems'])

    def test_checks_the_provided_export_and_binds_result_to_its_bytes(self):
        entries, report = fixtures()
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'export.step'; target.write_bytes(b'exported bytes')
            with patch('cadgen._internal.pmi_verification.report', return_value=report) as reader:
                result = verify(entries, target)
            reader.assert_called_once_with(target)
            self.assertEqual(result['matched'], 3)
            self.assertEqual(result['sha256'], hashlib.sha256(target.read_bytes()).hexdigest())
            with patch('cadgen._internal.pmi_verification.report', side_effect=ValueError('unsupported syntax')):
                self.assertTrue(verify(entries, target)['problems'])

    def test_the_committed_fixture_verifies_whole_basic_dimensions_included(self):
        """The plate's served PMI against its own exported STEP: every annotation, its two basic
        dimensions too (their 'theoretical' note), matched one to one."""
        from cadgen.engine import pmi
        fixture = Path(__file__).resolve().parents[5] / 'docs/pmi'
        entries = pmi.read(fixture / 'pmi_plate.xbf')
        self.assertEqual(sum(1 for e in entries if (e.get('dimension') or {}).get('basic')), 2)
        result = verify(entries, fixture / 'pmi_plate.step')
        self.assertEqual((result['matched'], result['total'], result['problems']), (9, 9, []))

    def test_a_basic_flag_the_file_does_not_carry_is_not_verified(self):
        entries, report = fixtures()
        entries.append(dict(id='hole-from-B', kind='dimension', status='ok', refs=[dict(ref='part/f:front'), dict(ref='part/f:bore')],
                            dimension=dict(type='distance', basic=True, nominal=dict(value=30, unit='mm'), tolerance=None)))
        row = dict(name='linear distance', features=[dict(name='f:front'), dict(name='f:bore')],
                   nominal=dict(value=30, unit='mm'), tolerance=None, notes=[['dimensional note', 'theoretical']])
        self.assertEqual(compare(entries, {**report, 'dimensions': report['dimensions'] + [row]})['matched'], 4)
        bare = {**row, 'notes': []}  # the same distance with no 'theoretical' note: not the basic one modelled
        self.assertEqual(compare(entries, {**report, 'dimensions': report['dimensions'] + [bare]})['matched'], 3)

    def test_reader_checks_unannotated_face_names(self):
        from cadgen._internal.ap242_pmi_report import report
        with tempfile.TemporaryDirectory() as temp:
            step = Path(temp) / 'duplicate.step'
            step.write_text("ISO-10303-21; HEADER; FILE_SCHEMA(('AP242_TEST')); ENDSEC; DATA;\n"
                            "#1=ADVANCED_FACE('f:bore',(),$,.T.);\n"
                            "#2=ADVANCED_FACE('f:bore',(),$,.T.);\nENDSEC; END-ISO-10303-21;", encoding="utf-8")
            self.assertEqual(report(step)['ambiguousFaceNames'], ['f:bore'])

    def test_reader_checks_both_deviation_units(self):
        from cadgen._internal.ap242_pmi_report import Report, parse_builtin
        reader = Report(parse_builtin("""ISO-10303-21; HEADER; ENDSEC; DATA;
          #1=PLUS_MINUS_TOLERANCE(#2,#3,$);
          #2=TOLERANCE_VALUE(#4,#5);
          #3=DIMENSIONAL_SIZE($,'diameter');
          #4=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(-0.2),#6);
          #5=LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(0.2),#7);
          #6=SI_UNIT($,.METRE.);
          #7=SI_UNIT(.MILLI.,.METRE.);
          ENDSEC; END-ISO-10303-21;"""))
        reader.plus_minus(3)
        self.assertTrue(any('unit' in problem.lower() for problem in reader.problems))
