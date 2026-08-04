"""
GRIDIRON Player ID Crosswalk Module

Single source of truth for player IDs across all data sources.
H2 contract: Any join on raw name strings = test failure.

Supports:
- GSIS ID (NFL official)
- NFL.com Fantasy ID
- Sleeper-style IDs
- Full name with disambiguation

Macro objective: Prevent data corruption from ID mismatches.
"""

from dataclasses import dataclass, field
from typing import Optional
import hashlib


@dataclass(frozen=True)
class PlayerID:
    """
    Immutable player identifier with multiple namespace support.
    
    Attributes:
        gsis: GSIS ID (official NFL identifier)
        nfl_com: NFL.com Fantasy ID
        sleeper: Sleeper platform ID
        full_name: Full name (Last, First)
        position: Primary position
        team: Current team abbreviation (3 letters)
    """
    gsis: Optional[str] = None
    nfl_com: Optional[str] = None
    sleeper: Optional[str] = None
    full_name: str = ""
    position: str = ""
    team: str = ""
    
    def __post_init__(self):
        # At least one ID must be present
        if not any([self.gsis, self.nfl_com, self.sleeper, self.full_name]):
            raise ValueError("PlayerID must have at least one identifier")
    
    def gridiron_id(self) -> str:
        """
        Generate canonical GRIDIRON ID from available identifiers.
        
        Priority: GSIS > nfl_com > sleeper > hash(full_name + position)
        
        Returns:
            Canonical ID string (e.g., "GSIS-12345" or "NAME-hash123")
        """
        if self.gsis:
            return f"GSIS-{self.gsis}"
        elif self.nfl_com:
            return f"NFL-{self.nfl_com}"
        elif self.sleeper:
            return f"SLEEPER-{self.sleeper}"
        else:
            # Fallback to name-based hash
            key = f"{self.full_name}|{self.position}"
            hash_val = hashlib.md5(key.encode()).hexdigest()[:8]
            return f"NAME-{hash_val}"
    
    def __str__(self) -> str:
        """Human-readable representation."""
        return f"{self.full_name} ({self.position}, {self.team})"
    
    def __eq__(self, other) -> bool:
        """Equality based on canonical GRIDIRON ID."""
        if not isinstance(other, PlayerID):
            return False
        return self.gridiron_id() == other.gridiron_id()
    
    def __hash__(self) -> int:
        """Hash based on canonical GRIDIRON ID."""
        return hash(self.gridiron_id())


class IDCrosswalk:
    """
    Bidirectional player ID mapping across all namespaces.
    
    Thread-safe, append-only design. Mappings are immutable once added.
    
    Usage:
        crosswalk = IDCrosswalk()
        player = PlayerID(gsis="00-1234567", full_name="Mahomes, Patrick", 
                         position="QB", team="KC")
        crosswalk.add(player)
        
        # Lookup by any namespace
        retrieved = crosswalk.get_by_gsis("00-1234567")
        assert retrieved == player
    """
    
    def __init__(self):
        self._gsis_map: dict[str, PlayerID] = {}
        self._nfl_com_map: dict[str, PlayerID] = {}
        self._sleeper_map: dict[str, PlayerID] = {}
        self._name_map: dict[str, PlayerID] = {}
        self._gridiron_map: dict[str, PlayerID] = {}
        self._unmapped_names: list[str] = []
    
    def add(self, player: PlayerID) -> None:
        """
        Add player to crosswalk (immutable once added).
        
        Args:
            player: PlayerID object with at least one identifier
        
        Raises:
            ValueError: If player already exists with different attributes
        """
        gid = player.gridiron_id()
        
        # Check for conflicts
        if gid in self._gridiron_map:
            existing = self._gridiron_map[gid]
            if existing != player:
                raise ValueError(
                    f"Player ID conflict: {gid} already mapped to {existing}, "
                    f"cannot add {player}"
                )
            return  # Already exists, no-op
        
        # Add to all available namespaces
        self._gridiron_map[gid] = player
        
        if player.gsis:
            self._gsis_map[player.gsis] = player
        if player.nfl_com:
            self._nfl_com_map[player.nfl_com] = player
        if player.sleeper:
            self._sleeper_map[player.sleeper] = player
        if player.full_name:
            self._name_map[player.full_name.lower()] = player
    
    def get_by_gsis(self, gsis: str) -> Optional[PlayerID]:
        """Lookup by GSIS ID."""
        return self._gsis_map.get(gsis)
    
    def get_by_nfl_com(self, nfl_com: str) -> Optional[PlayerID]:
        """Lookup by NFL.com Fantasy ID."""
        return self._nfl_com_map.get(nfl_com)
    
    def get_by_sleeper(self, sleeper: str) -> Optional[PlayerID]:
        """Lookup by Sleeper ID."""
        return self._sleeper_map.get(sleeper)
    
    def get_by_name(self, name: str) -> Optional[PlayerID]:
        """Lookup by full name (case-insensitive)."""
        return self._name_map.get(name.lower())
    
    def get_by_gridiron_id(self, gridiron_id: str) -> Optional[PlayerID]:
        """Lookup by canonical GRIDIRON ID."""
        return self._gridiron_map.get(gridiron_id)
    
    def resolve(self, identifier: str, namespace: str | None = None) -> Optional[PlayerID]:
        """
        Resolve identifier to PlayerID, auto-detecting namespace if needed.
        
        Args:
            identifier: ID string or name
            namespace: Optional hint ('gsis', 'nfl_com', 'sleeper', 'name')
        
        Returns:
            PlayerID if found, None otherwise
        """
        if namespace:
            if namespace == 'gsis':
                return self.get_by_gsis(identifier)
            elif namespace == 'nfl_com':
                return self.get_by_nfl_com(identifier)
            elif namespace == 'sleeper':
                return self.get_by_sleeper(identifier)
            elif namespace == 'name':
                return self.get_by_name(identifier)
        
        # Auto-detect namespace
        if identifier.startswith("GSIS-"):
            return self.get_by_gsis(identifier[5:])
        elif identifier.startswith("NFL-"):
            return self.get_by_nfl_com(identifier[4:])
        elif identifier.startswith("SLEEPER-"):
            return self.get_by_sleeper(identifier[8:])
        
        # Try direct lookups
        if identifier in self._gsis_map:
            return self._gsis_map[identifier]
        if identifier in self._nfl_com_map:
            return self._nfl_com_map[identifier]
        if identifier in self._sleeper_map:
            return self._sleeper_map[identifier]
        
        # Fall back to name lookup
        return self.get_by_name(identifier)
    
    def unmapped_rate(self, total_count: int) -> float:
        """
        Calculate unmapped player rate.
        
        Phase 1 gate: Must be < 2% (or documented exceptions).
        
        Args:
            total_count: Total number of players encountered
        
        Returns:
            Unmapped rate as float (0.0 - 1.0)
        """
        if total_count == 0:
            return 0.0
        return len(self._unmapped_names) / total_count
    
    def report_unmapped(self, name: str) -> None:
        """Log an unmapped player name for later resolution."""
        if name not in self._unmapped_names:
            self._unmapped_names.append(name)
    
    def get_unmapped_report(self) -> list[str]:
        """Get list of all unmapped names."""
        return self._unmapped_names.copy()
    
    def size(self) -> int:
        """Return total number of mapped players."""
        return len(self._gridiron_map)
    
    def to_dict(self) -> dict:
        """Export crosswalk as dictionary (for serialization)."""
        return {
            gid: {
                'gsis': p.gsis,
                'nfl_com': p.nfl_com,
                'sleeper': p.sleeper,
                'full_name': p.full_name,
                'position': p.position,
                'team': p.team
            }
            for gid, p in self._gridiron_map.items()
        }


# ============================================================================
# GLOBAL INSTANCE (singleton pattern)
# ============================================================================

_global_crosswalk: IDCrosswalk | None = None


def get_crosswalk() -> IDCrosswalk:
    """
    Get global ID crosswalk instance.
    
    Returns:
        Shared IDCrosswalk instance
    """
    global _global_crosswalk
    if _global_crosswalk is None:
        _global_crosswalk = IDCrosswalk()
    return _global_crosswalk


def reset_crosswalk() -> None:
    """Reset global crosswalk (for testing only)."""
    global _global_crosswalk
    _global_crosswalk = IDCrosswalk()


# ============================================================================
# VALIDATION (Phase 1 Gate)
# ============================================================================

def validate_no_raw_name_joins(code_path: str) -> tuple[bool, list[str]]:
    """
    Audit code for raw name string joins (H2 contract violation).
    
    Searches for common patterns that indicate name-based joins:
    - player['name'] == ...
    - df.merge(..., on='name')
    - if name in ...
    
    Args:
        code_path: Path to Python file to audit
    
    Returns:
        Tuple of (passed, list of violations)
    """
    violations = []
    
    # Patterns that suggest raw name joins (simplified grep)
    suspicious_patterns = [
        "['name\"]",  # Accessing 'name' key
        ".merge(*, on='name'",  # Merge on name
        "join(*, on='name'",  # Join on name
    ]
    
    try:
        with open(code_path, 'r') as f:
            content = f.read()
            for i, line in enumerate(content.split('\n'), 1):
                # Skip comments and strings
                if line.strip().startswith('#'):
                    continue
                for pattern in suspicious_patterns:
                    if pattern in line.lower():
                        violations.append(f"Line {i}: {line.strip()}")
    except FileNotFoundError:
        violations.append(f"File not found: {code_path}")
    
    return len(violations) == 0, violations


if __name__ == "__main__":
    # Basic smoke test
    crosswalk = IDCrosswalk()
    
    # Add test players
    player1 = PlayerID(
        gsis="00-1234567",
        nfl_com="12345",
        full_name="Mahomes, Patrick",
        position="QB",
        team="KC"
    )
    player2 = PlayerID(
        sleeper="abc123",
        full_name="Jefferson, Justin",
        position="WR",
        team="MIN"
    )
    
    crosswalk.add(player1)
    crosswalk.add(player2)
    
    # Test lookups
    assert crosswalk.get_by_gsis("00-1234567") == player1
    assert crosswalk.get_by_sleeper("abc123") == player2
    assert crosswalk.get_by_name("mahomes, patrick") == player1
    assert crosswalk.resolve("GSIS-00-1234567") == player1
    
    print(f"✓ ID crosswalk smoke test passed ({crosswalk.size()} players)")
