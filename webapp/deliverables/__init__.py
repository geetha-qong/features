"""Deliverables subsystem — generators + customer templates.

Importing this package registers all generators in REGISTRY. The router
imports this package once at startup so the registry is populated.
"""

from webapp.deliverables import datasheet  # noqa: F401
from webapp.deliverables import equipment_list  # noqa: F401
from webapp.deliverables import instrument_index  # noqa: F401
from webapp.deliverables import valve_list  # noqa: F401
from webapp.deliverables.registry import REGISTRY  # noqa: F401
