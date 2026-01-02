"""
Tests for BlueprintNormalizer.

Run with: python -m pytest test_normalizer.py -v
Or simply: python test_normalizer.py
"""

import unittest
from blueprint_normalizer import BlueprintNormalizer


class TestBlueprintNormalizer(unittest.TestCase):
    
    def setUp(self):
        """Create normalizer without mapping file for algorithmic tests."""
        self.normalizer = BlueprintNormalizer()
    
    def test_strip_foil_suffix(self):
        """* suffix (foil) should be stripped."""
        self.assertEqual(self.normalizer.normalize('1_84*'), '1_84')
    
    def test_strip_tengwar_suffix(self):
        """T suffix (tengwar) should be stripped."""
        self.assertEqual(self.normalizer.normalize('1_84T'), '1_84')
    
    def test_strip_combined_suffixes(self):
        """Both * and T suffixes should be stripped."""
        self.assertEqual(self.normalizer.normalize('1_84*T'), '1_84')
        self.assertEqual(self.normalizer.normalize('1_84T*'), '1_84')
    
    def test_errata_set_normalization(self):
        """Sets 50-69 should map to 0-19 (PC errata)."""
        self.assertEqual(self.normalizer.normalize('51_84'), '1_84')
        self.assertEqual(self.normalizer.normalize('50_1'), '0_1')
        self.assertEqual(self.normalizer.normalize('69_99'), '19_99')
    
    def test_errata_set_with_suffix(self):
        """Errata normalization should work with cosmetic suffixes."""
        self.assertEqual(self.normalizer.normalize('51_84*'), '1_84')
        self.assertEqual(self.normalizer.normalize('51_84T'), '1_84')
    
    def test_playtest_vset_normalization(self):
        """Sets 150-199 should map to 100-149 (defunct playtest V-sets)."""
        self.assertEqual(self.normalizer.normalize('150_1'), '100_1')
        self.assertEqual(self.normalizer.normalize('151_20'), '101_20')
        self.assertEqual(self.normalizer.normalize('199_99'), '149_99')
    
    def test_normal_sets_unchanged(self):
        """Normal sets should not be modified."""
        self.assertEqual(self.normalizer.normalize('1_84'), '1_84')
        self.assertEqual(self.normalizer.normalize('19_1'), '19_1')
        self.assertEqual(self.normalizer.normalize('100_5'), '100_5')
        self.assertEqual(self.normalizer.normalize('101_20'), '101_20')
    
    def test_vsets_unchanged(self):
        """V-sets (100-149) should not be modified."""
        self.assertEqual(self.normalizer.normalize('101_3'), '101_3')
        self.assertEqual(self.normalizer.normalize('102_29'), '102_29')
    
    def test_empty_and_none(self):
        """Empty string and None should pass through."""
        self.assertEqual(self.normalizer.normalize(''), '')
        self.assertEqual(self.normalizer.normalize(None), None)


class TestBlueprintNormalizerWithMapping(unittest.TestCase):
    
    def setUp(self):
        """Create normalizer with some test mappings."""
        self.normalizer = BlueprintNormalizer()
        # Add test mappings manually
        self.normalizer.add_mapping('0_12', '1_13')  # Promo Legolas -> base
        self.normalizer.add_mapping('gl_theOneRing', '1_2')  # Special ID
        self.normalizer.add_mapping('chain_a', 'chain_b')  # Chain test
        self.normalizer.add_mapping('chain_b', '1_1')
    
    def test_simple_mapping(self):
        """Direct mapping should resolve."""
        self.assertEqual(self.normalizer.normalize('0_12'), '1_13')
    
    def test_special_id_mapping(self):
        """Non-standard IDs should map correctly."""
        self.assertEqual(self.normalizer.normalize('gl_theOneRing'), '1_2')
    
    def test_mapping_chain(self):
        """Chained mappings should resolve to final target."""
        self.assertEqual(self.normalizer.normalize('chain_a'), '1_1')
    
    def test_unmapped_passthrough(self):
        """Unmapped IDs should pass through unchanged."""
        self.assertEqual(self.normalizer.normalize('1_999'), '1_999')
    
    def test_suffix_then_mapping(self):
        """Suffixes should be stripped before mapping lookup."""
        # Add mapping for base ID
        self.normalizer.add_mapping('1_50', '1_51')
        # Foil version should strip suffix then map
        self.assertEqual(self.normalizer.normalize('1_50*'), '1_51')


class TestSetAdjustmentEdgeCases(unittest.TestCase):
    
    def setUp(self):
        self.normalizer = BlueprintNormalizer()
    
    def test_boundary_49(self):
        """Set 49 should NOT be adjusted (it's in the unused 40-49 range)."""
        self.assertEqual(self.normalizer.normalize('49_1'), '49_1')
    
    def test_boundary_70(self):
        """Set 70 should NOT be adjusted (defunct playtest, but not in 50-69)."""
        self.assertEqual(self.normalizer.normalize('70_1'), '70_1')
    
    def test_boundary_149(self):
        """Set 149 should NOT be adjusted."""
        self.assertEqual(self.normalizer.normalize('149_1'), '149_1')
    
    def test_boundary_200(self):
        """Set 200 should NOT be adjusted."""
        self.assertEqual(self.normalizer.normalize('200_1'), '200_1')


if __name__ == '__main__':
    unittest.main()
