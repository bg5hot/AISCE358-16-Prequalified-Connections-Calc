#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Double-Tee Moment Connection Design Verification
Based on AISC 358-16 Chapter 13, Section 13.6 - Design Procedure

Double-tee connections use T-stub components bolted to both the column flange
(tension bolts) and beam flanges (shear bolts). The top and bottom T-stubs are
identical, cut from rolled W-shapes. A single-plate shear connection transfers
beam web shear to the column.

Key characteristics:
  - T-stubs cut from rolled W-shapes (ASTM A992 or A913 Grade 50)
  - Tension bolts: 4 or 8 per T-stub flange (ASTM F3125 A325/A490)
  - Shear bolts: 2 per row, pretensioned, slip-critical faying surfaces
  - Plastic hinge forms at shear bolts farthest from column face
  - FR (fully restrained) connection - stiffness check required (Step 13)
  - Continuity plates required at all column locations
  - g_tb/t_ft <= 7.0 (tension bolt gage to flange thickness ratio)

Usage:
    # Basic 4-bolt tension configuration
    python doubletee_design.py --beam-section W21x44 --column-section W14x145 \
        --span 300 --system-type SMF

    # 8-bolt tension configuration
    python doubletee_design.py --beam-section W24x55 --column-section W14x193 \
        --span 360 --system-type SMF --tension-bolts 8

    # With gravity loads
    python doubletee_design.py --beam-section W21x44 --column-section W14x145 \
        --span 300 --system-type SMF --load-D 10 --load-L 20
"""

import argparse
import sys
import io
import os
import csv
import math
from dataclasses import dataclass
from typing import Optional, Dict

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ====================== CONSTANTS ======================
PHI_D = 1.00   # Ductile limit states
PHI_N = 0.90   # Nonductile limit states
PHI_V = 0.90   # Shear

DEFAULT_FY_BEAM = 50.0    # ksi (A992)
DEFAULT_FU_BEAM = 65.0    # ksi
DEFAULT_FY_COL = 50.0     # ksi
DEFAULT_FY_T = 50.0       # ksi (A992/A913 Gr 50 for T-stub)
DEFAULT_FU_T = 65.0       # ksi

# T-stub material Ry/Rt (A992)
RY_T = 1.1
RT_T = 1.1

# Beam prequalification limits (Section 13.3.1)
BEAM_MAX_DEPTH = 24.0     # W24 max
BEAM_MAX_WEIGHT = 55.0    # plf
BEAM_MAX_TF = 0.625       # 5/8 in (15 mm)
BEAM_MIN_SPAN_DEPTH = 9.0

# Column prequalification limits (Section 13.3.2)
COL_MAX_DEPTH_SLAB = 36.0  # W36 with concrete slab
COL_MAX_DEPTH_NO_SLAB = 14.0  # W14 without slab

# Bolt properties
# A325: Fnt = 90 ksi, Fnv = 54 ksi (threads excluded)
# A490: Fnt = 113 ksi, Fnv = 68 ksi (threads excluded)
FNT_A325 = 90.0
FNV_A325 = 54.0
FNT_A490 = 113.0
FNV_A490 = 68.0

# Slip coefficient
MU_CLASS_A = 0.30
DELTA_SLIP = 0.0076  # in (Eq. 13.6-39)

# Steel properties
E = 29000.0   # ksi
G = 11200.0   # ksi (shear modulus)

# Standard bolt diameters (in)
STANDARD_BOLT_DIAMETERS = [0.625, 0.75, 0.875, 1.0, 1.125, 1.25, 1.375, 1.5]


# ====================== DATA CLASSES ======================

@dataclass
class Section:
    designation: str
    d: float
    bf: float
    tf: float
    tw: float
    Zx: float
    Fy: float = DEFAULT_FY_BEAM
    Fu: float = DEFAULT_FU_BEAM
    Ry: float = 1.1
    Rt: float = 1.1

    @property
    def weight(self) -> float:
        try:
            return float(self.designation.upper().split('X')[1])
        except (ValueError, IndexError):
            return 999

    @property
    def Ix(self) -> float:
        # Approximate from Zx: Ix ~ Zx * d / 2 * 0.9
        return self.Zx * (self.d / 2) * 0.9


@dataclass
class Loads:
    D: float = 0.0
    L: float = 0.0
    S: float = 0.0
    f1: float = 0.5

    @property
    def gravity_combination(self) -> float:
        return 1.2 * self.D + self.f1 * self.L + 0.2 * self.S


@dataclass
class DesignParameters:
    L: float
    system_type: str
    n_tb: int = 4           # number of tension bolts (4 or 8)
    S1: float = 3.0         # distance column face to first shear bolt row (in)
    s_vb: float = 3.0       # shear bolt spacing (in)
    g_vb: float = 3.5       # shear bolt gage in T-stem (in)
    g_tb: float = 5.5       # tension bolt gage in T-flange (in)
    bolt_type: str = "A325"  # A325 or A490
    has_slab: bool = False   # concrete slab present (affects column depth limit)
    story_above: float = 156.0  # story height above (in)
    story_below: float = 156.0  # story height below (in)
    Pu: float = 0.0         # column axial load (kips)
    As_col: float = 0.0     # column cross-section area (in^2)


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


def create_section(args, prefix, defaults) -> Section:
    """Create a Section from CLI args with given prefix (beam/col)."""
    section_arg = getattr(args, f'{prefix}_section', None)
    if section_arg:
        props = get_section_properties(section_arg)
        if props:
            return Section(
                designation=props["designation"],
                d=getattr(args, f'{prefix}_d', None) or props["d"],
                bf=getattr(args, f'{prefix}_bf', None) or props["bf"],
                tf=getattr(args, f'{prefix}_tf', None) or props["tf"],
                tw=getattr(args, f'{prefix}_tw', None) or props["tw"],
                Zx=getattr(args, f'{prefix}_Zx', None) or props["Zx"],
                Fy=defaults.get('Fy', 50.0),
                Fu=defaults.get('Fu', 65.0),
            )
    if all([getattr(args, f'{prefix}_{p}', None) for p in ['d', 'bf', 'tf', 'tw', 'Zx']]):
        return Section(
            designation="Custom",
            d=getattr(args, f'{prefix}_d'),
            bf=getattr(args, f'{prefix}_bf'),
            tf=getattr(args, f'{prefix}_tf'),
            tw=getattr(args, f'{prefix}_tw'),
            Zx=getattr(args, f'{prefix}_Zx'),
            Fy=defaults.get('Fy', 50.0),
            Fu=defaults.get('Fu', 65.0),
        )
    raise ValueError(f"Invalid {prefix} section. "
                     f"Use --{prefix}-section or provide all dimensions.")


# ====================== DESIGN CHECKER ======================

class DoubleTeeDesignChecker:
    """Double-Tee Connection Design per AISC 358-16 Section 13.6 (23 steps)"""

    def __init__(self, beam: Section, column: Section,
                 params: DesignParameters, loads: Loads):
        self.beam = beam
        self.column = column
        self.params = params
        self.loads = loads
        self.checks: dict = {}

        # Computed values
        self.M_pr = 0.0
        self.V_h = 0.0
        self.S_h = 0.0
        self.M_f = 0.0
        self.F_pr = 0.0
        self.F_f = 0.0
        self.n_vb = 0
        self.d_vb = 0.0
        self.d_tb = 0.0
        self.t_st = 0.0
        self.t_ft = 0.0
        self.b_ft = 0.0
        self.W_T = 0.0
        self.W_Whit = 0.0

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
        self.section("DOUBLE-TEE CONNECTION DESIGN VERIFICATION "
                     "(AISC 358-16 CHAPTER 13)")
        print()
        self.print_input()

        self.step0_prequalification()
        self.section("DESIGN PROCEDURE (SECTION 13.6)")

        self.step1_Mpr()
        self.step2_shear_bolt_diameter()
        self.step3_bolt_strength()
        self.step4_shear_bolt_count()
        self.step5_hinge_location()
        self.step6_shear_at_hinge()
        self.step6a_beam_shear()
        self.step7_column_face_moment()
        self.step7a_column_beam()
        self.step8_Tstub_force()
        self.step9_Tstem_size()
        self.step10_tension_bolt_size()
        self.step11_Tflange_config()
        self.step12_select_Tstub()
        self.step13_stiffness_check()
        self.step14_actual_flange_force()
        self.step15_backcheck_shear_bolts()
        self.step16_backcheck_Tstem()
        self.step17_backcheck_Tflange()
        self.step18_bearing_tearout()
        self.step19_block_shear()
        self.step20_shear_connection()
        self.step21_column_flange()
        self.step22_column_web()
        self.step23_continuity_plates()

        self.print_summary()
        return all(v for v in self.checks.values() if v is not None)

    # ---------- Input ----------
    def print_input(self):
        self.section("INPUT PARAMETERS")
        b, c, pm, ld = self.beam, self.column, self.params, self.loads
        print(f"BEAM: {b.designation} | d={b.d:.2f} bf={b.bf:.2f} "
              f"tf={b.tf:.3f} tw={b.tw:.3f} Zx={b.Zx:.1f}")
        print(f"      Fy={b.Fy} Fu={b.Fu} Ry={b.Ry} Rt={b.Rt}")
        print(f"COLUMN: {c.designation} | d={c.d:.2f} bf={c.bf:.2f} "
              f"tf={c.tf:.3f} tw={c.tw:.3f} Zx={c.Zx:.1f}")
        print(f"        Fy={c.Fy} Fu={c.Fu}")
        print(f"TENSION BOLTS: {pm.n_tb} | BOLT TYPE: {pm.bolt_type}")
        print(f"GEOMETRY: S1={pm.S1} s_vb={pm.s_vb} "
              f"g_vb={pm.g_vb} g_tb={pm.g_tb}")
        print(f"SPAN: L={pm.L:.0f} in ({pm.L/12:.1f} ft) | {pm.system_type}")
        slab_str = "with slab" if pm.has_slab else "no slab"
        print(f"STORY: H_above={pm.story_above:.0f} in | H_below={pm.story_below:.0f} in | "
              f"Pu={pm.Pu:.0f} kips | {slab_str}")
        print(f"LOADS: D={ld.D} L={ld.L} S={ld.S} | "
              f"Gravity={ld.gravity_combination:.2f} kips")
        print()

    # ---------- Step 0: Prequalification ----------
    def step0_prequalification(self):
        self.subsection("PREQUALIFICATION LIMITS (SECTION 13.3)")
        passed = True
        b = self.beam
        c = self.column
        pm = self.params
        st = pm.system_type

        # Beam depth <= W24
        print(f"  Beam depth: d = {b.d:.2f} in <= {BEAM_MAX_DEPTH:.0f}: ", end="")
        if b.d > BEAM_MAX_DEPTH:
            print("FAIL"); passed = False
        else:
            print("OK")

        # Beam weight <= 55 plf
        print(f"  Beam weight: {b.weight:.0f} plf <= {BEAM_MAX_WEIGHT:.0f}: ", end="")
        if b.weight > BEAM_MAX_WEIGHT:
            print("FAIL"); passed = False
        else:
            print("OK")

        # Beam flange thickness <= 5/8 in
        print(f"  Beam tf: {b.tf:.3f} in <= {BEAM_MAX_TF:.3f}: ", end="")
        if b.tf > BEAM_MAX_TF:
            print("FAIL"); passed = False
        else:
            print("OK")

        # Span/depth >= 9
        sd = self.params.L / b.d
        print(f"  Span/depth: L/d = {sd:.1f} >= {BEAM_MIN_SPAN_DEPTH:.0f}: ", end="")
        if sd < BEAM_MIN_SPAN_DEPTH:
            print("FAIL"); passed = False
        else:
            print("OK")

        # Column depth
        col_max = COL_MAX_DEPTH_SLAB if pm.has_slab else COL_MAX_DEPTH_NO_SLAB
        slab_str = "with slab" if pm.has_slab else "no slab"
        print(f"  Column depth: d = {c.d:.2f} in <= {col_max:.0f} ({slab_str}): ", end="")
        if c.d > col_max:
            print("FAIL"); passed = False
        else:
            print("OK")

        self.checks["prequalification"] = passed
        print()

    # ---------- Step 1: M_pr ----------
    def step1_Mpr(self):
        self.subsection("STEP 1: PROBABLE MAXIMUM MOMENT (EQ. 13.6-1)")
        b = self.beam
        # C_pr per Section 2.4.3
        C_pr = min((b.Fy + b.Fu) / (2 * b.Fy), 1.2)
        self.M_pr = C_pr * b.Ry * b.Fy * b.Zx

        print(f"  C_pr = min((Fy+Fu)/(2*Fy), 1.2)")
        print(f"  C_pr = min(({b.Fy}+{b.Fu})/(2*{b.Fy}), 1.2) = {C_pr:.3f}")
        print(f"  M_pr = C_pr * Ry * Fy * Zx  (Eq. 13.6-1)")
        print(f"  M_pr = {C_pr:.3f} * {b.Ry} * {b.Fy} * {b.Zx:.1f}")
        print(f"  M_pr = {self.M_pr:.0f} kip-in ({self.M_pr/12:.1f} kip-ft)")
        print()

    # ---------- Step 2: Shear bolt diameter ----------
    def step2_shear_bolt_diameter(self):
        self.subsection("STEP 2: MAXIMUM SHEAR BOLT DIAMETER (EQ. 13.6-3)")
        b = self.beam
        # Eq. 13.6-3
        dvb_max = (b.Zx / (2 * b.tf * (b.d - b.tf))) * \
                  (1 - b.Ry * b.Fy / (b.Rt * b.Fu)) - 0.125

        print(f"  d_vb <= (Zx/(2*tf*(d-tf)))*(1 - Ry*Fy/(Rt*Fu)) - 1/8")
        print(f"  d_vb <= ({b.Zx:.1f}/(2*{b.tf:.3f}*{b.d-b.tf:.3f}))"
              f"*(1 - {b.Ry}*{b.Fy}/({b.Rt}*{b.Fu})) - 0.125")
        print(f"  d_vb <= {dvb_max:.3f} in")

        # Select largest bolt diameter that fits
        self.d_vb = 0.625  # minimum fallback
        for d in reversed(STANDARD_BOLT_DIAMETERS):
            if d <= dvb_max:
                self.d_vb = d
                break

        ok = self.d_vb <= dvb_max
        print(f"  Use d_vb = {self.d_vb:.3f} in (7/8 in A325): "
              f"{'OK' if ok else 'WARNING - may need smaller bolt'}")
        self.checks["bolt_diameter"] = ok
        print()

    # ---------- Step 3: Bolt strength per bolt ----------
    def step3_bolt_strength(self):
        self.subsection("STEP 3: DESIGN SHEAR STRENGTH PER BOLT (EQ. 13.6-4)")
        b = self.beam
        pm = self.params

        Fnv = FNV_A325 if pm.bolt_type == "A325" else FNV_A490
        A_vb = math.pi / 4 * self.d_vb**2

        # T-stub stem thickness estimated (will be finalized in Step 9)
        t_st_est = 0.5  # initial estimate

        # Eq. 13.6-4: three-term minimum
        r_bolt_shear = PHI_N * Fnv * A_vb
        r_beam_bearing = PHI_D * 2.4 * self.d_vb * b.tf * b.Fu
        r_stem_bearing = PHI_D * 2.4 * self.d_vb * t_st_est * DEFAULT_FU_T

        self._phi_rnv = min(r_bolt_shear, r_beam_bearing, r_stem_bearing)
        self._r_bolt_shear = r_bolt_shear
        self._r_beam_bearing = r_beam_bearing

        print(f"  phi*r_nv = min(bolt shear, beam bearing, T-stem bearing)")
        print(f"    Bolt shear: {PHI_N}*{Fnv}*{A_vb:.3f} = {r_bolt_shear:.1f} kips")
        print(f"    Beam bearing: {PHI_D}*2.4*{self.d_vb:.3f}*{b.tf:.3f}"
              f"*{b.Fu} = {r_beam_bearing:.1f} kips")
        print(f"    T-stem bearing (est): {r_stem_bearing:.1f} kips")
        print(f"  phi*r_nv = {self._phi_rnv:.1f} kips/bolt")
        print()

    # ---------- Step 4: Number of shear bolts ----------
    def step4_shear_bolt_count(self):
        self.subsection("STEP 4: NUMBER OF SHEAR BOLTS (EQ. 13.6-5)")
        b = self.beam
        # Eq. 13.6-5
        n_vb_calc = 1.25 * self.M_pr / (b.d * self._phi_rnv)
        # Round up to next even integer
        self.n_vb = math.ceil(n_vb_calc)
        if self.n_vb % 2 != 0:
            self.n_vb += 1

        print(f"  n_vb >= 1.25*M_pr / (d * phi*r_nv)  (Eq. 13.6-5)")
        print(f"  n_vb >= 1.25*{self.M_pr:.0f} / ({b.d:.2f} * {self._phi_rnv:.1f})")
        print(f"  n_vb >= {n_vb_calc:.1f}, use n_vb = {self.n_vb} (even integer)")
        print()

    # ---------- Step 5: Plastic hinge location ----------
    def step5_hinge_location(self):
        self.subsection("STEP 5: PLASTIC HINGE LOCATION (EQ. 13.6-6, 13.6-7)")
        pm = self.params
        # Eq. 13.6-7
        L_vb = pm.s_vb * (self.n_vb / 2 - 1)
        # Eq. 13.6-6
        self.S_h = pm.S1 + L_vb

        print(f"  L_vb = s_vb*(n_vb/2 - 1) = {pm.s_vb}*({self.n_vb}/2 - 1)"
              f" = {L_vb:.2f} in  (Eq. 13.6-7)")
        print(f"  S_h = S1 + L_vb = {pm.S1} + {L_vb:.2f}"
              f" = {self.S_h:.2f} in  (Eq. 13.6-6)")
        print()

    # ---------- Step 6: Shear at hinge ----------
    def step6_shear_at_hinge(self):
        self.subsection("STEP 6: SHEAR AT PLASTIC HINGE")
        pm = self.params
        ld = self.loads
        dc = self.column.d
        L_h = pm.L - 2 * (dc / 2 + self.S_h)
        gravity = ld.gravity_combination

        self.V_h = 2 * self.M_pr / L_h + gravity / 2

        print(f"  L_h = L - 2*(dc/2 + S_h) = {pm.L:.0f} - "
              f"2*({dc/2:.2f}+{self.S_h:.2f}) = {L_h:.1f} in")
        print(f"  V_h = 2*M_pr/L_h + gravity/2")
        print(f"  V_h = 2*{self.M_pr:.0f}/{L_h:.1f} + {gravity:.2f}/2"
              f" = {self.V_h:.1f} kips")
        self._L_h = L_h
        print()

    # ---------- Beam Shear Strength ----------
    def step6a_beam_shear(self):
        self.subsection("BEAM SHEAR STRENGTH CHECK (AISC 360 G2.1)")
        b = self.beam
        Aw = b.d * b.tw
        Cv = 1.0  # assume Cv=1 for typical beam proportions
        V_n = 0.6 * b.Fy * Aw * Cv
        phi_Vn = PHI_V * V_n
        ok = self.V_h <= phi_Vn
        print(f"  V_n = 0.6*Fy*d*tw = 0.6*{b.Fy}*{b.d:.2f}*{b.tw:.3f} = {V_n:.1f} kips")
        print(f"  phi*V_n = {phi_Vn:.1f} kips >= V_h = {self.V_h:.1f}: "
              f"{'OK' if ok else 'FAIL'}")
        self.checks["beam_shear"] = ok
        print()

    # ---------- Step 7: Moment at column face ----------
    def step7_column_face_moment(self):
        self.subsection("STEP 7: MOMENT AT COLUMN FACE (EQ. 13.6-10)")
        # Eq. 13.6-10
        self.M_f = self.M_pr + self.V_h * self.S_h
        print(f"  M_f = M_pr + V_h * S_h  (Eq. 13.6-10)")
        print(f"  M_f = {self.M_pr:.0f} + {self.V_h:.1f} * {self.S_h:.2f}"
              f" = {self.M_f:.0f} kip-in ({self.M_f/12:.1f} kip-ft)")
        print()

    # ---------- Step 7a: Column-Beam Relationship ----------
    def step7a_column_beam(self):
        self.subsection("COLUMN-BEAM RELATIONSHIP (AISC 341 E3.6c)")
        b = self.beam
        c = self.column
        pm = self.params
        st = pm.system_type

        if st == "IMF":
            print("  IMF: Column-beam ratio per AISC Seismic Provisions")
            print("  (Strong-column/weak-beam may not be required for IMF)")
            self.checks["column_beam"] = True
            print()
            return

        # M_uv = V_h * (d_c / 2)  (column shear contribution from beam moment)
        M_uv = self.V_h * (c.d / 2)

        # Sum M_pb* for beams framing into column (2 beams, one each side)
        M_pb_star = self.M_pr + M_uv
        n_beams = 2
        Sum_Mpb = n_beams * M_pb_star

        # Column moment capacity (with axial load effect per AISC 341 E3.6c)
        # M_pc = Z_c * F_yc * (1 - Pu / (As * F_yc))
        As_col = pm.As_col
        if As_col <= 0:
            As_col = c.bf * c.tf * 2 + (c.d - 2 * c.tf) * c.tw  # approximate

        denom = As_col * c.Fy
        if denom > 0 and pm.Pu > 0:
            M_pc = c.Zx * c.Fy * max(0, 1 - pm.Pu / denom)
        else:
            M_pc = c.Zx * c.Fy

        # Two columns (above and below), both contribute
        # Simplified: same column above and below
        Sum_Mpc = 2 * M_pc

        ratio = Sum_Mpc / Sum_Mpb if Sum_Mpb > 0 else 999
        passed = ratio >= 1.0

        print(f"  Strong-Column / Weak-Beam (SMF):")
        print(f"  M_uv = V_h * (d_c/2) = {self.V_h:.1f} * {c.d/2:.2f} = {M_uv:.0f} kip-in")
        print(f"  M_pb* = M_pr + M_uv = {self.M_pr:.0f} + {M_uv:.0f} = {M_pb_star:.0f} kip-in")
        print(f"  Sum M_pb* = {n_beams} * {M_pb_star:.0f} = {Sum_Mpb:.0f} kip-in")
        print(f"  M_pc = Zx_c * Fy_c * (1 - Pu/(As*Fy))")
        print(f"  M_pc = {c.Zx:.1f} * {c.Fy} * (1 - {pm.Pu:.0f}/{denom:.0f})"
              f" = {M_pc:.0f} kip-in")
        print(f"  Sum M_pc = 2 * {M_pc:.0f} = {Sum_Mpc:.0f} kip-in")
        print(f"  Ratio = {Sum_Mpc:.0f} / {Sum_Mpb:.0f} = {ratio:.3f}")
        if not passed:
            print(f"  FAIL - Increase column size")
        else:
            print(f"  OK")
        print(f"  Note: Simplified (same column above/below, {n_beams} beams)")
        self.checks["column_beam"] = passed
        print()

    # ---------- Step 8: T-stub force ----------
    def step8_Tstub_force(self):
        self.subsection("STEP 8: PROBABLE T-STUB FORCE (EQ. 13.6-11)")
        b = self.beam
        # Eq. 13.6-11
        self.F_pr = self.M_f / (1.05 * b.d)
        print(f"  F_pr = M_f / (1.05*d)  (Eq. 13.6-11)")
        print(f"  F_pr = {self.M_f:.0f} / (1.05*{b.d:.2f})"
              f" = {self.F_pr:.1f} kips")
        print()

    # ---------- Step 9: T-stem size ----------
    def step9_Tstem_size(self):
        self.subsection("STEP 9: T-STEM SIZE (EQ. 13.6-12 TO 13.6-15)")
        pm = self.params
        b = self.beam

        # Eq. 13.6-12: Whitmore width
        L_vb = pm.s_vb * (self.n_vb / 2 - 1)
        self.W_Whit = 2 * L_vb * math.tan(math.radians(30)) + pm.g_vb
        print(f"  W_Whit = 2*L_vb*tan30 + g_vb  (Eq. 13.6-12)")
        print(f"  W_Whit = 2*{L_vb:.2f}*0.577 + {pm.g_vb} = {self.W_Whit:.2f} in")

        # W_T: T-stub width parallel to column flange (estimate)
        self.W_T = min(b.bf, self.column.bf)
        W_eff = min(self.W_T, self.W_Whit)

        # Eq. 13.6-13: Stem thickness for yielding
        t_st_yield = self.F_pr / (W_eff * PHI_D * DEFAULT_FY_T)

        # Eq. 13.6-14: Stem thickness for fracture
        d_vht = self.d_vb + 1 / 16  # hole diameter = bolt + 1/16
        t_st_fracture = self.F_pr / (PHI_N * DEFAULT_FU_T *
                                     (W_eff - 2 * (d_vht + 1 / 16)))

        # Eq. 13.6-15: Compression buckling
        t_ft_est = 1.0  # estimate
        t_st_buckling = (pm.S1 - t_ft_est) / 9.60

        t_st_req = max(t_st_yield, t_st_fracture, t_st_buckling)
        # Round up to nearest 1/8 in, minimum 1/4 in
        self.t_st = max(0.25, math.ceil(t_st_req * 8) / 8)

        print(f"  W_T (estimate) = {self.W_T:.2f} in")
        print(f"  W_eff = min(W_T, W_Whit) = {W_eff:.2f} in")
        print(f"  t_st (yielding) = {t_st_yield:.3f} in  (Eq. 13.6-13)")
        print(f"  t_st (fracture) = {t_st_fracture:.3f} in  (Eq. 13.6-14)")
        print(f"  t_st (buckling) = {t_st_buckling:.3f} in  (Eq. 13.6-15)")
        print(f"  t_st,req = {t_st_req:.3f} in, use t_st = {self.t_st:.3f} in")

        # Recompute phi_rnv with actual t_st for T-stem bearing
        r_stem_bearing = PHI_D * 2.4 * self.d_vb * self.t_st * DEFAULT_FU_T
        self._phi_rnv = min(self._r_bolt_shear, self._r_beam_bearing,
                            r_stem_bearing)
        print(f"  Updated phi*r_nv = {self._phi_rnv:.1f} kips/bolt")
        print()

    # ---------- Step 10: Tension bolt size ----------
    def step10_tension_bolt_size(self):
        self.subsection("STEP 10: TENSION BOLT SIZE (EQ. 13.6-16)")
        pm = self.params
        Fnt = FNT_A325 if pm.bolt_type == "A325" else FNT_A490

        # Eq. 13.6-16
        d_tb_req = math.sqrt(4 * self.F_pr / (pm.n_tb * PHI_N * math.pi * Fnt))
        self.d_tb = 0.875  # default 7/8 in
        for d in STANDARD_BOLT_DIAMETERS:
            if d >= d_tb_req:
                self.d_tb = d
                break

        print(f"  d_tb >= sqrt(4*F_pr / (n_tb*phi_n*pi*Fnt))  (Eq. 13.6-16)")
        print(f"  d_tb >= sqrt(4*{self.F_pr:.1f} / "
              f"({pm.n_tb}*{PHI_N}*pi*{Fnt}))")
        print(f"  d_tb >= {d_tb_req:.3f} in, use d_tb = {self.d_tb:.3f} in")
        print()

    # ---------- Step 11: T-flange configuration ----------
    def step11_Tflange_config(self):
        self.subsection("STEP 11: T-FLANGE CONFIGURATION (EQ. 13.6-17 TO 13.6-27)")
        pm = self.params

        # b = distance between effective T-stem and bolt line (Eq. 13.6-53)
        k1 = 0.75  # estimate for distance from web centerline to flange toe
        t_st_eff = k1 + self.t_st / 2  # Eq. 13.6-54
        b = 0.5 * (pm.g_tb - t_st_eff)  # Eq. 13.6-53

        # a = (b_ft - g_tb) / 2, limited to 1.25*b (Eq. 13.6-18)
        a = 1.5 * self.d_tb
        a_limit = 1.25 * b

        # b_ft (Eq. 13.6-17)
        b_ft_req = pm.g_tb + 2 * a

        # p = tributary width per bolt (Eq. 13.6-22)
        p = 2 * self.W_T / pm.n_tb

        # a', b' (Eqs. 13.6-23, 13.6-24)
        a_prime = a + 0.5 * self.d_tb
        b_prime = b - 0.5 * self.d_tb

        # Bolt design strength (Eq. 13.6-19)
        A_tb = math.pi / 4 * self.d_tb**2
        Fnt = FNT_A325 if pm.bolt_type == "A325" else FNT_A490
        phi_rnt = PHI_N * A_tb * Fnt

        # T_req (Eq. 13.6-20)
        T_req = self.F_pr / pm.n_tb

        # t_ft from mixed-mode (Eq. 13.6-21)
        radical_21 = T_req * (a_prime + b_prime) - phi_rnt * a_prime
        if radical_21 > 0:
            t_ft_21 = 2 * math.sqrt(radical_21 / (PHI_D * DEFAULT_FY_T * p))
        else:
            # Use alternate (Eq. 13.6-25)
            dtht = self.d_tb + 1 / 16
            delta = 1 - dtht / p
            t_ft_21 = 2 * math.sqrt(
                phi_rnt * a_prime * b_prime /
                (PHI_D * DEFAULT_FY_T * p * (a_prime + delta * (a_prime + b_prime)))
            )

        # No-prying thickness (Eq. 13.6-27)
        t_ft_crit = math.sqrt(4 * phi_rnt * b_prime / (PHI_D * DEFAULT_FY_T * p))

        self.t_ft = max(t_ft_21, t_ft_crit)
        self.t_ft = max(self.t_ft, math.ceil(self.t_ft * 8) / 8)  # round up
        self.b_ft = max(b_ft_req, pm.g_tb + 2 * 1.5 * self.d_tb)
        self.b_ft = math.ceil(self.b_ft * 4) / 4  # round up to 1/4 in

        self._a = a
        self._b = b
        self._a_prime = a_prime
        self._b_prime = b_prime
        self._p = p
        self._phi_rnt = phi_rnt

        print(f"  b = (g_tb - t_st_eff)/2 = ({pm.g_tb} - {t_st_eff:.3f})/2"
              f" = {b:.3f} in  (Eq. 13.6-53)")
        print(f"  a = 1.5*d_tb = {a:.3f} in (limit 1.25*b = {a_limit:.3f})")
        print(f"  p = 2*W_T/n_tb = {p:.2f} in  (Eq. 13.6-22)")
        print(f"  phi*r_nt = {phi_rnt:.1f} kips/bolt  (Eq. 13.6-19)")
        print(f"  T_req = {T_req:.1f} kips/bolt  (Eq. 13.6-20)")
        print(f"  t_ft (mixed-mode) = {t_ft_21:.3f} in  (Eq. 13.6-21)")
        print(f"  t_ft (no prying) = {t_ft_crit:.3f} in  (Eq. 13.6-27)")
        print(f"  Use t_ft = {self.t_ft:.3f} in")
        print(f"  b_ft = {self.b_ft:.2f} in")

        # Section 13.5.4(5): g_tb/t_ft <= 7.0
        gage_ratio = pm.g_tb / self.t_ft
        gage_ok = gage_ratio <= 7.0
        print(f"  g_tb/t_ft = {pm.g_tb}/{self.t_ft:.3f} = {gage_ratio:.2f} "
              f"<= 7.0: {'OK' if gage_ok else 'FAIL'}  (Section 13.5.4(5))")
        self.checks["gage_ratio"] = gage_ok
        print()

    # ---------- Step 12: Select T-stub from W-shape ----------
    def step12_select_Tstub(self):
        self.subsection("STEP 12: SELECT T-STUB FROM W-SHAPE")
        print(f"  Required: t_st >= {self.t_st:.3f} in, "
              f"t_ft >= {self.t_ft:.3f} in, b_ft >= {self.b_ft:.2f} in")
        print(f"  Minimum depth >= S1 + L_vb = {self.params.S1:.1f} + "
              f"{self.params.s_vb*(self.n_vb/2-1):.1f} = "
              f"{self.params.S1 + self.params.s_vb*(self.n_vb/2-1):.1f} in")
        print(f"  Note: Select a W-shape with tw >= {self.t_st:.3f}, "
              f"tf >= {self.t_ft:.3f}, bf >= {self.b_ft:.2f}")
        print(f"  T-stub cut from W-shape (ASTM A992 or A913 Gr 50)")
        print()

    # ---------- Step 13: Stiffness check ----------
    def step13_stiffness_check(self):
        self.subsection("STEP 13: FR CONNECTION STIFFNESS CHECK (EQ. 13.6-28)")
        b = self.beam
        pm = self.params

        I_beam = b.Ix
        L_o = pm.L

        # Eq. 13.6-28: K_i >= 18*E*I_beam / L_o
        K_req = 18 * E * I_beam / L_o

        # Eq. 13.6-32: K_flange
        I_ft = self._p * self.t_ft**3 / 12  # Eq. 13.6-36
        beta_a = 1 + 12 * E * I_ft / (G * self._p * self.t_ft * self._a_prime**2)
        beta_b = 1 + 12 * E * I_ft / (G * self._p * self.t_ft * self._b_prime**2)

        K_flange = (12 * pm.n_tb * E * I_ft *
                    (self._a_prime * beta_a + 3 * self._b_prime * beta_b) /
                    (self._b_prime**3 * beta_b *
                     (4 * self._a_prime * beta_a + 3 * self._b_prime * beta_b)))

        # Eq. 13.6-33: K_stem
        b_fb = b.bf  # beam flange width
        ratio_W_bf = self.W_T - b_fb
        if abs(ratio_W_bf) > 1e-4 and self.W_T > 0:
            K_stem = (self.t_st * E * ratio_W_bf**2 /
                      (self.params.S1 * (ratio_W_bf +
                       b_fb * math.log(b_fb / self.W_T))))
        else:
            # W_T == b_fb: degenerate case, use simple axial stiffness AE/L
            K_stem = self.t_st * self.W_T * E / self.params.S1

        # Eq. 13.6-35: P_slip
        A_vb = math.pi / 4 * self.d_vb**2
        Fnt = FNT_A325 if pm.bolt_type == "A325" else FNT_A490
        alpha = 1.0 if pm.bolt_type == "A325" else 0.88
        P_slip = self.n_vb * alpha * (0.70 * Fnt * A_vb) * MU_CLASS_A

        # Eq. 13.6-34: K_slip
        K_slip = P_slip / DELTA_SLIP

        # Eq. 13.6-30: K_ten
        K_ten = 1.0 / (1.0/K_flange + 1.0/K_stem + 1.0/K_slip)
        # Eq. 13.6-31: K_comp
        K_comp = 1.0 / (1.0/K_stem + 1.0/K_slip)
        # Eq. 13.6-29: K_i
        K_i = b.d**2 * K_ten * K_comp / (K_ten + K_comp)

        stiff_ok = K_i >= K_req
        ratio = K_i / K_req if K_req > 0 else 999

        print(f"  K_req = 18*E*I_beam/L = 18*{E:.0f}*{I_beam:.0f}/{L_o:.0f}"
              f" = {K_req:.0f} kip-in/rad  (Eq. 13.6-28)")
        print(f"  K_flange = {K_flange:.0f} kip/in  (Eq. 13.6-32)")
        print(f"  K_stem = {K_stem:.0f} kip/in  (Eq. 13.6-33)")
        print(f"  K_slip = {K_slip:.0f} kip/in  (Eq. 13.6-34)")
        print(f"  K_ten = {K_ten:.0f} kip/in  (Eq. 13.6-30)")
        print(f"  K_comp = {K_comp:.0f} kip/in  (Eq. 13.6-31)")
        print(f"  K_i = {K_i:.0f} kip-in/rad  (Eq. 13.6-29)")
        print(f"  K_i/K_req = {ratio:.3f} >= 1.0: "
              f"{'OK (FR)' if stiff_ok else 'FAIL (PR - not prequalified)'}")

        self.checks["stiffness"] = stiff_ok
        print()

    # ---------- Step 14: Actual flange force ----------
    def step14_actual_flange_force(self):
        self.subsection("STEP 14: ACTUAL FLANGE FORCE (EQ. 13.6-40)")
        b = self.beam
        # Eq. 13.6-40
        self.F_f = self.M_f / (b.d + self.t_st)
        print(f"  F_f = M_f / (d + t_st)  (Eq. 13.6-40)")
        print(f"  F_f = {self.M_f:.0f} / ({b.d:.2f} + {self.t_st:.3f})"
              f" = {self.F_f:.1f} kips")
        print()

    # ---------- Step 15: Back-check shear bolts ----------
    def step15_backcheck_shear_bolts(self):
        self.subsection("STEP 15: BACK-CHECK SHEAR BOLTS (EQ. 13.6-41)")
        phi_Rn = self.n_vb * self._phi_rnv  # total shear bolt capacity
        ok = phi_Rn >= self.F_f
        print(f"  phi*R_n = {self.n_vb} * {self._phi_rnv:.1f} = {phi_Rn:.1f} kips")
        print(f"  F_f = {self.F_f:.1f} kips")
        print(f"  {'OK' if ok else 'FAIL'} "
              f"(Utilization: {self.F_f/phi_Rn:.3f})")
        self.checks["shear_bolts"] = ok
        print()

    # ---------- Step 16: Back-check T-stem ----------
    def step16_backcheck_Tstem(self):
        self.subsection("STEP 16: BACK-CHECK T-STEM (EQ. 13.6-42 TO 13.6-45)")
        W_eff = min(self.W_T, self.W_Whit)
        d_vht = self.d_vb + 1 / 16

        # Gross section yielding (Eq. 13.6-42)
        phi_Rn_yield = PHI_D * DEFAULT_FY_T * W_eff * self.t_st

        # Net section fracture (Eq. 13.6-43)
        phi_Rn_fracture = PHI_N * DEFAULT_FU_T * (W_eff - 2*(d_vht + 1/16)) * self.t_st

        # Flexural buckling (Eq. 13.6-44)
        KLr = 2.60 * (self.params.S1 - self.t_ft) / self.t_st

        if KLr <= 25:
            phi_Rn_buckling = PHI_D * DEFAULT_FY_T * W_eff * self.t_st
        else:
            # AISC 360 E3: Euler / inelastic buckling
            F_e = math.pi**2 * E / KLr**2
            if F_e >= 0.44 * DEFAULT_FY_T:
                F_cr = 0.658**(DEFAULT_FY_T / F_e) * DEFAULT_FY_T
            else:
                F_cr = 0.877 * F_e
            phi_Rn_buckling = PHI_N * F_cr * W_eff * self.t_st

        phi_Rn_min = min(phi_Rn_yield, phi_Rn_fracture, phi_Rn_buckling)
        ok = phi_Rn_min >= self.F_f

        print(f"  W_eff = {W_eff:.2f} in")
        print(f"  Yielding: phi*R_n = {phi_Rn_yield:.1f} kips  (Eq. 13.6-42)")
        print(f"  Fracture: phi*R_n = {phi_Rn_fracture:.1f} kips  (Eq. 13.6-43)")
        print(f"  KL/r = {KLr:.1f}  (Eq. 13.6-44)")
        print(f"  Buckling: phi*R_n = {phi_Rn_buckling:.1f} kips")
        print(f"  Governing: phi*R_n = {phi_Rn_min:.1f} kips >= F_f = {self.F_f:.1f}: "
              f"{'OK' if ok else 'FAIL'}")
        self.checks["T_stem"] = ok
        print()

    # ---------- Step 17: Back-check T-flange ----------
    def step17_backcheck_Tflange(self):
        self.subsection("STEP 17: BACK-CHECK T-FLANGE (EQ. 13.6-46 TO 13.6-54)")
        pm = self.params

        # Recompute a, b from actual b_ft per Eqs. 13.6-50 to 13.6-54
        k1 = 0.75
        t_st_eff = k1 + self.t_st / 2
        b = 0.5 * (pm.g_tb - t_st_eff)  # Eq. 13.6-53
        a = 0.5 * (self.b_ft - pm.g_tb)  # Eq. 13.6-51
        a = min(a, 1.25 * b)             # Eq. 13.6-52
        a_prime = a + 0.5 * self.d_tb    # Eq. 13.6-50
        b_prime = b - 0.5 * self.d_tb

        dtht = self.d_tb + 1 / 16
        delta = 1 - dtht / self._p

        # Eq. 13.6-47: Plastic flange mechanism
        phi_T1 = ((1 + delta) / (4 * b_prime)) * self._p * \
                  PHI_D * DEFAULT_FY_T * self.t_ft**2

        # Eq. 13.6-48: Mixed-mode failure
        phi_T2 = (self._phi_rnt * a_prime / (a_prime + b_prime) +
                  self._p * PHI_D * DEFAULT_FY_T * self.t_ft**2 /
                  (4 * (a_prime + b_prime)))

        # Eq. 13.6-49: Bolt fracture without prying
        phi_T3 = self._phi_rnt

        phi_T_min = min(phi_T1, phi_T2, phi_T3)
        phi_Rn = pm.n_tb * phi_T_min
        ok = phi_Rn >= self.F_f

        print(f"  a = {a:.3f} in | b = {b:.3f} in | a' = {a_prime:.3f} | b' = {b_prime:.3f}")
        print(f"  phi*T1 (plastic mechanism) = {phi_T1:.1f} kips/bolt  (Eq. 13.6-47)")
        print(f"  phi*T2 (mixed-mode) = {phi_T2:.1f} kips/bolt  (Eq. 13.6-48)")
        print(f"  phi*T3 (bolt fracture) = {phi_T3:.1f} kips/bolt  (Eq. 13.6-49)")
        print(f"  Governing: phi*T = {phi_T_min:.1f} kips/bolt")
        print(f"  phi*R_n = {pm.n_tb} * {phi_T_min:.1f} = {phi_Rn:.1f} kips")
        print(f"  phi*R_n = {phi_Rn:.1f} >= F_f = {self.F_f:.1f}: "
              f"{'OK' if ok else 'FAIL'}")
        self.checks["T_flange"] = ok
        print()

    # ---------- Step 18: Bearing and tear-out ----------
    def step18_bearing_tearout(self):
        self.subsection("STEP 18: BEARING AND TEAR-OUT (AISC 360 CH. J)")
        b = self.beam
        F_f_per_bolt = self.F_f / self.n_vb

        # Beam flange bearing (ductile, phi_d = 1.0)
        r_bf = PHI_D * 2.4 * self.d_vb * b.tf * b.Fu
        r_bf_total = self.n_vb * r_bf

        # T-stem bearing
        r_ts = PHI_D * 2.4 * self.d_vb * self.t_st * DEFAULT_FU_T
        r_ts_total = self.n_vb * r_ts

        # Tear-out check assumes minimum edge distance = 1.5*db per AISC 360
        # (actual edge distances depend on detailing, this is a basic check)
        Lc_min = 1.5 * self.d_vb  # minimum clear distance
        r_to_bf = PHI_D * 1.2 * Lc_min * b.tf * b.Fu
        r_to_ts = PHI_D * 1.2 * Lc_min * self.t_st * DEFAULT_FU_T

        r_min_per_bolt = min(r_bf, r_ts, r_to_bf, r_to_ts)
        phi_Rn = self.n_vb * r_min_per_bolt
        ok = phi_Rn >= self.F_f

        print(f"  Beam flange bearing: {r_bf:.1f} kips/bolt")
        print(f"  T-stem bearing: {r_ts:.1f} kips/bolt")
        print(f"  Tear-out (Lc={Lc_min:.2f}): beam={r_to_bf:.1f}, T-stem={r_to_ts:.1f} kips/bolt")
        print(f"  Governing: {r_min_per_bolt:.1f} kips/bolt")
        print(f"  phi*R_n = {self.n_vb}*{r_min_per_bolt:.1f} = {phi_Rn:.1f} kips")
        print(f"  F_f = {self.F_f:.1f} kips: {'OK' if ok else 'FAIL'}")
        self.checks["bearing"] = ok
        print()

    # ---------- Step 19: Block shear ----------
    def step19_block_shear(self):
        self.subsection("STEP 19: BLOCK SHEAR (AISC 360 CH. J)")
        pm = self.params
        # Block shear of T-stem (phi_d = 1.0 per Step 19)
        # Assume standard block shear pattern with 2 rows of bolts
        d_vht = self.d_vb + 1 / 16
        n_rows = self.n_vb // 2

        # Gross and net shear areas (T-stem)
        L_gv = (n_rows - 1) * pm.s_vb  # gross shear length along bolt lines
        Agv = 2 * L_gv * self.t_st
        Anv = Agv - 2 * (n_rows - 1) * (d_vht + 1/16) * self.t_st

        # Gross and net tension area (T-stem)
        Agt = pm.g_vb * self.t_st
        Ant = (pm.g_vb - (d_vht + 1/16)) * self.t_st

        # AISC 360 J4.3: phi*[0.6*Fu*Anv + Ubs*Fu*Ant] and phi*[0.6*Fu*Anv + Fy*Agv]
        Ubs = 0.5  # block shear with eccentricity
        phi_Rn_1 = PHI_D * (0.6 * DEFAULT_FU_T * Anv + Ubs * DEFAULT_FU_T * Ant)
        phi_Rn_2 = PHI_D * (0.6 * DEFAULT_FU_T * Anv + DEFAULT_FY_T * Agv)
        phi_Rn = min(phi_Rn_1, phi_Rn_2)

        ok = phi_Rn >= self.F_f
        print(f"  T-stem block shear:")
        print(f"    Agv = {Agv:.2f} in^2, Anv = {Anv:.2f} in^2")
        print(f"    Agt = {Agt:.2f} in^2, Ant = {Ant:.2f} in^2")
        print(f"    phi*R_n = {phi_Rn:.1f} kips >= F_f = {self.F_f:.1f}: "
              f"{'OK' if ok else 'FAIL'}")
        print(f"  (Alternate mechanism per Fig. 13.7 need not be checked)")
        self.checks["block_shear"] = ok
        print()

    # ---------- Step 20: Shear connection ----------
    def step20_shear_connection(self):
        self.subsection("STEP 20: SHEAR CONNECTION TO WEB")
        V_u = self.V_h
        print(f"  V_u = V_h = {V_u:.1f} kips")
        print("  Design single-plate shear connection per AISC 360")
        print("  Note: Extended shear tab likely needed due to large setback")
        print("  L_sc must fit between T-stub flanges")
        print("  [EOR responsibility - not automatically checked]")
        self.checks["shear_connection"] = None  # advisory, EOR responsibility
        print()

    # ---------- Step 21: Column flange ----------
    def step21_column_flange(self):
        self.subsection("STEP 21: COLUMN FLANGE FLEXURAL YIELDING (EQ. 13.6-55)")
        c = self.column
        pm = self.params

        # Column flange yield line parameters (Eqs. 13.6-57 to 13.6-60)
        g_ic = pm.g_tb  # interior bolt gage in column flange
        a_c = (c.bf - g_ic) / 2  # Eq. 13.6-57
        b_c = g_ic / 2  # Eq. 13.6-58

        # s (Eq. 13.6-60)
        s = math.sqrt(c.bf * g_ic) / 2

        # p_s with continuity plate (Eq. 13.6-59)
        t_cp = self.beam.tf  # continuity plate thickness >= beam tf
        p_s = min((g_ic - t_cp) / 2, s)  # Eq. 13.6-59

        # Y_C (Eq. 13.6-56)
        if b_c > 0 and (s + p_s) > 0:
            Y_C = (2 / b_c) * (s + p_s +
                   (a_c * b_c + b_c**2) / s +
                   (a_c * b_c + b_c**2) / p_s)
        else:
            Y_C = 6.0  # fallback

        # Eq. 13.6-55
        phi_Rn_cf = PHI_D * c.Fy * Y_C * c.tf**2
        ok = phi_Rn_cf >= self.F_f

        # Alternative: Eq. 13.6-61
        t_fc_req = math.sqrt(1.11 * self.F_f / (PHI_D * c.Fy * Y_C))

        print(f"  a_c = {a_c:.2f} in | b_c = {b_c:.2f} in | s = {s:.2f} in")
        print(f"  p_s = {p_s:.2f} in | Y_C = {Y_C:.2f}")
        print(f"  phi*R_n = phi_d*Fyc*Y_C*t_fc = {phi_Rn_cf:.1f} kips  (Eq. 13.6-55)")
        print(f"  t_fc,req = {t_fc_req:.3f} in  (Eq. 13.6-61)")
        print(f"  Column tf = {c.tf:.3f} in: "
              f"{'OK' if c.tf >= t_fc_req else 'FAIL - need continuity plates'}")

        self.checks["column_flange"] = ok
        print()

    # ---------- Step 22: Column web ----------
    def step22_column_web(self):
        self.subsection("STEP 22: COLUMN WEB AND PANEL ZONE CHECKS")
        c = self.column
        b = self.beam
        F_f = self.F_f

        # --- Web local yielding (AISC 360 J10.2) ---
        k = c.tf
        phi_Rn_wy = PHI_D * 5 * c.Fy * k * c.tw

        # --- Web local crippling (AISC 360 J10.3, Eq J10-4) ---
        N_bearing = b.bf
        phi_Rn_wc = PHI_N * 0.80 * c.tw**2 * (
            1 + 3 * (N_bearing / c.d) * (c.tw / c.tf)**1.5
        ) * math.sqrt(E * c.Fy * c.tf / c.tw)

        phi_Rn_web = min(phi_Rn_wy, phi_Rn_wc)
        web_ok = phi_Rn_web >= F_f

        print(f"  --- Web Local Checks ---")
        print(f"  F_f = {F_f:.1f} kips (concentrated force)")
        print(f"  Web local yielding: phi*R_n = {phi_Rn_wy:.1f} kips")
        print(f"  Web local crippling: phi*R_n = {phi_Rn_wc:.1f} kips")
        print(f"  Web governing: phi*R_n = {phi_Rn_web:.1f} kips: "
              f"{'OK' if web_ok else 'FAIL - need continuity plates/doublers'}")

        # --- Panel zone shear (AISC 341 D1.2c + AISC 360 J10.6) ---
        # Demand: V_pz from column face moments
        # V_pz = Sum(M_face) / d_beam - V_col
        # For symmetric frame: Sum(M_face) = 2 * M_f, V_col ~ V_h/2 * (d_beam / H_story)
        dc = c.d  # overall column depth per AISC 360 J10.6
        d_beam = b.d
        Sum_Mface = 2 * self.M_f  # beams from both sides

        # Column shear from moment gradient
        H_story = (self.params.story_above + self.params.story_below) / 2
        if H_story > 0:
            V_col = Sum_Mface / H_story
        else:
            V_col = 0

        V_pz = Sum_Mface / d_beam - V_col

        # Panel zone capacity per AISC 360 J10.6
        # phi*R_n = phi * 0.6 * Fy * dc * tw * (1 + 4*b tf*tf/(dc*dc*tw))  [with doubler]
        # Simplified (no doubler plates): phi*R_n = phi * 0.6 * Fy * dc * tw
        phi_pz = 1.0  # per AISC 341
        phi_Rn_pz = phi_pz * 0.6 * c.Fy * dc * c.tw

        pz_ok = phi_Rn_pz >= V_pz

        print(f"\n  --- Panel Zone Shear (AISC 341 D1.2c + AISC 360 J10.6) ---")
        print(f"  Sum M_face = 2*M_f = 2*{self.M_f:.0f} = {Sum_Mface:.0f} kip-in")
        print(f"  V_col = Sum M_face / H = {Sum_Mface:.0f} / {H_story:.0f} = {V_col:.1f} kips")
        print(f"  V_pz = {Sum_Mface:.0f}/{d_beam:.2f} - {V_col:.1f} = {V_pz:.1f} kips")
        print(f"  phi*R_n = {phi_pz}*0.6*{c.Fy}*{dc:.2f}*{c.tw:.3f} = {phi_Rn_pz:.1f} kips")
        print(f"  Panel zone: phi*R_n = {phi_Rn_pz:.1f} >= V_pz = {V_pz:.1f}: "
              f"{'OK' if pz_ok else 'FAIL - need doubler plates'}")

        self.checks["column_web"] = web_ok
        self.checks["panel_zone"] = pz_ok
        print()

    # ---------- Step 23: Continuity plates ----------
    def step23_continuity_plates(self):
        self.subsection("STEP 23: CONTINUITY PLATES (SECTION 13.5.2)")
        print("  Continuity plates required at all column locations")
        print(f"  Min thickness = beam tf = {self.beam.tf:.3f} in")
        print("  Extend to column flange edge less 1/4 in")
        print("  Weld per AISC Seismic Provisions")
        self.checks["continuity_plates"] = True
        print()

    # ---------- Summary ----------
    def print_summary(self):
        self.section("DESIGN VERIFICATION SUMMARY")

        def s(k):
            v = self.checks.get(k)
            if v is None:
                return "N/A"
            return "PASS" if v else "FAIL"

        print(f"Prequalification: {s('prequalification')}")
        print(f"Bolt diameter (Step 2): {s('bolt_diameter')}")
        print(f"Beam shear (Step 6a): {s('beam_shear')}")
        print(f"Column-beam ratio (Step 7a): {s('column_beam')}")
        print(f"FR Stiffness (Step 13): {s('stiffness')}")
        print(f"Shear bolts (Step 15): {s('shear_bolts')}")
        print(f"T-stem (Step 16): {s('T_stem')}")
        print(f"T-flange (Step 17): {s('T_flange')}")
        print(f"Gage ratio g_tb/t_ft (Step 11): {s('gage_ratio')}")
        print(f"Bearing/tearout (Step 18): {s('bearing')}")
        print(f"Block shear (Step 19): {s('block_shear')}")
        print(f"Shear connection (Step 20): {s('shear_connection')}")
        print(f"Column flange (Step 21): {s('column_flange')}")
        print(f"Column web (Step 22): {s('column_web')}")
        print(f"Panel zone (Step 22): {s('panel_zone')}")
        print(f"Continuity plates (Step 23): {s('continuity_plates')}")
        print()

        print(f"KEY RESULTS:")
        print(f"  M_pr = {self.M_pr:.0f} kip-in | M_f = {self.M_f:.0f} kip-in")
        print(f"  F_pr = {self.F_pr:.1f} kips | F_f = {self.F_f:.1f} kips")
        print(f"  V_h = {self.V_h:.1f} kips")
        print(f"  Shear bolts: n_vb = {self.n_vb}, d_vb = {self.d_vb:.3f} in")
        print(f"  Tension bolts: n_tb = {self.params.n_tb}, "
              f"d_tb = {self.d_tb:.3f} in")
        print(f"  T-stub: t_st = {self.t_st:.3f}, t_ft = {self.t_ft:.3f}, "
              f"b_ft = {self.b_ft:.2f}")
        print(f"  S_h = {self.S_h:.2f} in | L_h = {self._L_h:.1f} in")
        print()

        all_pass = all(v for v in self.checks.values() if v is not None)
        self.sep("=")
        if all_pass:
            print("  ALL CHECKS PASSED")
        else:
            print("  SOME CHECKS FAILED - REVIEW AND ADJUST DESIGN")
        self.sep("=")


# ====================== COMMAND LINE ======================

def parse_args():
    parser = argparse.ArgumentParser(
        description="Double-Tee Connection Design Verification "
                    "(AISC 358-16 Chapter 13)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python doubletee_design.py --beam-section W21x44 --column-section W14x145 \\
      --span 300 --system-type SMF

  python doubletee_design.py --beam-section W24x55 --column-section W14x193 \\
      --span 360 --system-type SMF --tension-bolts 8
        """
    )

    if "--list-sections" in sys.argv:
        sections = load_sections_from_csv()
        print("Available W-shape sections "
              "(Double-Tee prequalified: beam <= W24x55):")
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

    cg = parser.add_argument_group("Column")
    cg.add_argument("--column-section", type=str, dest='col_section')
    cg.add_argument("--col-d", type=float)
    cg.add_argument("--col-bf", type=float)
    cg.add_argument("--col-tf", type=float)
    cg.add_argument("--col-tw", type=float)
    cg.add_argument("--col-Zx", type=float)
    cg.add_argument("--col-Fy", type=float, default=DEFAULT_FY_COL)
    cg.add_argument("--col-Fu", type=float, default=65.0)

    dg = parser.add_argument_group("Design")
    dg.add_argument("--span", type=float, required=True)
    dg.add_argument("--system-type", type=str, required=True,
                    choices=["SMF", "IMF"])
    dg.add_argument("--tension-bolts", type=int, default=4,
                    choices=[4, 8],
                    help="Number of tension bolts per T-stub (default: 4)")
    dg.add_argument("--bolt-type", type=str, default="A325",
                    choices=["A325", "A490"],
                    help="Bolt grade (default: A325)")
    dg.add_argument("--S1", type=float, default=3.0,
                    help="Distance column face to first shear bolt (in)")
    dg.add_argument("--s-vb", type=float, default=3.0,
                    help="Shear bolt spacing (in)")
    dg.add_argument("--g-vb", type=float, default=3.5,
                    help="Shear bolt gage in T-stem (in)")
    dg.add_argument("--g-tb", type=float, default=5.5,
                    help="Tension bolt gage in T-flange (in)")
    dg.add_argument("--slab", action="store_true", default=False,
                    help="Concrete slab present (affects column depth limit)")
    dg.add_argument("--story-above", type=float, default=156.0,
                    help="Story height above joint (in)")
    dg.add_argument("--story-below", type=float, default=156.0,
                    help="Story height below joint (in)")
    dg.add_argument("--Pu", type=float, default=0.0,
                    help="Column axial load (kips)")
    dg.add_argument("--As-col", type=float, default=0.0,
                    help="Column cross-section area (in^2, 0=approximate)")

    lg = parser.add_argument_group("Loads")
    lg.add_argument("--load-D", type=float, default=0)
    lg.add_argument("--load-L", type=float, default=0)
    lg.add_argument("--load-S", type=float, default=0)
    lg.add_argument("--load-f1", type=float, default=0.5)

    return parser.parse_args()


def main():
    args = parse_args()
    try:
        beam = create_section(args, 'beam',
                              {'Fy': DEFAULT_FY_BEAM, 'Fu': DEFAULT_FU_BEAM})
        column = create_section(args, 'col',
                                {'Fy': DEFAULT_FY_COL, 'Fu': 65.0})

        loads = Loads(D=args.load_D, L=args.load_L, S=args.load_S,
                      f1=args.load_f1)

        params = DesignParameters(
            L=args.span, system_type=args.system_type,
            n_tb=args.tension_bolts, bolt_type=args.bolt_type,
            S1=args.S1, s_vb=args.s_vb, g_vb=args.g_vb, g_tb=args.g_tb,
            has_slab=args.slab,
            story_above=args.story_above, story_below=args.story_below,
            Pu=args.Pu, As_col=args.As_col,
        )

        checker = DoubleTeeDesignChecker(beam, column, params, loads)
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
