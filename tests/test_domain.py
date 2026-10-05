"""The world model: one source of truth, and authority enforced in code."""
import pytest

from airdrop_alpha.domain import data, performance as perf
from airdrop_alpha.domain.world import PERMISSIONS, ROLES, World

from .conftest import ready_for_drop


# -- one fuel state (the original had two that disagreed) --------------------

def test_fuel_state_and_instruments_read_the_same_fuel(world):
    world.aircraft.engines_running = True
    world.advance_time(12)
    assert world.fuel_state()["current_fuel_lbs"] == world.aircraft_state()["fuel_lbs"]
    assert world.fuel_state()["current_fuel_lbs"] < data.DEPARTURE_FUEL_LBS


def test_weight_and_balance_uses_live_fuel_and_cargo(world):
    before = world.weight_balance()
    assert before["total_weight_lbs"] == 159_600          # CARGO_MANIFEST_ALPHA departure weight
    assert before["cg_pct_mac"] == 31.2
    world.advance_time(30)
    assert world.weight_balance()["total_weight_lbs"] < before["total_weight_lbs"]


def test_drop_speed_is_inside_the_safe_envelope(world):
    world.set_flight_phase("dz_approach")
    env = world.performance_envelope()
    assert world.airspeed_kias == 130
    assert env["airspeed_within_envelope"], env


# -- authority guards --------------------------------------------------------

def test_airdrop_refused_without_commander_authorization(world):
    ready_for_drop(world)
    world.authority.drop_authorized = False
    result = world.execute_airdrop("LOADMASTER", "B-03")
    assert result["denied"] and result["rule"] == "commander_authorization"
    assert not world.cargo.bundles["B-03"].released
    assert world.journal[-1]["type"] == "guard_denied"


@pytest.mark.parametrize("setup, rule", [
    (lambda w: setattr(w.cargo, "door", "closed"), "door_not_open"),
    (lambda w: w.atc.clearances.clear(), "romeo4_clearance"),
    (lambda w: w.set_flight_phase("cruise"), "not_on_drop_run"),
    (lambda w: setattr(w.cargo, "aborted", True), "abort_in_effect"),
    (lambda w: setattr(w.authority, "mission_aborted", True), "mission_aborted"),
    (lambda w: w.apply_effect("strap_failure", bundle="B-03"), "cargo_restraint"),
    (lambda w: w.apply_effect("cargo_shift", bundle="B-04", cg_shift_pct=4.9), "cg_limits"),
])
def test_airdrop_preconditions(world, setup, rule):
    ready_for_drop(world)
    setup(world)
    result = world.execute_airdrop("LOADMASTER", "B-03")
    assert result.get("denied") and result["rule"] == rule, result
    assert not world.cargo.bundles["B-03"].released


def test_airdrop_succeeds_when_everything_is_in_place(world):
    ready_for_drop(world)
    for bundle in data.RECOMMENDED_DROP_SEQUENCE:
        assert world.execute_airdrop("LOADMASTER", bundle)["released"]
    assert world.cargo_aboard_lbs == 0
    assert world.check("drop_resolved")
    assert world.cg_pct_mac == pytest.approx(28.7, abs=0.05)
    assert [world.cargo.bundles[b].release_order for b in data.RECOMMENDED_DROP_SEQUENCE] == [1, 2, 3, 4, 5]


def test_every_state_changing_action_checks_the_actor(world):
    """No role can perform another role's action, whatever tools it is handed."""
    calls = {
        "make_go_nogo": lambda a: world.make_go_nogo(a, "GO", "x"),
        "authorize_door_open": world.authorize_door_open,
        "authorize_airdrop": world.authorize_airdrop,
        "revoke_authorizations": lambda a: world.revoke_authorizations(a, "x"),
        "declare_emergency": lambda a: world.declare_emergency(a, "MAYDAY", "x"),
        "abort_mission": lambda a: world.abort_mission(a, "x"),
        "file_flight_plan": lambda a: world.file_flight_plan(a, "r", "KRDW"),
        "set_transponder": lambda a: world.set_transponder(a, "4712"),
        "execute_checklist": lambda a: world.execute_checklist(a, "PREFLIGHT"),
        "set_cruise_altitude": lambda a: world.set_cruise_altitude(a, 140),
        "calculate_carp": world.calculate_carp,
        "update_route": lambda a: world.update_route(a, "x"),
        "plan_drop_sequence": world.plan_drop_sequence,
        "open_door": world.open_door,
        "close_door": world.close_door,
        "execute_airdrop": lambda a: world.execute_airdrop(a, "B-03"),
        "abort_airdrop": lambda a: world.abort_airdrop(a, "x"),
        "clear_abort": lambda a: world.clear_abort(a, "x"),
        "secure_cargo": lambda a: world.secure_cargo(a, "B-03"),
        "approve_flight_plan": world.approve_flight_plan,
        "issue_clearance": lambda a: world.issue_clearance(a, "TAXI", "x"),
        "cancel_clearance": lambda a: world.cancel_clearance(a, "TAXI", "x"),
        "issue_hold": lambda a: world.record_advisory(a, "issue_hold", text="x"),
        "provide_weather_advisory": lambda a: world.record_advisory(a, "provide_weather_advisory", text="x"),
        "issue_traffic_advisory": lambda a: world.record_advisory(a, "issue_traffic_advisory", text="x"),
        "coordinate_emergency": lambda a: world.record_advisory(a, "coordinate_emergency", text="x"),
    }
    assert set(calls) == set(PERMISSIONS)
    for action, call in calls.items():
        for role in ROLES:
            if role in PERMISSIONS[action]:
                continue
            result = call(role)
            assert result.get("denied") and result["rule"] == "role_authority", (action, role, result)


def test_door_needs_authorization_and_drop_speed(world):
    assert world.open_door("LOADMASTER")["rule"] == "commander_authorization"
    world.authorize_door_open("COMMANDER")
    world.set_flight_phase("descent")                       # 250 KIAS
    assert world.open_door("LOADMASTER")["rule"] == "door_airspeed_limits"
    world.set_flight_phase("dz_approach")                   # 130 KIAS
    assert world.open_door("LOADMASTER")["ok"]


def test_loadmaster_abort_needs_no_authorization_and_blocks_reauthorization(world):
    ready_for_drop(world)
    world.apply_effect("cargo_shift", bundle="B-03", cg_shift_pct=4.9)
    assert world.weight_balance()["cg_pct_mac"] == 36.1
    assert not world.weight_balance()["within_limits"]
    assert world.abort_airdrop("LOADMASTER", "strap failure")["abort_confirmed"]
    assert not world.authority.drop_authorized
    assert world.authorize_airdrop("COMMANDER")["rule"] == "abort_in_effect"
    assert world.clear_abort("LOADMASTER", "nothing done")["rule"] == "unsafe_condition_persists"
    assert world.secure_cargo("LOADMASTER", "B-03")["rule"] == "door_must_be_closed"
    world.close_door("LOADMASTER")
    assert world.secure_cargo("LOADMASTER", "B-03")["ok"]
    assert world.clear_abort("LOADMASTER", "B-03 re-secured")["ok"]
    assert world.authorize_airdrop("COMMANDER")["ok"]


# -- ATC ---------------------------------------------------------------------

def test_ifr_clearance_needs_an_approved_plan(world):
    assert world.issue_clearance("ATC", "IFR", "x")["rule"] == "flight_plan_not_approved"
    assert world.approve_flight_plan("ATC")["rule"] == "flight_plan_not_filed"
    world.file_flight_plan("COPILOT", "KIRO ... KIRO", "KRDW")
    assert world.approve_flight_plan("ATC")["squawk"] == "4712"
    assert world.issue_clearance("ATC", "IFR", "x", 180)["ok"]
    assert world.check("ifr_clearance")


def test_romeo4_cannot_be_cleared_into_a_traffic_conflict(world):
    world.apply_effect("traffic_conflict", active="true")
    assert world.sector_traffic()["romeo4_traffic_conflict"]
    assert world.issue_clearance("ATC", "ROMEO4_TRANSIT", "x")["rule"] == "traffic_conflict"
    world.apply_effect("traffic_conflict", active="false")
    assert world.issue_clearance("ATC", "romeo-4 transit", "x")["type"] == "ROMEO4_TRANSIT"
    world.cancel_clearance("ATC", "ROMEO4_TRANSIT", "traffic")
    assert not world.check("romeo4_clearance")


def test_altitude_change_in_flight_needs_a_matching_clearance(world):
    world.set_flight_phase("cruise")
    assert world.set_cruise_altitude("COPILOT", 140)["rule"] == "atc_clearance_required"
    world.issue_clearance("ATC", "ALTITUDE", "descend FL140", 140)
    assert world.set_cruise_altitude("COPILOT", 140)["ok"]
    assert world.altitude_ft == 14_000
    assert world.fuel_flow_pph > perf.fuel_flow_pph("cruise")


# -- checklists reflect the world --------------------------------------------

def test_checklist_reports_open_items_until_the_world_satisfies_them(world):
    result = world.execute_checklist("COPILOT", "preflight")
    assert not result["all_complete"]
    assert {i["item"] for i in result["open_items"]} == {"Flight plan", "ATC squawk code", "GO/NO-GO decision"}
    assert not world.check("checklist:PREFLIGHT")
    assert world.execute_checklist("COPILOT", "ENGINE START")["rule"] == "checklist_order"

    world.make_go_nogo("COMMANDER", "GO", "all good")
    world.file_flight_plan("COPILOT", "route", "KRDW")
    world.approve_flight_plan("ATC")
    world.set_transponder("COPILOT", "4712")
    assert world.execute_checklist("COPILOT", "PREFLIGHT")["all_complete"]
    assert world.execute_checklist("COPILOT", "Engine Start checklist")["all_complete"]
    assert world.aircraft.engines_running
    assert world.check("checklist:TAKEOFF") is False     # alias of BEFORE TAKEOFF


def test_wrong_squawk_does_not_satisfy_the_checklist(world):
    world.file_flight_plan("COPILOT", "route", "KRDW")
    world.approve_flight_plan("ATC")
    assert world.set_transponder("COPILOT", "1200")["matches_assigned_code"] is False
    assert not world.check("squawk_set")
    assert world.set_transponder("COPILOT", "9999").get("error")


# -- time, fuel plan, hazards, effects ---------------------------------------

def test_holding_shows_up_as_fuel_variance(world):
    world.set_flight_phase("cruise")
    world.clock_min = 30
    world.aircraft.fuel_lbs = world.planned_fuel_now()
    assert world.fuel_plan()["variance_vs_plan_lbs"] == 0
    world.aircraft.holding = True
    world.nav.timeline_offset_min += 6
    world.advance_time(6)
    assert world.effective_phase == "holding"
    assert world.fuel_plan()["variance_vs_plan_lbs"] > 700
    assert world.eta("DZ-ALPHA")["eta_sim_min"] == 70


def test_turbulence_exposure_depends_on_altitude(world):
    world.set_flight_phase("cruise")
    world.clock_min = 40
    world.advance_time(14)                                  # T+40..54 at FL180, band opens at T+44
    assert world.aircraft.turbulence_exposure_min == pytest.approx(10)
    low = World.model_validate(world.model_dump())
    low.aircraft.turbulence_exposure_min = 0
    low.aircraft.cruise_altitude_ft = 14_000
    low.clock_min = 40
    low.advance_time(14)
    assert low.aircraft.turbulence_exposure_min == 0


def test_carp_follows_observed_wind_and_weather_gate(world):
    carp = world.calculate_carp("NAVIGATOR")
    assert carp["carp_nm_from_dz"] == 4.2 and carp["run_heading_deg"] == 90
    world.apply_effect("weather", location="DZ-ALPHA", wind_speed_kts=30, ceiling_ft_agl=300)
    assert not world.check("dz_weather_ok")
    assert world.calculate_carp("NAVIGATOR")["carp_nm_from_dz"] == 7.0


def test_engine_failure_changes_performance(world):
    world.set_flight_phase("cruise")
    four = world.fuel_flow_pph
    world.apply_effect("engine_failure", engine=2)
    assert world.engines_operative == 3
    assert world.fuel_flow_pph == pytest.approx(four * 0.82)
    assert world.engine_out_performance()["service_ceiling_da_ft"] == 20_000
    with pytest.raises(ValueError):
        world.apply_effect("no_such_effect")


def test_world_round_trips_through_plain_json(world):
    import json
    ready_for_drop(world)
    world.execute_airdrop("LOADMASTER", "B-03")
    dumped = json.loads(json.dumps(world.model_dump()))
    assert "journal" not in dumped
    assert World.model_validate(dumped).model_dump() == world.model_dump()


# -- drop accuracy: allowed, but scored ---------------------------------------

def test_release_before_the_carp_is_allowed_and_marked_off_target(world):
    ready_for_drop(world)
    world.clock_min = 60                                    # CARP is at T+64
    assert world.aircraft_state()["drop_run"]["minutes_to_carp"] == 4
    assert "4 min before the CARP" in world.cargo_status()["release_point"]
    result = world.execute_airdrop("LOADMASTER", "B-03")
    assert result["released"] and result["on_target"] is False       # not refused
    assert "will not land on DZ-ALPHA" in result["warning"]
    assert "NM short" in result["release_point"]
    bundle = world.cargo.bundles["B-03"]
    assert bundle.on_target is False and bundle.minutes_from_carp == -4
    assert world.journal[-1]["on_target"] is False


def test_release_inside_the_window_is_on_target_and_late_is_not(world):
    ready_for_drop(world)
    assert world.aircraft_state()["drop_run"]["in_release_window"]
    assert world.execute_airdrop("LOADMASTER", "B-03")["on_target"] is True
    world.clock_min = 68
    late = world.execute_airdrop("LOADMASTER", "B-04")
    assert late["on_target"] is False and "past the release window" in late["release_point"]


def test_release_window_slips_with_the_timeline(world):
    ready_for_drop(world)
    world.nav.timeline_offset_min = 4                       # two holds earlier in the mission
    world.clock_min = 64
    assert world.execute_airdrop("LOADMASTER", "B-03")["on_target"] is False
    world.clock_min = 68
    assert world.execute_airdrop("LOADMASTER", "B-04")["on_target"] is True


def test_drop_run_information_only_appears_on_the_drop_run(world):
    world.set_flight_phase("cruise")
    assert "drop_run" not in world.aircraft_state()
    assert world.cargo_status()["release_point"] == "not on the drop run"
