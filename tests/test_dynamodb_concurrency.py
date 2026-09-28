"""Required storage concurrency gate: real DynamoDB Local, never Moto."""

import threading
import time
from queue import SimpleQueue

import pytest
from prometheus_client import REGISTRY
from sqlalchemy import select

from rideloop_common import trips
from rideloop_common.db import Trip
from rideloop_common.geo import offset_m
from rideloop_common.models import TripStatus
from tests.test_dispatch import CENTER, make_matcher, request_at

pytestmark = pytest.mark.integration


def race(count, action):
    barrier = threading.Barrier(count, timeout=5)
    outcomes = SimpleQueue()
    errors = SimpleQueue()

    def worker(index):
        try:
            barrier.wait()
            outcomes.put((index, action(index)))
        except BaseException as error:
            errors.put((index, repr(error)))

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(count)]
    deadline = time.monotonic() + 15
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=max(0, deadline - time.monotonic()))
    assert not any(thread.is_alive() for thread in threads), "concurrent operations timed out"
    failures = [errors.get() for _ in range(errors.qsize())]
    results = sorted(outcomes.get() for _ in range(outcomes.qsize()))
    assert not failures, failures
    assert len(results) == count, results
    return results


@pytest.mark.parametrize("claimants", [8, 16])
def test_conditional_claims_have_exactly_one_winner_and_count_every_conflict(
    local_store, claimants
):
    position = local_store.put_position("only", *CENTER)
    before = REGISTRY.get_sample_value("rideloop_claim_conflicts_total")
    outcomes = race(
        claimants,
        lambda index: local_store.try_mark_busy(position.cell, "only", f"trip-{index}"),
    )
    wins = [index for index, result in outcomes if result is True]
    losses = [index for index, result in outcomes if result is False]
    assert len(wins) == 1, outcomes
    assert len(losses) == claimants - 1, outcomes
    assert REGISTRY.get_sample_value("rideloop_claim_conflicts_total") == before + claimants - 1
    # Read the base key, not the eventually consistent by_driver GSI.
    item = local_store.table.get_item(
        Key={"cell": position.cell, "driver_id": "only"}, ConsistentRead=True
    )["Item"]
    assert item["status"] == "busy"
    assert item["trip_id"] == f"trip-{wins[0]}"
    assert local_store.try_mark_busy(position.cell, "only", "late") is False
    assert REGISTRY.get_sample_value("rideloop_claim_conflicts_total") == before + claimants


def test_concurrent_matchers_never_double_assign_a_driver(local_store, session_factory):
    lat, lng = CENTER
    position = local_store.put_position("only", *offset_m(lat, lng, 30, 0))
    with session_factory() as session, session.begin():
        for index in range(12):
            trips.create_trip(
                session, request_at(*offset_m(lat, lng, 10 * index, 0), rider=f"r{index}")
            )
    matchers = [make_matcher(local_store, session_factory, batch_size=1) for _ in range(6)]

    def run_matcher(index):
        return [matchers[index].run_once() for _ in range(4)]

    outcomes = race(len(matchers), run_matcher)
    assert sum(sum(sweeps) for _, sweeps in outcomes) == 1, outcomes
    with session_factory() as session:
        matched = session.scalars(select(Trip).where(Trip.status == TripStatus.MATCHED)).all()
        requested = session.scalars(select(Trip).where(Trip.status == TripStatus.REQUESTED)).all()
        assert len(matched) == 1
        assert matched[0].driver_id == "only"
        assert len(requested) == 11
        winner = str(matched[0].id)
    item = local_store.table.get_item(
        Key={"cell": position.cell, "driver_id": "only"}, ConsistentRead=True
    )["Item"]
    assert item["trip_id"] == winner
