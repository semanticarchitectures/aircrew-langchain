"""Scenario loading and the consistency of the numbers it produces."""
import pytest

from airdrop_alpha.domain import data
from airdrop_alpha.scenario import ScenarioError, build_scenario, default_scenario_path, load_scenario


def test_timeline_is_ordered_and_complete(scenario):
    times = [item["at"] for item in scenario["timeline"]]
    assert times == sorted(times)
    kinds = [item["kind"] for item in scenario["timeline"]]
    assert kinds[-1] == "end"
    assert kinds.count("mission_phase") == 5
    assert kinds.count("event") == 13                      # 12 scenario events + the initial trigger
    assert scenario["timeline"][0]["kind"] == "mission_phase"
    assert len({item["id"] for item in scenario["timeline"]}) == len(scenario["timeline"])


def test_nominal_profile_burns_what_the_mission_brief_plans(scenario):
    """MISSION_BRIEF_ALPHA: 45,000 lbs departure, 16,500 lbs burn, 28,500 lbs arrival."""
    arrival = scenario["fuel_curve"][-1][1]
    assert data.DEPARTURE_FUEL_LBS - arrival == pytest.approx(data.PLANNED_BURN_LBS, abs=50)
    fuel_at_dz = next(f for t, f in scenario["fuel_curve"] if t >= 60)
    assert fuel_at_dz > data.BINGO_FUEL_LBS                # nominal plan does not hit bingo before the DZ


def test_waypoint_times_follow_the_brief_leg_times(scenario):
    wt = scenario["waypoint_times"]
    legs = [wt["WPT ALPHA"] - wt["TAKEOFF"], wt["WPT BRAVO"] - wt["WPT ALPHA"],
            wt["DZ-ALPHA"] - wt["WPT BRAVO"], wt["WPT CHARLIE"] - wt["DZ-ALPHA"] - 4,   # 4 min drop run
            wt["KIRO"] - wt["WPT CHARLIE"]]
    assert legs == [leg["time_min"] for leg in data.LEGS]


def test_abort_variant_extends_the_base_scenario(scenario):
    abort = load_scenario(default_scenario_path().with_name("airdrop_alpha_abort.yaml"))
    extra = [i for i in abort["timeline"] if i["kind"] == "event" and i["effects"]]
    assert len(abort["timeline"]) == len(scenario["timeline"]) + 1
    assert extra[0]["effects"] == [{"name": "cargo_shift", "args": {"bundle": "B-03", "cg_shift_pct": 4.9}}]
    assert extra[0]["priority"] == "URGENT" and extra[0]["at"] == 62


def test_release_window_sits_at_the_carp(scenario):
    assert scenario["drop_window"] == [64.0, 65.0]
    assert scenario["drop_window"][0] == scenario["waypoint_times"]["DZ-ALPHA"]
    carp_event = next(i for i in scenario["timeline"] if "at the CARP" in i.get("message", ""))
    assert scenario["drop_window"][0] <= carp_event["at"] <= scenario["drop_window"][1]


def test_setting_overrides(scenario):
    assert load_scenario(party_line=True)["settings"]["party_line"] is True
    assert scenario["settings"]["party_line"] is False


@pytest.mark.parametrize("mutate, message", [
    (lambda s: s["flight_profile"][1].__setitem__("requires", ["no_such_condition"]), "unknown condition"),
    (lambda s: s["phases"][0]["events"][0].__setitem__("inject_to", "PURSER"), "unknown callsign"),
    (lambda s: s["phases"][0]["events"][0].__setitem__("effects", [{"name": "meteor"}]), "unknown effect"),
    (lambda s: s.__setitem__("settings", {"warp": 9}), "unknown settings"),
    (lambda s: s["flight_profile"][0].__setitem__("flight_phase", "cruise"), "must start on the ground"),
    (lambda s: s.__setitem__("end_at", 5), "before the last timeline item"),
    (lambda s: s.__setitem__("drop_window", {"opens": 66, "closes": 64}), "drop_window must open before"),
])
def test_bad_scenarios_are_rejected(mutate, message):
    import yaml
    raw = yaml.safe_load(default_scenario_path().read_text())
    mutate(raw["scenario"])
    with pytest.raises(ScenarioError, match=message):
        build_scenario(raw)
