"""Five validated MYELIN user profiles.

Profiles select ordinary presentation/workflow preferences only. They never
select a factual SINE stage, intervention colour, Resource Intent verdict, or
runtime authority state.

Phase 1 learning contract
-------------------------
Each profile also owns one stable *learning identity*.  The learning identity
is deliberately the same immutable key already used by the profile itself:

    general / study / deep_work / research / custom

No lambda value, Ebbinghaus equation, database state, recovery result, or SINE
timing lives in this module.  Later phases may use ``learning_key`` to address
that profile's independent durable learning record.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final


PROFILE_KEYS: Final[tuple[str, ...]] = (
    "general",
    "study",
    "deep_work",
    "research",
    "custom",
)


@dataclass(frozen=True, slots=True)
class ProfileSpec:
    key: str
    label: str
    description: str
    default_study_minutes: int
    default_break_minutes: int

    @property
    def learning_key(self) -> str:
        """Stable key for this profile's independent learned-model memory.

        This is identity only.  Learned values themselves belong to
        PERSISTENCE and are intentionally absent from ProfileSpec.
        """
        return self.key


PROFILES: Final = (
    ProfileSpec("general", "General", "Balanced everyday MYELIN use", 45, 10),
    ProfileSpec("study", "Study", "Structured study sessions", 50, 10),
    ProfileSpec("deep_work", "Deep Work", "Long uninterrupted work blocks", 75, 15),
    ProfileSpec("research", "Research", "Reading, analysis and research work", 60, 10),
    ProfileSpec("custom", "Custom", "User-selected ordinary preferences", 45, 10),
)

# Fail immediately if this file ever drifts away from the canonical five-profile
# identity map.  A dict alone would silently hide a duplicate key.
if tuple(item.key for item in PROFILES) != PROFILE_KEYS:
    raise RuntimeError("MYELIN profile identity/order drift detected")
if len({item.learning_key for item in PROFILES}) != len(PROFILE_KEYS):
    raise RuntimeError("MYELIN profile learning identities must be one-to-one")

_PROFILE_BY_KEY: Final = {item.key: item for item in PROFILES}


class ProfileController:
    """One small profile authority; runtime truth is deliberately excluded."""

    def __init__(self, settings) -> None:
        self._settings = settings
        self._active_key = "general"

    @property
    def active_key(self) -> str:
        return self._active_key

    @property
    def active_learning_key(self) -> str:
        """Learning-record identity for the currently selected profile."""
        return self.active.learning_key

    @property
    def active(self) -> ProfileSpec:
        return _PROFILE_BY_KEY[self._active_key]

    def all_profiles(self) -> tuple[ProfileSpec, ...]:
        return PROFILES

    def set_active(self, key: str) -> bool:
        normalized = str(key or "").strip().lower()
        if normalized not in _PROFILE_BY_KEY:
            return False
        self._active_key = normalized
        return True


__all__ = [
    "PROFILE_KEYS",
    "ProfileController",
    "ProfileSpec",
    "PROFILES",
]
