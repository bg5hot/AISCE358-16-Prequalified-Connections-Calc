#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bolted Flange Plate (BFP) Moment Connection Design Verification
Based on AISC 358-16 Chapter 7, Section 7.6 - Design Procedure

BFP connections use flange plates welded (CJP) to the column flange and bolted
to the beam flange. The connection transfers moment through flange plate tension
/compression and bolt shear (threads excluded).

Key differences from other connection types:
  - Bolts in SHEAR (not tension like end-plate)
  - Only A490 / F2280 bolts prequalified (Section 7.5)
  - F_pr = M_f / (d + t_p)  [not d - t_f]
  - S_h = S_1 + s * (n/2 - 1)  [bolt centroid]

Usage:
    python bfp_design.py --beam-section W24x68 --column-section W14x120 \
        --span 300 --system-type SMF --n-bolts 4 --bolt-diameter 1.0
"""

import argparse
import sys
import io
import os
import csv
import math
from dataclasses import dataclass
from typing import Optional, Dict

# Set UTF-8 encoding for Windows console
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ====================== CONSTANTS ======================
# Resistance factors (AISC 358-16 Section 2.4.1)
PHI_D = 1.00  # Ductile limit states
PHI_N = 0.90  # Nonductile limit states

# Default material properties
DEFAULT_FY_BEAM = 50.0    # ksi (A992)
DEFAULT_FU_BEAM = 65.0    # ksi (A992)
DEFAULT_FY_PLATE = 50.0   # ksi (A572 Gr 50) — A36 (36/58) also prequalified
DEFAULT_FU_PLATE = 65.0   # ksi (A572 Gr 50)
DEFAULT_FY_COLUMN = 50.0  # ksi (A992)
DEFAULT_FU_COLUMN = 65.0  # ksi (A992)

# Steel properties
E = 29000.0  # Modulus of elasticity (ksi)


# ====================== DATA CLASSES ======================

@dataclass
class BeamSection:
    """Beam section properties"""
    designation: str
    d: float       # Depth (in)
    bf: float      # Flange width (in)
    tf: float      # Flange thickness (in)
    tw: float      # Web thickness (in)
    Zx: float      # Plastic section modulus (in^3)
    Fy: float = DEFAULT_FY_BEAM
    Fu: float = DEFAULT_FU_BEAM
    Ry: float = 1.1
    Rt: float = 1.2  # Ratio of expected tensile strength to specified min

    @property
    def dw(self) -> float:
        return self.d - 2 * self.tf

    @property
    def weight(self) -> float:
        """Approximate weight from designation (plf)"""
        try:
            return float(self.designation.upper().split('X')[1])
        except (ValueError, IndexError):
            return 999  # Unknown, skip check


@dataclass
class ColumnSection:
    """Column section properties"""
    designation: str
    d: float
    bf: float
    tf: float
    tw: float
    Zx: float
    Fy: float = DEFAULT_FY_COLUMN
    Fu: float = DEFAULT_FU_COLUMN
    Ry: float = 1.1


@dataclass
class FlangePlateGeometry:
    """Flange plate and bolt configuration per Section 7.5"""
    bp: float      # Plate width b_fp (in)
    tp: float      # Plate thickness t_p (in)
    Lp: float      # Plate total length from column face (in)

    # Bolt parameters
    db: float          # Bolt diameter d_b (in)
    bolt_grade: str    # A490 only for BFP prequalified
    n_bolts: int       # Number of bolts per flange (must be even)

    # Bolt layout per Section 7.5
    S1: float       # Distance from column face to first bolt row (in)
    s: float        # Spacing between bolt rows (in)

    # Edge distance at beam end
    ed_edge: float

    @property
    def Sh(self) -> float:
        """S_h per Eq. 7.6-5: distance from column face to plastic hinge"""
        return self.S1 + self.s * (self.n_bolts / 2 - 1)

    @property
    def gross_area(self) -> float:
        return self.bp * self.tp

    @property
    def net_area(self) -> float:
        """Net area through bolt holes (2 holes for standard 2-bolt row)"""
        dh = self.db + 0.0625  # Standard hole
        return self.tp * (self.bp - 2 * dh)

    @property
    def Ab(self) -> float:
        """Nominal unthreaded bolt area"""
        BOLT_AREAS = {
            0.625: 0.307, 0.75: 0.442, 0.875: 0.601,
            1.0: 0.785, 1.125: 0.994,
        }
        return BOLT_AREAS.get(self.db, math.pi * self.db**2 / 4)


@dataclass
class Loads:
    """Gravity loads on beam"""
    D: float = 0.0
    L: float = 0.0
    S: float = 0.0
    f1: float = 0.5
    Vu: float = 0.0

    @property
    def gravity_combination(self) -> float:
        return 1.2 * self.D + self.f1 * self.L + 0.2 * self.S


@dataclass
class DesignParameters:
    L: float
    Lh: float
    system_type: str
    C_pr: Optional[float] = None
    use_calculated_Cpr: bool = True


# ====================== SECTION DATABASE ======================

_SECTIONS_CACHE: Dict[str, Dict] = {}


def get_csv_file_path() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(script_dir, "aisc_w_shapes.csv")


def load_sections_from_csv() -> Dict[str, Dict]:
    global _SECTIONS_CACHE
    if _SECTIONS_CACHE:
        return _SECTIONS_CACHE
    csv_path = get_csv_file_path()
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Section database not found: {csv_path}")
    sections = {}
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                d = row['designation']
                sections[d.upper()] = {
                    'designation': d,
                    'd': float(row['d']), 'bf': float(row['bf']),
                    'tw': float(row['tw']), 'tf': float(row['tf']),
                    'Zx': float(row['Zx']),
                }
            except (ValueError, KeyError):
                continue
    _SECTIONS_CACHE = sections
    return sections


def get_section_properties(designation: str) -> Optional[Dict]:
    sections = load_sections_from_csv()
    clean = designation.upper().replace(" ", "")
    for name, props in sections.items():
        if name.upper().replace(" ", "") == clean:
            return props.copy()
    return None


# ====================== BOLT PROPERTIES ======================

BOLT_GRADES = {
    "A490": {"Fnt": 113.0, "Fnv": 68.0, "Fu": 150.0},
    "F2280": {"Fnt": 113.0, "Fnv": 68.0, "Fu": 150.0},
}


# ====================== BFP DESIGN CHECKER ======================

class BFPDesignChecker:
    """BFP Connection Design per AISC 358-16 Section 7.6 (17 steps)"""

    def __init__(self, beam: BeamSection, column: ColumnSection,
                 plate: FlangePlateGeometry, params: DesignParameters,
                 loads: Loads, plate_Fy: float = DEFAULT_FY_PLATE,
                 plate_Fu: float = DEFAULT_FU_PLATE):
        self.beam = beam
        self.column = column
        self.plate = plate
        self.params = params
        self.loads = loads
        self.plate_Fy = plate_Fy
        self.plate_Fu = plate_Fu
        self.M_pr = 0.0
        self.M_f = 0.0
        self.F_pr = 0.0
        self.V_h = 0.0
        self.r_n = 0.0
        self.checks: dict = {}

    # ---------- output ----------
    def sep(self, c="=", n=80):
        print(c * n)

    def section(self, t):
        self.sep("=")
        print(f"  {t}")
        self.sep("=")

    def subsection(self, t):
        self.sep("-")
        print(f"  {t}")
        self.sep("-")

    # ---------- main ----------
    def run_all_checks(self) -> bool:
        self.section("BFP CONNECTION DESIGN VERIFICATION (AISC 358-16 SECTION 7.6)")
        print()
        self.print_input()

        # Prequalification limits
        self.step0_prequalification()

        # 17-step design procedure
        self.section("DESIGN PROCEDURE (SECTION 7.6)")

        self.step1_Mpr()
        self.step2_max_bolt_diameter()
        self.step3_rn()
        self.step4_trial_bolts()
        self.step5_Sh()
        self.step6_Vh()
        self.step7_Mf()
        self.step8_Fpr()
        self.step9_confirm_bolts()
        self.step10_plate_yielding()
        self.step11_plate_rupture()
        self.step12_block_shear()
        self.step13_compression_buckling()
        self.step14_shear_strength()
        self.step15_web_connection()
        self.step16_continuity_plates()
        self.step17_panel_zone()

        self.print_summary()
        return all(v for v in self.checks.values() if v is not None)

    # ---------- input ----------
    def print_input(self):
        self.section("INPUT PARAMETERS")
        b, c, p, pm, ld = self.beam, self.column, self.plate, self.params, self.loads
        print(f"BEAM: {b.designation} | d={b.d:.2f} bf={b.bf:.2f} tf={b.tf:.3f} tw={b.tw:.3f} Zx={b.Zx:.1f}")
        print(f"      Fy={b.Fy} Fu={b.Fu} Ry={b.Ry} Rt={b.Rt}")
        print(f"COLUMN: {c.designation} | d={c.d:.2f} bf={c.bf:.2f} tf={c.tf:.3f} tw={c.tw:.3f}")
        print(f"        Fy={c.Fy}")
        print(f"PLATE: bp={p.bp:.2f} tp={p.tp:.3f} Lp={p.Lp:.2f} | Fy={self.plate_Fy} Fu={self.plate_Fu} ksi")
        print(f"       db={p.db:.3f} ({p.bolt_grade}) n={p.n_bolts} S1={p.S1:.2f} s={p.s:.2f}")
        print(f"SPAN: L={pm.L:.0f} in ({pm.L/12:.1f} ft) | {pm.system_type}")
        print(f"LOADS: D={ld.D} L={ld.L} S={ld.S} | Vu={ld.Vu:.2f}")
        print()

    # ---------- Step 0: prequalification ----------
    def step0_prequalification(self):
        self.subsection("PREQUALIFICATION LIMITS (SECTION 7.3)")
        passed = True
        st = self.params.system_type

        # Beam depth <= W36
        print(f"  Beam depth: d = {self.beam.d:.1f} in <= 36 in (W36 max): ", end="")
        if self.beam.d > 36:
            print("FAIL"); passed = False
        else:
            print("OK")

        # Beam weight <= 150 plf
        wt = self.beam.weight
        print(f"  Beam weight: {wt:.0f} plf <= 150 plf: ", end="")
        if wt > 150:
            print("FAIL"); passed = False
        else:
            print("OK")

        # Flange thickness <= 1.0 in
        print(f"  Flange thickness: tf = {self.beam.tf:.3f} in <= 1.0 in: ", end="")
        if self.beam.tf > 1.0:
            print("FAIL"); passed = False
        else:
            print("OK")

        # Span/depth ratio
        sd = self.params.L / self.beam.d
        sd_min = 9.0 if st == "SMF" else 7.0
        print(f"  Span/depth L/d = {sd:.1f} >= {sd_min:.0f} ({st}): ", end="")
        if sd < sd_min:
            print("FAIL"); passed = False
        else:
            print("OK")

        # Bolt diameter max 1-1/8"
        print(f"  Bolt diameter: {self.plate.db:.3f} in <= 1.125 in: ", end="")
        if self.plate.db > 1.125:
            print("FAIL"); passed = False
        else:
            print("OK")

        # Bolt grade A490 only
        print(f"  Bolt grade: {self.plate.bolt_grade} (A490 or F2280 required): ", end="")
        if self.plate.bolt_grade not in ("A490", "F2280"):
            print("FAIL - Only A490/F2280 prequalified"); passed = False
        else:
            print("OK")

        # Even number of bolts
        print(f"  Bolt count: {self.plate.n_bolts} (must be even): ", end="")
        if self.plate.n_bolts % 2 != 0:
            print("FAIL"); passed = False
        else:
            print("OK")

        # Plate Fy <= 55 ksi (A572 Gr 50) or A36
        print(f"  Plate Fy = {self.plate_Fy} ksi (A36 or A572 Gr 50): ", end="")
        if self.plate_Fy > 55:
            print("FAIL"); passed = False
        else:
            print("OK")

        self.checks["prequalification"] = passed
        print()

    # ---------- Step 1: M_pr ----------
    def step1_Mpr(self):
        self.subsection("STEP 1: PROBABLE MAXIMUM MOMENT M_pr (Eq. 2.4-1)")
        pm = self.params
        b = self.beam

        if pm.use_calculated_Cpr or pm.C_pr is None:
            C_pr = min((b.Fy + b.Fu) / (2 * b.Fy), 1.2)
            print(f"  C_pr = min((Fy+Fu)/(2*Fy), 1.2) = {C_pr:.3f}")
        else:
            C_pr = pm.C_pr
            print(f"  C_pr = {C_pr:.3f} (user)")

        self.M_pr = C_pr * b.Ry * b.Fy * b.Zx
        print(f"  M_pr = C_pr * Ry * Fy * Zx = {C_pr:.3f} * {b.Ry} * {b.Fy} * {b.Zx:.1f}")
        print(f"  M_pr = {self.M_pr:.0f} kip-in ({self.M_pr/12:.1f} kip-ft)")
        print()

    # ---------- Step 2: max bolt diameter ----------
    def step2_max_bolt_diameter(self):
        self.subsection("STEP 2: MAX BOLT DIAMETER TO PREVENT TENSILE RUPTURE (Eq. 7.6-2)")
        b = self.beam
        # db <= (bf/2) * (1 - Ry*Fy / (Rt*Fu)) - 1/8
        db_max = (b.bf / 2) * (1 - b.Ry * b.Fy / (b.Rt * b.Fu)) - 0.125
        print(f"  d_b,max = (bf/2)*(1 - Ry*Fy/(Rt*Fu)) - 1/8")
        print(f"  d_b,max = ({b.bf:.2f}/2)*(1 - {b.Ry}*{b.Fy}/({b.Rt}*{b.Fu})) - 0.125")
        print(f"  d_b,max = {db_max:.3f} in")
        print(f"  Selected d_b = {self.plate.db:.3f} in")

        passed = self.plate.db <= db_max
        print(f"  {'OK' if passed else 'FAIL'}")
        self.checks["bolt_diameter_check"] = passed
        print()

    # ---------- Step 3: r_n ----------
    def step3_rn(self):
        self.subsection("STEP 3: CONTROLLING NOMINAL SHEAR STRENGTH PER BOLT (Eq. 7.6-3)")
        p = self.plate
        b = self.beam
        grade = BOLT_GRADES.get(p.bolt_grade, BOLT_GRADES["A490"])

        Fnv = grade["Fnv"]
        Fub = b.Fu
        Fup = self.plate_Fu

        r1 = 1.0 * Fnv * p.Ab
        r2 = 2.4 * Fub * p.db * b.tf
        r3 = 2.4 * Fup * p.db * p.tp
        self.r_n = min(r1, r2, r3)

        print(f"  r_n = min(1.0*Fnv*Ab, 2.4*Fub*db*tf, 2.4*Fup*db*tp)")
        print(f"  r_1 = 1.0 * {Fnv} * {p.Ab:.3f} = {r1:.1f} kips (bolt shear)")
        print(f"  r_2 = 2.4 * {Fub} * {p.db:.3f} * {b.tf:.3f} = {r2:.1f} kips (beam bearing)")
        print(f"  r_3 = 2.4 * {Fup} * {p.db:.3f} * {p.tp:.3f} = {r3:.1f} kips (plate bearing)")
        print(f"  r_n = {self.r_n:.1f} kips/bolt (controlling)")
        print()

    # ---------- Step 4: trial bolts ----------
    def step4_trial_bolts(self):
        self.subsection("STEP 4: TRIAL NUMBER OF BOLTS (Eq. 7.6-4)")
        n_req = math.ceil(1.25 * self.M_pr / (PHI_N * self.r_n * (self.beam.d + self.plate.tp)))
        # Round to next even number
        if n_req % 2 != 0:
            n_req += 1
        print(f"  n >= 1.25*M_pr / (phi_n * r_n * (d + tp))")
        print(f"  n >= 1.25*{self.M_pr:.0f} / ({PHI_N} * {self.r_n:.1f} * ({self.beam.d:.2f} + {self.plate.tp:.3f}))")
        print(f"  n >= {n_req} (rounded to even)")
        print(f"  Selected n = {self.plate.n_bolts}")

        if self.plate.n_bolts < n_req:
            print(f"  WARNING: More bolts may be needed")
        print()

    # ---------- Step 5: S_h ----------
    def step5_Sh(self):
        self.subsection("STEP 5: PLASTIC HINGE LOCATION S_h (Eq. 7.6-5)")
        Sh = self.plate.Sh
        print(f"  S_h = S_1 + s*(n/2 - 1)")
        print(f"  S_h = {self.plate.S1:.2f} + {self.plate.s:.2f}*({self.plate.n_bolts}/2 - 1)")
        print(f"  S_h = {Sh:.2f} in")
        print()

    # ---------- Step 6: V_h ----------
    def step6_Vh(self):
        self.subsection("STEP 6: SHEAR FORCE AT PLASTIC HINGE")
        ld = self.loads
        pm = self.params
        Lh = pm.L - self.column.d - 2 * self.plate.Sh
        gravity = ld.gravity_combination

        # V_h = 2*M_pr/L_h + V_gravity (simplified for uniform gravity)
        self.V_h = 2 * self.M_pr / Lh + gravity / 2
        print(f"  L_h = L - d_c - 2*S_h = {pm.L:.0f} - {self.column.d:.2f} - 2*{self.plate.Sh:.2f} = {Lh:.1f} in")
        print(f"  V_h = 2*M_pr/L_h + V_gravity/2 = {self.V_h:.2f} kips")
        print()

    # ---------- Step 7: M_f ----------
    def step7_Mf(self):
        self.subsection("STEP 7: MOMENT AT COLUMN FACE M_f (Eq. 7.6-6)")
        self.M_f = self.M_pr + self.V_h * self.plate.Sh
        print(f"  M_f = M_pr + V_h * S_h")
        print(f"  M_f = {self.M_pr:.0f} + {self.V_h:.2f} * {self.plate.Sh:.2f}")
        print(f"  M_f = {self.M_f:.0f} kip-in ({self.M_f/12:.1f} kip-ft)")
        print()

    # ---------- Step 8: F_pr ----------
    def step8_Fpr(self):
        self.subsection("STEP 8: FLANGE PLATE FORCE F_pr (Eq. 7.6-7)")
        # NOTE: d + t_p, NOT d - t_f
        self.F_pr = self.M_f / (self.beam.d + self.plate.tp)
        print(f"  F_pr = M_f / (d + t_p)")
        print(f"  F_pr = {self.M_f:.0f} / ({self.beam.d:.2f} + {self.plate.tp:.3f})")
        print(f"  F_pr = {self.F_pr:.1f} kips")
        print()

    # ---------- Step 9: confirm bolts ----------
    def step9_confirm_bolts(self):
        self.subsection("STEP 9: CONFIRM NUMBER OF BOLTS (Eq. 7.6-8)")
        n_req = self.F_pr / (PHI_N * self.r_n)
        n_sel = self.plate.n_bolts
        print(f"  n >= F_pr / (phi_n * r_n)")
        print(f"  n >= {self.F_pr:.1f} / ({PHI_N} * {self.r_n:.1f}) = {n_req:.1f}")
        print(f"  n >= {math.ceil(n_req)} (minimum)")

        passed = n_sel >= n_req
        print(f"  Selected n = {n_sel}: {'OK' if passed else 'FAIL'}")
        self.checks["bolt_count"] = passed
        print()

    # ---------- Step 10: plate yielding ----------
    def step10_plate_yielding(self):
        self.subsection("STEP 10: FLANGE PLATE TENSION YIELDING (Eq. 7.6-9)")
        Fyp = self.plate_Fy
        tp_req = self.F_pr / (PHI_D * Fyp * self.plate.bp)
        print(f"  t_p >= F_pr / (phi_d * Fy * b_fp)")
        print(f"  t_p >= {self.F_pr:.1f} / ({PHI_D} * {Fyp} * {self.plate.bp:.2f})")
        print(f"  t_p >= {tp_req:.3f} in")
        print(f"  Selected t_p = {self.plate.tp:.3f} in")

        passed = self.plate.tp >= tp_req
        print(f"  {'OK' if passed else 'FAIL'}")
        self.checks["plate_yielding"] = passed
        print()

    # ---------- Step 11: plate rupture ----------
    def step11_plate_rupture(self):
        self.subsection("STEP 11: FLANGE PLATE TENSILE RUPTURE (Eq. 7.6-10)")
        Fup = self.plate_Fu
        An = self.plate.net_area
        # AISC 360 Chapter J tensile rupture
        R_n = PHI_N * Fup * An

        dh = self.plate.db + 0.0625
        print(f"  Net area An = tp*(bp - 2*dh) = {self.plate.tp:.3f}*({self.plate.bp:.2f} - 2*{dh:.4f}) = {An:.2f} in²")
        print(f"  phi_n * Fu * An = {PHI_N} * {Fup} * {An:.2f} = {R_n:.1f} kips")
        print(f"  Demand F_pr = {self.F_pr:.1f} kips")

        passed = self.F_pr <= R_n
        print(f"  {'OK' if passed else 'FAIL'} (Utilization: {self.F_pr/R_n:.3f})")
        self.checks["plate_rupture"] = passed
        print()

    # ---------- Step 12: block shear ----------
    def step12_block_shear(self):
        self.subsection("STEP 12: BEAM FLANGE BLOCK SHEAR RUPTURE (Eq. 7.6-11)")
        p = self.plate
        b = self.beam
        dh = p.db + 0.0625
        Fub = b.Fu
        Fyb = b.Fy
        tf = b.tf

        # Block shear through beam flange (2 lines of holes)
        n = p.n_bolts
        # Gross shear length (along each bolt line)
        L_gv = p.ed_edge + (n / 2 - 1) * p.s  # One bolt line
        Agv = 2 * tf * L_gv  # Two sides
        Anv = 2 * tf * (L_gv - (n / 2 - 0.5) * dh)
        # Net tension area (across flange)
        Ant = tf * (b.bf - 2 * dh)

        Ubs = 1.0
        R_n1 = 0.6 * Fub * Anv + Ubs * Fub * Ant
        R_n2 = 0.6 * Fyb * Agv + Ubs * Fub * Ant
        R_n = PHI_N * min(R_n1, R_n2)

        print(f"  Block shear through beam flange:")
        print(f"  Agv = {Agv:.2f} in², Anv = {Anv:.2f} in², Ant = {Ant:.2f} in²")
        print(f"  R_n = phi_n * min({R_n1:.1f}, {R_n2:.1f}) = {R_n:.1f} kips")
        print(f"  Demand F_pr = {self.F_pr:.1f} kips")

        passed = self.F_pr <= R_n
        print(f"  {'OK' if passed else 'FAIL'} (Utilization: {self.F_pr/R_n:.3f})")
        self.checks["block_shear"] = passed
        print()

    # ---------- Step 13: compression buckling ----------
    def step13_compression_buckling(self):
        self.subsection("STEP 13: COMPRESSION PLATE BUCKLING (Eq. 7.6-12)")
        p = self.plate
        Fyp = self.plate_Fy

        # Commentary: KL = 0.65 * S_1
        KL = 0.65 * p.S1
        r = p.tp / math.sqrt(12)  # Radius of gyration
        slenderness = KL / r
        # AISC 360 E3: Fcr = 0.658^(Fe/Fy) * Fy for Fe >= Fy
        Fe = math.pi**2 * E / slenderness**2
        if Fe >= Fyp:
            Fcr = 0.658**(Fyp / Fe) * Fyp
        else:
            Fcr = 0.877 * Fe

        R_n = PHI_N * Fcr * p.gross_area

        print(f"  KL = 0.65 * S1 = 0.65 * {p.S1:.2f} = {KL:.2f} in (per Commentary)")
        print(f"  r = tp/sqrt(12) = {r:.3f} in")
        print(f"  KL/r = {slenderness:.1f}")
        print(f"  Fe = pi^2*E/(KL/r)^2 = {Fe:.1f} ksi")
        print(f"  Fcr = {Fcr:.1f} ksi")
        print(f"  R_n = phi_n * Fcr * Ag = {PHI_N} * {Fcr:.1f} * {p.gross_area:.2f} = {R_n:.1f} kips")
        print(f"  Demand F_pr = {self.F_pr:.1f} kips")

        passed = self.F_pr <= R_n
        print(f"  {'OK' if passed else 'FAIL'} (Utilization: {self.F_pr/R_n:.3f})")
        self.checks["compression_buckling"] = passed
        print()

    # ---------- Step 14: shear strength ----------
    def step14_shear_strength(self):
        self.subsection("STEP 14: REQUIRED SHEAR STRENGTH (Eq. 7.6-13)")
        Lh = self.params.L - self.column.d - 2 * self.plate.Sh
        gravity = self.loads.gravity_combination
        Vu = 2 * self.M_pr / Lh + gravity / 2

        # Check beam shear per AISC 360
        Vn = PHI_N * 0.6 * self.beam.Fy * self.beam.tw * self.beam.dw

        print(f"  V_u = 2*M_pr/L_h + V_gravity = {Vu:.1f} kips")
        print(f"  Beam shear capacity = phi*0.6*Fy*tw*dw = {Vn:.1f} kips")

        passed = Vu <= Vn
        print(f"  {'OK' if passed else 'FAIL'} (Utilization: {Vu/Vn:.3f})")
        self.checks["beam_shear"] = passed
        print()

    # ---------- Step 15: web connection ----------
    def step15_web_connection(self):
        self.subsection("STEP 15: SINGLE-PLATE SHEAR CONNECTION")
        Vu = self.loads.Vu if self.loads.Vu > 0 else self.V_h
        tw = self.beam.tw
        dw = self.beam.dw
        Fy = self.beam.Fy

        # Beam web shear capacity (baseline check)
        Vn_web = 0.6 * Fy * tw * dw

        print(f"  Required shear V_u = {Vu:.1f} kips")
        print(f"  Beam web shear capacity (unreduced): 0.6*Fy*tw*dw = {Vn_web:.1f} kips")
        if Vn_web > 0:
            print(f"  Utilization: {Vu/Vn_web:.3f}")
        print(f"  Design single-plate shear connection per AISC 360 for V_u")
        print(f"  Weld to column: CJP, two-sided PJP, or two-sided fillet")
        print(f"  Beam web: bolts in short-slotted holes")
        print(f"  Note: Plate material {self.plate_Fy} ksi (verify with actual design)")
        self.checks["web_connection"] = True
        print()

    # ---------- Step 16: continuity plates ----------
    def step16_continuity_plates(self):
        self.subsection("STEP 16: CONTINUITY PLATE CHECK (CHAPTER 2)")
        tcf = self.column.tf
        Fyc = self.column.Fy
        bcf = self.column.bf
        tcf_req = math.sqrt(self.F_pr / (PHI_D * Fyc * bcf)) if bcf > 0 else 999

        print(f"  Column flange tcf = {tcf:.3f} in, required ~ {tcf_req:.3f} in (simplified)")
        need = tcf < tcf_req
        if need:
            ts_min = max(self.column.tw, 0.5 * self.beam.tf)
            print(f"  Continuity plates RECOMMENDED (ts >= {ts_min:.3f} in)")
        else:
            print(f"  Continuity plates may not be required")
        self.checks["continuity_plates"] = not need
        print()

    # ---------- Step 17: panel zone ----------
    def step17_panel_zone(self):
        self.subsection("STEP 17: COLUMN PANEL ZONE (SECTION 7.4)")
        dc = self.column.d
        twc = self.column.tw
        Fyc = self.column.Fy

        V_pz = self.F_pr
        Vn = 0.6 * Fyc * dc * twc  # phi=1.0 for panel zone

        print(f"  Panel zone demand V_pz = F_pr = {V_pz:.1f} kips")
        print(f"  Capacity Vn = 0.6*Fyc*dc*twc = 0.6*{Fyc}*{dc:.2f}*{twc:.3f} = {Vn:.1f} kips")

        passed = V_pz <= Vn
        if not passed:
            print(f"  FAIL - Consider web doubler plates (Utilization: {V_pz/Vn:.3f})")
        else:
            print(f"  OK (Utilization: {V_pz/Vn:.3f})")
        self.checks["panel_zone"] = passed
        print()

    # ---------- summary ----------
    def print_summary(self):
        self.section("DESIGN VERIFICATION SUMMARY")

        def s(k):
            return "PASS" if self.checks.get(k) else "FAIL"

        print(f"Prequalification: {s('prequalification')}")
        print(f"Bolt diameter check: {s('bolt_diameter_check')}")
        print(f"Bolt count: {s('bolt_count')}")
        print(f"Plate yielding: {s('plate_yielding')}")
        print(f"Plate rupture: {s('plate_rupture')}")
        print(f"Block shear: {s('block_shear')}")
        print(f"Compression buckling: {s('compression_buckling')}")
        print(f"Beam shear: {s('beam_shear')}")
        print(f"Continuity plates: {s('continuity_plates')}")
        print(f"Panel zone: {s('panel_zone')}")
        print()
        print(f"KEY: M_pr={self.M_pr:.0f} kip-in | M_f={self.M_f:.0f} kip-in | F_pr={self.F_pr:.1f} kips | r_n={self.r_n:.1f} kips/bolt")
        print()

        all_pass = all(v for v in self.checks.values() if v is not None)
        self.sep("=")
        if all_pass:
            print("  ALL CHECKS PASSED")
        else:
            print("  SOME CHECKS FAILED - REVIEW AND ADJUST DESIGN")
        self.sep("=")


# ====================== HELPER FUNCTIONS ======================

def create_beam_section(args) -> BeamSection:
    if args.beam_section:
        props = get_section_properties(args.beam_section)
        if props:
            return BeamSection(
                designation=props["designation"],
                d=args.beam_d or props["d"],
                bf=args.beam_bf or props["bf"],
                tf=args.beam_tf or props["tf"],
                tw=args.beam_tw or props["tw"],
                Zx=args.beam_Zx or props["Zx"],
                Fy=args.beam_Fy, Fu=args.beam_Fu,
                Ry=args.beam_Ry, Rt=args.beam_Rt,
            )
    if all([args.beam_d, args.beam_bf, args.beam_tf, args.beam_tw, args.beam_Zx]):
        return BeamSection(
            designation="Custom", d=args.beam_d, bf=args.beam_bf,
            tf=args.beam_tf, tw=args.beam_tw, Zx=args.beam_Zx,
            Fy=args.beam_Fy, Fu=args.beam_Fu, Ry=args.beam_Ry, Rt=args.beam_Rt,
        )
    raise ValueError("Invalid beam section. Use --beam-section or provide all dimensions.")


def create_column_section(args) -> ColumnSection:
    if args.column_section:
        props = get_section_properties(args.column_section)
        if props:
            return ColumnSection(
                designation=props["designation"],
                d=args.column_d or props["d"],
                bf=args.column_bf or props["bf"],
                tf=args.column_tf or props["tf"],
                tw=args.column_tw or props["tw"],
                Zx=args.column_Zx or props["Zx"],
                Fy=args.column_Fy, Fu=args.column_Fu, Ry=args.column_Ry,
            )
    if all([args.column_d, args.column_bf, args.column_tf, args.column_tw, args.column_Zx]):
        return ColumnSection(
            designation="Custom", d=args.column_d, bf=args.column_bf,
            tf=args.column_tf, tw=args.column_tw, Zx=args.column_Zx,
            Fy=args.column_Fy, Fu=args.column_Fu, Ry=args.column_Ry,
        )
    raise ValueError("Invalid column section.")


# ====================== COMMAND LINE ======================

def parse_args():
    parser = argparse.ArgumentParser(
        description="BFP Connection Design Verification (AISC 358-16 Section 7.6)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python bfp_design.py --beam-section W24x68 --column-section W14x120 --span 300 --system-type SMF
  python bfp_design.py --beam-section W24x68 --column-section W14x193 --span 360 --system-type SMF \
      --plate-width 12 --plate-thickness 0.75 --n-bolts 6 --bolt-diameter 1.0
        """
    )

    if "--list-sections" in sys.argv:
        sections = load_sections_from_csv()
        print("Available W-shape sections:")
        print("=" * 80)
        for d in sorted(sections.keys()):
            p = sections[d]
            print(f"  {d:12s}: d={p['d']:5.1f}, bf={p['bf']:5.2f}, Zx={p['Zx']:6.1f}")
        print("=" * 80)
        print(f"Total: {len(sections)}")
        sys.exit(0)

    pg = parser.add_argument_group("Flange Plate")
    pg.add_argument("--plate-width", type=float, help="Plate width b_fp (in)")
    pg.add_argument("--plate-thickness", type=float, help="Plate thickness t_p (in)")
    pg.add_argument("--plate-length", type=float, help="Plate length from column face (in)")
    pg.add_argument("--plate-Fy", type=float, default=DEFAULT_FY_PLATE,
                    help=f"Plate yield strength Fy (ksi, default: {DEFAULT_FY_PLATE} for A572 Gr 50)")
    pg.add_argument("--plate-Fu", type=float, default=DEFAULT_FU_PLATE,
                    help=f"Plate tensile strength Fu (ksi, default: {DEFAULT_FU_PLATE} for A572 Gr 50)")
    pg.add_argument("--n-bolts", type=int, default=6, help="Bolts per flange (even, default: 6)")
    pg.add_argument("--bolt-diameter", type=float, default=1.0, help="Bolt dia (in, default: 1.0, max: 1.125)")
    pg.add_argument("--bolt-grade", type=str, default="A490", choices=["A490"])
    pg.add_argument("--bolt-spacing", type=float, default=3.0, help="Bolt row spacing s (in, default: 3.0)")
    pg.add_argument("--bolt-offset", type=float, default=3.0, help="Col face to first bolt S1 (in, default: 3.0)")
    pg.add_argument("--edge-distance", type=float, default=2.0, help="Edge dist at beam end (in)")

    bg = parser.add_argument_group("Beam")
    bg.add_argument("--beam-section", type=str)
    bg.add_argument("--beam-d", type=float)
    bg.add_argument("--beam-bf", type=float)
    bg.add_argument("--beam-tf", type=float)
    bg.add_argument("--beam-tw", type=float)
    bg.add_argument("--beam-Zx", type=float)
    bg.add_argument("--beam-Fy", type=float, default=DEFAULT_FY_BEAM)
    bg.add_argument("--beam-Fu", type=float, default=DEFAULT_FU_BEAM)
    bg.add_argument("--beam-Ry", type=float, default=1.1)
    bg.add_argument("--beam-Rt", type=float, default=1.2)

    cg = parser.add_argument_group("Column")
    cg.add_argument("--column-section", type=str)
    cg.add_argument("--column-d", type=float)
    cg.add_argument("--column-bf", type=float)
    cg.add_argument("--column-tf", type=float)
    cg.add_argument("--column-tw", type=float)
    cg.add_argument("--column-Zx", type=float)
    cg.add_argument("--column-Fy", type=float, default=DEFAULT_FY_COLUMN)
    cg.add_argument("--column-Fu", type=float, default=DEFAULT_FU_COLUMN)
    cg.add_argument("--column-Ry", type=float, default=1.1)

    dg = parser.add_argument_group("Design")
    dg.add_argument("--span", type=float, required=True)
    dg.add_argument("--system-type", type=str, required=True, choices=["SMF", "IMF"])
    dg.add_argument("--C-pr", type=float, default=None)
    dg.add_argument("--use-calc-cpr", action="store_true")

    lg = parser.add_argument_group("Loads")
    lg.add_argument("--load-D", type=float, default=0)
    lg.add_argument("--load-L", type=float, default=0)
    lg.add_argument("--load-S", type=float, default=0)
    lg.add_argument("--load-f1", type=float, default=0.5)
    lg.add_argument("--Vu", type=float, default=0)

    return parser.parse_args()


# ====================== MAIN ======================

def main():
    args = parse_args()
    try:
        beam = create_beam_section(args)
        column = create_column_section(args)

        bp = args.plate_width or (beam.bf + 2.0)
        tp = args.plate_thickness or max(0.5, beam.tf * 0.75)
        Lp = args.plate_length or (args.bolt_offset + (args.n_bolts / 2 - 1) * args.bolt_spacing + args.edge_distance)

        plate = FlangePlateGeometry(
            bp=bp, tp=tp, Lp=Lp,
            db=args.bolt_diameter, bolt_grade=args.bolt_grade,
            n_bolts=args.n_bolts,
            S1=args.bolt_offset, s=args.bolt_spacing,
            ed_edge=args.edge_distance,
        )

        if args.use_calc_cpr or args.C_pr is None:
            C_pr = min((beam.Fy + beam.Fu) / (2 * beam.Fy), 1.2)
        else:
            C_pr = args.C_pr

        # Calculate S_h and L_h properly (per Eq. 7.6-5)
        S_h = plate.Sh
        L_h = args.span - column.d - 2 * S_h

        loads = Loads(D=args.load_D, L=args.load_L, S=args.load_S,
                      f1=args.load_f1, Vu=args.Vu)

        params = DesignParameters(
            L=args.span, Lh=L_h, system_type=args.system_type,
            C_pr=args.C_pr, use_calculated_Cpr=(args.C_pr is None),
        )

        checker = BFPDesignChecker(beam, column, plate, params, loads,
                                    plate_Fy=args.plate_Fy, plate_Fu=args.plate_Fu)
        all_passed = checker.run_all_checks()
        sys.exit(0 if all_passed else 1)

    except ValueError as e:
        print(f"Error: {e}\nUse --help for usage.")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
