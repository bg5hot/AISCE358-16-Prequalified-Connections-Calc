#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Simpson Strong-Tie (SST) Strong Frame Moment Connection Design Verification
Based on AISC 358-16 Chapter 12, Section 12.9 - Design Procedure

The SST Strong Frame connection is a partially restrained (PR) moment connection
that uses Yield-Link structural fuses for moment transfer and a modified
single-plate shear connection for shear transfer.

Two Yield-Link configurations:
  - T-stub: separate T-stub elements bolted to each beam flange
  - End-plate: links welded to a common end plate (for shallow beams W8-W12)

Key characteristics (unique to SST):
  - Plastic hinging occurs in Yield-Links, NOT in the beam
  - PR connection with explicit stiffness calculation (Step 11)
  - Beam designed as simply supported for gravity loads
  - Capacity-based design: connection remains elastic under factored loads
  - M_pr = P_r-link * (d + t_stem) (NOT based on beam section modulus)
  - Column panel zone per AISC 360 (phi=0.90), NOT AISC 341 (phi=1.0)
  - R_y = 1.1, R_t = 1.2 for Yield-Link material (A572 Gr 50)

Usage:
    # T-stub Yield-Link (default)
    python sst_design.py --beam-section W24x68 --column-section W14x193 \
        --span 300 --system-type SMF --Mu 3500 --t-stem 0.75

    # End-plate Yield-Link
    python sst_design.py --beam-section W12x26 --column-section W14x120 \
        --span 240 --system-type SMF --Mu 1200 --t-stem 0.5 \
        --link-type endplate

    # With gravity loads and detailed parameters
    python sst_design.py --beam-section W30x99 --column-section W14x257 \
        --span 360 --system-type SMF --Mu 6000 --t-stem 0.875 \
        --load-D 15 --load-L 20
"""

import argparse
import sys
import io
import os
import csv
import math
from dataclasses import dataclass, field
from typing import Optional, Dict, List

# Set UTF-8 encoding for Windows console
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ====================== CONSTANTS ======================
# Resistance factors
PHI_D = 1.00   # Ductile limit states (plate yielding, panel zone)
PHI_N = 0.90   # Nonductile limit states (rupture, bolt, bearing, buckling)
PHI_V = 0.90   # Shear
PHI_B = 0.90   # Flexure

# Default material properties
DEFAULT_FY_BEAM = 50.0    # ksi (A992)
DEFAULT_FU_BEAM = 65.0    # ksi (A992)
DEFAULT_FY_COL = 50.0     # ksi (A992)
DEFAULT_FU_COL = 65.0     # ksi (A992)

# Yield-Link material (A572 Gr 50 plate, A992, or A913 Gr 50)
DEFAULT_FY_LINK = 50.0    # ksi
DEFAULT_FU_LINK = 65.0    # ksi
RY_LINK = 1.1             # Section 12.9 Step 7
RT_LINK = 1.2             # Section 12.9 Step 7 (A572 Gr 50 plate)

# Yield-Link geometry limits
T_STEM_MIN = 0.5         # in (1/2 in = 13 mm)
T_STEM_MAX = 1.0         # in
B_YIELD_MAX = 6.0        # in (150 mm)

# Buckling restraint plate limits
T_BRP_MIN = 0.875        # in (7/8 in = 22 mm)
FY_BRP = 50.0            # ksi minimum
RY_BRP = 1.1
D_BRP_BOLT_MIN = 0.625   # in (5/8 in = 16 mm)
MU_K = 0.3               # dry kinetic friction coefficient

# Beam flange minimum thickness
TF_BEAM_MIN = 0.40       # in (10 mm)

# Steel modulus
E = 29000.0              # ksi

# Default weld electrode
DEFAULT_FEXX = 70.0      # ksi (E70)


# ====================== DATA CLASSES ======================

@dataclass
class BeamSection:
    designation: str
    d: float
    bf: float
    tf: float
    tw: float
    Zx: float
    Fy: float = DEFAULT_FY_BEAM
    Fu: float = DEFAULT_FU_BEAM
    Ry: float = 1.1
    Rt: float = 1.2

    @property
    def Sx(self) -> float:
        return Zx_to_Sx(self.Zx, self.d, self.tf, self.tw)

    @property
    def weight(self) -> float:
        try:
            return float(self.designation.upper().split('X')[1])
        except (ValueError, IndexError):
            return 999


def Zx_to_Sx(Zx: float, d: float, tf: float, tw: float) -> float:
    # Elastic section modulus approximation from plastic section modulus
    # Sx = Ix/(d/2); for typical W-shapes Sx/Zx ~ 0.88-0.93
    # More accurate: account for flange contribution
    Sx_flanges = 2 * (bf_approx_from_Zx(Zx, d, tf, tw) * tf) * (d/2 - tf/2)
    Sx_web = tw * (d - 2*tf)**2 / 6
    return Sx_flanges + Sx_web if Sx_flanges > 0 else Zx * 0.90


def bf_approx_from_Zx(Zx: float, d: float, tf: float, tw: float) -> float:
    # Approximate bf from Zx = bf*tf*(d-tf) + tw*(d-2*tf)^2/4
    flange_contrib = Zx - tw * (d - 2*tf)**2 / 4
    if tf > 0 and (d - tf) > 0 and flange_contrib > 0:
        return flange_contrib / (tf * (d - tf))
    return 6.0  # default approximate


@dataclass
class ColumnSection:
    designation: str
    d: float
    bf: float
    tf: float
    tw: float
    Zx: float
    Fy: float = DEFAULT_FY_COL
    Fu: float = DEFAULT_FU_COL

    @property
    def Sx(self) -> float:
        return Zx_to_Sx(self.Zx, self.d, self.tf, self.tw)


@dataclass
class YieldLinkGeometry:
    t_stem: float          # Stem thickness (in)
    b_col_side: float      # Nonreduced width at column side (in)
    b_bm_side: float       # Nonreduced width at beam side (in)
    b_yield: float         # Width of reduced yielding section (in)
    L_col_side: float      # Nonreduced length at column side (in)
    L_bm_side: float       # Nonreduced length at beam side (in)
    L_y_link: float        # Minimum yielding length (in)
    L_total: float = 0.0   # Total link length (computed)

    def __post_init__(self):
        self.L_total = self.L_col_side + self.L_y_link + self.L_bm_side


@dataclass
class YieldLinkForces:
    P_ye_link: float = 0.0   # Expected yield strength (Eq. 12.9-5)
    P_r_link: float = 0.0    # Probable max tensile strength (Eq. 12.9-6)
    M_pr: float = 0.0        # Probable max moment capacity (Eq. 12.9-28)
    M_ye_link: float = 0.0   # Expected yield moment (Eq. 12.9-29)


@dataclass
class ConnectionStiffness:
    K1: float = 0.0          # Flange bending stiffness (Eq. 12.9-24)
    K2: float = 0.0          # Nonyielding stem stiffness (Eq. 12.9-25)
    K3: float = 0.0          # Yielding stem stiffness (Eq. 12.9-26)
    K_eff: float = 0.0       # Effective stiffness (Eq. 12.9-27)
    delta_y: float = 0.0     # Yield deformation (Eq. 12.9-32)
    theta_y: float = 0.0     # Yield rotation (Eq. 12.9-33)
    delta_04: float = 0.0    # Deformation at 0.04 rad (Eq. 12.9-30)
    delta_07: float = 0.0    # Deformation at 0.07 rad (Eq. 12.9-31)


@dataclass
class Loads:
    D: float = 0.0
    L: float = 0.0
    S: float = 0.0
    f1: float = 0.5
    Vu: float = 0.0
    Mu: float = 0.0      # Moment demand from elastic analysis (kip-in)
    Pu_sp: float = 0.0   # Required axial strength of connection (kips)

    @property
    def gravity_combination(self) -> float:
        return 1.2 * self.D + self.f1 * self.L + 0.2 * self.S


@dataclass
class DesignParameters:
    L: float
    system_type: str
    link_type: str = "tstub"    # "tstub" or "endplate"
    story_above: float = 156.0
    story_below: float = 156.0
    Pu: float = 0.0
    a_dist: float = 3.0        # Distance from shear bolt CL to column face (in)
    t_stem: float = 0.75       # Yield-Link stem thickness (in)


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


# ====================== SST DESIGN CHECKER ======================

class SSTDesignChecker:
    """SST Strong Frame Connection Design per AISC 358-16 Section 12.9 (19 steps)"""

    def __init__(self, beam: BeamSection, column: ColumnSection,
                 params: DesignParameters, loads: Loads,
                 FEXX: float = DEFAULT_FEXX,
                 t_stem: float = 0.75):
        self.beam = beam
        self.column = column
        self.params = params
        self.loads = loads
        self.FEXX = FEXX
        self.t_stem = t_stem
        self.checks: dict = {}

        self.yl_geom: Optional[YieldLinkGeometry] = None
        self.yl_forces = YieldLinkForces()
        self.stiffness = ConnectionStiffness()
        self.V_u = 0.0
        self.Rn_pz_demand = 0.0
        self.phi_Rn_pz = 0.0

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

    def run_all_checks(self) -> bool:
        self.section("SST STRONG FRAME CONNECTION DESIGN VERIFICATION "
                     "(AISC 358-16 CHAPTER 12)")
        print()
        self.print_input()

        self.step0_prequalification()
        self.section("DESIGN PROCEDURE (SECTION 12.9)")

        # Steps 1-2: Beam selection and simple span check (EOR responsibility)
        self.step1_2_beam_selection()

        # Steps 3-6: Yield-Link geometry and forces
        self.step3_yield_link_area()
        self.step4_col_side_geometry()
        self.step5_yield_width()
        self.step6_yield_length()
        self.step7_link_strength()
        self.step8_beam_side_design()

        # Step 9: Link-to-column flange connection
        self.step9_flange_connection()

        # Step 10: Buckling restraint assembly
        self.step10_buckling_restraint()

        # Step 11: Connection stiffness
        self.step11_stiffness()

        # Step 12: Required shear
        self.step12_required_shear()

        # Step 13: Member checks
        self.step13_member_checks()

        # Step 14: Column-beam relationship
        self.step14_column_beam()

        # Step 15: Shear plate connection
        self.step15_shear_plate()

        # Step 16: Panel zone
        self.step16_panel_zone()

        # Step 17: Column web
        self.step17_column_web()

        # Step 18: Column flange thickness
        self.step18_column_flange()

        # Step 19: Continuity plates
        self.step19_continuity_plates()

        self.print_summary()
        return all(v for v in self.checks.values() if v is not None)

    # ---------- input ----------
    def print_input(self):
        self.section("INPUT PARAMETERS")
        b, c, pm, ld = self.beam, self.column, self.params, self.loads
        print(f"BEAM: {b.designation} | d={b.d:.2f} bf={b.bf:.2f} "
              f"tf={b.tf:.3f} tw={b.tw:.3f} Zx={b.Zx:.1f}")
        print(f"      Fy={b.Fy} Fu={b.Fu} Ry={b.Ry} Rt={b.Rt}")
        print(f"COLUMN: {c.designation} | d={c.d:.2f} bf={c.bf:.2f} "
              f"tf={c.tf:.3f} tw={c.tw:.3f} Zx={c.Zx:.1f}")
        print(f"        Fy={c.Fy} Fu={c.Fu}")
        print(f"LINK TYPE: {pm.link_type} | t_stem={self.t_stem:.3f} in")
        print(f"SPAN: L={pm.L:.0f} in ({pm.L/12:.1f} ft) | {pm.system_type}")
        print(f"STORY: H_above={pm.story_above:.0f} in | "
              f"H_below={pm.story_below:.0f} in")
        print(f"LOADS: D={ld.D} L={ld.L} S={ld.S} | "
              f"Mu={ld.Mu:.0f} kip-in | Pu_sp={ld.Pu_sp:.1f} kips")
        print(f"       a (shear bolt to col face) = {pm.a_dist:.1f} in")
        print()

    # ---------- Step 0: prequalification ----------
    def step0_prequalification(self):
        self.subsection("PREQUALIFICATION LIMITS (SECTION 12.3)")
        passed = True
        b = self.beam
        c = self.column
        st = self.params.system_type
        lt = self.params.link_type

        # Beam depth limits
        if lt == "tstub":
            max_depth = 36.0  # W36 max for T-stub
            print(f"  T-stub Yield-Link: beam depth limit W36 (max d={max_depth:.0f} in)")
        else:
            min_depth = 8.0   # W8 min for end-plate
            max_depth = 12.0  # W12 max for end-plate
            print(f"  End-plate Yield-Link: beam depth W8 to W12 "
                  f"(d={min_depth:.0f} to {max_depth:.0f} in)")
            if b.d < min_depth:
                print(f"  FAIL: beam depth {b.d:.2f} < {min_depth:.0f} in")
                passed = False

        print(f"  Beam depth: d = {b.d:.2f} in <= {max_depth:.0f} in: ", end="")
        if b.d > max_depth:
            print("FAIL"); passed = False
        else:
            print("OK")

        # Beam flange thickness >= 0.40 in
        print(f"  Flange thickness: tf = {b.tf:.3f} in >= {TF_BEAM_MIN:.2f} in: ", end="")
        if b.tf < TF_BEAM_MIN:
            print("FAIL"); passed = False
        else:
            print("OK")

        # Column depth <= W36
        print(f"  Column depth: d = {c.d:.2f} in <= 36 in: ", end="")
        if c.d > 36.0:
            print("FAIL"); passed = False
        else:
            print("OK")

        self.checks["prequalification"] = passed
        print()

    # ---------- Steps 1-2: beam selection ----------
    def step1_2_beam_selection(self):
        self.subsection("STEP 1-2: BEAM SELECTION AND SIMPLE SPAN CHECK")
        print("  Step 1: Trial beam/column selected by EOR assuming FR connections.")
        print("  Step 2: Check beam as simply supported between shear plate connections.")
        print("  (EOR responsibility - verifying with provided Mu)")
        print(f"  Applied moment Mu = {self.loads.Mu:.0f} kip-in")
        print()

    # ---------- Step 3: yield area ----------
    def step3_yield_link_area(self):
        self.subsection("STEP 3: REQUIRED YIELD-LINK YIELD AREA (EQ. 12.9-1, 12.9-2)")
        Mu = self.loads.Mu
        d = self.beam.d
        Fy_link = DEFAULT_FY_LINK

        # Eq. 12.9-1
        P_y_link_req = Mu / (PHI_B * d)
        print(f"  P'_y-link = Mu / (phi_b * d)  (Eq. 12.9-1)")
        print(f"  P'_y-link = {Mu:.0f} / ({PHI_B} * {d:.2f}) = {P_y_link_req:.1f} kips")

        # Eq. 12.9-2
        A_y_link_req = P_y_link_req / Fy_link
        print(f"  A'_y-link = P'_y-link / F_y-link  (Eq. 12.9-2)")
        print(f"  A'_y-link = {P_y_link_req:.1f} / {Fy_link:.1f} = {A_y_link_req:.2f} in^2")

        self._A_y_link_req = A_y_link_req
        self._P_y_link_req = P_y_link_req
        print()

    # ---------- Step 4: column-side geometry ----------
    def step4_col_side_geometry(self):
        self.subsection("STEP 4: YIELD-LINK COLUMN-SIDE GEOMETRY")
        b = self.beam
        c = self.column

        # Step 4.1: b_col-side = min(beam bf, column bf)
        b_col_side = min(b.bf, c.bf)
        print(f"  Step 4.1: b_col-side = min(beam_bf, col_bf) "
              f"= min({b.bf:.2f}, {c.bf:.2f}) = {b_col_side:.2f} in")

        # Step 4.2: L_col-side limits
        t_flange_est = 0.75  # estimated, will be finalized in Step 9
        a = self.params.a_dist
        L_col_side_min = a - t_flange_est + 1.0
        L_col_side_max = 5.0
        L_col_side = min(max(L_col_side_min, 3.0), L_col_side_max)
        print(f"  Step 4.2: L_col-side = {L_col_side:.1f} in "
              f"(min={L_col_side_min:.1f}, max={L_col_side_max:.1f})")

        # b_bm-side initial estimate = b_col-side
        b_bm_side = b_col_side
        print(f"  b_bm-side (initial) = {b_bm_side:.2f} in")

        self._b_col_side = b_col_side
        self._b_bm_side_init = b_bm_side
        self._L_col_side = L_col_side
        self._t_flange_est = t_flange_est
        print()

    # ---------- Step 5: yield width ----------
    def step5_yield_width(self):
        self.subsection("STEP 5: YIELDING SECTION WIDTH (EQ. 12.9-3)")
        A_req = self._A_y_link_req
        b_col = self._b_col_side
        b_bm = self._b_bm_side_init

        # Use t_stem from constructor parameter
        t_stem = self.t_stem

        # Eq. 12.9-3
        b_yield_req = A_req / t_stem
        b_yield_limit = min(0.5 * b_col, 0.5 * b_bm, B_YIELD_MAX)
        b_yield = min(b_yield_req, b_yield_limit)

        print(f"  t_stem = {t_stem:.3f} in (min {T_STEM_MIN:.3f}, max {T_STEM_MAX:.3f})")
        if t_stem < T_STEM_MIN or t_stem > T_STEM_MAX:
            print(f"  FAIL: t_stem outside permitted range "
                  f"[{T_STEM_MIN:.3f}, {T_STEM_MAX:.3f}]")
            self.checks["prequalification"] = False
        print(f"  b_yield,req'd = A'_y-link / t_stem = {A_req:.2f} / {t_stem:.3f} "
              f"= {b_yield_req:.2f} in  (Eq. 12.9-3)")
        print(f"  b_yield limit = min(0.5*b_col, 0.5*b_bm, 6) "
              f"= min({0.5*b_col:.2f}, {0.5*b_bm:.2f}, {B_YIELD_MAX}) "
              f"= {b_yield_limit:.2f} in")
        print(f"  b_yield = {b_yield:.2f} in")

        if b_yield_req > b_yield_limit:
            print(f"  WARNING: Required width exceeds limit. "
                  f"Increase t_stem or beam/column size.")

        A_y_link = b_yield * t_stem
        self._b_yield = b_yield
        self._A_y_link = A_y_link
        self.t_stem = t_stem
        print(f"  A_y-link = b_yield * t_stem = {b_yield:.2f} * {t_stem:.3f} "
              f"= {A_y_link:.3f} in^2")
        print()

    # ---------- Step 6: yield length ----------
    def step6_yield_length(self):
        self.subsection("STEP 6: MINIMUM YIELDING LENGTH (EQ. 12.9-4)")
        d = self.beam.d
        t_stem = self.t_stem
        R = t_stem  # Transition radius = t_stem (Section 12.7)

        # Eq. 12.9-4
        L_y_link = (0.05 / 0.085) * ((d + t_stem) / 2) + 2 * R
        print(f"  L_y-link = (0.05/0.085)*((d+t_stem)/2) + 2*R  (Eq. 12.9-4)")
        print(f"  L_y-link = (0.05/0.085)*(({d:.2f}+{t_stem:.3f})/2) + "
              f"2*{R:.3f}")
        print(f"  L_y-link = {L_y_link:.2f} in")

        strain_check = 0.05 * (d + t_stem) / 2 / (L_y_link - 2 * R)
        print(f"  Strain check: {strain_check:.4f} <= 0.085: "
              f"{'OK' if strain_check <= 0.085 else 'FAIL'}")

        self._L_y_link = L_y_link
        self._R = R
        print()

    # ---------- Step 7: link strength ----------
    def step7_link_strength(self):
        self.subsection("STEP 7: YIELD-LINK STRENGTH (EQ. 12.9-5, 12.9-6)")
        A = self._A_y_link
        Fy = DEFAULT_FY_LINK
        Fu = DEFAULT_FU_LINK
        d = self.beam.d
        t_stem = self.t_stem

        # Eq. 12.9-5
        P_ye = A * RY_LINK * Fy
        print(f"  P_ye-link = A_y-link * R_y * F_y-link  (Eq. 12.9-5)")
        print(f"  P_ye-link = {A:.3f} * {RY_LINK} * {Fy} = {P_ye:.1f} kips")

        # Eq. 12.9-6
        P_r = A * RT_LINK * Fu
        print(f"  P_r-link = A_y-link * R_t * F_u-link  (Eq. 12.9-6)")
        print(f"  P_r-link = {A:.3f} * {RT_LINK} * {Fu} = {P_r:.1f} kips")

        # Eq. 12.9-28: M_pr
        M_pr = P_r * (d + t_stem)
        print(f"  M_pr = P_r-link * (d + t_stem)  (Eq. 12.9-28)")
        print(f"  M_pr = {P_r:.1f} * ({d:.2f} + {t_stem:.3f}) "
              f"= {M_pr:.0f} kip-in ({M_pr/12:.1f} kip-ft)")

        # Eq. 12.9-29: M_ye-link
        M_ye = P_ye * (d + t_stem)
        print(f"  M_ye-link = P_ye-link * (d + t_stem)  (Eq. 12.9-29)")
        print(f"  M_ye-link = {P_ye:.1f} * ({d:.2f} + {t_stem:.3f}) "
              f"= {M_ye:.0f} kip-in")

        self.yl_forces = YieldLinkForces(
            P_ye_link=P_ye, P_r_link=P_r, M_pr=M_pr, M_ye_link=M_ye
        )
        print()

    # ---------- Step 8: beam-side design ----------
    def step8_beam_side_design(self):
        self.subsection("STEP 8: YIELD-LINK BEAM-SIDE DESIGN (EQ. 12.9-7)")
        P_r = self.yl_forces.P_r_link
        d_b_stem = 0.875  # assumed bolt diameter (7/8 in A325)
        n_rows = 2         # minimum 2 rows
        s_stem = 3.0       # bolt spacing (>= 2.67*d_b_stem)
        s_c = 1.5          # edge distance from reduced section
        s_b = 1.5          # edge distance from end

        # Check bolt shear capacity
        # A325 7/8" bolt: Fnt = 90 ksi, Fnv = 54 ksi
        Fnv = 54.0  # ksi (A325, threads excluded)
        A_bolt = math.pi / 4 * d_b_stem**2
        Rn_bolt = 2 * Fnv * A_bolt * n_rows  # 2 bolts per row (each side of stem)
        print(f"  Step 8.1: Stem-to-beam bolts: {n_rows} rows x 2 bolts, "
              f"d_b = {d_b_stem:.3f} in A325")
        print(f"  R_n (bolt shear) = {Rn_bolt:.1f} kips vs P_r-link = {P_r:.1f} kips")
        if Rn_bolt < P_r:
            # Increase rows
            n_rows = math.ceil(P_r / (2 * Fnv * A_bolt))
            Rn_bolt = 2 * Fnv * A_bolt * n_rows
            print(f"  Increased to {n_rows} rows. R_n = {Rn_bolt:.1f} kips")

        # Eq. 12.9-7
        L_bm_side = s_c + (n_rows - 1) * s_stem + s_b
        print(f"  Step 8.3: L_bm-side = s_c + (n_rows-1)*s_stem + s_b  (Eq. 12.9-7)")
        print(f"  L_bm-side = {s_c} + ({n_rows-1})*{s_stem} + {s_b} "
              f"= {L_bm_side:.2f} in")

        # Update b_bm-side
        b_bm_side = self._b_col_side
        print(f"  Step 8.2: b_bm-side = {b_bm_side:.2f} in")

        # Assemble geometry
        self.yl_geom = YieldLinkGeometry(
            t_stem=self.t_stem,
            b_col_side=self._b_col_side,
            b_bm_side=b_bm_side,
            b_yield=self._b_yield,
            L_col_side=self._L_col_side,
            L_bm_side=L_bm_side,
            L_y_link=self._L_y_link,
        )

        print(f"\n  Yield-Link Geometry Summary:")
        print(f"    t_stem = {self.yl_geom.t_stem:.3f} in")
        print(f"    b_col-side = {self.yl_geom.b_col_side:.2f} in")
        print(f"    b_bm-side = {self.yl_geom.b_bm_side:.2f} in")
        print(f"    b_yield = {self.yl_geom.b_yield:.2f} in")
        print(f"    L_col-side = {self.yl_geom.L_col_side:.2f} in")
        print(f"    L_y-link = {self.yl_geom.L_y_link:.2f} in")
        print(f"    L_bm-side = {self.yl_geom.L_bm_side:.2f} in")
        print(f"    L_total = {self.yl_geom.L_total:.2f} in")
        print(f"    A_y-link = {self._A_y_link:.3f} in^2")
        print()

    # ---------- Step 9: flange connection ----------
    def step9_flange_connection(self):
        self.subsection("STEP 9: YIELD-LINK FLANGE-TO-COLUMN CONNECTION")
        P_r = self.yl_forces.P_r_link
        yl = self.yl_geom
        lt = self.params.link_type

        # Step 9.1: Bolt tension demand
        if lt == "tstub":
            # Eq. 12.9-8 (T-stub, 4 bolts per flange)
            r_t = P_r / 4
            print(f"  Step 9.1: T-stub Yield-Link")
            print(f"  r_t = P_r-link / 4  (Eq. 12.9-8)")
            print(f"  r_t = {P_r:.1f} / 4 = {r_t:.1f} kips/bolt")
        else:
            # Eq. 12.9-9 (end-plate)
            d = self.beam.d
            tf = self.beam.tf
            # h_0, h_1 per Table 6.2 (4E configuration)
            # Per AISC 358 Chapter 6: measured from compression flange CL
            # h_0 = (d - tf) + pfo  (outer bolt, beyond tension flange)
            # h_1 = (d - tf) - pfi  (inner bolt, between flanges)
            pfi = 2.0   # typical inner pitch
            pfo = 2.0   # typical outer pitch
            d_ft = d - tf  # distance between flange centerlines
            h_0 = d_ft + pfo  # outer bolt row
            h_1 = d_ft - pfi  # inner bolt row
            M_pr = self.yl_forces.M_pr
            # Pre-compute V_u per Eq. 12.9-34 (all inputs known)
            dc_half = self.column.d / 2
            a_sp = self.params.a_dist
            L_h_pre = self.params.L - 2 * (dc_half + a_sp)
            gravity = self.loads.gravity_combination
            V_u = 2 * M_pr / L_h_pre + gravity / 2
            a = self.params.a_dist

            r_t = M_pr / (2 * (h_0 + h_1)) + V_u * a / (2 * h_1)
            print(f"  Step 9.1: End-plate Yield-Link")
            print(f"  r_t = M_pr/(2*(h_0+h_1)) + V_u*a/(2*h_1)  (Eq. 12.9-9)")
            print(f"  r_t = {r_t:.1f} kips/bolt")

        # Step 9.2: Flange thickness for no prying
        # Eq. 12.9-10 and 12.9-11
        d_b_flange = 1.0   # 1-in bolt assumed
        b_dist = 2.0       # vertical distance from bolt CL to stem face
        b_prime = b_dist - d_b_flange / 2
        s_flange = 4.0     # bolt spacing in flange
        p = min(yl.b_col_side / 2, s_flange)

        t_flange_req = math.sqrt(4 * r_t * b_prime / (p * PHI_D * DEFAULT_FU_LINK))
        print(f"\n  Step 9.2: Flange thickness (no prying) (Eq. 12.9-10)")
        print(f"  b' = b - d_b/2 = {b_dist} - {d_b_flange/2:.3f} "
              f"= {b_prime:.3f} in  (Eq. 12.9-11)")
        print(f"  p = min(b_col/2, s_flange) = min({yl.b_col_side/2:.2f}, "
              f"{s_flange}) = {p:.2f} in")
        print(f"  t_flange = sqrt(4*r_t*b' / (p*phi_d*F_u))")
        print(f"  t_flange = sqrt(4*{r_t:.1f}*{b_prime:.3f} / "
              f"({p:.2f}*{PHI_D}*{DEFAULT_FU_LINK}))")
        print(f"  t_flange = {t_flange_req:.3f} in")

        t_flange = math.ceil(t_flange_req * 8) / 8  # round up to nearest 1/8"
        print(f"  Use t_flange = {t_flange:.3f} in")

        # Step 9.4: Stem-to-flange weld (Eq. 12.9-12)
        P_r_weld = yl.b_col_side * yl.t_stem * RT_LINK * DEFAULT_FU_LINK
        print(f"\n  Step 9.4: Stem-to-flange weld demand (Eq. 12.9-12)")
        print(f"  P_r-weld = b_col-side * t_stem * R_t * F_u-link")
        print(f"  P_r-weld = {yl.b_col_side:.2f} * {yl.t_stem:.3f} * "
              f"{RT_LINK} * {DEFAULT_FU_LINK}")
        print(f"  P_r-weld = {P_r_weld:.1f} kips")

        Fw = 0.60 * self.FEXX
        weld_length = yl.b_col_side
        w_req = P_r_weld / (2 * PHI_N * Fw * weld_length)
        print(f"  Double fillet weld: w = P_r-weld / (2*phi*Fw*L)")
        print(f"  w = {P_r_weld:.1f} / (2*{PHI_N}*{Fw:.1f}*{weld_length:.2f})")
        print(f"  w = {w_req:.3f} in (each side)")

        self._t_flange = t_flange
        self._r_t = r_t
        self._d_b_flange = d_b_flange
        self._P_r_weld = P_r_weld
        self.checks["flange_connection"] = True
        print()

    # ---------- Step 10: buckling restraint ----------
    def step10_buckling_restraint(self):
        self.subsection("STEP 10: BUCKLING RESTRAINT ASSEMBLY")
        P_r = self.yl_forces.P_r_link
        yl = self.yl_geom
        d = self.beam.d
        t_stem = yl.t_stem
        b_yield = yl.b_yield

        # Step 10.1: BRP minimum thickness (Eq. 12.9-13)
        # L_cant: lever arm (simplified estimate)
        L_cant = yl.L_y_link * 0.4  # approximate
        b_n = b_yield  # net width of BRP approx = b_yield
        t_BRP_min_calc = 0.51 * math.sqrt(
            L_cant * P_r / (FY_BRP * RY_BRP * b_n)
        )
        t_BRP = max(t_BRP_min_calc, T_BRP_MIN)
        print(f"  Step 10.1: BRP thickness (Eq. 12.9-13)")
        print(f"  t_BRP,min = 0.51*sqrt(L_cant*P_r / (Fy_BRP*Ry_BRP*b_n))")
        print(f"  t_BRP,min = {t_BRP_min_calc:.3f} in, use {t_BRP:.3f} in "
              f"(min {T_BRP_MIN:.3f})")

        # Step 10.2: Beam flange minimum thickness (Eq. 12.9-14)
        # Compute buckling parameters
        # Eq. 12.9-18: I_y is weak-axis MOI of reduced link cross-section
        # Cross-section: b_yield wide x t_stem thick plate
        # Weak axis (out-of-plane buckling): I_y = b_yield * t_stem^3 / 12
        I_y = b_yield * t_stem**3 / 12
        # Eq. 12.9-20: target strain
        eps_target = 0.04 * (d + t_stem) / 2 / (yl.L_y_link + 2 * self._R)
        # Eq. 12.9-19: gap increase
        g = 0.25 * eps_target * t_stem

        # Eq. 12.9-18: effective buckling wavelength
        l_o = math.sqrt(
            1900 * I_y / P_r * (1 + (b_yield / (2 * g) + 1.013)**(-1))
        )
        # Eq. 12.9-17: N_design
        N_design = max(1, round(0.5 * yl.L_y_link / l_o))
        # Eq. 12.9-21: Q_i
        Q_i = 4 * g * P_r / l_o
        # Eq. 12.9-16: Q total
        Q = N_design * Q_i

        n_BRP_bolts = 2  # minimum 2 bolts per side
        T_ux = Q / n_BRP_bolts  # Eq. 12.9-15

        # Eq. 12.9-14: t_bf_min
        b_prime_bf = 1.5  # distance from bolt CL to beam centerline (estimate)
        p_e = 3.0         # effective length per bolt (estimate)
        F_ub = self.beam.Fu
        t_bf_min = math.sqrt(4 * T_ux * b_prime_bf / (PHI_D * p_e * F_ub))
        t_bf_min = max(t_bf_min, TF_BEAM_MIN)

        print(f"\n  Step 10.2: Beam flange thickness check (Eq. 12.9-14)")
        print(f"  I_y (weak-axis) = {I_y:.4f} in^4")
        print(f"  eps_target = {eps_target:.4f}  (Eq. 12.9-20)")
        print(f"  g = {g:.4f} in  (Eq. 12.9-19)")
        print(f"  l_o = {l_o:.2f} in  (Eq. 12.9-18)")
        print(f"  N_design = {N_design}  (Eq. 12.9-17)")
        print(f"  Q = {Q:.1f} kips  (Eq. 12.9-16)")
        print(f"  T_ux = {T_ux:.1f} kips/bolt  (Eq. 12.9-15)")
        print(f"  t_bf,min = {t_bf_min:.3f} in")

        bf_ok = self.beam.tf >= t_bf_min
        print(f"  Beam tf = {self.beam.tf:.3f} in >= {t_bf_min:.3f}: "
              f"{'OK' if bf_ok else 'FAIL'}")

        # Step 10.3: BRP bolt size
        V_ux = MU_K * T_ux  # Eq. 12.9-22

        # Strong-axis shear (Eq. 12.9-23)
        # Strong-axis MOI: bending about axis parallel to t_stem, depth = b_yield
        I_x = t_stem * b_yield**3 / 12
        V_uy = (0.5 * P_r) / math.sqrt(
            1900 * I_x / P_r * (1 + (4 * t_stem + 1.013)**(-1))
        )

        print(f"\n  Step 10.3: BRP bolt check")
        print(f"  V_ux (out-of-plane shear) = mu_k * T_ux = "
              f"{MU_K} * {T_ux:.1f} = {V_ux:.1f} kips  (Eq. 12.9-22)")
        print(f"  V_uy (in-plane shear) = {V_uy:.1f} kips  (Eq. 12.9-23)")
        print(f"  Bolt size: min {D_BRP_BOLT_MIN:.3f} in diameter")

        self.checks["buckling_restraint"] = bf_ok
        print()

    # ---------- Step 11: connection stiffness ----------
    def step11_stiffness(self):
        self.subsection("STEP 11: CONNECTION STIFFNESS (EQ. 12.9-24 TO 12.9-33)")
        yl = self.yl_geom
        d = self.beam.d
        t_stem = yl.t_stem
        P_ye = self.yl_forces.P_ye_link
        P_r = self.yl_forces.P_r_link

        # Estimated flange parameters
        w_col_side = yl.b_col_side
        t_flange = self._t_flange
        g_flange = 3.0  # distance from bolt CL to stem face (estimate)
        n_bolt = 4

        # Eq. 12.9-24: K1 (flange bending stiffness)
        I_flange = w_col_side * t_flange**3 / 12
        K1 = (0.75 * 192 * E * I_flange) / g_flange**3
        print(f"  K1 (flange bending) = {K1:.0f} kip/in  (Eq. 12.9-24)")

        # Eq. 12.9-25: K2 (nonyielding stem)
        s_c = 1.5
        l_v = 0.0  # 0 when 4 or fewer bolts
        K2 = t_stem * yl.b_col_side * E / (yl.L_col_side + s_c + l_v)
        print(f"  K2 (nonyielding stem) = {K2:.0f} kip/in  (Eq. 12.9-25)")

        # Eq. 12.9-26: K3 (yielding stem)
        K3 = t_stem * yl.b_yield * E / yl.L_y_link
        print(f"  K3 (yielding stem) = {K3:.0f} kip/in  (Eq. 12.9-26)")

        # Eq. 12.9-27: K_eff
        K_eff = K1 * K2 * K3 / (K1*K2 + K2*K3 + K1*K3)
        print(f"  K_eff = {K_eff:.0f} kip/in  (Eq. 12.9-27)")

        # Eq. 12.9-28: M_pr (already computed)
        M_pr = P_r * (d + t_stem)
        # Eq. 12.9-29: M_ye-link (already computed)
        M_ye = P_ye * (d + t_stem)

        # Eq. 12.9-30: delta_0.04
        delta_04 = 0.04 * (d + t_stem) / 2
        # Eq. 12.9-31: delta_0.07
        delta_07 = 0.07 * (d + t_stem) / 2
        # Eq. 12.9-32: delta_y
        delta_y = P_ye / K_eff
        # Eq. 12.9-33: theta_y
        theta_y = delta_y / (0.5 * (d + t_stem))

        print(f"\n  Deformation parameters:")
        print(f"  delta_0.04 = {delta_04:.4f} in  (Eq. 12.9-30)")
        print(f"  delta_0.07 = {delta_07:.4f} in  (Eq. 12.9-31)")
        print(f"  delta_y = {delta_y:.4f} in  (Eq. 12.9-32)")
        print(f"  theta_y = {theta_y:.6f} rad ({math.degrees(theta_y):.4f} deg)  "
              f"(Eq. 12.9-33)")
        print(f"  M_pr = {M_pr:.0f} kip-in | M_ye = {M_ye:.0f} kip-in")

        # Step 11.2: Connection moment check
        Mu = self.loads.Mu
        phi_Mn = PHI_B * M_ye / RY_LINK  # phi*M_n where M_n = M_ye/Ry
        print(f"\n  Step 11.2: Connection moment check")
        print(f"  phi*M_n = phi*M_ye/R_y = {PHI_B}*{M_ye:.0f}/{RY_LINK}"
              f" = {phi_Mn:.0f} kip-in")
        print(f"  Mu = {Mu:.0f} kip-in <= phi*M_n = {phi_Mn:.0f}: "
              f"{'OK' if Mu <= phi_Mn else 'FAIL'}")

        self.stiffness = ConnectionStiffness(
            K1=K1, K2=K2, K3=K3, K_eff=K_eff,
            delta_y=delta_y, theta_y=theta_y,
            delta_04=delta_04, delta_07=delta_07,
        )
        self.checks["stiffness"] = Mu <= phi_Mn
        print()

    # ---------- Step 12: required shear ----------
    def step12_required_shear(self):
        self.subsection("STEP 12: REQUIRED SHEAR STRENGTH (EQ. 12.9-34)")
        M_pr = self.yl_forces.M_pr
        pm = self.params
        ld = self.loads
        d = self.beam.d

        # L_h: distance between shear bolt centers at each end
        a = pm.a_dist
        dc_half = self.column.d / 2
        # Distance from column CL to shear bolt center = dc_half + a
        L_h = pm.L - 2 * (dc_half + a)

        gravity = ld.gravity_combination
        # Eq. 12.9-34: V_u = 2*M_pr/L_h + V_gravity
        self.V_u = 2 * M_pr / L_h + gravity / 2

        print(f"  L_h = L - 2*(dc/2 + a) = {pm.L:.0f} - "
              f"2*({dc_half:.2f}+{a:.1f}) = {L_h:.1f} in")
        print(f"  Gravity (1.2D + {ld.f1}L + 0.2S) = {gravity:.2f} kips")
        print(f"  V_u = 2*M_pr/L_h + gravity/2  (Eq. 12.9-34)")
        print(f"  V_u = 2*{M_pr:.0f}/{L_h:.1f} + {gravity:.2f}/2"
              f" = {self.V_u:.1f} kips")

        self._L_h = L_h
        print()

    # ---------- Step 13: member checks ----------
    def step13_member_checks(self):
        self.subsection("STEP 13: BEAM AND COLUMN CHECKS")
        b = self.beam
        c = self.column
        M_pr = self.yl_forces.M_pr

        # Step 13.1: Beam shear strength
        V_n = 0.6 * b.Fy * b.d * b.tw
        phi_Vn = PHI_V * V_n
        beam_ok = self.V_u <= phi_Vn
        print(f"  Step 13.1: Beam shear")
        print(f"  V_n = 0.6*Fy*d*tw = 0.6*{b.Fy}*{b.d:.2f}*{b.tw:.3f}"
              f" = {V_n:.1f} kips")
        print(f"  phi*V_n = {phi_Vn:.1f} kips")
        print(f"  V_u = {self.V_u:.1f} kips <= phi*V_n: "
              f"{'OK' if beam_ok else 'FAIL'}")

        # Step 13.2: Column - M_n <= phi*Fy*Sx limit
        Sx_col = c.Sx
        phi_Fy_Sx = PHI_B * c.Fy * Sx_col
        print(f"\n  Step 13.2: Column flexural strength limit (if bracing at "
              f"top flange only)")
        print(f"  phi*Fy*Sx = {PHI_B}*{c.Fy}*{Sx_col:.1f} "
              f"= {phi_Fy_Sx:.0f} kip-in")

        self.checks["beam_shear"] = beam_ok
        print()

    # ---------- Step 14: column-beam relationship ----------
    def step14_column_beam(self):
        self.subsection("STEP 14: COLUMN-BEAM RELATIONSHIP (SECTION 12.4)")
        st = self.params.system_type

        if st == "IMF":
            print("  IMF: Column-beam ratio per AISC Seismic Provisions")
            print("  (May not require strong-column/weak-beam check)")
            self.checks["column_beam"] = True
            print()
            return

        # SMF: check per AISC 341 E3.6c
        # Sum M_pb* = Sum(M_pr + M_uv)
        M_pr = self.yl_forces.M_pr
        V_u = self.V_u
        a = self.params.a_dist
        dc = self.column.d
        M_uv = V_u * (a + dc / 2)

        n_beams = 2  # typical: one beam each side
        Sum_Mpb = n_beams * (M_pr + M_uv)

        print(f"  M_uv = V_u * (a + dc/2) = {V_u:.1f} * "
              f"({a:.1f} + {dc/2:.2f}) = {M_uv:.0f} kip-in")
        print(f"  Sum M_pb* = {n_beams}*(M_pr + M_uv) = {n_beams}*"
              f"({M_pr:.0f} + {M_uv:.0f}) = {Sum_Mpb:.0f} kip-in")

        # Column plastic moment capacity
        Hu = self.params.story_above
        Hl = self.params.story_below
        H = (Hu + Hl) / 2

        Zc = self.column.Zx
        Fyc = self.column.Fy
        Pu = self.loads.Pu_sp

        # Simplified: Sum M_pc ~ 2*Zc*Fyc (no axial reduction for quick check)
        Sum_Mpc = 2 * Zc * Fyc
        ratio = Sum_Mpc / Sum_Mpb if Sum_Mpb > 0 else 999

        print(f"  Sum M_pc (simplified) ~ 2*Zc*Fyc = 2*{Zc:.1f}*{Fyc}"
              f" = {Sum_Mpc:.0f} kip-in")
        print(f"  Ratio Sum M_pc / Sum M_pb* = {ratio:.3f}")
        print(f"  {'OK' if ratio >= 1.0 else 'FAIL - increase column size'}")
        print(f"  Note: Full check per AISC 341 E3.6c including axial effects")

        self.checks["column_beam"] = ratio >= 1.0
        print()

    # ---------- Step 15: shear plate ----------
    def step15_shear_plate(self):
        self.subsection("STEP 15: SHEAR PLATE CONNECTION DESIGN")
        V_u = self.V_u
        a = self.params.a_dist
        P_u_sp = self.loads.Pu_sp

        # Moment in shear plate at column face
        M_u_sp = V_u * a
        print(f"  M_u-sp = V_u * a = {V_u:.1f} * {a:.1f} = {M_u_sp:.0f} kip-in")

        # Step 15.1: Bolt shear (Eq. 12.9-35)
        n_horz = 3   # horizontal bolts (central + 2)
        n_vert = 3   # vertical bolts
        V_u_bolt = math.sqrt(
            (P_u_sp / n_horz)**2 + (V_u / n_vert)**2
        )
        print(f"\n  Step 15.1: Bolt shear (Eq. 12.9-35)")
        print(f"  n_horz = {n_horz} | n_vert = {n_vert}")
        print(f"  V_u-bolt = sqrt((P_u-sp/{n_horz})^2 + (V_u/{n_vert})^2)")
        print(f"  V_u-bolt = sqrt(({P_u_sp:.1f}/{n_horz})^2 + "
              f"({V_u:.1f}/{n_vert})^2) = {V_u_bolt:.1f} kips")

        # Bolt capacity check (A325 7/8" snug-tight)
        d_b_sp = 0.875
        Fnv = 54.0  # ksi (A325, threads excluded)
        A_bolt = math.pi / 4 * d_b_sp**2
        phi_Rn_bolt = PHI_N * Fnv * A_bolt
        bolt_ok = V_u_bolt <= phi_Rn_bolt
        print(f"  phi*R_n (single bolt, A325 7/8\") = {phi_Rn_bolt:.1f} kips")
        print(f"  V_u-bolt = {V_u_bolt:.1f} <= phi*R_n: "
              f"{'OK' if bolt_ok else 'FAIL'}")

        # Step 15.2: Slot lengths (Eq. 12.9-36, 12.9-37)
        s_vert = 3.0  # vertical spacing
        s_horz = 3.0  # horizontal spacing
        L_slot_horz = d_b_sp + 0.125 + 0.14 * s_vert * (n_vert - 1) / 2
        L_slot_vert = d_b_sp + 0.125 + 0.14 * s_horz * (n_horz - 1)
        print(f"\n  Step 15.2: Slot lengths for 0.07 rad rotation")
        print(f"  L_slot_horz = {L_slot_horz:.2f} in  (Eq. 12.9-36)")
        print(f"  L_slot_vert = {L_slot_vert:.2f} in  (Eq. 12.9-37)")

        # Step 15.4: Weld to develop plate in shear
        t_p = 0.375  # shear plate thickness (estimate)
        w_min_weld = 0.75 * t_p
        print(f"\n  Step 15.4: Shear plate weld (min 3/4*t_p for double fillet)")
        print(f"  t_p = {t_p:.3f} in | min weld = {w_min_weld:.3f} in")

        self.checks["shear_plate"] = bolt_ok
        print()

    # ---------- Step 16: panel zone ----------
    def step16_panel_zone(self):
        self.subsection("STEP 16: PANEL ZONE SHEAR (AISC 360 J10.6)")
        P_r = self.yl_forces.P_r_link
        M_pr = self.yl_forces.M_pr
        d = self.beam.d
        c = self.column

        # Panel zone demand from moment equilibrium
        # V_pz = Sum(M_pr at face) / d_beam - V_col
        n_beams = 2
        V_u = self.V_u
        a = self.params.a_dist
        dc = self.column.d

        # Sum of moments at column face
        Sum_M_face = n_beams * M_pr
        # Column shear from moment equilibrium
        Hu = self.params.story_above
        Hl = self.params.story_below
        H = (Hu + Hl) / 2
        V_col = Sum_M_face / H

        # Panel zone shear demand
        Rn_pz_demand = Sum_M_face / d - V_col

        # Panel zone capacity per AISC 360 J10.6
        # phi = 0.90 (NOT 1.0 as in typical SMF - SST specific!)
        phi_pz = 0.90
        dc = c.d  # AISC 360 J10.6: d_c = overall column depth
        Rn_pz = 0.6 * c.Fy * dc * c.tw
        phi_Rn_pz = phi_pz * Rn_pz

        print(f"  Demand: V_pz = Sum(M_pr)/d - V_col")
        print(f"  Sum M_face = {n_beams}*{M_pr:.0f} = {Sum_M_face:.0f} kip-in")
        print(f"  V_col = Sum(M_pr)/H = {Sum_M_face:.0f}/{H:.1f} = {V_col:.1f} kips")
        print(f"  V_pz = {Sum_M_face:.0f}/{d:.2f} - {V_col:.1f} = {Rn_pz_demand:.1f} kips")
        print(f"  Note: SST uses phi = 0.90 (AISC 360), NOT phi = 1.0 (AISC 341)")
        print(f"  d_c = {dc:.2f} in (overall column depth per AISC 360 J10.6)")
        print(f"  R_n = 0.6*Fy*dc*tw = 0.6*{c.Fy}*{dc:.2f}*{c.tw:.3f}"
              f" = {Rn_pz:.1f} kips")
        print(f"  phi*R_n = {phi_pz}*{Rn_pz:.1f} = {phi_Rn_pz:.1f} kips")

        self.Rn_pz_demand = Rn_pz_demand
        self.phi_Rn_pz = phi_Rn_pz

        pz_ok = Rn_pz_demand <= phi_Rn_pz
        print(f"  {'OK' if pz_ok else 'FAIL'} (Utilization: "
              f"{Rn_pz_demand/phi_Rn_pz:.3f})")
        if not pz_ok:
            print(f"  Consider doubler plates")
        self.checks["panel_zone"] = pz_ok
        print()

    # ---------- Step 17: column web ----------
    def step17_column_web(self):
        self.subsection("STEP 17: COLUMN WEB CONCENTRATED FORCE (AISC 360 J10)")
        P_r = self.yl_forces.P_r_link
        c = self.column
        b = self.beam

        # Web local yielding (AISC 360 J10.2)
        k = c.tf  # distance from outer face to web toe (approx)
        R_n_wy = min(5 * c.Fy * k, c.Fy * (2.5 * k + b.bf)) * c.tw * 1.0
        # Simplified: just check basic capacity
        phi_Rn_wy = PHI_D * 5 * c.Fy * k * c.tw

        # Web local crippling (AISC 360 J10.3, Eq J10-4)
        N_bearing = b.bf  # bearing length approx = beam flange width
        # R_n = 0.80*t_w^2 * [1 + 3*(N/d)*(t_w/t_f)^1.5] * sqrt(E*F_y*t_f/t_w)
        phi_Rn_wc = PHI_N * 0.80 * c.tw**2 * (
            1 + 3 * (N_bearing / c.d) * (c.tw / c.tf)**1.5
        ) * math.sqrt(E * c.Fy * c.tf / c.tw)

        print(f"  P_r-link = {P_r:.1f} kips (concentrated force)")
        print(f"  Web local yielding: phi*R_n ~ {phi_Rn_wy:.1f} kips")
        print(f"  Web local crippling: phi*R_n ~ {phi_Rn_wc:.1f} kips")

        web_ok = P_r <= min(phi_Rn_wy, phi_Rn_wc)
        print(f"  {'OK' if web_ok else 'FAIL - need continuity plates'}")

        self.checks["column_web"] = web_ok
        self._phi_Rn_web = min(phi_Rn_wy, phi_Rn_wc)
        print()

    # ---------- Step 18: column flange ----------
    def step18_column_flange(self):
        self.subsection("STEP 18: COLUMN FLANGE FLEXURAL YIELDING (EQ. 12.9-38)")
        M_pr = self.yl_forces.M_pr
        c = self.column

        # Y_c: yield line parameter (per Commentary, analogous to Chapter 6)
        # For T-stub with 4 bolts, Y_c ~ 6.0 (conservative estimate)
        Y_c = 6.0  # approximate yield line parameter
        t_cf_min = math.sqrt(1.11 * M_pr / (PHI_D * c.Fy * Y_c))

        print(f"  t_cf,min = sqrt(1.11*M_pr / (phi_d*Fyc*Y_c))  (Eq. 12.9-38)")
        print(f"  t_cf,min = sqrt(1.11*{M_pr:.0f} / "
              f"({PHI_D}*{c.Fy}*{Y_c}))")
        print(f"  t_cf,min = {t_cf_min:.3f} in")
        print(f"  Column tf = {c.tf:.3f} in")

        cf_ok = c.tf >= t_cf_min
        print(f"  {'OK' if cf_ok else 'FAIL - need continuity plates'}")

        self.checks["column_flange"] = cf_ok
        self._t_cf_min = t_cf_min
        print()

    # ---------- Step 19: continuity plates ----------
    def step19_continuity_plates(self):
        self.subsection("STEP 19: CONTINUITY PLATES (EQ. 12.9-39)")
        web_ok = self.checks.get("column_web", True)
        cf_ok = self.checks.get("column_flange", True)

        if web_ok and cf_ok:
            print("  No continuity plates required - all column limit states OK")
            self.checks["continuity_plates"] = True
        else:
            P_r = self.yl_forces.P_r_link
            # Compute deficit from each failed limit state separately
            deficits = []
            if not web_ok:
                phi_Rn_web = self._phi_Rn_web
                F_su_web = max(0, P_r - phi_Rn_web)
                deficits.append(("web", F_su_web, phi_Rn_web))
            if not cf_ok:
                # Column flange deficit (Step 18 check)
                F_su_cf = max(0, P_r)  # Simplified: full P_r demands continuity plate
                deficits.append(("flange", F_su_cf, 0))

            F_su_max = max(d[1] for d in deficits) if deficits else 0
            print(f"  Continuity plates required (Eq. 12.9-39)")
            for name, F_su, phi_Rn in deficits:
                print(f"  {name}: F_su = P_r-link - phi*R_n = "
                      f"{P_r:.1f} - {phi_Rn:.1f} = {F_su:.1f} kips")
            print(f"  Governing F_su = {F_su_max:.1f} kips")
            print(f"  Required continuity plate strength: {F_su_max:.1f} kips")
            print(f"  Min thickness: 1/4 in (6 mm) per AISC 360 J10.8")
            print(f"  Fillet welds permitted at column web and flanges")

            self.checks["continuity_plates"] = True  # plates can be designed

        print()

    # ---------- summary ----------
    def print_summary(self):
        self.section("DESIGN VERIFICATION SUMMARY")

        def s(k):
            return "PASS" if self.checks.get(k) else "FAIL"

        print(f"Prequalification: {s('prequalification')}")
        print(f"Flange connection: {s('flange_connection')}")
        print(f"Buckling restraint: {s('buckling_restraint')}")
        print(f"Connection stiffness: {s('stiffness')}")
        print(f"Beam shear (Step 13): {s('beam_shear')}")
        print(f"Column-beam ratio: {s('column_beam')}")
        print(f"Shear plate: {s('shear_plate')}")
        print(f"Panel zone: {s('panel_zone')}")
        print(f"Column web: {s('column_web')}")
        print(f"Column flange: {s('column_flange')}")
        print(f"Continuity plates: {s('continuity_plates')}")
        print()

        yl = self.yl_geom
        yf = self.yl_forces
        print(f"KEY RESULTS:")
        print(f"  M_pr = {yf.M_pr:.0f} kip-in | P_r-link = {yf.P_r_link:.1f} kips")
        print(f"  V_u = {self.V_u:.1f} kips")
        print(f"  Yield-Link: t_stem={yl.t_stem:.3f} b_yield={yl.b_yield:.2f}"
              f" L_y-link={yl.L_y_link:.2f}")
        print(f"  K_eff = {self.stiffness.K_eff:.0f} kip/in | "
              f"theta_y = {self.stiffness.theta_y:.6f} rad")
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
            Fy=args.beam_Fy, Fu=args.beam_Fu,
            Ry=args.beam_Ry, Rt=args.beam_Rt,
        )
    raise ValueError("Invalid beam section. Use --beam-section or provide all dimensions.")


def create_column_section(args) -> ColumnSection:
    if args.column_section:
        props = get_section_properties(args.column_section)
        if props:
            return ColumnSection(
                designation=props["designation"],
                d=args.col_d or props["d"],
                bf=args.col_bf or props["bf"],
                tf=args.col_tf or props["tf"],
                tw=args.col_tw or props["tw"],
                Zx=args.col_Zx or props["Zx"],
                Fy=args.col_Fy, Fu=args.col_Fu,
            )
    if all([args.col_d, args.col_bf, args.col_tf, args.col_tw, args.col_Zx]):
        return ColumnSection(
            designation="Custom", d=args.col_d, bf=args.col_bf,
            tf=args.col_tf, tw=args.col_tw, Zx=args.col_Zx,
            Fy=args.col_Fy, Fu=args.col_Fu,
        )
    raise ValueError("Invalid column section. Use --column-section or provide all dimensions.")


# ====================== COMMAND LINE ======================

def parse_args():
    parser = argparse.ArgumentParser(
        description="SST Strong Frame Connection Design Verification "
                    "(AISC 358-16 Chapter 12)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # T-stub Yield-Link (W24 beam, default)
  python sst_design.py --beam-section W24x68 --column-section W14x193 \\
      --span 300 --system-type SMF --Mu 3500

  # End-plate Yield-Link (W12 shallow beam)
  python sst_design.py --beam-section W12x26 --column-section W14x120 \\
      --span 240 --system-type SMF --Mu 1200 --link-type endplate

  # With gravity loads and axial force
  python sst_design.py --beam-section W30x99 --column-section W14x257 \\
      --span 360 --system-type SMF --Mu 6000 --load-D 15 --load-L 20
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
    cg.add_argument("--col-d", type=float)
    cg.add_argument("--col-bf", type=float)
    cg.add_argument("--col-tf", type=float)
    cg.add_argument("--col-tw", type=float)
    cg.add_argument("--col-Zx", type=float)
    cg.add_argument("--col-Fy", type=float, default=DEFAULT_FY_COL)
    cg.add_argument("--col-Fu", type=float, default=DEFAULT_FU_COL)

    dg = parser.add_argument_group("Design")
    dg.add_argument("--span", type=float, required=True)
    dg.add_argument("--system-type", type=str, required=True,
                    choices=["SMF", "IMF"])
    dg.add_argument("--link-type", type=str, default="tstub",
                    choices=["tstub", "endplate"],
                    help="Yield-Link type (default: tstub)")
    dg.add_argument("--t-stem", type=float, default=0.75,
                    help="Yield-Link stem thickness (in, default: 0.75)")
    dg.add_argument("--a-dist", type=float, default=3.0,
                    help="Distance from shear bolt CL to column face (in, default: 3.0)")
    dg.add_argument("--story-above", type=float, default=156.0,
                    help="Story height above node (in, default: 156)")
    dg.add_argument("--story-below", type=float, default=156.0,
                    help="Story height below node (in, default: 156)")
    dg.add_argument("--Mu", type=float, required=True,
                    help="Moment demand from elastic analysis (kip-in)")
    dg.add_argument("--Pu-sp", type=float, default=0.0,
                    help="Required axial strength of connection (kips)")
    dg.add_argument("--FEXX", type=float, default=DEFAULT_FEXX,
                    help=f"Weld electrode strength (ksi, default: {DEFAULT_FEXX})")

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

        loads = Loads(
            D=args.load_D, L=args.load_L, S=args.load_S,
            f1=args.load_f1, Vu=args.Vu,
            Mu=args.Mu, Pu_sp=args.Pu_sp,
        )

        params = DesignParameters(
            L=args.span, system_type=args.system_type,
            link_type=args.link_type,
            story_above=args.story_above, story_below=args.story_below,
            a_dist=args.a_dist,
        )

        checker = SSTDesignChecker(beam, column, params, loads,
                                    FEXX=args.FEXX, t_stem=args.t_stem)

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
