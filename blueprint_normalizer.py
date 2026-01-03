"""
Blueprint ID normalization for GEMP card analytics.

Handles:
- Cosmetic suffixes (* for foil, T for tengwar)
- Errata sets (50-69 → 0-19)
- Defunct playtest V-sets (150-199 → 100-149)
- Promo/alt-art mappings from blueprintMapping.txt
"""

import re
from pathlib import Path
from typing import Optional


class BlueprintNormalizer:
    """
    Normalizes card blueprint IDs to their canonical form.
    
    Usage:
        normalizer = BlueprintNormalizer('blueprintMapping.txt')
        canonical = normalizer.normalize('51_84*')  # Returns '1_84'
    """
    
    # Pattern to parse blueprint IDs: set_card with optional suffixes
    ID_PATTERN = re.compile(r'^(\d+)_(\d+)([*T]*)$')
    
    def __init__(self, mapping_file: Optional[str] = None):
        """
        Initialize normalizer with optional mapping file.
        
        Args:
            mapping_file: Path to blueprintMapping.txt
        """
        self.mapping = {}
        
        if mapping_file:
            self._load_mapping(mapping_file)
    
    def _load_mapping(self, filepath: str):
        """Load promo/alt-art mappings from file."""
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Mapping file not found: {filepath}")
        
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                
                # Skip comments and empty lines
                if not line or line.startswith('#'):
                    continue
                
                parts = line.split(',')
                if len(parts) != 2:
                    continue
                
                source, target = parts[0].strip(), parts[1].strip()
                self.mapping[source] = target
    
    def normalize(self, blueprint_id: str) -> str:
        """
        Normalize a blueprint ID to its canonical form.
        
        Normalization order:
        1. Strip cosmetic suffixes (* and T)
        2. Apply set number adjustments (errata, playtest)
        3. Apply promo mapping lookup (may chain)
        
        Args:
            blueprint_id: Raw blueprint ID (e.g., '51_84*', '0_12T')
        
        Returns:
            Canonical blueprint ID (e.g., '1_84', '1_13')
        """
        if not blueprint_id:
            return blueprint_id
        
        # Step 1: Strip cosmetic suffixes
        cleaned = self._strip_suffixes(blueprint_id)
        
        # Step 2: Apply set adjustments
        adjusted = self._adjust_set(cleaned)
        
        # Step 3: Apply mapping lookup (with chain resolution)
        canonical = self._resolve_mapping(adjusted)
        
        return canonical
    
    def _strip_suffixes(self, blueprint_id: str) -> str:
        """Remove * (foil) and T (tengwar) suffixes."""
        return blueprint_id.rstrip('*T')
    
    def _adjust_set(self, blueprint_id: str) -> str:
        """
        Adjust set numbers for errata and playtest sets.
        
        - Sets 50-69 → subtract 50 (PC errata of sets 0-19)
        - Sets 150-199 → subtract 50 (defunct playtest V-sets)
        """
        match = self.ID_PATTERN.match(blueprint_id)
        if not match:
            # Non-standard ID format (e.g., 'gl_theOneRing'), return as-is
            return blueprint_id
        
        set_num = int(match.group(1))
        card_num = match.group(2)
        
        # Defunct PC playtest errata sets
        if 70 <= set_num <= 89:
            set_num -= 70
        # Defunct playtest V-sets
        elif 150 <= set_num <= 199:
            set_num -= 50
        
        return f"{set_num}_{card_num}"
    
    def _resolve_mapping(self, blueprint_id: str) -> str:
        """
        Resolve mapping chain to final canonical ID.
        
        Some mappings chain (promo → another promo → base card).
        We follow the chain up to a reasonable depth to prevent loops.
        """
        max_depth = 10
        current = blueprint_id
        
        for _ in range(max_depth):
            if current not in self.mapping:
                return current
            current = self.mapping[current]
        
        # If we hit max depth, something is wrong with the mapping
        return current
    
    def add_mapping(self, source: str, target: str):
        """Add a mapping at runtime (for testing or API updates)."""
        self.mapping[source] = target
    
    def get_mapping_count(self) -> int:
        """Return number of loaded mappings."""
        return len(self.mapping)
