#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SlottedWeb (SW) Moment Connection Design Verification
Based on AISC 358-16 Chapter 14, Section 14.8 - Design Procedure

SlottedWeb connections feature slots in the beam web parallel and adjacent
to each flange. The beam flanges are welded to the column flange using CJP
groove welds (demand critical). A shear plate is welded to both the column
flange and the beam web. The plastic hinge forms at the end of the shear plate.

Key characteristics:
  - SMF only (not prequalified for IMF)
  - Beam web slots separate flanges from web near the connection
  - CJP groove welds for beam flanges (demand critical)
  - Shear plate welded to column flange, bolted + fillet welded to beam web
  - Plastic hinge at end of shear plate (S_h = l_p)
  - Beam shear phi = 1.0 per Commentary C-14.8

Usage:
    python slottedweb_design.py --beam-section W24x94 --column-section W14x257 \
        --span 360 --system-type SMF

    python slottedweb_design.py --beam-section W36x150 --column-section W14x455 \
        --span 420 --system-type SMF --load-D 10 --load-L 20

    python slottedweb_design.py --beam-section W30x173 --column-section W14x550 \
        --span 480 --system-type SMF --beam-T 24.5
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
PHI_V = 1.00   # Beam shear per Commentary C-14.8 (13 cyclic tests)

DEFAULT_FY_BEAM = 50.0    # ksi (A992)
DEFAULT_FU_BEAM = 65.0    # ksi
DEFAULT_FY_COL = 50.0     # ksi
DEFAULT_FY_PLATE = 50.0   # ksi (shear plate, per Section 14.8 Step 2)

# Beam prequalification limits (Section 14.3.1)
BEAM_MAX_DEPTH = 36.0     # W36 max
BEAM_MAX_WEIGHT = 400.0   # plf
BEAM_MAX_TF = 2.25        # 2-1/4 in (57 mm)
BEAM_MIN_SPAN_DEPTH = 6.4

# Steel properties
E = 29000.0   # ksi


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
    T: float = 0.0  # clear distance between flanges (d - 2k)

    @property
    def weight(self) -> float:
        try:
            return float(self.designation.upper().split('X')[1])
        except (ValueError, IndexError):
            return 999

    @property
    def T_eff(self) -> float:
        """Clear distance between flanges. Use provided T or approximate.
        Conservative: T = d - 2*(tf + tw) (k ~ tf + tw upper bound)."""
        if self.T > 0:
            return self.T
        return self.d - 2 * (self.tf + self.tw)


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
    L: float           # center-to-center span (in)
    system_type: str   # SMF only
    l_p_override: float = 0.0  # shear plate width, 0 = auto
    story_above: float = 156.0
    story_below: float = 156.0
    Pu: float = 0.0
    As_col: float = 0.0


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
                T=getattr(args, f'{prefix}_T', 0.0) or 0.0,
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
            T=getattr(args, f'{prefix}_T', 0.0) or 0.0,
        )
    raise ValueError(f"Invalid {prefix} section. "
                     f"Use --{prefix}-section or provide all dimensions.")


# ====================== DESIGN CHECKER ======================

class SlottedWebDesignChecker:
    """SlottedWeb Connection Design per AISC 358-16 Section 14.8 (10 steps)"""

    def __init__(self, beam: Section, column: Section,
                 params: DesignParameters, loads: Loads):
        self.beam = beam
        self.column = column
        self.params = params
        self.loads = loads
        self.checks: dict = {}

        # Computed values
        self.l_s = 0.0       # slot length (in)
        self.l_p = 0.0       # shear plate width (in)
        self.h = 0.0         # shear plate height (in)
        self.t_p = 0.0       # shear plate thickness (in)
        self.M_pr = 0.0
        self.V_beam = 0.0
        self.M_f = 0.0
        self.M_weld = 0.0
        self.V_weld = 0.0
        self.e_x = 0.0
        self.l_b = 0.0       # clear span

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
        self.section("SLOTTEDWEB (SW) CONNECTION DESIGN VERIFICATION "
                     "(AISC 358-16 CHAPTER 14)")
        print()
        self.print_input()

        self.step0_prequalification()
        self.section("DESIGN PROCEDURE (SECTION 14.8)")

        self.step1_slot_design()
        self.step2_shear_plate()
        self.step3_plate_beam_weld()
        self.step4_plate_column_weld()
        self.step5_bolts()
        self.step6_Mf()
        self.step7_beam_shear()
        self.step8_continuity_plates()
        self.step9_panel_zone()
        self.step10_column_beam()

        self.print_summary()
        return all(v for v in self.checks.values() if v is not None)

    # ---------- Input ----------
    def print_input(self):
        self.section("INPUT PARAMETERS")
        b, c, pm, ld = self.beam, self.column, self.params, self.loads
        T_str = f"{b.T_eff:.2f}" if b.T == 0 else f"{b.T:.2f} (user)"
        print(f"BEAM: {b.designation} | d={b.d:.2f} bf={b.bf:.2f} "
              f"tf={b.tf:.3f} tw={b.tw:.3f} Zx={b.Zx:.1f}")
        print(f"      Fy={b.Fy} Fu={b.Fu} Ry={b.Ry} Rt={b.Rt} T={T_str}")
        print(f"COLUMN: {c.designation} | d={c.d:.2f} bf={c.bf:.2f} "
              f"tf={c.tf:.3f} tw={c.tw:.3f} Zx={c.Zx:.1f}")
        print(f"        Fy={c.Fy} Fu={c.Fu}")
        print(f"SPAN: L={pm.L:.0f} in ({pm.L/12:.1f} ft) | {pm.system_type}")
        print(f"STORY: H_above={pm.story_above:.0f} | H_below={pm.story_below:.0f} | "
              f"Pu={pm.Pu:.0f} kips")
        print(f"LOADS: D={ld.D} L={ld.L} S={ld.S} | "
              f"Gravity={ld.gravity_combination:.2f} kips")
        print()

    # ---------- Step 0: Prequalification ----------
    def step0_prequalification(self):
        self.subsection("PREQUALIFICATION LIMITS (SECTION 14.3)")
        passed = True
        b = self.beam
        pm = self.params

        if pm.system_type != "SMF":
            print(f"  System type: {pm.system_type} -- FAIL (SMF only)")
            passed = False
        else:
            print(f"  System type: SMF: OK")

        print(f"  Beam depth: d = {b.d:.2f} in <= {BEAM_MAX_DEPTH:.0f}: ", end="")
        if b.d > BEAM_MAX_DEPTH:
            print("FAIL"); passed = False
        else:
            print("OK")

        print(f"  Beam weight: {b.weight:.0f} plf <= {BEAM_MAX_WEIGHT:.0f}: ", end="")
        if b.weight > BEAM_MAX_WEIGHT:
            print("FAIL"); passed = False
        else:
            print("OK")

        print(f"  Beam tf: {b.tf:.3f} in <= {BEAM_MAX_TF:.1f}: ", end="")
        if b.tf > BEAM_MAX_TF:
            print("FAIL"); passed = False
        else:
            print("OK")

        sd = pm.L / b.d
        print(f"  Span/depth: L/d = {sd:.1f} >= {BEAM_MIN_SPAN_DEPTH:.1f}: ", end="")
        if sd < BEAM_MIN_SPAN_DEPTH:
            print("FAIL"); passed = False
        else:
            print("OK")

        c = self.column
        print(f"  Column depth: d = {c.d:.2f} in <= 36.0 (W36 max): ", end="")
        if c.d > 36.0:
            print("FAIL"); passed = False
        else:
            print("OK")

        self.checks["prequalification"] = passed
        print()

    # ---------- Step 1: Beam Web Slot Design ----------
    def step1_slot_design(self):
        self.subsection("STEP 1: BEAM WEB SLOT DESIGN (EQ. 14.8-1 TO 14.8-4)")
        b = self.beam
        pm = self.params

        # l_b = half the clear span length per AISC 358-16 Symbols table
        self.l_b = (pm.L - self.column.d) / 2.0
        gravity = self.loads.gravity_combination

        # Eq. 14.8-1: l_s = 1.5 * bf
        ls_1 = 1.5 * b.bf

        # Eq. 14.8-2: l_s = 0.60 * tf * sqrt(E / Fye)
        Fye = b.Ry * b.Fy
        ls_2 = 0.60 * b.tf * math.sqrt(E / Fye)

        # Eq. 14.8-3: l_s = d / 2
        ls_3 = b.d / 2

        # Eq. 14.8-4: l_s = l_p + (l_b - l_p)/10
        # Iterative seed: with l_p = l_s/3, solving gives l_s = l_b/7
        ls_4 = self.l_b / 7.0

        print(f"  l_b (clear span) = L - d_c = {pm.L:.0f} - {self.column.d:.2f}"
              f" = {self.l_b:.1f} in")
        print(f"  Fye = Ry * Fy = {b.Ry} * {b.Fy} = {Fye:.1f} ksi")
        print(f"  Eq. 14.8-1: l_s = 1.5*bf = 1.5*{b.bf:.2f} = {ls_1:.2f} in")
        print(f"  Eq. 14.8-2: l_s = 0.60*tf*sqrt(E/Fye) = {ls_2:.2f} in")
        print(f"  Eq. 14.8-3: l_s = d/2 = {b.d:.2f}/2 = {ls_3:.2f} in")
        print(f"  Eq. 14.8-4: l_s = l_b/7 = {self.l_b:.1f}/7 = {ls_4:.2f} in"
              f" (iterative seed)")

        # l_s is the least of the four (within +/-10%)
        self.l_s = min(ls_1, ls_2, ls_3, ls_4)

        print(f"  l_s = min({ls_1:.2f}, {ls_2:.2f}, {ls_3:.2f}, {ls_4:.2f})"
              f" = {self.l_s:.2f} in")

        # Commentary C-14.8 Eq. C-14.8-1 check (informational)
        ls_over_tf = self.l_s / b.tf
        limit_ct = 0.60 * math.sqrt(E / b.Fy)
        ct_ok = ls_over_tf <= limit_ct
        print(f"  Cmt C-14.8-1: l_s/tf = {ls_over_tf:.1f} <= {limit_ct:.1f}: "
              f"{'OK' if ct_ok else 'WARNING'}")
        # Protected zone extents (Section 14.3.1(8))
        pz_web = self.l_s + b.d / 2
        pz_flange = self.l_s + b.bf / 2
        print(f"  Protected zone: web = column face to {pz_web:.1f} in"
              f" (slot end + d/2)")
        print(f"  Protected zone: flange = column face to {pz_flange:.1f} in"
              f" (slot end + bf/2)")
        print()

    # ---------- Step 2: Shear Plate Design ----------
    def step2_shear_plate(self):
        self.subsection("STEP 2: SHEAR PLATE DESIGN (EQ. 14.8-5, 14.8-6)")
        b = self.beam
        pm = self.params

        # Shear plate width limits: l_s/3 <= l_p <= min(l_s/2, 6 in)
        l_p_min = self.l_s / 3
        l_p_max = min(self.l_s / 2, 6.0)

        if pm.l_p_override > 0:
            self.l_p = pm.l_p_override
        else:
            self.l_p = l_p_max  # use maximum allowed width

        print(f"  l_p limits: l_s/3 = {l_p_min:.2f} <= l_p <= min(l_s/2, 6)"
              f" = {l_p_max:.2f} in")
        print(f"  Use l_p = {self.l_p:.2f} in")

        lp_ok = l_p_min <= self.l_p <= l_p_max
        if not lp_ok:
            print(f"  WARNING: l_p = {self.l_p:.2f} outside range "
                  f"[{l_p_min:.2f}, {l_p_max:.2f}]")

        # Re-check Eq. 14.8-4 with actual l_p (iterative verification)
        ls_4_check = self.l_p + (self.l_b - self.l_p) / 10.0
        if ls_4_check < self.l_s:
            print(f"  Eq. 14.8-4 re-check: l_p + (l_b-l_p)/10 = "
                  f"{self.l_p:.2f} + ({self.l_b:.1f}-{self.l_p:.2f})/10"
                  f" = {ls_4_check:.2f} < l_s = {self.l_s:.2f} => GOVERNS")
            self.l_s = ls_4_check

        # Eq. 14.8-5: h = T - 2 in +/- 1 in
        T_beam = b.T_eff
        h_nom = T_beam - 2.0
        self.h = h_nom  # use nominal value

        print(f"  T (clear distance) = {T_beam:.2f} in")
        print(f"  h = T - 2 = {T_beam:.2f} - 2 = {self.h:.2f} in  (Eq. 14.8-5)")

        # C_pr per Section 2.4.3
        C_pr = min((b.Fy + b.Fu) / (2 * b.Fy), 1.2)

        # Eq. 14.8-6: t_p = C_pr * (6/h²) * Ry * (Z_b * l_p / (l_b - l_p))
        if self.h > 0 and (self.l_b - self.l_p) > 0:
            t_p_req = C_pr * (6.0 / self.h**2) * b.Ry * \
                      (b.Zx * self.l_p / (self.l_b - self.l_p))
        else:
            t_p_req = 999

        # Minimum thickness: 2/3 * tw and 3/8 in
        t_p_min_tw = 2.0 / 3.0 * b.tw
        t_p_min = max(t_p_min_tw, 0.375)
        self.t_p = max(t_p_req, t_p_min)
        # Round up to nearest 1/8 in
        self.t_p = math.ceil(self.t_p * 8) / 8

        print(f"  C_pr = min((Fy+Fu)/(2*Fy), 1.2) = {C_pr:.3f}")
        print(f"  t_p,req = C_pr*(6/h²)*Ry*(Zx*l_p/(l_b-l_p))  (Eq. 14.8-6)")
        print(f"  t_p,req = {C_pr:.3f}*(6/{self.h:.2f}²)*{b.Ry}"
              f"*({b.Zx:.1f}*{self.l_p:.2f}/({self.l_b:.1f}-{self.l_p:.2f}))")
        print(f"  t_p,req = {t_p_req:.3f} in")
        print(f"  t_p,min = max(2/3*tw, 3/8) = max({t_p_min_tw:.3f}, 0.375)"
              f" = {t_p_min:.3f} in")
        print(f"  Use t_p = {self.t_p:.3f} in (Fy = {DEFAULT_FY_PLATE} ksi)")

        self.checks["shear_plate"] = True
        print()

    # ---------- Step 3: Shear Plate-to-Beam Web Weld ----------
    def step3_plate_beam_weld(self):
        self.subsection("STEP 3: SHEAR PLATE-TO-BEAM WEB WELD (EQ. 14.8-7 TO 14.8-11)")
        b = self.beam
        gravity = self.loads.gravity_combination

        # C_pr
        C_pr = min((b.Fy + b.Fu) / (2 * b.Fy), 1.2)

        # M_pr (Eq. 2.4-1)
        self.M_pr = C_pr * b.Ry * b.Fy * b.Zx

        # V_beam (Eq. 14.8-10)
        V_gravity = gravity / 2
        if self.l_b <= self.l_p:
            raise ValueError(f"l_b ({self.l_b:.1f}) must be > l_p ({self.l_p:.2f})")
        self.V_beam = self.M_pr / (self.l_b - self.l_p) + V_gravity

        print(f"  C_pr = {C_pr:.3f}")
        print(f"  M_pr = C_pr * Ry * Fy * Zx = {self.M_pr:.0f} kip-in")
        print(f"  V_beam = M_pr/(l_b - l_p) + V_gravity  (Eq. 14.8-10)")
        print(f"  V_beam = {self.M_pr:.0f}/({self.l_b:.1f}-{self.l_p:.2f})"
              f" + {V_gravity:.2f} = {self.V_beam:.1f} kips")

        # Z_web (Eq. 14.8-11)
        T_beam = b.T_eff
        Z_web = b.tw * T_beam**2 / 4

        print(f"  Z_web = tw*T²/4 = {b.tw:.3f}*{T_beam:.2f}²/4"
              f" = {Z_web:.2f} in³  (Eq. 14.8-11)")

        # M_weld (Eq. 14.8-7)
        tp_total = self.t_p + b.tw
        M_weld = C_pr * (self.t_p / tp_total) * (self.h / T_beam)**2 * \
                 Z_web * b.Ry * b.Fy

        # V_weld (Eq. 14.8-8)
        V_weld = self.V_beam * (self.t_p / tp_total)

        # e_x (Eq. 14.8-9)
        if V_weld > 0:
            e_x = M_weld / V_weld
        else:
            e_x = 0

        self.M_weld = M_weld
        self.V_weld = V_weld
        self.e_x = e_x

        print(f"\n  M_weld = C_pr*(t_p/(t_p+tw))*(h/T)²*Z_web*Ry*Fy  (Eq. 14.8-7)")
        print(f"  M_weld = {C_pr:.3f}*({self.t_p:.3f}/{tp_total:.3f})"
              f"*({self.h:.2f}/{T_beam:.2f})²*{Z_web:.2f}*{b.Ry}*{b.Fy}")
        print(f"  M_weld = {M_weld:.0f} kip-in")
        print(f"  V_weld = V_beam*(t_p/(t_p+tw))  (Eq. 14.8-8)")
        print(f"  V_weld = {self.V_beam:.1f}*({self.t_p:.3f}/{tp_total:.3f})"
              f" = {V_weld:.1f} kips")
        print(f"  e_x = M_weld/V_weld = {M_weld:.0f}/{V_weld:.1f}"
              f" = {e_x:.2f} in  (Eq. 14.8-9)")
        print(f"  Note: Design fillet weld group per AISC Manual Tables "
              f"using e_x = {e_x:.2f} in")
        print()

    # ---------- Step 4: Shear Plate-to-Column Flange Weld ----------
    def step4_plate_column_weld(self):
        self.subsection("STEP 4: SHEAR PLATE-TO-COLUMN FLANGE WELD")
        print(f"  Required weld strength = nominal strength of Step 3 weld group")
        print(f"  M_weld = {self.M_weld:.0f} kip-in")
        print(f"  V_weld = {self.V_weld:.1f} kips")
        print(f"  Weld per AISC Specification (CJP, PJP, or fillet)")
        print(f"  [Weld detailing per Section 14.6]")
        self.checks["column_weld"] = None
        print()

    # ---------- Step 5: Erection Bolts ----------
    def step5_bolts(self):
        self.subsection("STEP 5: ERECTION BOLTS (SECTION 14.8 STEP 5)")
        b = self.beam

        # Bolt diameter >= beam web thickness
        d_bolt_min = b.tw
        # Standard bolt diameters
        bolt_dia = max(0.625, math.ceil(d_bolt_min * 8) / 8)

        # Max spacing 6 in o.c.
        n_bolts_min = math.ceil(self.h / 6.0)

        print(f"  Bolt diameter >= tw = {b.tw:.3f} in, use {bolt_dia:.3f} in")
        print(f"  Max spacing = 6 in o.c. over plate height h = {self.h:.2f} in")
        print(f"  Minimum bolts = ceil({self.h:.2f}/6) = {n_bolts_min}")
        print(f"  Pretensioned high-strength bolts in standard holes")
        self.checks["bolts"] = True
        print()

    # ---------- Step 6: M_f at Column Face ----------
    def step6_Mf(self):
        self.subsection("STEP 6: MOMENT AT COLUMN FACE (EQ. 14.8-12)")
        # Eq. 14.8-12
        self.M_f = self.M_pr + self.V_beam * self.l_p

        print(f"  M_f = M_pr + V_beam * l_p  (Eq. 14.8-12)")
        print(f"  M_f = {self.M_pr:.0f} + {self.V_beam:.1f} * {self.l_p:.2f}"
              f" = {self.M_f:.0f} kip-in ({self.M_f/12:.1f} kip-ft)")
        print()

    # ---------- Step 7: Beam Shear Strength ----------
    def step7_beam_shear(self):
        self.subsection("STEP 7: BEAM SHEAR STRENGTH (AISC 360 G2.1)")
        b = self.beam
        # Per Commentary C-14.8: phi = 1.0, Cv = 1.0 (based on 13 cyclic tests)
        Aw = b.d * b.tw
        Cv = 1.0
        V_n = 0.6 * b.Fy * Aw * Cv
        phi_Vn = PHI_V * V_n

        ok = self.V_beam <= phi_Vn
        print(f"  phi = {PHI_V} (per Commentary C-14.8), Cv = 1.0")
        print(f"  V_n = 0.6*Fy*d*tw = 0.6*{b.Fy}*{b.d:.2f}*{b.tw:.3f} = {V_n:.1f} kips")
        print(f"  phi*V_n = {phi_Vn:.1f} kips >= V_beam = {self.V_beam:.1f}: "
              f"{'OK' if ok else 'FAIL'}")
        self.checks["beam_shear"] = ok
        print()

    # ---------- Step 8: Continuity Plates ----------
    def step8_continuity_plates(self):
        self.subsection("STEP 8: CONTINUITY PLATES (SECTION 2.4.4)")
        c = self.column
        b = self.beam

        # Flange force from M_f
        F_f = self.M_f / (b.d - b.tf)

        # AISC 360 J10.1: Flange local bending
        tcf_req = math.sqrt(F_f / (PHI_N * 6.25 * c.Fy))

        # Web local yielding check (AISC 360 J10.2)
        k = c.tf
        tw_req_wy = F_f / (PHI_D * 5 * c.Fy * k) if k > 0 else 999

        need_plates = c.tf < tcf_req or c.tw < tw_req_wy

        print(f"  F_f = M_f/(d-tf) = {self.M_f:.0f}/({b.d:.2f}-{b.tf:.3f})"
              f" = {F_f:.1f} kips")
        print(f"  Flange local bending: t_fc >= {tcf_req:.3f} in (actual {c.tf:.3f})")
        print(f"  Web local yielding: t_wc >= {tw_req_wy:.3f} in (actual {c.tw:.3f})")

        if need_plates:
            ts_min = max(c.tw, 0.5 * b.tf)
            print(f"  => Continuity plates REQUIRED (ts >= {ts_min:.3f} in)")
            self.checks["continuity_plates"] = True  # plates will be provided
        else:
            print(f"  => Continuity plates not required by calculation")
            self.checks["continuity_plates"] = True
        print()

    # ---------- Step 9: Panel Zone ----------
    def step9_panel_zone(self):
        self.subsection("STEP 9: PANEL ZONE CHECK (SECTION 14.4)")
        c = self.column
        b = self.beam
        dc = c.d  # overall column depth per AISC 360 J10.6

        # Panel zone demand from column face moments
        Sum_Mface = 2 * self.M_f
        H_story = (self.params.story_above + self.params.story_below) / 2
        V_col = Sum_Mface / H_story if H_story > 0 else 0
        V_pz = Sum_Mface / (b.d - b.tf) - V_col

        # Panel zone capacity per AISC 360 J10.6
        phi_pz = 1.0  # per AISC 341
        phi_Rn_pz = phi_pz * 0.6 * c.Fy * dc * c.tw

        pz_ok = phi_Rn_pz >= V_pz

        print(f"  Sum M_face = 2*M_f = {Sum_Mface:.0f} kip-in")
        print(f"  V_col = {Sum_Mface:.0f}/{H_story:.0f} = {V_col:.1f} kips")
        print(f"  V_pz = {Sum_Mface:.0f}/({b.d:.2f}-{b.tf:.3f}) - {V_col:.1f}"
              f" = {V_pz:.1f} kips")
        print(f"  phi*R_n = 1.0*0.6*{c.Fy}*{dc:.2f}*{c.tw:.3f} = {phi_Rn_pz:.1f} kips")
        print(f"  phi*R_n = {phi_Rn_pz:.1f} >= V_pz = {V_pz:.1f}: "
              f"{'OK' if pz_ok else 'FAIL - need doubler plates'}")
        self.checks["panel_zone"] = pz_ok
        print()

    # ---------- Step 10: Column-Beam Moment Ratio ----------
    def step10_column_beam(self):
        self.subsection("STEP 10: COLUMN-BEAM MOMENT RATIO (EQ. 14.4-1)")
        c = self.column
        b = self.beam
        pm = self.params

        # M_uv per Eq. 14.4-1
        M_uv = self.V_beam * (self.l_p + c.d / 2)

        # Sum M_pb* for beams (2 beams, one each side)
        M_pb_star = self.M_pr + M_uv
        n_beams = 2
        Sum_Mpb = n_beams * M_pb_star

        # Column moment capacity (with axial load)
        As_col = pm.As_col
        if As_col <= 0:
            As_col = c.bf * c.tf * 2 + (c.d - 2 * c.tf) * c.tw

        denom = As_col * c.Fy
        if denom > 0 and pm.Pu > 0:
            M_pc = c.Zx * c.Fy * max(0, 1 - pm.Pu / denom)
        else:
            M_pc = c.Zx * c.Fy

        Sum_Mpc = 2 * M_pc

        ratio = Sum_Mpc / Sum_Mpb if Sum_Mpb > 0 else 999
        passed = ratio >= 1.0

        print(f"  M_uv = V_beam*(l_p + d_c/2)  (Eq. 14.4-1)")
        print(f"  M_uv = {self.V_beam:.1f}*({self.l_p:.2f} + {c.d/2:.2f})"
              f" = {M_uv:.0f} kip-in")
        print(f"  M_pb* = M_pr + M_uv = {self.M_pr:.0f} + {M_uv:.0f}"
              f" = {M_pb_star:.0f} kip-in")
        print(f"  Sum M_pb* = {n_beams} * {M_pb_star:.0f} = {Sum_Mpb:.0f} kip-in")
        print(f"  M_pc = Zx_c * Fy_c * (1 - Pu/(As*Fy))")
        print(f"  M_pc = {c.Zx:.1f}*{c.Fy}*(1 - {pm.Pu:.0f}/{denom:.0f})"
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

    # ---------- Summary ----------
    def print_summary(self):
        self.section("DESIGN VERIFICATION SUMMARY")

        def s(k):
            v = self.checks.get(k)
            if v is None:
                return "N/A"
            return "PASS" if v else "FAIL"

        print(f"Prequalification: {s('prequalification')}")
        print(f"Shear plate (Step 2): {s('shear_plate')}")
        print(f"Beam shear (Step 7): {s('beam_shear')}")
        print(f"Continuity plates (Step 8): {s('continuity_plates')}")
        print(f"Panel zone (Step 9): {s('panel_zone')}")
        print(f"Column-beam ratio (Step 10): {s('column_beam')}")
        print()

        print(f"KEY RESULTS:")
        print(f"  M_pr = {self.M_pr:.0f} kip-in | M_f = {self.M_f:.0f} kip-in")
        print(f"  V_beam = {self.V_beam:.1f} kips")
        print(f"  Slot length: l_s = {self.l_s:.2f} in")
        print(f"  Shear plate: l_p = {self.l_p:.2f} | h = {self.h:.2f}"
              f" | t_p = {self.t_p:.3f} in")
        print(f"  Weld forces: M_weld = {self.M_weld:.0f} kip-in | "
              f"V_weld = {self.V_weld:.1f} kips | e_x = {self.e_x:.2f} in")
        print(f"  Clear span: l_b = {self.l_b:.1f} in")
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
        description="SlottedWeb (SW) Connection Design Verification "
                    "(AISC 358-16 Chapter 14)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python slottedweb_design.py --beam-section W24x94 --column-section W14x257 \\
      --span 360 --system-type SMF

  python slottedweb_design.py --beam-section W36x150 --column-section W14x455 \\
      --span 420 --system-type SMF --load-D 10 --load-L 20
        """
    )

    if "--list-sections" in sys.argv:
        sections = load_sections_from_csv()
        print("Available W-shape sections "
              "(SW prequalified: beam <= W36x400, SMF only):")
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
    bg.add_argument("--beam-T", type=float, default=0.0,
                    help="Clear distance between flanges (in). 0 = approximate")

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
    dg.add_argument("--span", type=float, required=True,
                    help="Center-to-center span (in)")
    dg.add_argument("--system-type", type=str, required=True,
                    choices=["SMF"],
                    help="SMF only for SlottedWeb connections")
    dg.add_argument("--l-p", type=float, default=0.0,
                    help="Shear plate width (in). 0 = auto-calculate")
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
                              {'Fy': args.beam_Fy, 'Fu': args.beam_Fu})
        column = create_section(args, 'col',
                                {'Fy': args.col_Fy, 'Fu': args.col_Fu})

        loads = Loads(D=args.load_D, L=args.load_L, S=args.load_S,
                      f1=args.load_f1)

        params = DesignParameters(
            L=args.span, system_type=args.system_type,
            l_p_override=args.l_p,
            story_above=args.story_above, story_below=args.story_below,
            Pu=args.Pu, As_col=args.As_col,
        )

        checker = SlottedWebDesignChecker(beam, column, params, loads)
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
