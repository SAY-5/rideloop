"""A recorded ride stream replays to the same matches every time."""

import json
from pathlib import Path

import pytest

from sim import replay
from sim.replay import Summary, compare, read, synthesize
from sim.replay import replay as run_replay

SEED, DRIVERS, RATE, DURATION = 7, 40, 2.0, 15.0


@pytest.fixture
def stream(tmp_path) -> Path:
    path = tmp_path / "stream.jsonl"
    synthesize(SEED, DRIVERS, RATE, DURATION).write(path)
    return path


def test_synthesized_stream_is_deterministic(tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    synthesize(SEED, DRIVERS, RATE, DURATION).write(a)
    synthesize(SEED, DRIVERS, RATE, DURATION).write(b)
    assert a.read_text() == b.read_text()
    header, events, summary = read(a)
    assert header == {"version": 1, "seed": SEED, "drivers": DRIVERS}
    assert summary is None
    assert sum(1 for e in events if e.kind == "ride") == int(RATE * DURATION)
    assert sum(1 for e in events if e.kind == "position") == DRIVERS * (int(DURATION) + 1)
    assert events == sorted(events)
    other = tmp_path / "other.jsonl"
    synthesize(SEED + 1, DRIVERS, RATE, DURATION).write(other)
    assert other.read_text() != a.read_text()


def test_replay_reproduces_the_recorded_matches(stream, store, session_factory, engine):
    _, events, _ = read(stream)
    first = run_replay(events, store, session_factory)
    assert first.rides == int(RATE * DURATION)
    assert first.matched == first.rides
    assert first.unmatched == 0
    assert first.p95_latency_ms >= first.p50_latency_ms >= 0
    assert first.matches_per_minute > 0

    # wipe both stores and run the same file again: identical outcome
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE ride_events, trips, drivers RESTART IDENTITY CASCADE"))
    for item in store.table.scan()["Items"]:
        store.table.delete_item(Key={"cell": item["cell"], "driver_id": item["driver_id"]})
    second = run_replay(events, store, session_factory)
    assert second.fingerprint == first.fingerprint
    assert (second.matched, second.rides, second.p50_latency_ms) == (
        first.matched,
        first.rides,
        first.p50_latency_ms,
    )
    assert compare(first, second) == []


def test_compare_flags_a_changed_match_count_or_assignment():
    recorded = Summary(30, 30, 0, 120.0, 0.0, 0.0, "abcdef0123456789")
    same = Summary(30, 30, 0, 118.0, 1.0, 2.0, "abcdef0123456789")
    assert compare(recorded, same) == []
    fewer = Summary(30, 28, 2, 118.0, 1.0, 2.0, "ffffffffffffffff")
    diffs = compare(recorded, fewer)
    assert diffs == [
        "matched 28 (recorded 30)",
        "assignments ffffffffffffffff (recorded abcdef0123456789)",
    ]


def test_cli_writes_a_summary_then_verifies_it(stream, session_factory, engine, capsys):
    """The CLI round trip: run with --write-summary, run again to compare, then
    tamper with the summary and watch the comparison fail."""
    from sqlalchemy import text

    def reset():
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE ride_events, trips, drivers RESTART IDENTITY CASCADE"))

    assert replay.main(["run", str(stream), "--in-memory", "--write-summary"]) == 0
    _, _, summary = read(stream)
    assert summary is not None and summary.matched == int(RATE * DURATION)
    reset()
    assert replay.main(["run", str(stream), "--in-memory"]) == 0
    assert "matches recording" in capsys.readouterr().out
    reset()

    lines = stream.read_text().splitlines()
    tampered = json.loads(lines[-1])
    tampered["matched"] -= 1
    stream.write_text("\n".join([*lines[:-1], json.dumps(tampered)]) + "\n")
    assert replay.main(["run", str(stream), "--in-memory"]) == 1
    assert "REGRESSION: matched" in capsys.readouterr().out
    reset()


def test_unsupported_recording_version_is_rejected(tmp_path):
    path = tmp_path / "old.jsonl"
    path.write_text(json.dumps({"kind": "header", "version": 0}) + "\n")
    with pytest.raises(ValueError):
        read(path)
