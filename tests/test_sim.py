import random

from sim.city import BLOCK_M, PICKUP_DWELL_S, SimDriver


def test_driver_routes_pickup_then_dropoff():
    driver = SimDriver.spawn("d", random.Random(3))
    driver.north_m, driver.east_m = 0.0, 0.0
    driver.set_route((BLOCK_M, 0.0), (BLOCK_M, 2 * BLOCK_M))
    steps_to_pickup = 0
    while (driver.north_m, driver.east_m) != (BLOCK_M, 0.0):
        driver.step(1.0)
        steps_to_pickup += 1
    assert steps_to_pickup == 23
    assert driver.target == (BLOCK_M, 0.0)
    for _ in range(int(PICKUP_DWELL_S)):
        driver.step(1.0)
    assert driver.target == (BLOCK_M, 2 * BLOCK_M)
    assert driver.dropoff is None
    for _ in range(60):
        driver.step(1.0)
    assert (driver.north_m, driver.east_m) == (BLOCK_M, 2 * BLOCK_M)
    driver.clear_target()
    assert driver.target is None
