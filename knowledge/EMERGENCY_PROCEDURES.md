# CONDOR OPERATIONS — EMERGENCY PROCEDURES
**Document:** EMERGENCY_PROCEDURES
**Aircraft Type:** CONDOR-class Heavy Cargo (Fictional)
**Applies To:** All crew — AC, CP, NAV, LM
**Classification:** DEMONSTRATION — UNCLASSIFIED FICTIONAL

---

> **GENERAL RULE:** In any emergency — Fly the aircraft first. Navigate second. Communicate third.
> The Aircraft Commander holds emergency authority. Co-Pilot manages all external communications.
> Any crew member may initiate an emergency call. All emergencies are reported to the AC immediately.

---

## 1. EMERGENCY DECLARATION — AUTHORITY AND FORMAT

### 1.1 MAYDAY (Distress — Immediate danger to life or aircraft)
**Who declares:** Aircraft Commander, via the `declare_emergency` tool. Co-Pilot transmits to ATC.

**MAYDAY transmission (Co-Pilot to ATC):**
```
"MAYDAY, MAYDAY, MAYDAY.
Alpha Approach, CONDOR 71.
[Nature of emergency].
[Souls on board: X].
[Fuel remaining: X lbs].
[Position and intended action]."
```

**ATC will:** Acknowledge, clear traffic, provide direct routing to nearest suitable airfield.

### 1.2 PAN-PAN (Urgency — Serious but not immediately life-threatening)
**Who declares:** Aircraft Commander.

**PAN-PAN transmission (Co-Pilot to ATC):**
```
"PAN-PAN, PAN-PAN, PAN-PAN.
Alpha Approach, CONDOR 71.
[Nature of urgency].
[Assistance required]."
```

### 1.3 Any Crew Member Can Initiate
Any crew member who identifies an emergency condition immediately calls it out to ALL STATIONS:
```
"ALL STATIONS, [CALLSIGN]. [Emergency description]. [Immediate action taken]."
```
The AC then assumes command and declares MAYDAY or PAN-PAN as appropriate.

---

## 2. ENGINE FAILURE

### 2.1 Recognition
- Sudden loss of power on one side
- Engine fire warning
- Uncommanded yaw

### 2.2 Immediate Actions (AC directs, CP executes)
1. **Maintain aircraft control** — counteract yaw, maintain altitude if possible
2. **Identify failed engine** — "Left/Right engine — CONFIRM"
3. **Isolate** — Co-Pilot executes Engine Failure checklist (CHECKLISTS.md)
4. **Declare PAN-PAN** — AC directs Co-Pilot: "COPILOT, COMMANDER. Declare PAN-PAN, engine failure, request direct routing nearest suitable."
5. **Navigator** — "COMMANDER, NAVIGATOR. Nearest suitable airfield is [NAME], [bearing]° [distance] NM. ETA [x] minutes."
6. **Loadmaster** — Secure cargo, prepare for possible emergency landing, report bay status

### 2.3 If Engine Fire (MAYDAY)
If engine fire warning, escalate immediately to MAYDAY. Use `declare_emergency("ENGINE_FIRE", description)`.

---

## 3. CARGO SHIFT / CG EXCEEDANCE

### 3.1 Recognition
- Loadmaster reports aft bundle shift
- Unexpected change in pitch trim
- Loadmaster computes CG outside limits (>35.0% or <25.0% MAC)

### 3.2 Immediate Actions
1. **Loadmaster** (immediate, no AC required): Abort any in-progress airdrop. Call ABORT.
2. **Loadmaster → ALL STATIONS** (EMERGENCY): Report cargo shift and current CG status
3. **AC**: Assess aircraft control, declare PAN-PAN if controllable with exceedance, MAYDAY if control is affected
4. **Loadmaster**: Attempt to re-secure or redistribute cargo if safe
5. **Navigator**: Compute route to nearest suitable airfield if divert required
6. **Co-Pilot**: Contact ATC on AC direction

### 3.3 CG Exceedance Limits
- CG > 35.0% MAC (aft): Pitch-up tendency — nose-heavy control inputs may be required
- CG < 25.0% MAC (forward): Pitch-down tendency — nose-heavy; elevator authority may be limited
- Either condition is a PAN-PAN minimum; significant exceedance is MAYDAY

---

## 4. CARGO DOOR MALFUNCTION

### 4.1 Door Fails to Open
1. **Loadmaster**: Do not force. Call to AC: "COMMANDER, LOADMASTER. Cargo door malfunction — door will not open. Unable to execute airdrop."
2. **AC**: Abort airdrop run. Contact ATC via Co-Pilot to advise of abort.
3. **Navigator**: Compute return route to KIRO or nearest suitable field.
4. **Loadmaster**: Secure all cargo and verify all bundles remain safely restrained.

### 4.2 Door Jams Open (Cannot Close)
This is a MAYDAY-level emergency affecting structural integrity and pressurization.
1. **Loadmaster** (EMERGENCY, ALL STATIONS): "ALL STATIONS, LOADMASTER. Cargo door jammed open. Unable to close."
2. **AC**: Declare MAYDAY. Maintain low altitude (below pressure differential threshold). Do not climb above 10,000 ft MSL.
3. **Co-Pilot**: Declare MAYDAY to ATC; request immediate approach and landing
4. **Navigator**: Direct routing to nearest suitable long-runway airfield
5. **Loadmaster**: Secure all cargo to prevent further shift; stay clear of open door

### 4.3 Partial Door Opening (<80% travel)
Airdrop abort (Loadmaster authority). Do not drop cargo through a partially-open door — bundle may contact door frame. Report to AC and await direction.

---

## 5. LOSS OF COMMUNICATIONS

### 5.1 CP Loses Contact with ATC
1. Three attempts on primary frequency (124.35 MHz): "Alpha Approach, CONDOR 71, radio check."
2. If no response, attempt on guard frequency (121.5 MHz)
3. Report to AC immediately: "COMMANDER, COPILOT. Lost comms with ATC. Attempting guard."
4. If guard also fails, squawk **7600** (lost comms code) — confirm with AC before squawking
5. AC decides: continue as per lost-comms procedures (maintain last cleared altitude/route) or divert

### 5.2 Lost Comms Procedure
If radio contact cannot be restored:
- Maintain last ATC clearance altitude and route
- If in VMC, proceed to destination per VFR lost-comms rules
- At destination, follow light gun signal procedures on final approach
- Navigator provides AC with routing options

---

## 6. CREW INCAPACITATION

### 6.1 Any Crew Member Incapacitated
1. Identifying crew member broadcasts: "ALL STATIONS, [CALLSIGN]. [Name of incapacitated crew member] is incapacitated."
2. AC assesses mission continuation:
   - If AC incapacitated: Co-Pilot assumes command; declares PAN-PAN; requests direct routing
   - If Co-Pilot incapacitated: AC assumes ATC communications directly (emergency exception to standard SOP)
   - If Navigator incapacitated: AC directs Co-Pilot to request ATC navigation assistance
   - If Loadmaster incapacitated: AC assesses cargo status; abort airdrop if LM cannot certify W&B

### 6.2 Medical Emergency
Declare PAN-PAN (or MAYDAY if life-threatening). Request priority handling and medical services at destination.

---

## 7. DIVERT AIRFIELDS

| Airfield | Designation | Location from KIRO | Notes |
|----------|-------------|-------------------|-------|
| Iron Mountain AB (primary) | KIRO | — | Home base; full services |
| Ridgeway Field | KRDW | 185° / 35 NM from DZ-ALPHA | Bingo divert; long runway; limited services |
| Cascade Regional | KCSC | 090° / 55 NM from KIRO | Full services; commercial airfield |

**Divert fuel requirement:** Always retain enough fuel to reach KRDW plus 8,000 lbs reserve.

---

## 8. EMERGENCY AUTHORITY SUMMARY

| Decision | Authority |
|----------|-----------|
| Declare MAYDAY / PAN-PAN | Aircraft Commander |
| Abort airdrop (mid-run) | Loadmaster (no AC authorization required) |
| Initiate divert | Aircraft Commander |
| Assume command (AC incapacitated) | Co-Pilot |
| Close cargo door (safety hazard) | Loadmaster (no AC authorization required) |
| Direct routing request to ATC | Co-Pilot (on AC direction) |
| Any other emergency action | Aircraft Commander |
