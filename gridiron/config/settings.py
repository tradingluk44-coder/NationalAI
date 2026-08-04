"""
GRIDIRON Configuration Settings
Loaded from league_config.yaml with runtime overrides.
"""
import yaml
from pathlib import Path
from typing import Any, Dict

# Load main league config
CONFIG_PATH = Path(__file__).parent.parent / "league_config.yaml"

with open(CONFIG_PATH, 'r') as f:
    _base_config = yaml.safe_load(f)

# Runtime settings
CONFIG: Dict[str, Any] = {
    **_base_config,
    
    # Posture logic thresholds (I5)
    'posture': {
        'tossup_lower': 0.40,
        'tossup_upper': 0.60,
    },
    
    # Waiver priority threshold (I8)
    'waivers': {
        'priority_cutoff': 0.04,  # Spend top-3 priority only if ΔP(playoffs) >= 4pp
    },
    
    # Simulation defaults
    'sim': {
        'n_iterations': 10000,
        'seed': 42,
    },
    
    # Paths
    'paths': {
        'data': Path(__file__).parent.parent / 'data',
        'models': Path(__file__).parent.parent / 'models',
        'warehouse': Path(__file__).parent.parent / 'data' / 'warehouse.duckdb',
    }
}

# Validate critical keys
assert 'scoring' in CONFIG, "Missing scoring config"
assert 'roster' in CONFIG, "Missing roster config"
assert 'playoffs' in CONFIG, "Missing playoffs config"

if __name__ == "__main__":
    print("Configuration loaded successfully.")
    print(f"Teams: {CONFIG['teams']}")
    print(f"Scoring: PPR={CONFIG['scoring']['receiving']['reception']}")
    print(f"Playoff Teams: {CONFIG['playoffs']['teams']}")
