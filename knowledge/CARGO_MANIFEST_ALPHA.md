# OPERATION AIRDROP ALPHA — CARGO MANIFEST
**Document:** CARGO_MANIFEST_ALPHA
**Mission:** Operation AIRDROP ALPHA
**Aircraft:** CONDOR 71
**Loadmaster Authority:** This document is the Loadmaster's primary reference for all cargo operations.
**Classification:** DEMONSTRATION — UNCLASSIFIED FICTIONAL

---

## 1. BUNDLE INVENTORY

| Bundle ID | Description | Weight (lbs) | Category | Special Handling | Position in Bay |
|-----------|-------------|--------------|----------|-----------------|-----------------|
| B-01 | Medical Supply Kit A | 980 | Medical / Priority | Handle with care — fragile contents | Bay Position 2 (forward center) |
| B-02 | Medical Supply Kit B | 980 | Medical / Priority | Handle with care — fragile contents | Bay Position 3 (aft center) |
| B-03 | Field Ration Pack 1 | 720 | Consumables | None | Bay Position 4 (aft) |
| B-04 | Field Ration Pack 2 | 720 | Consumables | None | Bay Position 5 (aft) |
| B-05 | Communications Equipment | 800 | Equipment | Moisture-sensitive — inspect seal before drop | Bay Position 1 (forward) |

**Total bundle count:** 5
**Total cargo weight:** 4,200 lbs

---

## 2. WEIGHT AND BALANCE

### 2.1 Aircraft Configuration at Departure

| Component | Weight (lbs) |
|-----------|-------------|
| Basic empty weight (CONDOR-class) | 108,000 |
| Crew and personal equipment (4 crew) | 2,400 |
| Fuel at departure | 45,000 |
| Cargo (all 5 bundles) | 4,200 |
| **Maximum Gross Weight (limit)** | **175,000** |
| **Total departure weight** | **159,600** ✓ |

### 2.2 Center of Gravity

| Parameter | Value | Status |
|-----------|-------|--------|
| Forward CG limit | 25.0% MAC | — |
| Aft CG limit | 35.0% MAC | — |
| **Computed CG at departure** | **31.2% MAC** | **✓ WITHIN LIMITS** |

### 2.3 CG Shift During Airdrop (Estimated)

As bundles are released sequentially, the CG will shift. The Loadmaster must monitor CG after each significant release.

| After releasing | Est. CG change | Estimated CG | Status |
|-----------------|---------------|--------------|--------|
| B-03 (720 lbs) | Slight fwd | ~31.0% MAC | ✓ |
| B-04 (720 lbs) | Slight fwd | ~30.7% MAC | ✓ |
| B-01 (980 lbs) | Moderate fwd | ~30.2% MAC | ✓ |
| B-02 (980 lbs) | Moderate fwd | ~29.5% MAC | ✓ |
| B-05 (800 lbs) | Slight fwd | ~29.0% MAC | ✓ |

All post-drop CG values are within limits using the recommended sequence. If the sequence is changed (e.g., B-01 before B-03), recompute using `calculate_weight_balance()`.

---

## 3. RECOMMENDED DROP SEQUENCE

The following sequence is recommended to maintain CG within limits throughout the airdrop:

| Order | Bundle ID | Weight | Rationale |
|-------|-----------|--------|-----------|
| 1st | B-03 | 720 lbs | Lightest aft bundle — minimal CG impact |
| 2nd | B-04 | 720 lbs | Lightest aft bundle — minimal CG impact |
| 3rd | B-01 | 980 lbs | Medical priority — deliver early once aft is clear |
| 4th | B-02 | 980 lbs | Medical priority — deliver before equipment |
| 5th | B-05 | 800 lbs | Equipment — last; forward position releases last |

**The Loadmaster may reorder at their discretion** provided `calculate_weight_balance()` confirms CG remains within limits at every step of the new sequence.

---

## 4. SPECIAL HANDLING NOTES

### B-01 and B-02 — Medical Supply Kits (Priority)
- Fragile contents — minimize impact during airdrop. Parachute deployment confirmed for both bundles.
- If only a partial drop is possible, prioritize B-01 and B-02 over all other bundles.
- If parachute malfunction is suspected on either medical bundle, report to AC before release.

### B-05 — Communications Equipment (Moisture-Sensitive)
- Verify outer packaging seal is intact before door opens.
- If seal is broken or packaging is wet, hold B-05 and report to AC: "COMMANDER, LOADMASTER. B-05 packaging compromised — moisture seal broken. Recommend retaining B-05 aboard unless AC directs otherwise."
- B-05 may be retained aboard without mission failure if drop is unsafe.

---

## 5. ABORT CONDITIONS (LOADMASTER AUTHORITY)

The Loadmaster will call ABORT and use `abort_airdrop(reason)` if any of the following are observed during the drop run:

| Condition | Action |
|-----------|--------|
| Any strap or restraint failure before release | ABORT — secure cargo, report CG status |
| Door fails to open fully or jams | ABORT — do not force; report to AC |
| Door opens partially (< 80% travel) | ABORT — unsafe release angle |
| CG exceedance detected (>35.0% or <25.0% MAC) | ABORT — report immediately |
| Airspeed < 120 KIAS or > 165 KIAS | HOLD drop — report to Co-Pilot |
| Bundle caught or snagged on door frame | ABORT — do not force release |
| Any crew member in unsafe position near door | ABORT — crew safety overrides mission |

---

## 6. POST-DROP WEIGHT AND BALANCE

After a full drop (all 5 bundles released):

| Component | Weight (lbs) |
|-----------|-------------|
| Basic empty weight | 108,000 |
| Crew and personal equipment | 2,400 |
| Fuel remaining (est. after drop) | ~37,500 |
| Cargo | 0 |
| **Total post-drop weight** | **~147,900 lbs** |
| Estimated post-drop CG | ~29.0% MAC ✓ |

The Loadmaster confirms post-drop W&B to AC before landing.
