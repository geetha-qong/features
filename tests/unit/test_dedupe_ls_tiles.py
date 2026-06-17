"""Tests for the LS tile-dedupe selection logic (pure, no LS needed).

Safety contract: annotated duplicates are NEVER in delete_safe — deleting them
would lose labeling work, so they're surfaced separately for an explicit opt-in.
"""
from webapp.scripts.dedupe_ls_tiles import plan_dedupe


def _t(tid, image, anns=0):
    return {"id": tid, "data": {"image": image}, "total_annotations": anns}


def test_unannotated_dupes_are_safe_to_delete():
    tasks = [
        _t(1, "/u/a.png"),
        _t(2, "/u/a.png"),   # dup, no annotations → safe delete
        _t(3, "/u/b.png"),
    ]
    keep, safe, annotated = plan_dedupe(tasks)
    assert sorted(keep) == [1, 3]
    assert safe == [2]
    assert annotated == []


def test_annotated_dupes_are_held_back_not_safe():
    # both copies annotated → keep the better, the other is an ANNOTATED dupe
    # (held back, never in safe).
    tasks = [_t(10, "/u/x.png", anns=2), _t(11, "/u/x.png", anns=1)]
    keep, safe, annotated = plan_dedupe(tasks)
    assert keep == [10]            # most annotations kept
    assert safe == []              # nothing safe to delete
    assert annotated == [11]       # held back


def test_prefers_annotated_copy_then_safe_deletes_blanks():
    tasks = [
        _t(20, "/u/y.png", anns=0),
        _t(21, "/u/y.png", anns=3),  # keep (most annotations)
        _t(22, "/u/y.png", anns=0),  # safe delete
    ]
    keep, safe, annotated = plan_dedupe(tasks)
    assert keep == [21]
    assert sorted(safe) == [20, 22]
    assert annotated == []


def test_no_image_tasks_kept():
    tasks = [_t(30, ""), _t(31, None), _t(32, "/u/z.png")]
    keep, safe, annotated = plan_dedupe(tasks)
    assert sorted(keep) == [30, 31, 32]
    assert safe == [] and annotated == []


def test_no_duplicates_nothing_deleted():
    tasks = [_t(i, f"/img/{i}.png", anns=i % 2) for i in range(1, 6)]
    keep, safe, annotated = plan_dedupe(tasks)
    assert sorted(keep) == [1, 2, 3, 4, 5]
    assert safe == [] and annotated == []


from webapp.scripts.dedupe_ls_tiles import normalize_result, build_groups


def test_normalize_result_ignores_region_id_and_order():
    a = [{"id": "AAA", "from_name": "label", "type": "rectanglelabels",
          "value": {"x": 1, "rectanglelabels": ["valve_bv"]}}]
    b = [{"id": "ZZZ", "from_name": "label", "type": "rectanglelabels",
          "value": {"x": 1, "rectanglelabels": ["valve_bv"]}}]
    assert normalize_result(a) == normalize_result(b)  # same label, different id


def test_normalize_result_distinguishes_different_labels():
    a = [{"id": "1", "value": {"rectanglelabels": ["valve_bv"]}}]
    b = [{"id": "1", "value": {"rectanglelabels": ["valve_gt"]}}]
    assert normalize_result(a) != normalize_result(b)


def test_build_groups_keeper_is_most_annotated():
    tasks = [
        _t(1, "/u/a.png", anns=0),
        _t(2, "/u/a.png", anns=3),  # keeper
        _t(3, "/u/a.png", anns=1),
        _t(4, "/u/solo.png", anns=0),  # singleton → not a group
    ]
    groups = build_groups(tasks)
    assert len(groups) == 1
    keeper, dups = groups[0]
    assert keeper["id"] == 2
    assert sorted(d["id"] for d in dups) == [1, 3]
