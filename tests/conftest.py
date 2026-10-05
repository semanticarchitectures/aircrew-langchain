import pytest

from airdrop_alpha.domain.world import World
from airdrop_alpha.scenario import load_scenario


@pytest.fixture(scope="session")
def scenario():
    return load_scenario()


@pytest.fixture
def world(scenario):
    return World.new(
        departure_fuel_lbs=scenario["departure_fuel_lbs"],
        waypoint_times=scenario["waypoint_times"],
        fuel_curve=scenario["fuel_curve"],
        hazards=scenario["hazards"],
        drop_window=scenario["drop_window"],
    )


def ready_for_drop(world: World) -> World:
    """Put a world on the drop run with everything a release needs."""
    world.atc.clearances.append({"clearance_id": 1, "type": "ROMEO4_TRANSIT", "text": "", "altitude_fl": None,
                                 "t": 0, "cancelled": False})
    world.set_flight_phase("dz_approach")
    world.clock_min = world.nav.drop_window[0]              # at the CARP
    world.authority.door_open_authorized = True
    world.authority.drop_authorized = True
    world.cargo.door = "open"
    world.drain_journal()
    return world
