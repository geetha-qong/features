"""
Stage 5b validator: write Instrument Index CSV (21 columns).

Column order matches the deliverable:
  ref/05011-CPP-01-00-4V-IIN-01-K-101-0001_M.pdf
"""
import pandas as pd

from instrument_parser import InstrumentRow


def write_instrument_index(rows: list, output_path: str = "docs/instrumentation_index.csv") -> None:
    """Write InstrumentRow list to a 21-column CSV."""
    data = [row.to_csv_dict() for row in rows]
    df = pd.DataFrame(data)
    if df.empty:
        df = pd.DataFrame(columns=list(InstrumentRow().to_csv_dict().keys()))
    df.to_csv(output_path, index=False, encoding="utf-8")
    print(f"  Wrote {len(rows)} instruments to {output_path}")
