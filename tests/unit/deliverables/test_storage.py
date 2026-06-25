from pathlib import Path

from webapp.deliverables.storage import store_export


def test_store_export_writes_file_to_exports_subdir(tmp_path):
    csv_path = tmp_path / "42" / "valve_list.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("")

    out_path = store_export(
        output_csv_path=str(csv_path),
        deliverable_type="valve_list",
        file_format="xlsx",
        content=b"\x50\x4b\x03\x04PK fake xlsx",
    )

    assert Path(out_path).exists()
    assert Path(out_path).read_bytes() == b"\x50\x4b\x03\x04PK fake xlsx"
    assert Path(out_path).name == "valve_list.xlsx"
    assert Path(out_path).parent.name == "exports"


def test_store_export_overwrites_existing(tmp_path):
    csv_path = tmp_path / "42" / "valve_list.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("")

    store_export(str(csv_path), "valve_list", "csv", b"first")
    out_path = store_export(str(csv_path), "valve_list", "csv", b"second")

    assert Path(out_path).read_bytes() == b"second"
