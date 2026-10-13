import copy
import unittest

from check_research_response import validate_analysis, validate_indicators


class ResearchResponseTests(unittest.TestCase):
    def setUp(self):
        self.approved = {'symbol': 'TEST', 'history': [1], 'probabilityUp': 41.7,
                         'model': {'servingMode': 'approved_artifact', 'modelRunId': 'run-1'}}
        self.experimental = {'symbol': 'TEST', 'history': [1], 'probabilityUp': 52,
                             'predictionAvailable': True, 'experimental': True,
                             'model': {'servingMode': 'experimental_runtime', 'quality': 'unapproved'},
                             'predictionStatus': {'code': 'EXPERIMENTAL_ESTIMATE'}}

    def test_legacy_approved_without_flag(self):
        self.assertEqual(validate_analysis(self.approved, 'TEST'), 'approved_artifact')

    def test_approved_with_flag(self):
        self.approved['predictionAvailable'] = True
        validate_analysis(self.approved, 'TEST')

    def test_experimental(self):
        validate_analysis(self.experimental, 'TEST')

    def test_invalid_probability(self):
        for value in (None, True, '50', float('nan'), float('inf'), -1, 101):
            with self.subTest(value=value):
                self.approved['probabilityUp'] = value
                with self.assertRaises(ValueError):
                    validate_analysis(self.approved, 'TEST')

    def test_explicit_unavailability(self):
        self.approved['predictionAvailable'] = False
        with self.assertRaises(ValueError):
            validate_analysis(self.approved, 'TEST')

    def test_required_experimental_fields(self):
        for key in ('predictionAvailable', 'experimental', 'predictionStatus', 'model'):
            data = copy.deepcopy(self.experimental)
            del data[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_analysis(data, 'TEST')

    def test_missing_approved_run(self):
        del self.approved['model']['modelRunId']
        with self.assertRaises(ValueError):
            validate_analysis(self.approved, 'TEST')

    def test_wrong_symbol_or_missing_history(self):
        with self.assertRaises(ValueError):
            validate_analysis(self.approved, 'OTHER')
        self.approved['history'] = []
        with self.assertRaises(ValueError):
            validate_analysis(self.approved, 'TEST')

    def test_indicator_check(self):
        data = {'technicalIndicators': {'rsi14': 0}, 'expectedRange': {'low': 90, 'high': 110}}
        validate_indicators(data, 'TEST')
        for value in (None, float('nan'), True, 101):
            data['technicalIndicators']['rsi14'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_indicators(data, 'TEST')
        data['technicalIndicators']['rsi14'] = 50
        data['expectedRange']['high'] = None
        with self.assertRaises(ValueError):
            validate_indicators(data, 'TEST')


if __name__ == '__main__':
    unittest.main()
