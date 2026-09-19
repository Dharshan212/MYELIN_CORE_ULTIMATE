"""MYELIN Science Lab organ package boundary.

Science Lab is MYELIN's silent evidence layer: it presents chapters that
explain and, later, will report on behavioural evidence produced by the
existing MYELIN authorities (Monitor, SINE, MIRL, MINE, COSINE, ...).  It is
not a second monitoring engine, and importing this package must never start
one, open a database, or create an experiment.

Module map:

- ``lab``      -- display / UI (``ScienceLabWorkspace``).
- ``chapters`` -- chapter structure and static content.
- ``engine``   -- future Science Lab analysis coordinator (skeleton only).
- ``evidence`` -- future Science Lab evidence read/write boundary (skeleton only).
- ``report``   -- future research-PDF authority (skeleton only).
"""

from __future__ import annotations

from .lab import ScienceLabWorkspace

__all__ = ["ScienceLabWorkspace"]
