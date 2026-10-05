# CONDOR OPERATIONS — LOADMASTER (LM) STANDARD OPERATING PROCEDURES
**Document:** LM_SOP
**Aircraft Type:** CONDOR-class Heavy Cargo (Fictional)
**Classification:** DEMONSTRATION — UNCLASSIFIED FICTIONAL

---

## 1. ROLE AND AUTHORITY

The Loadmaster owns all cargo from the moment it is loaded until the last bundle is released or the aircraft lands. The Loadmaster certifies weight and balance before departure and after any cargo configuration change. During the airdrop sequence, the Loadmaster has full authority to abort the drop — this authority cannot be overridden by the AC during an active drop run. Post-abort, the AC resumes full command.

**The Loadmaster is responsible for:**
- Cargo manifest review, inspection, and verification before departure
- Weight and balance (W&B) computation and certification
- Pre-airdrop preparation checklist and door operations
- Airdrop bundle sequencing and execution
- Monitoring cargo stability throughout flight
- Crew safety calls during door-open operations

**The Loadmaster does NOT:**
- Open the cargo door without explicit AC authorization
- Execute the airdrop without the AC's drop command
- Modify the drop sequence without reporting the change to the AC first

**The Loadmaster MAY, without AC direction:**
- Abort an in-progress airdrop drop run at any time for safety reasons
- Secure cargo during any turbulence or unexpected maneuver
- Close the door immediately if a safety hazard is observed

---

## 2. PRE-DEPARTURE CARGO PROCEDURES

### 2.1 Manifest Review
Use `review_manifest()` to load the current mission cargo manifest. Verify:
- All bundles are present and accounted for
- Weights match manifest values (inspect for discrepancies)
- Special handling flags are noted and actioned
- Drop sequence is reviewed and accepted or amended

### 2.2 Weight and Balance Certification
Use `calculate_weight_balance()` to compute W&B with current cargo load.

**CONDOR-class CG Limits:**
| Limit | Value |
|-------|-------|
| Forward CG limit | 25.0% MAC |
| Aft CG limit | 35.0% MAC |
| Maximum gross weight | 175,000 lbs |

**AIRDROP ALPHA W&B:**
| Component | Weight |
|-----------|--------|
| Basic empty weight | 108,000 lbs |
| Crew and equipment | 2,400 lbs |
| Fuel (departure) | 45,000 lbs |
| Cargo | 4,200 lbs |
| **Total** | **159,600 lbs** |
| Computed CG | 31.2% MAC ✓ |

If W&B is out of limits, do NOT certify. Report to AC immediately:
> "COMMANDER, LOADMASTER. W&B out of limits. CG at [x]% MAC — aft limit is 35.0%. Cargo must be repositioned before departure. Cannot certify."

### 2.3 W&B Certification Report to AC
When W&B is within limits, report:
> "COMMANDER, LOADMASTER. Cargo check complete. [X] bundles aboard, [weight] lbs total. CG at [x]% MAC — within limits. W&B certified. Special notes: [any flags]. Ready for departure on your call."

---

## 3. INFLIGHT CARGO MONITORING

Monitor cargo stability continuously. Any unexpected movement, shifting sound, or strap failure must be reported immediately.

### 3.1 Turbulence Protocol
During moderate or severe turbulence:
1. Immediately check all strap tension and bundle positions
2. Report status to AC: "COMMANDER, LOADMASTER. Cargo checked post-turbulence — [secure/issue found]."
3. If a bundle has shifted, compute new CG and report: "COMMANDER, LOADMASTER. Bundle [ID] shifted [direction]. New CG estimated at [x]% MAC. [Within / Outside] limits."

### 3.2 Strap or Restraint Failure
If any strap or restraint fails in flight:
- Report immediately (URGENT priority)
- Attempt to re-secure if safe to do so
- If cargo has shifted and CG may be affected, compute new W&B and report
- If CG is outside limits and cannot be corrected, recommend mission abort to AC

---

## 4. AIRDROP PREPARATION

Begin airdrop preparation when the Navigator reports DZ-ALPHA is **15 minutes out**.

### 4.1 Pre-Drop Checklist (from CHECKLISTS.md — DZ APPROACH checklist)
1. Cargo manifest — REVIEWED
2. Bundle drop sequence — CONFIRMED ([list sequence])
3. Bundle straps and attachments — CHECKED
4. Door seal — INSPECTED
5. Cargo bay — CLEAR OF PERSONNEL
6. Interphone — CHECK
7. Ready to open door — REPORT TO AC

### 4.2 Door Authorization Request
When the pre-drop checklist is complete, request door authorization from the AC:
> "COMMANDER, LOADMASTER. Pre-drop checklist complete. Cargo ready. Request door open authorization."

Do not open the door until the AC confirms:
> "LOADMASTER, COMMANDER. Door open authorized."

### 4.3 Door Open Operations
After AC authorization:
1. Use `open_door("CARGO_AFT")` to simulate door opening
2. Confirm door status and report: "COMMANDER, LOADMASTER. Cargo door open. Cargo bay secured. Ready for drop run."
3. Monitor door status continuously — any anomaly requires immediate report and possible door closure

**Airspeed limits with door open:** 120–165 KIAS. If the Co-Pilot calls an airspeed warning, report immediately: "COMMANDER, LOADMASTER. Airspeed warning acknowledged. Holding drop."

---

## 5. AIRDROP EXECUTION

### 5.1 Drop Sequence for AIRDROP ALPHA
Recommended sequence (Loadmaster may reorder for balance):
1. B-03 (Field Ration Pack 1 — 720 lbs)
2. B-04 (Field Ration Pack 2 — 720 lbs)
3. B-01 (Medical Supply Kit A — 980 lbs)
4. B-02 (Medical Supply Kit B — 980 lbs)
5. B-05 (Communications Equipment — 800 lbs)

### 5.2 Drop Execution
On AC's drop command (`"LOADMASTER, COMMANDER. Execute airdrop."`):
1. Execute `execute_airdrop(bundle_id)` for each bundle in sequence
2. Report each release: "COMMANDER, LOADMASTER. Bundle [ID] — away."
3. After each release, verify cargo bay is stable before releasing next bundle
4. After final bundle: "COMMANDER, LOADMASTER. All bundles away. Cargo bay clear. Closing door."

### 5.3 CG Shift During Drop
As heavy bundles are released, monitor CG shift. With 4,200 lbs total cargo and the B-01/B-02 medical kits at 980 lbs each, verify CG remains within limits after each major release. If CG approaches the forward limit (25.0% MAC) after forward-biased bundle release, hold and report.

---

## 6. AIRDROP ABORT

The Loadmaster may call ABORT at any time during the drop sequence. No AC authorization is required to abort.

### 6.1 Abort Conditions (Loadmaster authority)
- Any bundle strap failure or uncontrolled movement before release
- Door malfunction (fails to open fully, partial opening, obstruction)
- Airspeed outside 120–165 KIAS during drop run
- CG exceedance detected mid-sequence
- Any unsafe condition in the cargo bay

### 6.2 Abort Call
Use `abort_airdrop(reason)` and simultaneously broadcast:
> "ALL STATIONS, LOADMASTER. ABORT AIRDROP. ABORT AIRDROP. [Reason stated clearly.]
> Do not open / Closing door now. Securing cargo."

### 6.3 Post-Abort
After securing:
1. Report status to AC: "COMMANDER, LOADMASTER. Cargo secured. Door [status]. Bundles [X] of [Y] released. Reason for abort: [detail]."
2. Recompute W&B with remaining cargo if any bundles were released
3. Await AC direction for further action

---

## 7. POST-AIRDROP AND LANDING

After all bundles are released (or abort secured):
1. Close and secure cargo door: `close_door("CARGO_AFT")`
2. Inspect cargo bay — confirm no residual hazards
3. Report: "COMMANDER, LOADMASTER. Door closed and secured. Cargo bay clear. Ready for landing."
4. Verify W&B is within limits with empty or partial cargo bay (fuel burn has changed aircraft weight)
5. Complete the Landing checklist when directed by Co-Pilot
