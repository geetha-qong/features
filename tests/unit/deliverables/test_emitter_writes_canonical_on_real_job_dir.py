"""Smoke test: write_canonical_for_job works against a realistic job_dir
shape (same as what webapp/pipeline_runner.py produces)."""

import csv
import json
from pathlib import Path

from webapp.deliverables.canonical import JobCanonical
from webapp.deliverables.pipeline_emitter import write_canonical_for_job


def test_realistic_job_dir(tmp_path):
    job_dir = tmp_path / "100"
    job_dir.mkdir()
    # Mimic what pipeline.run() writes
    (job_dir / "tmp").mkdir()  # tmp subdir
    with (job_dir / "valve_list.csv").open("w", newline="") as f:
        csv.writer(f).writerows([
            ['P&ID No','Dynamic Code','Category','Size','Area Code','Serial No','Series Code','Fluid Code','Piping Class','Qty','Motor Actuator','Pneumatic Actuator ','Solenoid','line'],
            ['VEN-M5BC-6-50-0002','-','GL','4','62','100001','-','G','AC-PP','1','-','-','-','4"-G-62100001-AC-PP'],
        ])
    with (job_dir / "instrumentation_index.csv").open("w", newline="") as f:
        csv.writer(f).writerows([
            ['Rev No','Unit Number','Loop Name','Tag Number','Instrument Type','Service Description','P&ID No','Line No','Equipment No','Location','System','Technical Room','IO Type','Signal Type','Signal Level','IO Grouping','External Power Supply','Analog Range Low','Analog Range High','Analog Range EU','HH Alarm Limit','H Alarm Limit','L Alarm Limit','LL Alarm Limit','Junction Box/Panel','Multi-Cable Pair No','Manufacturer','Model No','Inst. Datasheet','Hook-up Drawing','Remark'],
            ['0','422-11','422-11-P-006','422-11-PT-006A','PT','COMP SUCTION PRESS','VEN-M5BC-6-50-0002','LATER','422-11-K-001A','FIELD','UCP','','AI','4-20mA','','','','0','150','bar','-','-','-','-','','','Yokogawa','EJX130A','','',''],
        ])

    result = write_canonical_for_job(job_dir=job_dir, job_id=100)
    assert result.canonical_path.exists()
    data = json.loads(result.canonical_path.read_text())
    job = JobCanonical.model_validate(data)
    assert job.job_id == 100
    classes = sorted({e.entity_class for e in job.entities})
    assert classes == ["instrument", "valve"]
    assert len(job.entities) == 2

    pt = next(e for e in job.entities if e.entity_class == "instrument")
    assert pt.vendor_match is not None
    assert pt.vendor_match.vendor_name == "Yokogawa"

    valve = next(e for e in job.entities if e.entity_class == "valve")
    assert valve.tag == "62-GL-100001"
