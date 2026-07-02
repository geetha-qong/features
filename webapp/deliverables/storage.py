"""Persist generated deliverables to disk alongside job outputs."""

from pathlib import Path


def store_export(
    output_csv_path: str,
    deliverable_type: str,
    file_format: str,
    content: bytes,
) -> str:
    """Write `content` to {job_dir}/exports/{deliverable_type}.{file_format}.

    Returns the absolute path of the written file. Creates the exports/
    directory if missing. Overwrites any existing file of the same name.
    """
    job_dir = Path(output_csv_path).parent
    exports_dir = job_dir / "exports"
    exports_dir.mkdir(exist_ok=True)
    out_path = exports_dir / f"{deliverable_type}.{file_format}"
    out_path.write_bytes(content)
    return str(out_path)
