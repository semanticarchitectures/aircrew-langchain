"""
Playbooks for the scripted crew.

``NOMINAL`` flies Operation AIRDROP ALPHA by the book and also handles the
cargo-shift abort.  ``ROGUE_LOADMASTER`` is the same crew with a Loadmaster who
tries to open the door and release a bundle before being authorised, which is
how the tests show that authority is enforced in code rather than in prompts.
``EAGER_COMMANDER`` calls the drop before the CARP, which shows that a release
in the wrong place is allowed but scored as a miss.

These are test fixtures and a demo, not a model of crew behaviour.
"""
from __future__ import annotations

from .scripted import Rule, ScriptedChatModel, say

CREW_BRIEF = (
    "CREW BRIEF - OPERATION AIRDROP ALPHA. AIRCRAFT: CONDOR 71. "
    "1. MISSION: Deliver 5 humanitarian bundles to DZ-ALPHA via low-altitude airdrop. RTB KIRO. "
    "2. ROUTE: KIRO > WPT ALPHA > WPT BRAVO > DZ-ALPHA > WPT CHARLIE > KIRO. Cruise FL180. "
    "3. DZ: DZ-ALPHA, 42.8N/95.4W. Drop altitude 1,500 ft AGL. Drop heading 090. "
    "4. CARGO: 4,200 lbs, 5 bundles. Priority: B-01 and B-02 (medical). "
    "5. WEATHER: KIRO clear; moderate turbulence FL160-FL200 at BRAVO; DZ 3,500 ft ceiling, 8 SM, wind 270/18. "
    "6. THREATS: ROMEO-4 active. Transit clearance required via COPILOT. "
    "7. FUEL: 45,000 lbs departure. Bingo 32,000 lbs, divert KRDW. "
    "8. COMMS: ATC on 124.35 through COPILOT only. "
    "9. ABORT CRITERIA: fuel below bingo; DZ weather below minimums; LM abort call; CG out of limits. "
    "10. NAVIGATOR: send me the route brief. LOADMASTER: send me the W&B certification."
)

COMMANDER = [
    Rule(r"Begin mission planning", [
        [("review_mission_brief", {})],
        [("query_weather", {"location": "KIRO"}), ("query_weather", {"location": "WPT BRAVO"}),
         ("query_weather", {"location": "DZ-ALPHA"})],
        [say("ALL", CREW_BRIEF)],
    ]),
    Rule(r"W&B certified", [[("make_go_nogo", {
        "decision": "GO",
        "reason": "Weather above minimums at KIRO and the DZ, W&B certified, route and fuel plan briefed."})]],
         requires=r"ROUTE BRIEF", unless_logged=r"make_go_nogo"),
    Rule(r"ROUTE BRIEF", [[("make_go_nogo", {
        "decision": "GO",
        "reason": "Weather above minimums at KIRO and the DZ, W&B certified, route and fuel plan briefed."})]],
         requires=r"W&B certified", unless_now=r"W&B certified", unless_logged=r"make_go_nogo"),
    Rule(r"IFR clearance received", [[say("COPILOT", "COPILOT, COMMANDER. Run the Preflight checklist.")]]),
    Rule(r"Preflight checklist complete",
         [[say("COPILOT", "COPILOT, COMMANDER. Run the Engine Start checklist.")]]),
    Rule(r"Engine Start checklist complete",
         [[say("COPILOT", "COPILOT, COMMANDER. Contact Ground for taxi to runway two-seven-left.")]]),
    Rule(r"Ground clears us to taxi",
         [[say("COPILOT", "COPILOT, COMMANDER. Run the Before Takeoff checklist.")]]),
    Rule(r"ATC advises moderate turbulence", [[say(
        "NAVIGATOR", "NAVIGATOR, COMMANDER. I'm considering descending to FL140. Navigation and fuel impact?")]]),
    Rule(r"Recommend altitude amendment to FL140",
         [[say("COPILOT", "COPILOT, COMMANDER. Request flight level one-four-zero from ATC.")]],
         unless_logged=r"Request flight level one-four-zero"),
    Rule(r"established at drop altitude", [[("authorize_door_open", {})]],
         requires=r"Request door open authorization", unless_logged=r"ABORT AIRDROP"),
    Rule(r"at the CARP on the drop run", [[("authorize_airdrop", {})]],
         requires=r"Cargo door open", unless_logged=r"ABORT AIRDROP", unless_now=r"ABORT AIRDROP"),
    Rule(r"All bundles released", [[say(
        "COPILOT", "COPILOT, COMMANDER. Report clear of Romeo-4 to ATC and request climb to FL180, "
                   "direct Iron Mountain.")]]),
    Rule(r"ABORT AIRDROP", [[say(
        "LOADMASTER", "LOADMASTER, COMMANDER. Copy abort. Secure the cargo and report status.")]],
         unless_now=r"Reason for abort"),
    Rule(r"Reason for abort", [
        [("abort_mission", {"reason": "Loadmaster airdrop abort: cargo shift, CG outside limits."})],
        [say("COPILOT", "COPILOT, COMMANDER. Advise ATC we are exiting Romeo-4 with cargo aboard and "
                        "request climb to FL180, direct Iron Mountain.")],
    ]),
    Rule(r"ATC clears us for the ILS approach",
         [[say("COPILOT", "COPILOT, COMMANDER. Run the Before Landing checklist.")]]),
    Rule(r"has landed at KIRO", [[say(
        "ALL", "DEBRIEF - OPERATION AIRDROP ALPHA. Aircraft and crew recovered at KIRO. Cargo delivery "
               "as reported by LOADMASTER. Discrepancies as logged. Crew coordination was disciplined. "
               "Good work.")]]),
]

COPILOT = [
    Rule(r"Make initial radio contact", [[say(
        "ATC", "Alpha Approach, CONDOR 71, good morning. C-130J on the ground at KIRO, planning IFR "
               "departure in approximately one-zero minutes. Request current ATIS and advise we'll be "
               "calling back for our clearance shortly.")]]),
    Rule(r"Information Golf is current", [[say(
        "COMMANDER", "COMMANDER, COPILOT. ATIS Information Golf, altimeter two-niner-niner-two. "
                     "Standing by to file.")]]),
    Rule(r"File the flight plan", [
        [("file_flight_plan", {"route": "KIRO WPT-ALPHA WPT-BRAVO DZ-ALPHA WPT-CHARLIE KIRO",
                               "alternate": "KRDW"})],
        [say("ATC", "Alpha Approach, CONDOR 71, flight plan filed, ready to copy IFR clearance to "
                    "Iron Mountain.")],
    ]),
    Rule(r"Cleared to Iron Mountain via filed route", [
        [("set_transponder", {"code": "4712"})],
        [say("ATC", "Cleared to Iron Mountain via filed route, climb and maintain flight level "
                    "one-eight-zero, squawk four-seven-one-two, departure one-two-four-point-three-five, "
                    "CONDOR 71."),
         say("COMMANDER", "COMMANDER, COPILOT. IFR clearance received. Cleared to Iron Mountain via filed "
                          "route, maintain FL180, squawk 4712, departure frequency 124.35. Readback "
                          "correct. Transponder set to 4712.")],
    ]),
    Rule(r"Run the Preflight checklist", [
        [("execute_checklist", {"checklist_name": "PREFLIGHT"})],
        [say("COMMANDER", "COMMANDER, COPILOT. Preflight checklist complete.")],
    ]),
    Rule(r"Run the Engine Start checklist", [
        [("execute_checklist", {"checklist_name": "ENGINE START"})],
        [say("COMMANDER", "COMMANDER, COPILOT. Engine Start checklist complete. Engines running normally.")],
    ]),
    Rule(r"Contact Ground for taxi",
         [[say("ATC", "Ground, CONDOR 71, ready to taxi, information Golf.")]]),
    Rule(r"Ground\. Taxi to runway two-seven-left", [[
        say("ATC", "Taxi to runway two-seven-left via Alpha, Bravo, hold short of runway "
                   "two-seven-left, CONDOR 71."),
        say("COMMANDER", "COMMANDER, COPILOT. Ground clears us to taxi runway 27L via Alpha, Bravo, "
                         "hold short."),
    ]]),
    Rule(r"Run the Before Takeoff checklist", [
        [("execute_checklist", {"checklist_name": "BEFORE TAKEOFF"})],
        [say("COMMANDER", "COMMANDER, COPILOT. Before Takeoff checklist complete. Holding short runway "
                          "27L, ready for departure.")],
    ]),
    Rule(r"cleared for takeoff", [[
        say("ATC", "Runway two-seven-left, cleared for takeoff, left heading two-eight-five, will report "
                   "passing flight level one-zero-zero, CONDOR 71."),
        say("COMMANDER", "COMMANDER, COPILOT. Tower clears CONDOR 71 for takeoff runway 27L, left heading "
                         "285 after departure."),
    ]]),
    Rule(r"Pilot report", [[say(
        "COMMANDER", "COMMANDER, COPILOT. ATC advises moderate turbulence FL160 to FL200 near Bravo. "
                     "Smooth air reported at FL140.")]]),
    Rule(r"Request flight level one-four-zero from ATC", [[say(
        "ATC", "Alpha Approach, CONDOR 71, request descent to flight level one-four-zero due "
               "turbulence.")]]),
    Rule(r"Descend and maintain flight level one-four-zero", [
        [("set_cruise_altitude", {"flight_level": 140})],
        [say("ATC", "Descend and maintain flight level one-four-zero, CONDOR 71."),
         say("COMMANDER", "COMMANDER, COPILOT. ATC clears us down to FL140. Altitude set.")],
    ]),
    Rule(r"Cleared through Restricted Area Romeo-4", [[
        say("ATC", "Cleared through Restricted Area Romeo-4, will report clear, CONDOR 71."),
        say("COMMANDER", "COMMANDER, COPILOT. ATC clears us through Romeo-4. Report clear on exit."),
    ]]),
    Rule(r"(Report clear of Romeo-4 to ATC|Advise ATC we are exiting Romeo-4)", [[say(
        "ATC", "Alpha Approach, CONDOR 71. Clear of Romeo-4. Requesting climb to flight level "
               "one-eight-zero and direct Iron Mountain.")]]),
    Rule(r"Cleared direct Iron Mountain", [
        [("set_cruise_altitude", {"flight_level": 180})],
        [say("ATC", "Climb and maintain flight level one-eight-zero, direct Iron Mountain, CONDOR 71."),
         say("COMMANDER", "COMMANDER, COPILOT. ATC clears us direct Iron Mountain, climb and maintain "
                          "FL180.")],
    ]),
    Rule(r"Cleared ILS approach", [[
        say("ATC", "Cleared ILS approach runway two-seven-left, altimeter two-niner-niner-two, cleared "
                   "to land two-seven-left, CONDOR 71."),
        say("COMMANDER", "COMMANDER, COPILOT. ATC clears us for the ILS approach runway 27L, cleared "
                         "to land."),
    ]]),
    Rule(r"Run the Before Landing checklist", [
        [("execute_checklist", {"checklist_name": "BEFORE LANDING"})],
        [say("COMMANDER", "COMMANDER, COPILOT. Before Landing checklist complete.")],
    ]),
]

NAVIGATOR = [
    Rule(r"CREW BRIEF", [
        [("compute_route", {})],
        [("check_airspace", {"waypoint": "DZ-ALPHA", "altitude": "1500 ft AGL"})],
        [say("COMMANDER", "COMMANDER, NAVIGATOR. ROUTE BRIEF - OPERATION AIRDROP ALPHA. Route KIRO > WPT "
                          "ALPHA > WPT BRAVO > DZ-ALPHA > WPT CHARLIE > KIRO, 430 NM, cruise FL180. "
                          "Planned burn 16,500 lbs, arrival fuel 28,500 lbs. Bingo 32,000 lbs, divert "
                          "KRDW. ROMEO-4 active around DZ-ALPHA, transit clearance required via COPILOT. "
                          "Alternate DZ DELTA FIELD, plus 900 lbs.")],
    ]),
    *[Rule(rf"is passing {name}", [
        [("get_eta", {"waypoint": nxt}), ("get_fuel_plan", {})],
        [say("COMMANDER", f"COMMANDER, NAVIGATOR. Passing {name}. On track. Next waypoint {nxt}. "
                          "Fuel on plan.")],
    ]) for name, nxt in (("WPT ALPHA", "WPT BRAVO"), ("WPT BRAVO", "DZ-ALPHA"), ("WPT CHARLIE", "KIRO"))],
    Rule(r"(Navigation and fuel impact|impact of descending to FL140)", [
        [("query_weather", {"location": "WPT BRAVO"}), ("compute_performance_at", {"altitude_ft": 14000})],
        [say("COMMANDER", "COMMANDER, NAVIGATOR. Moderate turbulence FL160-FL200 at Bravo, smooth at "
                          "FL140. FL140 costs about 300 lbs/hr extra fuel flow, no meaningful time "
                          "penalty. Fuel state supports it. Recommend altitude amendment to FL140.")],
    ], unless_logged=r"Recommend altitude amendment to FL140"),
    Rule(r"Compute the CARP", [
        [("calculate_dz_offset", {})],
        [say(["COMMANDER", "LOADMASTER"],
             "COMMANDER, LOADMASTER, NAVIGATOR. CARP computed for DZ-ALPHA. Release point 4.2 NM upwind "
             "of DZ center. Wind 270/18 at drop altitude. Drop altitude 1,500 ft AGL (2,350 ft MSL). "
             "Run heading 090. Recompute if wind shifts more than 5 knots."),
         say("COPILOT", "COPILOT, NAVIGATOR. Romeo-4 boundary in 11 minutes. Ensure clearance is "
                        "confirmed.")],
    ]),
    Rule(r"drop run is finished", [
        [("get_eta", {"waypoint": "KIRO"}), ("get_fuel_plan", {})],
        [say("COMMANDER", "COMMANDER, NAVIGATOR. Course set Waypoint Charlie then Iron Mountain. ETA KIRO "
                          "on plan. Fuel on plan.")],
    ]),
]

_LM_PRE_DROP = [
    [("inspect_cargo", {}), ("plan_drop_sequence", {})],
    [say("COMMANDER", "COMMANDER, LOADMASTER. Pre-drop checklist complete. Cargo ready. Request door "
                      "open authorization.")],
]

LOADMASTER = [
    Rule(r"CREW BRIEF", [
        [("review_manifest", {})],
        [("inspect_cargo", {}), ("calculate_weight_balance", {})],
        [("plan_drop_sequence", {})],
        [say("COMMANDER", "COMMANDER, LOADMASTER. Cargo check complete. 5 bundles aboard, 4,200 lbs "
                          "total. CG at 31.2% MAC, within limits. W&B certified. Drop sequence "
                          "confirmed: B-03, B-04, B-01, B-02, B-05. B-05 seal intact. Ready for "
                          "departure on your call.")],
    ]),
    Rule(r"Begin drop preparation", _LM_PRE_DROP),
    Rule(r"Door open authorized", [
        [("open_door", {})],
        [say("COMMANDER", "COMMANDER, LOADMASTER. Cargo door open. Cargo bay secured. Ready for drop run.")],
    ]),
    Rule(r"Execute airdrop", [
        [("execute_airdrop", {"bundle_id": b}) for b in ("B-03", "B-04", "B-01", "B-02", "B-05")],
        [("close_door", {})],
        [say("COMMANDER", "COMMANDER, LOADMASTER. Bundles B-03, B-04, B-01, B-02, B-05 away. All bundles "
                          "released. Cargo door closed and secured.")],
    ]),
    Rule(r"loud bang from the aft cargo bay", [
        [("inspect_cargo", {}), ("calculate_weight_balance", {})],
        [("abort_airdrop", {"reason": "B-03 restraint failed and the bundle shifted aft. CG is outside "
                                      "the aft limit. Closing door now. Securing cargo."})],
        [("close_door", {})],
        [("secure_cargo", {"bundle_id": "B-03"})],
        [("calculate_weight_balance", {})],
        [say("COMMANDER", "COMMANDER, LOADMASTER. Cargo secured. Door closed. Bundles 0 of 5 released. "
                          "Reason for abort: B-03 restraint failure, cargo shifted aft, CG reached 36.1% "
                          "MAC, outside the 35.0% aft limit. B-03 is re-secured and CG is back within "
                          "limits.", "URGENT")],
    ]),
    Rule(r"left the drop zone", [
        [("report_cargo_status", {}), ("calculate_weight_balance", {})],
        [say("COMMANDER", "COMMANDER, LOADMASTER. Door closed and secured. Cargo bay clear. Ready for "
                          "landing.")],
    ]),
]

ATC = [
    Rule(r"Request current ATIS", [[say(
        "COPILOT", "CONDOR 71, Alpha Approach. Information Golf is current: KIRO winds two-five-zero at "
                   "one-two, visibility one-zero, ceiling unlimited, altimeter two-niner-niner-two. IFR "
                   "departure in use. Advise ready to copy clearance.")]]),
    Rule(r"ready to copy IFR clearance", [
        [("approve_flight_plan", {})],
        [("issue_clearance", {"clearance_type": "IFR", "altitude_fl": 180, "text": (
            "CONDOR 71, Alpha Approach, Clearance Delivery. Cleared to Iron Mountain via filed route. "
            "Climb and maintain flight level one-eight-zero. Squawk four-seven-one-two. Departure "
            "frequency one-two-four-point-three-five.")})],
    ]),
    Rule(r"ready to taxi", [[("issue_clearance", {"clearance_type": "TAXI", "text": (
        "CONDOR 71, Ground. Taxi to runway two-seven-left via Alpha, Bravo. Hold short of runway "
        "two-seven-left. Wind two-five-zero at one-two.")})]]),
    Rule(r"Issue takeoff clearance", [[("issue_clearance", {"clearance_type": "TAKEOFF", "text": (
        "CONDOR 71, Tower. Runway two-seven-left, wind two-five-zero at one-two, cleared for takeoff. "
        "Turn left heading two-eight-five after departure. Report passing flight level "
        "one-zero-zero.")})]]),
    Rule(r"Issue a PIREP", [[("provide_weather_advisory", {"pirep": (
        "Moderate turbulence between flight level one-six-zero and two-zero-zero near Waypoint Bravo. "
        "Pilots at flight level one-four-zero report smooth air.")})]]),
    Rule(r"request descent to flight level one-four-zero", [[("issue_clearance", {
        "clearance_type": "ALTITUDE", "altitude_fl": 140,
        "text": "CONDOR 71, Alpha Approach. Descend and maintain flight level one-four-zero."})]]),
    Rule(r"requesting transit clearance for Restricted Area ROMEO-4", [
        [("check_sector_traffic", {})],
        [("issue_clearance", {"clearance_type": "ROMEO4_TRANSIT", "text": (
            "CONDOR 71, Alpha Approach. Cleared through Restricted Area Romeo-4. Descend at pilot's "
            "discretion to two thousand three hundred fifty. Report clear of Romeo-4.")})],
    ]),
    Rule(r"Requesting climb to flight level one-eight-zero and direct Iron Mountain", [[("issue_clearance", {
        "clearance_type": "DIRECT", "altitude_fl": 180,
        "text": "CONDOR 71, Alpha Approach. Roger, clear of Romeo-4. Climb and maintain flight level "
                "one-eight-zero. Cleared direct Iron Mountain."})]]),
    Rule(r"Issue approach and landing clearance", [[("issue_clearance", {"clearance_type": "APPROACH", "text": (
        "CONDOR 71, Alpha Approach. Cleared ILS approach runway two-seven-left. Altimeter "
        "two-niner-niner-two. Cleared to land runway two-seven-left.")})]]),
]

NOMINAL = {"COMMANDER": COMMANDER, "COPILOT": COPILOT, "NAVIGATOR": NAVIGATOR,
           "LOADMASTER": LOADMASTER, "ATC": ATC}

#: A Loadmaster who jumps the gun: tries the door and a release at drop
#: preparation, before any authorization.  Both are refused; the mission then
#: proceeds normally.
ROGUE_LOADMASTER = {
    **NOMINAL,
    "LOADMASTER": [
        Rule(r"Begin drop preparation", [
            [("open_door", {})],
            [("execute_airdrop", {"bundle_id": "B-03"})],
            *_LM_PRE_DROP,
        ]) if rule.when == r"Begin drop preparation" else rule
        for rule in LOADMASTER
    ],
}

#: A Commander who calls the drop the moment the door is reported open, four
#: minutes before the CARP.  Nothing refuses it: an early release is physically
#: possible.  The bundles miss the drop zone and the scorecard says so.  This
#: reproduces what the first live crew did.
EAGER_COMMANDER = {
    **NOMINAL,
    "COMMANDER": [
        Rule(r"Cargo door open", [[("authorize_airdrop", {})]], unless_logged=r"ABORT AIRDROP")
        if rule.when == r"at the CARP on the drop run" else rule
        for rule in COMMANDER
    ],
}

PLAYBOOKS = {"scripted": NOMINAL, "nominal": NOMINAL, "rogue": ROGUE_LOADMASTER, "eager": EAGER_COMMANDER}


def scripted_models(playbook: str | dict = "scripted") -> dict[str, ScriptedChatModel]:
    """Role -> scripted model, ready to pass to agents.factory.build_crew."""
    book = PLAYBOOKS[playbook] if isinstance(playbook, str) else playbook
    return {role: ScriptedChatModel(role=role, playbook=rules) for role, rules in book.items()}
