#!/usr/bin/env python3
"""Backfill canonical.json for existing jobs in job_outputs/.

Wrapper script that imports from webapp.deliverables.backfill_canonical.

Usage:
    python3 scripts/backfill_canonical.py                # idempotent
    python3 scripts/backfill_canonical.py --force        # overwrite
    python3 scripts/backfill_canonical.py --root job_outputs/12  # subset
"""

import sys
from pathlib import Path

# Make webapp importable when running as a standalone script
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from webapp.deliverables.backfill_canonical import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
