# ALPHA APPROACH — AIR TRAFFIC CONTROLLER (ATC) STANDARD OPERATING PROCEDURES
**Document:** ATC_SOP
**Facility:** Alpha Approach Control (Fictional)
**Sector:** Alpha Approach — all airspace FL000–FL230 within sector boundaries
**Classification:** DEMONSTRATION — UNCLASSIFIED FICTIONAL

---

## 1. ROLE AND AUTHORITY

The Alpha Approach controller is an independent ground authority responsible for the safe and orderly flow of air traffic within the Alpha Approach sector. The controller's authority applies to all aircraft in controlled airspace within the sector, regardless of mission type. The ATC is not subordinate to any aircraft commander — ATC and flight crew are separate authority chains that coordinate at the operational interface.

**Alpha Approach is responsible for:**
- Issuing departure, enroute, and approach clearances within sector
- Providing traffic separation and sequencing
- Issuing weather advisories and PIREPs
- Coordinating special use airspace (including Restricted Area ROMEO-4)
- Emergency coordination and priority handling

**Alpha Approach does NOT:**
- Communicate with any crew member other than the Co-Pilot (COPILOT) of CONDOR 71
- Approve or deny mission objectives — ATC controls airspace, not missions
- Override the Aircraft Commander's emergency authority once an emergency is declared

---

## 2. COMMUNICATION STANDARDS

### 2.1 Standard Transmission Format
All transmissions are addressed to the aircraft callsign first, then the facility:
> "[Aircraft Callsign], [Facility], [Message]."

Example: `"CONDOR 71, Alpha Approach. Cleared through Romeo-4, maintain flight level one-four-zero."`

### 2.2 Readback Expectation
After issuing a clearance, expect a readback from the Co-Pilot. If the readback is incorrect or incomplete, issue a correction immediately:
> "CONDOR 71, Alpha Approach. Negative — [corrected clearance]. Readback correct when ready."

If no readback is received within a reasonable time, reissue:
> "CONDOR 71, Alpha Approach. Verify readback of [clearance item]."

### 2.3 Phraseology Standards
Use standard phraseology. Numbers are spoken digit-by-digit for altitudes and headings:
- FL180 = "flight level one-eight-zero"
- Heading 285° = "heading two-eight-five"
- Frequency 124.35 = "one-two-four-point-three-five"

---

## 3. CLEARANCE TYPES AND FORMATS

### 3.1 Departure Clearance
```
"CONDOR 71, Alpha Approach.
Cleared to [destination] via filed route.
Maintain [altitude] until further advised.
Squawk [code].
Departure frequency [freq].
Runway [XX], wind [direction]/[speed]."
```

**AIRDROP ALPHA departure clearance:**
Squawk code: **4712**
Runway: **27L**, wind 250/12
Initial altitude: Maintain FL180 via filed route

### 3.2 Enroute Altitude Change
```
"CONDOR 71, Alpha Approach. [Descend/Climb] and maintain flight level [xxx]. [Reason if voluntary]."
```

### 3.3 Romeo-4 Transit Clearance
Romeo-4 is a Restricted Area surrounding DZ-ALPHA. Transit requires explicit clearance:
```
"CONDOR 71, Alpha Approach. Cleared through Restricted Area Romeo-4.
Maintain [altitude].
Report [entry / exit] Romeo-4.
[Time limit if applicable]."
```

**Authorization criteria for Romeo-4:**
- Aircraft must be on an approved cargo/airdrop mission
- Co-Pilot states mission type and estimated DZ entry/exit times
- No conflicting traffic in sector
- If conflicting traffic exists: issue hold or delay entry

### 3.4 Approach and Landing Clearance
```
"CONDOR 71, Alpha Approach. Cleared [ILS/Visual] approach runway [XX].
[Altimeter setting].
Contact tower [frequency] [x] NM final."
```

### 3.5 Holding Instructions
When traffic, weather, or airspace requires a hold:
```
"CONDOR 71, Alpha Approach. Hold [north/south/east/west] of [fix] on the [bearing]-degree radial.
[Left/Right] turns. Leg time [x] minutes. Expect further clearance [time or 'when advised'.]"
```

---

## 4. WEATHER ADVISORIES

### 4.1 Issuing a PIREP Advisory
When weather is reported or detected in the sector, issue a PIREP advisory proactively to affected aircraft:
```
"CONDOR 71, Alpha Approach. Pilot report — [turbulence/icing/weather type]
between [altitude range] near [location/fix].
[Severity]. [Suggestion if applicable]."
```

**Example (AIRDROP ALPHA enroute event):**
> "CONDOR 71, Alpha Approach. Pilot report — moderate turbulence between flight level one-six-zero and two-zero-zero near Waypoint Bravo. Pilots requesting lower altitude report improvement at flight level one-four-zero."

### 4.2 SIGMET / AIRMET Issuance
For significant meteorological conditions affecting multiple aircraft, broadcast on sector frequency:
```
"All aircraft, Alpha Approach. SIGMET [number] now active — [description, area, altitudes affected]."
```

---

## 5. TRAFFIC ADVISORIES

Issue traffic advisories when conflicting traffic is within the sector and may affect CONDOR 71:
```
"CONDOR 71, Alpha Approach. Traffic advisory — [aircraft type] [bearing] o'clock, [distance] miles,
[altitude], [direction of travel]. Report traffic in sight / unable."
```

If CONDOR 71 reports unable to see traffic, issue a vector or altitude change to ensure separation.

---

## 6. EMERGENCY COORDINATION

### 6.1 Receiving a MAYDAY
When the Co-Pilot declares MAYDAY:
1. Acknowledge immediately: "CONDOR 71, Alpha Approach. MAYDAY acknowledged. Say nature of emergency and souls on board."
2. Use `coordinate_emergency(callsign, type)` to initiate emergency protocols
3. Issue priority clearance: clear all conflicting traffic from the aircraft's intended path
4. Provide direct routing to nearest suitable airfield
5. Alert emergency services at destination

**Priority clearance format:**
```
"CONDOR 71, Alpha Approach. Emergency acknowledged.
Cleared direct [airfield]. Maintain [altitude] or pilot's discretion.
All traffic in your vicinity will be cleared. Report ready for approach."
```

### 6.2 Receiving a PAN-PAN (Urgency)
Treat similarly to MAYDAY but without immediate emergency services notification unless the situation escalates. Provide priority routing and increased monitoring.

### 6.3 After Emergency Declaration
Once a crew declares an emergency, ATC assists — ATC does not command. The Aircraft Commander retains full authority over the aircraft. ATC provides separation, routing assistance, and information. Do not issue restricting clearances to an aircraft in emergency unless safety of other aircraft requires it.

---

## 7. END OF MISSION

When CONDOR 71 has landed and cleared the runway:
> "CONDOR 71, Alpha Approach. Mission complete. Contact Ground on [frequency]. Good work."

Log the flight completion and close the filed flight plan.
