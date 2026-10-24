from collections import defaultdict
import unittest

from gamedb.arcade.samples import attach_samples


class SampleTests(unittest.TestCase):
    def fixture(self):
        plan = dict(assets=[], complete=False, missing=[dict(kind='sample', name='boom', sampleOf='blockade', owner='clone', reason='missing_sample_inventory')])
        definitions = {'blockade': {'rom': [dict(name='boom.wav', size='4', crc='12345678')]}}
        inventory = defaultdict(list, {'blockade': [dict(member='boom.wav', size=4, crc='12345678', sha1='a' * 40, path='/roms/samples/blockade.zip')]})
        return plan, definitions, inventory

    def test_parent_sample_set_is_bundled_under_private_system_directory(self):
        plan, definitions, inventory = self.fixture()
        result = attach_samples(plan, definitions, inventory, 'digest')
        self.assertTrue(result['complete'])
        self.assertEqual(result['systemDirectory'], 'system')
        self.assertEqual(result['assets'][0]['installRoot'], 'system')
        self.assertEqual(result['assets'][0]['installPath'], 'fbneo/samples/blockade.zip')
        self.assertEqual(result['assets'][0]['requiredMembers'][0]['sha1'], 'a' * 40)
        self.assertFalse(plan['complete'])

    def test_name_without_matching_checksum_is_not_sufficient(self):
        plan, definitions, inventory = self.fixture()
        inventory['blockade'][0]['crc'] = '00000000'
        result = attach_samples(plan, definitions, inventory, 'digest')
        self.assertFalse(result['complete'])
        self.assertEqual(result['missing'][0]['reason'], 'missing_inventory')

    def test_missing_sample_definition_is_distinct_from_missing_file(self):
        plan, definitions, inventory = self.fixture()
        definitions['blockade']['rom'] = []
        result = attach_samples(plan, definitions, inventory, 'digest')
        self.assertEqual(result['missing'][0]['reason'], 'missing_sample_definition')
