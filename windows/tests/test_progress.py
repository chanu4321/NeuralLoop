"""Progress.swift and PlayCoverage.swift: the same cases as ProgressMergeTests and PlayCoverageTests."""

import json

from neuralloop_desktop.core import coverage, progress


def p(text: str) -> dict:
    return progress.normalize(json.loads(text))


def test_reads_what_the_study_site_and_the_mac_write():
    x = p("""{"cards":{"1:0":{"s":3.7,"d":5.2,"reps":1,"last":100,"due":400}},"quiz":{"1":{"score":2}},
     "loop":{"1":{"prime":10,"read":20,"closedShown":true}},"mapPos":{"k1":[1,2]},"mapSeen":[1],
     "last":{"n":1,"stage":"recall"},"log":{"2026-09-28":900}}""")
    assert (
        x["cards"]["1:0"]["reps"] == 1
        and x["loop"]["1"]["closedShown"] == 1
        and x["log"]["2026-09-28"] == 900
    )
    assert x["last"] == {"n": 1, "stage": "recall"}


def test_two_devices_reviewing_the_same_card_keep_the_latest_review():
    mac = p('{"cards":{"1:0":{"s":3,"d":5,"reps":1,"last":100,"due":500}},"updatedAt":900}')
    pad = p('{"cards":{"1:0":{"s":9,"d":4,"reps":2,"last":700,"due":9000}},"updatedAt":800}')
    m = progress.merged([mac, pad])
    assert m["cards"]["1:0"]["reps"] == 2 and m["cards"]["1:0"]["last"] == 700


def test_a_step_done_anywhere_is_done():
    mac = p('{"loop":{"1":{"prime":30,"read":40}}}')
    pad = p('{"loop":{"1":{"prime":10,"recall":50}},"updatedAt":5}')
    assert progress.merged([mac, pad])["loop"]["1"] == {"prime": 10, "read": 40, "recall": 50}


def test_study_time_adds_up_across_devices():
    mac = p('{"log":{"2026-09-28":600,"2026-09-27":60}}')
    pad = p('{"log":{"2026-09-28":300}}')
    assert progress.merged([mac, pad])["log"] == {"2026-09-28": 900, "2026-09-27": 60}


def test_two_copies_of_this_devices_file_merge_without_counting_study_time_twice():
    mine = p(
        '{"cards":{"1:0":{"s":3,"d":5,"reps":1,"last":100,"due":500}},"loop":{"1":{"prime":10}},'
        '"log":{"2026-09-28":600},"updatedAt":100}'
    )
    disk = p(
        '{"cards":{"1:1":{"s":3,"d":5,"reps":1,"last":200,"due":600}},"loop":{"1":{"read":20}},'
        '"log":{"2026-09-28":615,"2026-09-27":30},"updatedAt":200}'
    )
    m = progress.merged_same_device(mine, disk)
    assert set(m["cards"]) == {"1:0", "1:1"} and m["loop"]["1"] == {"prime": 10, "read": 20}
    assert m["log"] == {"2026-09-28": 615, "2026-09-27": 30}


def test_a_device_saves_the_merged_view_but_only_its_own_study_time(tmp_path):
    (tmp_path / "devices").mkdir()
    (tmp_path / "progress.json").write_text('{"log":{"2026-09-28":600},"loop":{"1":{"prime":5}}}')
    (tmp_path / "devices" / "ipad1.json").write_text('{"log":{"2026-09-28":300},"loop":{"1":{"read":9}}}')
    own, merged = progress.load_merged(tmp_path)
    assert merged["log"] == {"2026-09-28": 900} and merged["loop"]["1"] == {"prime": 5, "read": 9}
    progress.save(merged, tmp_path, own_log=own["log"])
    own2, merged2 = progress.load_merged(tmp_path)
    assert own2["log"] == {"2026-09-28": 600} and merged2["log"] == {"2026-09-28": 900}


def test_one_odd_entry_does_not_lose_the_rest():
    x = p("""{"cards":{"1:0":{"s":3,"d":5,"reps":1,"last":100,"due":400},"1:1":{"s":"oops"}},
     "log":{"2026-09-28":900,"x":"y"},"loop":{"1":{"prime":10,"read":"soon"}},"mapPos":{"a":[1,2],"b":[1]},
     "quiz":7,"updatedAt":"later"}""")
    assert list(x["cards"]) == ["1:0"] and x["log"] == {"2026-09-28": 900} and x["loop"]["1"] == {"prime": 10}
    assert x["mapPos"] == {"a": [1, 2]} and x["quiz"] == {} and x["updatedAt"] == 0


def test_an_unreadable_progress_file_is_kept_aside_not_overwritten(tmp_path):
    assert progress.load(tmp_path) == progress.empty()
    (tmp_path / "progress.json").write_text("{not json")
    assert progress.load(tmp_path, now=42) == progress.empty()
    assert (tmp_path / "progress.json.unreadable-42").read_text() == "{not json"


def test_where_you_left_off_comes_from_the_latest_device():
    mac = p('{"last":{"n":1,"stage":"read"},"mapSeen":[1],"updatedAt":100}')
    pad = p('{"last":{"n":2,"stage":"prime"},"mapSeen":[2],"updatedAt":200}')
    m = progress.merged([pad, mac])
    assert m["last"] == {"n": 2, "stage": "prime"} and m["mapSeen"] == [1, 2] and m["updatedAt"] == 200


def test_merging_is_idempotent_and_order_free():
    a, b = progress.empty(), progress.empty()
    progress.set_quiz(a, "1", "a", 10)
    progress.set_last(a, 1, "read", 40)
    a["log"] = {"d": 10}
    progress.set_quiz(b, "1", "b", 20)
    progress.set_remake(b, "1", "b", 5)
    b["log"] = {"d": 5}
    progress.set_last(b, 3, "map", 30)
    once = progress.merged([a, b])
    saved = dict(once, log=a["log"])
    assert progress.merged([saved, b]) == once and progress.merged([b, saved]) == once
    assert progress.merged([b, a]) == once
    assert once["quiz"]["1"] == "b" and once["last"] == {"n": 1, "stage": "read"} and once["log"] == {"d": 15}


def test_a_stale_save_does_not_roll_back_another_devices_newer_work(tmp_path):
    (tmp_path / "devices").mkdir()
    mac = progress.empty()
    progress.set_quiz(mac, "3", {"i": 1}, 500)
    progress.set_remake(mac, "2", {"guess": "old"}, 500)
    progress.set_last(mac, 1, "read", 500)
    mac["log"] = {"2026-09-29": 60}
    progress.save(mac, tmp_path, own_log=mac["log"])
    own, view = progress.load_merged(tmp_path)
    pad = json.loads(json.dumps(view))
    pad["log"] = {"2026-09-29": 30}
    progress.set_quiz(pad, "3", {"i": 4}, 2000)
    progress.set_remake(pad, "2", {"guess": "new"}, 2000)
    progress.set_last(pad, 2, "recall", 2000)
    progress.set_map_pos(pad, "k1", [5, 6], 2000)
    (tmp_path / "devices" / "ipad1.json").write_bytes(progress.encode(pad))
    stale = json.loads(json.dumps(view))
    progress.set_quiz(stale, "5", {"i": 2}, 3000)
    progress.set_map_pos(stale, "k1", [1, 1], 100)
    progress.save(stale, tmp_path, own_log=own["log"])
    for m in (progress.load_merged(tmp_path)[1], progress.merged([pad, progress.load(tmp_path)])):
        assert m["quiz"]["3"] == {"i": 4} and m["quiz"]["5"] == {"i": 2}
        assert m["remake"]["2"] == {"guess": "new"}
        assert m["last"] == {"n": 2, "stage": "recall"} and m["mapPos"]["k1"] == [5, 6]
        assert m["log"] == {"2026-09-29": 90}
    assert progress.load(tmp_path)["log"] == {"2026-09-29": 60}


def test_stamps_round_trip_and_old_files_have_none():
    assert p('{"quiz":{"1":{"i":1}},"updatedAt":5}')["stamps"] == {}
    assert p('{"stamps":{"quiz.1":7,"bad":"x"}}')["stamps"] == {"quiz.1": 7}
    x = progress.empty()
    progress.set_quiz(x, "2", True, 9)
    assert progress.normalize(json.loads(progress.encode(x))) == x
    assert x["stamps"] == {"quiz.2": 9} and x["updatedAt"] == 9


def test_files_are_byte_stable_and_leave_out_empty_watching_and_reading():
    text = progress.encode(progress.empty()).decode()
    assert "watch" not in text and "reading" not in text and '"updatedAt":0' in text
    assert progress.encode(progress.empty()) == progress.encode(progress.empty())


# Playback coverage.


def play(cover, start, end, rate=1.0):
    t = start
    while t < end:
        nxt = min(end, t + rate)
        cover, _ = coverage.add(cover, t, nxt, rate, 1)
        t = nxt
    return cover


def test_playing_straight_through_covers_the_whole_thing():
    c = play([], 0, 100)
    assert c == [[0, 100]] and coverage.fraction(c, 100) == 1


def test_a_seek_does_not_count_the_skipped_part():
    c = play([], 0, 10)
    c, counted = coverage.add(c, 10, 80, 1, 1)
    assert not counted
    c = play(c, 80, 100)
    assert c == [[0, 10], [80, 100]] and abs(coverage.fraction(c, 100) - 0.3) < 1e-9


def test_scrubbing_in_small_jumps_counts_nothing():
    c = []
    for start in range(0, 100, 15):
        c, _ = coverage.add(c, start, start + 15, 1, 0.2)
    assert coverage.fraction(c, 100) == 0


def test_faster_than_double_speed_does_not_count_but_double_speed_does():
    c, counted = coverage.add([], 0, 3, 3, 1)
    assert not counted
    c, counted = coverage.add(c, 0, 2, 2, 1)
    assert counted and c == [[0, 2]]
    assert not coverage.add(c, 2, 7, 1, 1)[1]


def test_replaying_and_going_backwards_add_nothing():
    c = play(play(play([], 0, 40), 0, 40), 30, 50)
    assert c == [[0, 50]] and coverage.fraction(c, 100) == 0.5
    assert not coverage.add([], 20, 10, 1, 1)[1] and not coverage.add([], 0, 1, 0, 1)[1]
    assert not coverage.add([], 0, float("nan"), 1, 1)[1]


def test_spans_from_a_file_are_tidied_and_clipped():
    assert coverage.fraction(coverage.spans([[90, 130]]), 100) == 0.1
    c = coverage.spans([[30, 40], [0, 10], [5, 20], [50, 45], [60, 60]])
    assert c == [[0, 20], [30, 40]] and coverage.union(c, [[15, 35]]) == [[0, 40]]


def test_listening_is_done_at_eighty_five_percent_of_the_podcast_or_the_video():
    w = {"audio": [[0, 84]], "video": []}
    assert not coverage.listening_done(w, 100, 50)
    w["audio"] = [[0, 85]]
    assert coverage.listening_done(w, 100, None)
    w = {"audio": [], "video": [[0, 43]]}
    assert coverage.listening_done(w, 100, 50) and not coverage.listening_done(w, 100, None)
    assert not coverage.listening_done(None, 100, 50)
    assert coverage.listening_share(w, 100, 50) == 0.86


def test_watching_round_trips_compactly_and_merges_as_a_union():
    x = p('{"watch":{"2":{"audio":[[0,12.34],[20,"x"],[5]],"video":"nope"},"x":7}}')
    assert x["watch"]["2"] == {"audio": [[0, 12.34]], "video": []} and "x" not in x["watch"]
    assert progress.normalize(json.loads(progress.encode(x)))["watch"]["2"]["audio"] == [[0, 12.3]]
    mac = p('{"watch":{"1":{"audio":[[0,50]],"video":[]}}}')
    pad = p('{"watch":{"1":{"audio":[[40,90]],"video":[[0,10]]},"2":{"audio":[[0,5]],"video":[]}}}')
    m = progress.merged([mac, pad])
    assert m["watch"]["1"] == {"audio": [[0, 90]], "video": [[0, 10]]} and m["watch"]["2"]["audio"] == [
        [0, 5]
    ]
    assert progress.merged([m, pad]) == m
