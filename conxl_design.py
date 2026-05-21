#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ConXtech ConXL Moment Connection Design Verification
Based on AISC 358-16 Chapter 10, Section 10.8 - Design Procedure

ConXL connections use a high-strength field-bolted collar assembly to connect
wide-flange beams to concrete-filled 16-in. square HSS or built-up box columns.
Beams are shop-welded to collar flange assemblies and field-bolted via collar
corner assemblies welded to the columns.

Key characteristics (unique to ConXL):
  - Column: 16-in. square concrete-filled HSS or built-up box ONLY
  - Collar bolts: 1-1/4" ASTM A574, pretension = 102 kips (like A490)
  - n_cf = 8 collar bolts per collar flange (fixed)
  - t_collar = 7.125 in (distance column face to collar outside face)
  - C_pr = 1.1 for non-RBS beams (NOT Eq. 2.4-2)
  - C_pr = min((Fy+Fu)/(2Fy), 1.2) for RBS beams
  - Optional RBS cutouts to satisfy strong-column/weak-beam
  - Panel zone includes collar corner leg contribution
  - Concrete fill contributes to column strength

Usage:
    # Non-RBS beam
    python conxl_design.py --beam-section W24x68 --column-wall 0.5 \
        --span 300 --system-type SMF

    # RBS beam
    python conxl_design.py --beam-section W24x68 --column-wall 0.625 \
        --span 300 --system-type SMF --rbs --rbs-a 5 --rbs-b 18 --rbs-c 1.5

    # With gravity loads and story heights
    python conxl_design.py --beam-section W24x68 --column-wall 0.5 \
        --span 300 --system-type SMF --load-D 20 --load-L 30 \
        --story-above 156 --story-below 156
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
PHI_V = 1.00  # Shear (rolled W-shapes, AISC 360 G2.1(a))

# Default material properties
DEFAULT_FY_BEAM = 50.0    # ksi (A992)
DEFAULT_FU_BEAM = 65.0    # ksi (A992)
DEFAULT_FY_COL = 50.0     # ksi (A500 Gr C / A572 Gr 50)
DEFAULT_FU_COL = 62.0     # ksi (A500 Gr C)

# ConXL proprietary constants
T_COLLAR = 7.125     # in - distance from column face to outside face of collar (Fig. 10.10)
DCOL = 16.0          # in - column outside dimension (always 16-in square)
N_CF = 8             # collar bolts per collar flange (fixed)
DB_COLLAR = 1.25     # in - collar bolt diameter (1-1/4 in ASTM A574)
TB = 102.0           # kips - minimum bolt pretension (same as 1-1/4" A490)
D_LEG_CC = 3.5       # in - effective depth of collar corner assembly leg (Eq. 10.8-19)

# Default weld electrode
DEFAULT_FEXX = 70.0  # ksi (E70)

# Steel properties
E = 29000.0  # ksi

# Concrete defaults
DEFAULT_FC = 4.0      # ksi (4000 psi)
MIN_FC = 3.0          # ksi (3000 psi minimum per Section 10.3.2(6))
MIN_CONCRETE_WEIGHT = 110.0  # pcf minimum per Section 10.3.2(6)

# Prequalified beam depth groups
BEAM_GROUPS = {
    "W30": {"lw_CWX": 54.0, "lw_CC": 72.0},
    "W27": {"lw_CWX": 48.0, "lw_CC": 66.0},
    "W24": {"lw_CWX": 42.0, "lw_CC": 60.0},
    "W21": {"lw_CWX": 36.0, "lw_CC": 54.0},
    "W18": {"lw_CWX": 30.0, "lw_CC": 48.0},
}

# Slip-critical bolt parameters (Class A, per AISC 360 J3.8)
MU_CLASS_A = 0.30   # Class A faying surface
DU = 1.13           # Uniformity factor


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
    def dw(self) -> float:
        return self.d - 2 * self.tf

    @property
    def weight(self) -> float:
        try:
            return float(self.designation.upper().split('X')[1])
        except (ValueError, IndexError):
            return 999

    @property
    def depth_group(self) -> str:
        """Extract nominal beam depth group (e.g., 'W24' from 'W24X68')"""
        name = self.designation.upper().replace(" ", "")
        for group in BEAM_GROUPS:
            if name.startswith(group):
                return group
        return ""


@dataclass
class ColumnBox:
    """16-in. square HSS or built-up box column with concrete fill"""
    D: float          # Outside dimension (in) - always 16
    t_col: float      # Wall thickness (in)
    Fy: float = DEFAULT_FY_COL
    Fu: float = DEFAULT_FU_COL
    fc: float = DEFAULT_FC  # Concrete compressive strength (ksi)
    concrete_weight: float = 145.0  # Concrete unit weight (pcf), min 110
    t_leg_CC: float = 0.75  # Effective collar corner leg thickness (in)

    @property
    def d_inner(self) -> float:
        return self.D - 2 * self.t_col

    @property
    def As(self) -> float:
        """Steel area (in^2) - approximate, ignoring corner radii"""
        return 4 * self.D * self.t_col - 4 * self.t_col**2

    @property
    def Ac(self) -> float:
        """Concrete area (in^2)"""
        return self.d_inner**2

    @property
    def Zc(self) -> float:
        """Plastic section modulus about either axis (in^3)"""
        D = self.D
        d = self.d_inner
        return (D**3 - d**3) / 4.0


@dataclass
class RBSGeometry:
    """RBS cutout dimensions (optional)"""
    a: float    # Distance from collar outside face to start of cut (in)
    b: float    # Length of cut (in)
    c: float    # Depth of cut at center (in)


@dataclass
class Loads:
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
    story_above: float = 156.0   # Story height above node (in), default 13 ft
    story_below: float = 156.0   # Story height below node (in), default 13 ft
    Pu: float = 0.0              # Axial load on column (kips)
    C_pr: float = 0.0


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


# ====================== CONXL DESIGN CHECKER ======================

class ConXLDesignChecker:
    """ConXL Connection Design per AISC 358-16 Section 10.8 (11 steps)"""

    def __init__(self, beam: BeamSection, column: ColumnBox,
                 params: DesignParameters, loads: Loads,
                 rbs: Optional[RBSGeometry] = None,
                 FEXX: float = DEFAULT_FEXX):
        self.beam = beam
        self.column = column
        self.params = params
        self.loads = loads
        self.FEXX = FEXX
        self.rbs = rbs
        self.use_rbs = rbs is not None

        self.M_pr = 0.0
        self.V_h = 0.0
        self.Z_e = beam.Zx
        self.s_h = 0.0     # Distance from column CL to plastic hinge
        self.s_f = 0.0     # Distance from column face to plastic hinge
        self.s_bolts = 0.0 # Distance from hinge to collar bolt centroid
        self.M_bolts = 0.0
        self.r_ut = 0.0
        self.checks: dict = {}

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
        self.section("ConXL CONNECTION DESIGN VERIFICATION (AISC 358-16 CHAPTER 10)")
        print()
        self.print_input()

        self.step0_prequalification()
        self.section("DESIGN PROCEDURE (SECTION 10.8)")

        self.step1_Mpr()
        self.step2_Vh()
        self.step3_column_beam()
        self.step4_Mbolts()
        self.step5_bolt_tension()
        self.step6_bolt_shear()
        self.step7_beam_shear()
        self.step8_CWX_weld()
        self.step9_CC_weld()
        self.step10_panel_zone_demand()
        self.step11_panel_zone_capacity()

        self.print_summary()
        return all(v for v in self.checks.values() if v is not None)

    # ---------- input ----------
    def print_input(self):
        self.section("INPUT PARAMETERS")
        b, c, pm, ld = self.beam, self.column, self.params, self.loads
        print(f"BEAM: {b.designation} | d={b.d:.2f} bf={b.bf:.2f} tf={b.tf:.3f} tw={b.tw:.3f} Zx={b.Zx:.1f}")
        print(f"      Fy={b.Fy} Fu={b.Fu} Ry={b.Ry} Rt={b.Rt}")
        if self.use_rbs:
            print(f"      RBS: a={self.rbs.a:.2f} b={self.rbs.b:.2f} c={self.rbs.c:.2f}")
        print(f"COLUMN: {c.D:.0f}-in. square HSS/box | t_col={c.t_col:.3f} Fy={c.Fy} Fu={c.Fu}")
        print(f"        Concrete: f'c={c.fc:.1f} ksi | As={c.As:.2f} in^2 | Ac={c.Ac:.1f} in^2")
        print(f"        Zc={c.Zc:.1f} in^3 | t_leg_CC={c.t_leg_CC:.3f}")
        print(f"COLLAR: t_collar={T_COLLAR:.3f} | n_cf={N_CF} | d_b={DB_COLLAR:.3f} (ASTM A574)")
        print(f"        T_b={TB:.0f} kips | d_leg_CC={D_LEG_CC:.1f}")
        print(f"SPAN: L={pm.L:.0f} in ({pm.L/12:.1f} ft) | {pm.system_type}")
        print(f"STORY: H_above={pm.story_above:.0f} in | H_below={pm.story_below:.0f} in")
        print(f"       Pu={pm.Pu:.1f} kips")
        print(f"LOADS: D={ld.D} L={ld.L} S={ld.S} | Vu={ld.Vu:.2f}")
        print()

    # ---------- Step 0: prequalification ----------
    def step0_prequalification(self):
        self.subsection("PREQUALIFICATION LIMITS (SECTION 10.3)")
        passed = True
        st = self.params.system_type
        b = self.beam
        c = self.column

        # Beam depth must be in prequalified list
        group = b.depth_group
        print(f"  Beam depth group: {group} | Must be W30, W27, W24, W21, or W18: ", end="")
        if group not in BEAM_GROUPS:
            print("FAIL"); passed = False
        else:
            print("OK")

        # Beam flange thickness <= 1.0 in
        print(f"  Flange thickness: tf = {b.tf:.3f} in <= 1.0 in: ", end="")
        if b.tf > 1.0:
            print("FAIL"); passed = False
        else:
            print("OK")

        # Beam flange width <= 12 in
        print(f"  Flange width: bf = {b.bf:.2f} in <= 12 in: ", end="")
        if b.bf > 12.0:
            print("FAIL"); passed = False
        else:
            print("OK")

        # Span/depth ratio
        sd = self.params.L / b.d
        sd_min = 7.0 if st == "SMF" else 5.0
        print(f"  Span/depth L/d = {sd:.1f} >= {sd_min:.0f} ({st}): ", end="")
        if sd < sd_min:
            print("FAIL"); passed = False
        else:
            print("OK")

        # Column: 16-in square HSS or box
        print(f"  Column dimension: {c.D:.1f} in (must be 16 in): ", end="")
        if abs(c.D - DCOL) > 0.01:
            print("FAIL"); passed = False
        else:
            print("OK")

        # Column wall thickness >= 3/8 in
        print(f"  Column wall thickness: t_col = {c.t_col:.3f} in >= 0.375 in: ", end="")
        if c.t_col < 0.375:
            print("FAIL"); passed = False
        else:
            print("OK")

        # Concrete strength >= 3000 psi
        print(f"  Concrete f'c = {c.fc:.1f} ksi >= {MIN_FC:.1f} ksi: ", end="")
        if c.fc < MIN_FC:
            print("FAIL"); passed = False
        else:
            print("OK")

        # Concrete unit weight >= 110 pcf
        print(f"  Concrete unit weight = {c.concrete_weight:.0f} pcf >= {MIN_CONCRETE_WEIGHT:.0f} pcf: ", end="")
        if c.concrete_weight < MIN_CONCRETE_WEIGHT:
            print("FAIL"); passed = False
        else:
            print("OK")

        # RBS geometry limits (if applicable)
        if self.use_rbs:
            rbs = self.rbs
            a_min, a_max = 0.5 * b.bf, 0.75 * b.bf
            b_min, b_max = 0.65 * b.d, 0.85 * b.d
            c_min, c_max = 0.1 * b.bf, 0.25 * b.bf
            print(f"  RBS a = {rbs.a:.2f} in ({a_min:.2f} to {a_max:.2f}): ", end="")
            if not (a_min <= rbs.a <= a_max):
                print("WARNING - outside recommended range")
            else:
                print("OK")
            print(f"  RBS b = {rbs.b:.2f} in ({b_min:.2f} to {b_max:.2f}): ", end="")
            if not (b_min <= rbs.b <= b_max):
                print("WARNING - outside recommended range")
            else:
                print("OK")
            print(f"  RBS c = {rbs.c:.2f} in ({c_min:.2f} to {c_max:.2f}): ", end="")
            if not (c_min <= rbs.c <= c_max):
                print("WARNING - outside recommended range")
            else:
                print("OK")

        # Protected zone
        if self.use_rbs:
            pz = T_COLLAR + self.rbs.a + self.rbs.b
            print(f"  Protected zone: column face to {pz:.1f} in (end of RBS)")
        else:
            pz = T_COLLAR + b.d
            print(f"  Protected zone: column face to {pz:.1f} in (collar face + d)")

        self.checks["prequalification"] = passed
        print()

    # ---------- Step 1: M_pr ----------
    def step1_Mpr(self):
        self.subsection("STEP 1: PROBABLE MAXIMUM MOMENT M_pr (SECTION 2.4.3)")
        b = self.beam

        if self.use_rbs:
            # RBS: C_pr per Eq. 2.4-2
            C_pr = min((b.Fy + b.Fu) / (2 * b.Fy), 1.2)
            print(f"  RBS beam: C_pr = min((Fy+Fu)/(2*Fy), 1.2)")
            print(f"  C_pr = min(({b.Fy}+{b.Fu})/(2*{b.Fy}), 1.2) = {C_pr:.3f}")
            # Z_e = Z_RBS
            self.Z_e = b.Zx - 2 * self.rbs.c * b.tf * (b.d - b.tf)
            print(f"  Z_e = Z_RBS = Zx - 2*c*tf*(d-tf)")
            print(f"  Z_e = {b.Zx:.1f} - 2*{self.rbs.c:.2f}*{b.tf:.3f}*({b.d:.2f}-{b.tf:.3f})")
            print(f"  Z_e = {self.Z_e:.1f} in^3")
        else:
            # Non-RBS: C_pr = 1.1 (ConXL specific!)
            C_pr = 1.1
            print(f"  Non-RBS beam: C_pr = 1.1 (ConXL specific, NOT Eq. 2.4-2)")
            self.Z_e = b.Zx
            print(f"  Z_e = Zx = {b.Zx:.1f} in^3")

        self.params.C_pr = C_pr
        self.M_pr = C_pr * b.Ry * b.Fy * self.Z_e

        print(f"  M_pr = C_pr * Ry * Fy * Ze")
        print(f"  M_pr = {C_pr:.3f} * {b.Ry} * {b.Fy} * {self.Z_e:.1f}")
        print(f"  M_pr = {self.M_pr:.0f} kip-in ({self.M_pr/12:.1f} kip-ft)")

        # Compute distances
        dc_half = self.column.D / 2
        if self.use_rbs:
            self.s_f = T_COLLAR + self.rbs.a + self.rbs.b / 2   # Eq. 10.8-13
            self.s_h = dc_half + T_COLLAR + self.rbs.a + self.rbs.b / 2  # Eq. 10.8-15
            self.s_bolts = T_COLLAR / 2 + self.rbs.a + self.rbs.b / 2     # Eq. 10.8-5
        else:
            self.s_f = T_COLLAR + b.d / 2          # Eq. 10.8-14
            self.s_h = dc_half + T_COLLAR + b.d / 2  # Eq. 10.8-16
            self.s_bolts = T_COLLAR / 2 + b.d / 2     # Eq. 10.8-6

        print(f"  s_h = {self.s_h:.2f} in (column CL to plastic hinge)")
        print(f"  s_f = {self.s_f:.2f} in (column face to plastic hinge)")
        print(f"  s_bolts = {self.s_bolts:.2f} in (hinge to bolt centroid)")
        print()

    # ---------- Step 2: V_h ----------
    def step2_Vh(self):
        self.subsection("STEP 2: SHEAR FORCE AT PLASTIC HINGE (EQ. 10.8-1)")
        pm = self.params
        ld = self.loads

        Lh = pm.L - 2 * self.s_h
        gravity = ld.gravity_combination

        # Eq. 10.8-1: V_h = 2*M_pr/L_h + V_gravity
        self.V_h = 2 * self.M_pr / Lh + gravity / 2

        print(f"  L_h = L - 2*s_h = {pm.L:.0f} - 2*{self.s_h:.2f} = {Lh:.1f} in")
        print(f"  Gravity (1.2D + {ld.f1}L + 0.2S) = {gravity:.2f} kips")
        print(f"  V_h = 2*M_pr/L_h + gravity/2  (Eq. 10.8-1)")
        print(f"  V_h = 2*{self.M_pr:.0f}/{Lh:.1f} + {gravity:.2f}/2 = {self.V_h:.1f} kips")
        print()

    # ---------- Step 3: column-beam ----------
    def step3_column_beam(self):
        self.subsection("STEP 3: COLUMN-BEAM MOMENT RATIO (EQ. 10.8-2, 10.8-3)")
        pm = self.params
        c = self.column
        st = pm.system_type

        if st == "IMF":
            print("  IMF: Column-beam ratio per AISC Seismic Provisions")
            print("  (May not require strong-column/weak-beam check)")
            self.checks["column_beam"] = True
            print()
            return

        # M_v = V_h * s_h (additional moment from shear on lever arm)
        M_v = self.V_h * self.s_h
        # Sum M_pb* about one axis (one beam each side = 2 beams)
        n_beams = 2  # beams framing into column about one axis
        Sum_Mpb = n_beams * (self.M_pr + M_v)

        print(f"  SMF biaxial strong-column/weak-beam check:")
        print(f"  M_v = V_h * s_h = {self.V_h:.1f} * {self.s_h:.2f} = {M_v:.0f} kip-in")
        print(f"  Sum M_pb* = {n_beams}*(M_pr + M_v) = {n_beams}*({self.M_pr:.0f} + {M_v:.0f})")
        print(f"            = {Sum_Mpb:.0f} kip-in (about one axis)")

        # Eq. 10.8-3: M_pc* for equal properties about both axes (square section)
        Pu = pm.Pu
        As = c.As
        Ac = c.Ac
        Fyc = c.Fy
        fc = c.fc
        Zc = c.Zc

        denom = As * Fyc + 0.85 * Ac * fc
        if denom == 0:
            Mpc_star = 0
        else:
            Mpc_star = max(0, 0.67 * Zc * Fyc * (1 - Pu / denom))

        print(f"\n  Eq. 10.8-3: M_pc* = 0.67*Zc*Fy*(1 - Pu/(As*Fy + 0.85*Ac*f'c))")
        print(f"  Zc = {Zc:.1f} in^3 | Fy = {Fyc} ksi")
        print(f"  As = {As:.2f} in^2 | Ac = {Ac:.1f} in^2 | f'c = {fc} ksi")
        print(f"  Pu = {Pu:.1f} kips")
        print(f"  M_pc* = 0.67*{Zc:.1f}*{Fyc}*(1 - {Pu:.1f}/({As*Fyc:.1f} + {0.85*Ac*fc:.1f}))")
        print(f"  M_pc* = {Mpc_star:.0f} kip-in")

        # Eq. 10.8-2: Sum M_pc* = M_pcu* + M_pcl* + (Sum M_pb*)/(Hu+Hl) * d
        # d = beam depth (panel zone height ≈ beam depth d, per Commentary C-10.8)
        Hu = pm.story_above
        Hl = pm.story_below
        d_beam = self.beam.d  # beam depth, NOT column width

        # Assume M_pcu* = M_pcl* = Mpc_star (same column above and below)
        Sum_Mpc = 2 * Mpc_star + Sum_Mpb / (Hu + Hl) * d_beam

        print(f"\n  Eq. 10.8-2: Sum M_pc* = M_pcu* + M_pcl* + Sum M_pb*/(Hu+Hl)*d")
        print(f"  Hu = {Hu:.0f} in | Hl = {Hl:.0f} in | d (beam) = {d_beam:.1f} in")
        print(f"  Sum M_pc* = 2*{Mpc_star:.0f} + {Sum_Mpb:.0f}/({Hu:.0f}+{Hl:.0f})*{d_beam:.1f}")
        print(f"  Sum M_pc* = {Sum_Mpc:.0f} kip-in")

        ratio = Sum_Mpc / Sum_Mpb if Sum_Mpb > 0 else 999
        passed = ratio >= 1.0
        print(f"\n  Ratio Sum M_pc* / Sum M_pb* = {ratio:.3f}")
        if not passed:
            print(f"  FAIL - Consider RBS cutouts or heavier column")
        else:
            print(f"  OK")
        print(f"  Note: Simplified (same column above/below, {n_beams} beams about one axis)")
        print(f"  For final design, check both axes per AISC 341 E3.6c.")
        self.checks["column_beam"] = passed
        print()

    # ---------- Step 4: M_bolts ----------
    def step4_Mbolts(self):
        self.subsection("STEP 4: MOMENT AT COLLAR BOLTS (EQ. 10.8-4)")

        # Eq. 10.8-4: M_bolts = M_pr + V_h * s_bolts
        self.M_bolts = self.M_pr + self.V_h * self.s_bolts

        if self.use_rbs:
            print(f"  s_bolts = t_collar/2 + a + b/2 = {T_COLLAR:.3f}/2 + {self.rbs.a:.2f} + {self.rbs.b:.2f}/2")
        else:
            print(f"  s_bolts = t_collar/2 + d/2 = {T_COLLAR:.3f}/2 + {self.beam.d:.2f}/2")
        print(f"  s_bolts = {self.s_bolts:.2f} in")
        print(f"  M_bolts = M_pr + V_h * s_bolts  (Eq. 10.8-4)")
        print(f"  M_bolts = {self.M_pr:.0f} + {self.V_h:.1f} * {self.s_bolts:.2f}")
        print(f"  M_bolts = {self.M_bolts:.0f} kip-in ({self.M_bolts/12:.1f} kip-ft)")
        print()

    # ---------- Step 5: collar bolt tension ----------
    def step5_bolt_tension(self):
        self.subsection("STEP 5: COLLAR BOLT TENSILE STRENGTH (EQ. 10.8-7, 10.8-8)")
        b = self.beam

        # Eq. 10.8-8: r_ut = M_bolts / (n_cf * d * sin45) = 0.177 * M_bolts / d
        self.r_ut = self.M_bolts / (N_CF * b.d * math.sin(math.radians(45)))
        r_ut_check = 0.177 * self.M_bolts / b.d

        print(f"  r_ut = M_bolts / (n_cf * d * sin45)  (Eq. 10.8-8)")
        print(f"  r_ut = {self.M_bolts:.0f} / ({N_CF} * {b.d:.2f} * sin45)")
        print(f"  r_ut = {self.r_ut:.1f} kips (= 0.177*{self.M_bolts:.0f}/{b.d:.2f} = {r_ut_check:.1f})")

        # Eq. 10.8-7: r_ut / (phi_d * R_pt) = r_ut / 102 <= 1.0
        ratio = self.r_ut / TB
        print(f"\n  r_ut / (phi_d * R_pt) = {self.r_ut:.1f} / {TB:.0f} = {ratio:.3f}  (Eq. 10.8-7)")
        print(f"  phi_d = {PHI_D} | R_pt = {TB:.0f} kips (min bolt pretension)")
        print(f"  Bolt: {DB_COLLAR:.3f}-in dia ASTM A574 (pretensioned as A490)")

        passed = ratio <= 1.0
        print(f"  {'OK' if passed else 'FAIL'} (Utilization: {ratio:.3f})")
        self.checks["bolt_tension"] = passed
        print()

    # ---------- Step 6: slip-critical bolt shear ----------
    def step6_bolt_shear(self):
        self.subsection("STEP 6: COLLAR BOLT SLIP-CRITICAL SHEAR CHECK")

        # V_bolts = V_h + additional gravity between hinge and collar center
        # Simplified: V_bolts ~ V_h (gravity on short segment is small)
        gravity = self.loads.gravity_combination
        V_bolts = self.V_h

        # Slip-critical resistance per AISC 360 J3.8 and Commentary C-10.8 Steps 6-7
        # Commentary: "machined surfaces are classified as a Class B surface"
        # φ = 0.85 (for oversized holes per AISC 360), μ = 0.50 (Class B)
        # 16 bolts per beam end (8 top collar flange + 8 bottom collar flange)
        MU_CLASS_B = 0.50    # Class B: unpainted blast-cleaned steel surfaces
        phi_sc = 0.85        # per Commentary C-10.8
        n_bolts_total = 16   # 8 per collar flange x 2 (top + bottom)

        Rn_per_bolt = MU_CLASS_B * DU * TB  # 0.50 * 1.13 * 102 = 57.6 kips
        phi_Rn_per_bolt = phi_sc * Rn_per_bolt  # 0.85 * 57.6 = 49.0 kips/bolt
        Rn_total = n_bolts_total * phi_Rn_per_bolt  # 16 * 49.0 = 784 kips

        print(f"  V_bolts ~ V_h = {V_bolts:.1f} kips (simplified, gravity on short segment neglected)")
        print(f"  Slip-critical resistance (Class B, oversized holes, per Commentary C-10.8):")
        print(f"    R_n/bolt = mu * D_u * T_b = {MU_CLASS_B} * {DU} * {TB:.0f} = {Rn_per_bolt:.1f} kips")
        print(f"    phi*R_n/bolt = {phi_sc} * {Rn_per_bolt:.1f} = {phi_Rn_per_bolt:.1f} kips/bolt")
        print(f"    phi*R_n(total) = {n_bolts_total} bolts * {phi_Rn_per_bolt:.1f} = {Rn_total:.1f} kips")
        print(f"    Note: 16 bolts = 8 (top CFT) + 8 (bottom CFB) per Commentary")

        passed = V_bolts <= Rn_total
        print(f"  {'OK' if passed else 'FAIL'} (Utilization: {V_bolts/Rn_total:.3f})")
        self.checks["bolt_shear"] = passed
        print()

    # ---------- Step 7: beam shear ----------
    def step7_beam_shear(self):
        self.subsection("STEP 7: BEAM SHEAR STRENGTH CHECK")

        # V_cf = V_h + gravity between hinge and collar face (simplified as V_h)
        V_cf = self.V_h
        Vu = max(V_cf, self.loads.Vu)

        b = self.beam
        Vn = 0.6 * b.Fy * b.d * b.tw
        phi_Vn = PHI_V * Vn  # phi_v = 1.0 for rolled W-shapes per AISC 360 G2.1(a)

        print(f"  V_cf ~ V_h = {V_cf:.1f} kips")
        print(f"  V_u = max(V_cf, Vu_user) = max({V_cf:.1f}, {self.loads.Vu:.2f}) = {Vu:.1f} kips")
        print(f"  V_n = 0.6*Fy*d*tw = 0.6*{b.Fy}*{b.d:.2f}*{b.tw:.3f} = {Vn:.1f} kips")
        print(f"  phi*V_n = {phi_Vn:.1f} kips")

        passed = Vu <= phi_Vn
        print(f"  {'OK' if passed else 'FAIL'} (Utilization: {Vu/phi_Vn:.3f})")
        self.checks["beam_shear"] = passed
        print()

    # ---------- Step 8: CWX fillet weld ----------
    def step8_CWX_weld(self):
        self.subsection("STEP 8: BEAM WEB-TO-CWX FILLET WELD (EQ. 10.8-9)")
        b = self.beam
        group = b.depth_group

        if group not in BEAM_GROUPS:
            print(f"  ERROR: Beam group '{group}' not in prequalified list")
            self.checks["CWX_weld"] = False
            print()
            return

        lw_CWX = BEAM_GROUPS[group]["lw_CWX"]
        V_cf = self.V_h
        Fw = 0.60 * self.FEXX

        # Eq. 10.8-9: tf_CWX >= sqrt(2) * V_cf / (phi_n * Fw * lw_CWX)
        tf_req = math.sqrt(2) * V_cf / (PHI_N * Fw * lw_CWX)

        print(f"  Beam group: {group} | l_w^CWX = {lw_CWX:.0f} in")
        print(f"  F_w = 0.60 * F_EXX = 0.60 * {self.FEXX} = {Fw:.1f} ksi")
        print(f"  V_cf = {V_cf:.1f} kips")
        print(f"  t_f^CWX >= sqrt(2)*V_cf / (phi_n*Fw*l_w^CWX)  (Eq. 10.8-9)")
        print(f"  t_f^CWX >= {math.sqrt(2):.3f}*{V_cf:.1f} / ({PHI_N}*{Fw:.1f}*{lw_CWX:.0f})")
        print(f"  t_f^CWX >= {tf_req:.4f} in")

        # Minimum practical weld size
        if b.tw <= 0.25:
            w_min = 0.125
        elif b.tw <= 0.375:
            w_min = 0.15625  # 5/32
        else:
            w_min = 0.1875  # 3/16

        print(f"  Recommended fillet weld size: {max(tf_req, w_min):.3f} in (each side)")
        print(f"  Note: Two-sided fillet weld to CWX per Section 10.5.2")

        # The check passes if a reasonable weld can be made
        max_weld = 0.5 * b.tw  # Practical upper limit
        if tf_req <= max_weld:
            print(f"  OK (required {tf_req:.3f} <= max practical {max_weld:.3f} in)")
            self.checks["CWX_weld"] = True
        else:
            print(f"  FAIL (required {tf_req:.3f} > max practical {max_weld:.3f} in)")
            self.checks["CWX_weld"] = False
        print()

    # ---------- Step 9: collar corner weld ----------
    def step9_CC_weld(self):
        self.subsection("STEP 9: COLLAR CORNER-TO-COLUMN FILLET WELD (EQ. 10.8-10)")
        b = self.beam
        c = self.column
        group = b.depth_group

        if group not in BEAM_GROUPS:
            print(f"  ERROR: Beam group '{group}' not in prequalified list")
            self.checks["CC_weld"] = False
            print()
            return

        lw_CC = BEAM_GROUPS[group]["lw_CC"]
        Fw = 0.60 * self.FEXX

        # V_f = V_h + gravity between hinge and column face
        V_f = self.V_h

        # Eq. 10.8-10: tf_CC >= sqrt(2) * V_f / (phi_n * Fw * lw_CC)
        tf_req = math.sqrt(2) * V_f / (PHI_N * Fw * lw_CC)

        print(f"  Beam group: {group} | l_w^CC = {lw_CC:.0f} in")
        print(f"  F_w = 0.60 * F_EXX = 0.60 * {self.FEXX} = {Fw:.1f} ksi")
        print(f"  V_f ~ V_h = {V_f:.1f} kips")
        print(f"  t_f^CC >= sqrt(2)*V_f / (phi_n*Fw*l_w^CC)  (Eq. 10.8-10)")
        print(f"  t_f^CC >= {math.sqrt(2):.3f}*{V_f:.1f} / ({PHI_N}*{Fw:.1f}*{lw_CC:.0f})")
        print(f"  t_f^CC >= {tf_req:.4f} in")
        print(f"  Note: Flare bevel groove weld with 3/8-in fillet reinforcing per Section 10.4(4)")

        self.checks["CC_weld"] = True  # Prescriptive detail
        print()

    # ---------- Step 10: panel zone demand ----------
    def step10_panel_zone_demand(self):
        self.subsection("STEP 10: PANEL ZONE DEMAND (EQ. 10.8-11)")
        pm = self.params
        c = self.column
        b = self.beam

        Hu = pm.story_above
        Hl = pm.story_below
        H = (Hu + Hl) / 2  # Eq. 10.8-17

        # V_col = Sum(M_pr + V_h * s_h) / H  (Eq. 10.8-12)
        # For 2 beams about one axis:
        n_beams = 2
        Sum_Mp_sh = n_beams * (self.M_pr + self.V_h * self.s_h)
        V_col = Sum_Mp_sh / H

        # R_n^pz = Sum(M_pr + V_h * s_f) / d - V_col  (Eq. 10.8-11)
        Sum_Mp_sf = n_beams * (self.M_pr + self.V_h * self.s_f)
        Rn_pz = Sum_Mp_sf / b.d - V_col

        print(f"  H = (Hu + Hl)/2 = ({Hu:.0f} + {Hl:.0f})/2 = {H:.1f} in  (Eq. 10.8-17)")
        print(f"  Sum(M_pr + V_h*s_h) = {n_beams}*({self.M_pr:.0f} + {self.V_h:.1f}*{self.s_h:.2f})")
        print(f"                       = {Sum_Mp_sh:.0f} kip-in")
        print(f"  V_col = Sum(M_pr + V_h*s_h)/H = {Sum_Mp_sh:.0f}/{H:.1f} = {V_col:.1f} kips  (Eq. 10.8-12)")
        print()
        print(f"  Sum(M_pr + V_h*s_f) = {n_beams}*({self.M_pr:.0f} + {self.V_h:.1f}*{self.s_f:.2f})")
        print(f"                       = {Sum_Mp_sf:.0f} kip-in")
        print(f"  R_n^pz = Sum(M_pr + V_h*s_f)/d - V_col  (Eq. 10.8-11)")
        print(f"  R_n^pz = {Sum_Mp_sf:.0f}/{b.d:.2f} - {V_col:.1f} = {Rn_pz:.1f} kips")

        self.Rn_pz_demand = Rn_pz
        print()

    # ---------- Step 11: panel zone capacity ----------
    def step11_panel_zone_capacity(self):
        self.subsection("STEP 11: PANEL ZONE CAPACITY (EQ. 10.8-18, 10.8-19)")
        c = self.column

        # Eq. 10.8-19: A_pz = 2*dc*tcol + 4*(d_leg_CC * t_leg_CC)
        A_pz = 2 * c.D * c.t_col + 4 * (D_LEG_CC * c.t_leg_CC)

        # Eq. 10.8-18: phi*R_n^pz = phi_d * 0.6 * Fy * A_pz
        phi_Rn_pz = PHI_D * 0.6 * c.Fy * A_pz

        print(f"  A_pz = 2*dc*tcol + 4*(d_leg_CC * t_leg_CC)  (Eq. 10.8-19)")
        print(f"  A_pz = 2*{c.D:.1f}*{c.t_col:.3f} + 4*({D_LEG_CC:.1f}*{c.t_leg_CC:.3f})")
        print(f"  A_pz = {2*c.D*c.t_col:.2f} + {4*D_LEG_CC*c.t_leg_CC:.2f} = {A_pz:.2f} in^2")
        print()
        print(f"  phi*R_n^pz = phi_d * 0.6 * Fy * A_pz  (Eq. 10.8-18)")
        print(f"  phi*R_n^pz = {PHI_D} * 0.6 * {c.Fy} * {A_pz:.2f}")
        print(f"  phi*R_n^pz = {phi_Rn_pz:.1f} kips")
        print()
        print(f"  Demand R_n^pz = {self.Rn_pz_demand:.1f} kips")

        passed = self.Rn_pz_demand <= phi_Rn_pz
        if not passed:
            print(f"  FAIL - Increase column wall thickness or reduce beam (Utilization: {self.Rn_pz_demand/phi_Rn_pz:.3f})")
        else:
            print(f"  OK (Utilization: {self.Rn_pz_demand/phi_Rn_pz:.3f})")
        self.checks["panel_zone"] = passed
        print()

    # ---------- summary ----------
    def print_summary(self):
        self.section("DESIGN VERIFICATION SUMMARY")

        def s(k):
            return "PASS" if self.checks.get(k) else "FAIL"

        print(f"Prequalification: {s('prequalification')}")
        print(f"Column-beam ratio: {s('column_beam')}")
        print(f"Bolt tension (Step 5): {s('bolt_tension')}")
        print(f"Bolt shear/slip (Step 6): {s('bolt_shear')}")
        print(f"Beam shear (Step 7): {s('beam_shear')}")
        print(f"CWX weld (Step 8): {s('CWX_weld')}")
        print(f"CC weld (Step 9): {s('CC_weld')}")
        print(f"Panel zone (Steps 10-11): {s('panel_zone')}")
        print()
        rbs_str = " (RBS)" if self.use_rbs else " (non-RBS)"
        print(f"KEY: M_pr={self.M_pr:.0f} kip-in | V_h={self.V_h:.1f} kips | C_pr={self.params.C_pr:.3f}{rbs_str}")
        print(f"     M_bolts={self.M_bolts:.0f} kip-in | r_ut={self.r_ut:.1f} kips")
        print(f"     s_h={self.s_h:.2f} | s_f={self.s_f:.2f} | s_bolts={self.s_bolts:.2f}")
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


# ====================== COMMAND LINE ======================

def parse_args():
    parser = argparse.ArgumentParser(
        description="ConXL Connection Design Verification (AISC 358-16 Chapter 10)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python conxl_design.py --beam-section W24x68 --column-wall 0.5 --span 300 --system-type SMF
  python conxl_design.py --beam-section W24x68 --column-wall 0.625 --span 360 --system-type SMF \
      --rbs --rbs-a 5 --rbs-b 18 --rbs-c 1.5
  python conxl_design.py --beam-section W21x57 --column-wall 0.5 --span 240 --system-type IMF \
      --load-D 15 --load-L 20
        """
    )

    if "--list-sections" in sys.argv:
        sections = load_sections_from_csv()
        print("Available W-shape sections (ConXL prequalified: W18, W21, W24, W27, W30):")
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

    cg = parser.add_argument_group("Column (16-in square HSS/box)")
    cg.add_argument("--column-wall", type=float, required=True,
                    help="Column wall thickness t_col (in), min 0.375")
    cg.add_argument("--column-Fy", type=float, default=DEFAULT_FY_COL,
                    help=f"Column steel Fy (ksi, default: {DEFAULT_FY_COL})")
    cg.add_argument("--column-Fu", type=float, default=DEFAULT_FU_COL)
    cg.add_argument("--fc", type=float, default=DEFAULT_FC,
                    help=f"Concrete f'c (ksi, default: {DEFAULT_FC})")
    cg.add_argument("--concrete-weight", type=float, default=145.0,
                    help="Concrete unit weight (pcf, min 110, default: 145)")
    cg.add_argument("--t-leg-CC", type=float, default=0.75,
                    help="Effective collar corner leg thickness t_leg_CC (in, default: 0.75)")

    dg = parser.add_argument_group("Design")
    dg.add_argument("--span", type=float, required=True)
    dg.add_argument("--system-type", type=str, required=True, choices=["SMF", "IMF"])
    dg.add_argument("--story-above", type=float, default=156.0,
                    help="Story height above node (in, default: 156)")
    dg.add_argument("--story-below", type=float, default=156.0,
                    help="Story height below node (in, default: 156)")
    dg.add_argument("--Pu", type=float, default=0.0,
                    help="Axial load on column (kips, not amplified)")
    dg.add_argument("--FEXX", type=float, default=DEFAULT_FEXX,
                    help=f"Weld electrode strength (ksi, default: {DEFAULT_FEXX})")

    rg = parser.add_argument_group("RBS (optional)")
    rg.add_argument("--rbs", action="store_true",
                    help="Use RBS beam cutout")
    rg.add_argument("--rbs-a", type=float, default=0.0,
                    help="RBS: distance from collar face to start of cut (in)")
    rg.add_argument("--rbs-b", type=float, default=0.0,
                    help="RBS: length of cut (in)")
    rg.add_argument("--rbs-c", type=float, default=0.0,
                    help="RBS: depth of cut at center (in)")

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

        column = ColumnBox(
            D=DCOL, t_col=args.column_wall,
            Fy=args.column_Fy, Fu=args.column_Fu,
            fc=args.fc, concrete_weight=args.concrete_weight,
            t_leg_CC=args.t_leg_CC,
        )

        rbs = None
        if args.rbs:
            if not (args.rbs_a and args.rbs_b and args.rbs_c):
                raise ValueError("RBS requires --rbs-a, --rbs-b, and --rbs-c")
            rbs = RBSGeometry(a=args.rbs_a, b=args.rbs_b, c=args.rbs_c)

        # Calculate L_h
        dc_half = column.D / 2
        if rbs:
            s_h = dc_half + T_COLLAR + rbs.a + rbs.b / 2
        else:
            s_h = dc_half + T_COLLAR + beam.d / 2
        Lh = args.span - 2 * s_h

        loads = Loads(D=args.load_D, L=args.load_L, S=args.load_S,
                      f1=args.load_f1, Vu=args.Vu)

        params = DesignParameters(
            L=args.span, Lh=Lh, system_type=args.system_type,
            story_above=args.story_above, story_below=args.story_below,
            Pu=args.Pu,
        )

        checker = ConXLDesignChecker(beam, column, params, loads,
                                      rbs=rbs, FEXX=args.FEXX)
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
