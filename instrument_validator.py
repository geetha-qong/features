"""
Stage 5b validator: write Instrumentation Index CSV (30 columns).

Column order matches the reference document:
  ref/26E009A001_Instrument index R0.pdf
"""
import pandas as pd

from instrument_parser import InstrumentRow


def write_instrument_index(rows: list, output_path: str = "docs/instrumentation_index.csv") -> None:
    """Write InstrumentRow list to a 30-column CSV."""
    data = [row.to_csv_dict() for row in rows]
    df = pd.DataFrame(data)
    if df.empty:
        # Write header-only file so downstream code always finds the file
        df = pd.DataFrame(columns=list(InstrumentRow().to_csv_dict().keys()))
    df.to_csv(output_path, index=False, encoding="utf-8")
    print(f"  Wrote {len(rows)} instruments to {output_path}")
