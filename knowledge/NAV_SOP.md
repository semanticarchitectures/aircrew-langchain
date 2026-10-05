# CONDOR OPERATIONS — NAVIGATOR / MISSION SYSTEMS OPERATOR (NAV) STANDARD OPERATING PROCEDURES
**Document:** NAV_SOP
**Aircraft Type:** CONDOR-class Heavy Cargo (Fictional)
**Classification:** DEMONSTRATION — UNCLASSIFIED FICTIONAL

---

## 1. ROLE AND AUTHORITY

The Navigator / Mission Systems Operator (NAV) owns the route. The Navigator is responsible for all aspects of flight planning, waypoint tracking, airspace deconfliction, and drop zone offset computation. The Navigator is an advisor to the Aircraft Commander — the Navigator provides data and recommendations; the AC makes decisions.

**The Navigator is responsible for:**
- Pre-mission route planning and fuel analysis
- Real-time waypoint tracking and ETA reporting throughout flight
- Monitoring airspace for restrictions and conflicts
- Computing the Computed Air Release Point (CARP) for every DZ
- Coordinating DZ timing with the Loadmaster during drop approach
- Proactively reporting any deviation from plan, regardless of whether asked

**The Navigator does NOT:**
- Contact ATC directly (route amendment requests go through the AC to the Co-Pilot)
- Authorize airdrop execution (that authority belongs to the AC)
- Change the route unilaterally — propose amendments to the AC and await direction

---

## 2. PRE-MISSION ROUTE PLANNING

Before departure, the Navigator uses `compute_route` to generate the full route plan and delivers a Route Brief to the AC.

### 2.1 Route Brief Format
```
ROUTE BRIEF — [MISSION NAME]
NAVIGATOR to COMMANDER

ROUTE: [Origin] → [WPT 1] → [WPT 2] → [DZ] → [WPT 3] → [Destination]
TOTAL DISTANCE: [x] NM
PLANNED CRUISE: FL[xxx]

LEG SUMMARY:
  [Origin] → [WPT 1]: [bearing]° / [dist] NM / ETE [min] min / Fuel burn [x] lbs
  [WPT 1] → [WPT 2]:  [bearing]° / [dist] NM / ETE [min] min / Fuel burn [x] lbs
  [WPT 2] → [DZ]:     [bearing]° / [dist] NM / ETE [min] min / Fuel burn [x] lbs
  [DZ] → [WPT 3]:     [bearing]° / [dist] NM / ETE [min] min / Fuel burn [x] lbs
  [WPT 3] → [Dest]:   [bearing]° / [dist] NM / ETE [min] min / Fuel burn [x] lbs

TOTAL FUEL BURN (planned): [x] lbs
FUEL REMAINING AT DESTINATION (planned): [x] lbs
BINGO FUEL STATE: [x] lbs — divert to [alternate airfield] if reached

AIRSPACE NOTES: [Any restrictions, active areas, required clearances]
ALTERNATE AIRFIELD: [Name] — [bearing]° / [dist] NM from DZ
```

### 2.2 AIRDROP ALPHA Route Data
For Operation AIRDROP ALPHA, the planned route is:

| Leg | From | To | Bearing | Distance | ETE | Fuel Burn |
|-----|------|----|---------|----------|-----|-----------|
| 1 | KIRO | WPT ALPHA | 285° | 85 NM | 18 min | 3,500 lbs |
| 2 | WPT ALPHA | WPT BRAVO | 310° | 110 NM | 24 min | 4,200 lbs |
| 3 | WPT BRAVO | DZ-ALPHA | 295° | 45 NM | 10 min | 1,700 lbs |
| 4 | DZ-ALPHA | WPT CHARLIE | 120° | 90 NM | 20 min | 3,400 lbs |
| 5 | WPT CHARLIE | KIRO | 095° | 100 NM | 22 min | 3,700 lbs |

**Total route distance:** 430 NM
**Total planned fuel burn:** 16,500 lbs
**Planned fuel remaining at KIRO:** 28,500 lbs
**Bingo fuel:** 32,000 lbs remaining total (divert to Ridgeway Field, 35 NM south of DZ-ALPHA)
**Alternate airfield:** Ridgeway Field (KRDW) — 185° / 35 NM from DZ-ALPHA

---

## 3. ENROUTE MONITORING AND REPORTING

### 3.1 Mandatory Waypoint Reports
At each waypoint, the Navigator reports to the AC without being asked:

```
"COMMANDER, NAVIGATOR. Passing Waypoint [NAME].
Groundspeed [x] knots, on/off track by [x] NM [left/right].
ETA next waypoint [WPT]: [time].
ETA DZ-ALPHA: [time].
Fuel state: [x] lbs — [status vs. plan].
No / [Note any] airspace conflicts ahead."
```

### 3.2 Off-Track Reporting
If the aircraft is more than **2 NM off planned track**, report immediately:
> "COMMANDER, NAVIGATOR. We are [x] NM [left/right] of track. Current heading [x]°. Recommend heading [x]° to rejoin. At current deviation, DZ ETA shifts by [+/-x] minutes."

### 3.3 Fuel State Monitoring
Monitor fuel burn at each waypoint against the plan. Report any significant variance (>500 lbs over plan):
> "COMMANDER, NAVIGATOR. Fuel burn is [x] lbs over plan at Waypoint [NAME]. Current state [x] lbs. Revised bingo ETA [time]. Recommend [action]."

### 3.4 Weather at Waypoints
Use `get_weather_at_waypoint` when approaching each waypoint and proactively report deteriorating conditions:
> "COMMANDER, NAVIGATOR. Weather check at Waypoint BRAVO shows [conditions]. Recommend [action / advisory]."

---

## 4. AIRSPACE MONITORING

Use `check_airspace` before and during each leg. Report any conflict immediately.

### 4.1 Restricted Area ROMEO-4
Restricted Area ROMEO-4 surrounds DZ-ALPHA. The aircraft must have ATC authorization (via Co-Pilot) before entering. The Navigator tracks the Romeo-4 boundary and provides the Co-Pilot with the ETA for entry:
> "COPILOT, NAVIGATOR. Romeo-4 boundary in [x] minutes. Ensure clearance is confirmed."

If clearance is not confirmed when the boundary is 5 minutes out, escalate to the AC:
> "COMMANDER, NAVIGATOR. Romeo-4 entry in 5 minutes, clearance not yet confirmed. Recommend AC direct COPILOT to expedite."

---

## 5. DROP ZONE OFFSET AND CARP COMPUTATION

The CARP (Computed Air Release Point) is the geographic position at which cargo must be released to land on the drop zone given current wind and airdrop altitude.

### 5.1 CARP Computation
Use `calculate_dz_offset(dz_coords, wind, altitude)`. Report the result to both the AC and Loadmaster:

```
"COMMANDER, LOADMASTER — NAVIGATOR. CARP computed for DZ-ALPHA.
Release Point: [bearing]° / [distance] NM from DZ center.
Wind: [direction]/[speed] knots at drop altitude.
Drop Altitude: [x] ft AGL ([x] ft MSL at DZ elevation 850 ft).
Confidence: [HIGH / MEDIUM — recompute if wind shifts >5 knots].
Begin DZ approach from Waypoint BRAVO, maintain [heading]°."
```

### 5.2 CARP for AIRDROP ALPHA
DZ-ALPHA coordinates: 42.8°N / 95.4°W
DZ elevation: 850 ft MSL
Planned drop altitude: 1,500 ft AGL (2,350 ft MSL)
Planned wind at drop altitude: 270°/18 knots

At planned conditions, the CARP is approximately **4.2 NM northwest** of DZ center.
Recompute CARP if actual wind deviates >5 knots from planned, or if drop altitude changes.

### 5.3 CARP Update on Wind Change
If wind shifts during approach, recompute and re-report immediately:
> "COMMANDER, LOADMASTER — NAVIGATOR. CARP updated. Wind now [direction]/[speed]. New release point [bearing]° / [distance] NM from DZ. Previous CARP is no longer valid."

---

## 6. ALTERNATE DZ AND ROUTE AMENDMENTS

If the primary DZ is unavailable (weather, ATC denial, abort), the Navigator computes an alternate route and DZ:

1. Query available alternates from mission brief
2. Compute route to alternate, including fuel impact
3. Brief AC: "COMMANDER, NAVIGATOR. Alternate DZ [NAME] is [bearing]° / [distance] NM. Route amendment adds [x] NM and [x] lbs fuel burn. Current fuel state supports this. Recommend [action]."
4. Await AC direction before updating route

**AIRDROP ALPHA Alternate DZ:** DELTA FIELD — 22 NM northeast of KIRO. Fuel penalty: +900 lbs. Within mission fuel margins.
