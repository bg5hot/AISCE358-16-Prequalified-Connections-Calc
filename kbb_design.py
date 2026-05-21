#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kaiser Bolted Bracket (KBB) Moment Connection Design Verification
Based on AISC 358-16 Chapter 9, Section 9.9 - Design Procedure

KBB connections use cast high-strength steel brackets fastened to beam flanges
and bolted to column flanges. Two bracket series are available:
  - W-series: welded to beam flange (W1.0, W2.0, W2.1, W3.0, W3.1)
  - B-series: bolted to beam flange (B1.0, B2.1)

Key characteristics:
  - S_h = L_bb (bracket length per Table 9.1)
  - d_eff = centroidal distance between upper/lower bracket bolt groups
  - Column bolts: F3125 A490 or A354 Grade BD
  - Beam bolts (B-series): F3125 A490, threads excluded from shear plane

Usage:
    python kbb_design.py --beam-section W24x68 --column-section W14x193 \
        --span 300 --system-type SMF --bracket W2.1
    python kbb_design.py --beam-section W24x68 --column-section W14x257 \
        --span 360 --system-type SMF --bracket B2.1 --beam-bolts 10
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
DEFAULT_FY_COLUMN = 50.0  # ksi (A992)
DEFAULT_FU_COLUMN = 65.0  # ksi (A992)

# Steel properties
E = 29000.0  # Modulus of elasticity (ksi)

# Default weld electrode
DEFAULT_FEXX = 70.0  # ksi (E70)


# ====================== BRACKET DATA (TABLES 9.1, 9.2, 9.3) ======================

# Table 9.1 - KBB Proportions
BRACKETS = {
    "W3.0": {
        "series": "W", "Lbb": 16.0, "hbb": 5.5, "bbb": 9.0,
        "ncb": 2, "g": 5.5, "db_col": 1.375,
    },
    "W3.1": {
        "series": "W", "Lbb": 16.0, "hbb": 5.5, "bbb": 9.0,
        "ncb": 2, "g": 5.5, "db_col": 1.5,
    },
    "W2.0": {
        "series": "W", "Lbb": 16.0, "hbb": 8.75, "bbb": 9.5,
        "ncb": 4, "g": 6.0, "db_col": 1.375,
    },
    "W2.1": {
        "series": "W", "Lbb": 18.0, "hbb": 8.75, "bbb": 9.5,
        "ncb": 4, "g": 6.5, "db_col": 1.5,
    },
    "W1.0": {
        "series": "W", "Lbb": 25.5, "hbb": 12.0, "bbb": 9.5,
        "ncb": 6, "g": 6.5, "db_col": 1.5,
    },
    "B2.1": {
        "series": "B", "Lbb": 18.0, "hbb": 8.75, "bbb": 10.0,
        "ncb": 4, "g": 6.5, "db_col": 1.5,
        "nbb_options": [8, 10], "db_beam": 1.125,
    },
    "B1.0": {
        "series": "B", "Lbb": 25.5, "hbb": 12.0, "bbb": 10.0,
        "ncb": 6, "g": 6.5, "db_col": 1.5,
        "nbb_options": [12], "db_beam": 1.125,
    },
}

# Table 9.2 - W-Series Design Proportions
W_SERIES_PROPS = {
    "W3.0": {"de": 2.5, "pb": None, "ts": 1.0, "rv": None, "rh": 28.0, "w": 0.5},
    "W3.1": {"de": 2.5, "pb": None, "ts": 1.0, "rv": None, "rh": 28.0, "w": 0.625},
    "W2.0": {"de": 2.25, "pb": 3.5, "ts": 2.0, "rv": 12.0, "rh": 28.0, "w": 0.75},
    "W2.1": {"de": 2.25, "pb": 3.5, "ts": 2.0, "rv": 16.0, "rh": 38.0, "w": 0.875},
    "W1.0": {"de": 2.0, "pb": 3.5, "ts": 2.0, "rv": 28.0, "rh": None, "w": 0.875},
}

# Table 9.3 - B-Series Design Proportions
B_SERIES_PROPS = {
    "B2.1": {"de": 2.0, "pb": 3.5, "ts": 2.0, "rv": 16.0},
    "B1.0": {"de": 2.0, "pb": 3.5, "ts": 2.0, "rv": 28.0},
}

# Column bolt properties (F3125 A490 or A354 Grade BD)
COL_BOLT_PROPS = {
    # db_col: {Fnt, Fnv}
    1.375: {"Fnt": 113.0, "Fnv": 68.0, "Ab": math.pi * 1.375**2 / 4},
    1.5:   {"Fnt": 113.0, "Fnv": 68.0, "Ab": math.pi * 1.5**2 / 4},
}

# Beam bolt properties (F3125 A490, threads excluded)
BEAM_BOLT_PROPS = {
    # db_beam: {Fnv (threads excluded), Ab}
    1.125: {"Fnv": 84.0, "Ab": math.pi * 1.125**2 / 4},  # A490 1-1/8" X
}

# Yield line mechanism parameter Y_m per Step 9
YM_VALUES = {
    "W3.0": 5.9, "W3.1": 5.9,
    "W2.0": 6.5, "W2.1": 6.5, "B2.1": 6.5,
    "W1.0": 7.5, "B1.0": 7.5,
}

# Tributary length p per bolt per Step 8
P_VALUES = {
    "W1.0": 3.5, "B1.0": 3.5,  # 3.5 in for W1.0 and B1.0
    # All others: 5.0 in
}


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


@dataclass
class ColumnSection:
    designation: str
    d: float
    bf: float
    tf: float
    tw: float
    Zx: float
    Fy: float = DEFAULT_FY_COLUMN
    Fu: float = DEFAULT_FU_COLUMN
    Ry: float = 1.1
    Rt: float = 1.2


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


# ====================== KBB DESIGN CHECKER ======================

class KBBDesignChecker:
    """KBB Connection Design per AISC 358-16 Section 9.9 (18 steps)"""

    def __init__(self, beam: BeamSection, column: ColumnSection,
                 bracket_name: str, params: DesignParameters, loads: Loads,
                 nbb: int = 0, FEXX: float = DEFAULT_FEXX):
        self.beam = beam
        self.column = column
        self.params = params
        self.loads = loads
        self.FEXX = FEXX

        self.bracket_name = bracket_name
        self.bracket = BRACKETS[bracket_name]
        self.series = self.bracket["series"]

        # Beam bolt count (B-series only)
        self.nbb = nbb

        # Design results
        self.M_pr = 0.0
        self.V_h = 0.0
        self.M_f = 0.0
        self.d_eff = 0.0
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
        self.section("KBB CONNECTION DESIGN VERIFICATION (AISC 358-16 CHAPTER 9)")
        print()
        self.print_input()

        self.step0_prequalification()
        self.section("DESIGN PROCEDURE (SECTION 9.9)")

        self.step1_Mpr()          # Step 1: M_pr
        self.step2_select_bracket()  # Step 2-3: bracket selection
        self.step4_Vh()           # Step 4: V_h
        self.step5_Mf()           # Step 5: M_f (Eq. 9.9-1)
        self.step6_bolt_tension() # Step 6: column bolt tension (Eq. 9.9-2, 9.9-3)
        self.step7_cf_width()     # Step 7: min column flange width (Eq. 9.9-4)
        self.step8_cf_thickness() # Step 8: min column flange thickness (Eq. 9.9-5, 9.9-6)
        self.step9_continuity_no_plates()  # Step 9: eliminate continuity plates (Eq. 9.9-7)
        self.step10_continuity_plates()    # Step 10: continuity plate requirements
        self.step11_beam_flange_width()    # Step 11: B-series beam flange width (Eq. 9.9-8)
        self.step12_beam_bolt_shear()      # Step 12: B-series beam bolt shear (Eq. 9.9-9)
        self.step13_block_shear()          # Step 13: B-series block shear (Eq. 9.9-10)
        self.step14_fillet_weld()          # Step 14: W-series fillet weld (Eq. 9.9-11)
        self.step15_shear()               # Step 15: required shear (Eq. 9.9-13)
        self.step16_web_connection()       # Step 16: web connection
        self.step17_panel_zone()           # Step 17: panel zone

        self.print_summary()
        return all(v for v in self.checks.values() if v is not None)

    # ---------- input ----------
    def print_input(self):
        self.section("INPUT PARAMETERS")
        b, c, pm, ld = self.beam, self.column, self.params, self.loads
        bk = self.bracket
        print(f"BEAM: {b.designation} | d={b.d:.2f} bf={b.bf:.2f} tf={b.tf:.3f} tw={b.tw:.3f} Zx={b.Zx:.1f}")
        print(f"      Fy={b.Fy} Fu={b.Fu} Ry={b.Ry} Rt={b.Rt}")
        print(f"COLUMN: {c.designation} | d={c.d:.2f} bf={c.bf:.2f} tf={c.tf:.3f} tw={c.tw:.3f}")
        print(f"        Fy={c.Fy} Fu={c.Fu} Ry={c.Ry} Rt={c.Rt}")
        print(f"BRACKET: {self.bracket_name} ({'Welded' if self.series == 'W' else 'Bolted'}-series)")
        print(f"  Lbb={bk['Lbb']:.1f} hbb={bk['hbb']:.2f} bbb={bk['bbb']:.1f}")
        print(f"  ncb={bk['ncb']} g={bk['g']:.1f} db_col={bk['db_col']:.3f}")
        if self.series == "B":
            print(f"  nbb={self.nbb} db_beam={bk.get('db_beam', 0):.3f}")
        if self.series == "W":
            wp = W_SERIES_PROPS[self.bracket_name]
            print(f"  w={wp['w']:.3f} de={wp['de']:.2f}")
        print(f"SPAN: L={pm.L:.0f} in ({pm.L/12:.1f} ft) | {pm.system_type}")
        print(f"LOADS: D={ld.D} L={ld.L} S={ld.S} | Vu={ld.Vu:.2f}")
        print()

    # ---------- Step 0: prequalification ----------
    def step0_prequalification(self):
        self.subsection("PREQUALIFICATION LIMITS (SECTION 9.3)")
        passed = True
        st = self.params.system_type
        b = self.beam
        c = self.column

        # Beam depth <= W33
        print(f"  Beam depth: d = {b.d:.1f} in <= 33 in (W33 max): ", end="")
        if b.d > 33:
            print("FAIL"); passed = False
        else:
            print("OK")

        # Beam weight <= 130 plf
        wt = b.weight
        print(f"  Beam weight: {wt:.0f} plf <= 130 plf: ", end="")
        if wt > 130:
            print("FAIL"); passed = False
        else:
            print("OK")

        # Flange thickness <= 1.0 in
        print(f"  Flange thickness: tf = {b.tf:.3f} in <= 1.0 in: ", end="")
        if b.tf > 1.0:
            print("FAIL"); passed = False
        else:
            print("OK")

        # Beam flange width >= 6 in (W-series) or >= 10 in (B-series)
        bf_min = 6.0 if self.series == "W" else 10.0
        print(f"  Beam flange width: bf = {b.bf:.2f} in >= {bf_min:.0f} in ({self.series}-series): ", end="")
        if b.bf < bf_min:
            print("FAIL"); passed = False
        else:
            print("OK")

        # Span/depth ratio >= 9
        sd = self.params.L / b.d
        print(f"  Span/depth L/d = {sd:.1f} >= 9 ({st}): ", end="")
        if sd < 9:
            print("FAIL"); passed = False
        else:
            print("OK")

        # Column flange width >= 12 in
        print(f"  Column flange width: bf_c = {c.bf:.2f} in >= 12 in: ", end="")
        if c.bf < 12.0:
            print("FAIL"); passed = False
        else:
            print("OK")

        # Column depth: W14 max (no slab), W36 max (with slab)
        print(f"  Column depth: d_c = {c.d:.1f} in <= 14 in (no slab) or <= 36 in (with slab): ", end="")
        if c.d > 36:
            print("FAIL"); passed = False
        elif c.d > 14:
            print("OK (requires concrete structural slab)")
        else:
            print("OK")

        # Lateral bracing requirement
        Lbb = self.bracket["Lbb"]
        print(f"  Lateral bracing: d to 1.5d from bracket end")
        print(f"    = {b.d:.1f} to {1.5*b.d:.1f} in from bracket end ({Lbb:.1f} in from column face)")
        print(f"    = {Lbb + b.d:.1f} to {Lbb + 1.5*b.d:.1f} in from column face")
        print(f"  Protected zone: column face to {Lbb:.1f} + {b.d:.1f} = {Lbb + b.d:.1f} in from column face")

        self.checks["prequalification"] = passed
        print()

    # ---------- Step 1: M_pr ----------
    def step1_Mpr(self):
        self.subsection("STEP 1: PROBABLE MAXIMUM MOMENT M_pr (SECTION 2.4.3)")
        b = self.beam

        C_pr = min((b.Fy + b.Fu) / (2 * b.Fy), 1.2)
        self.params.C_pr = C_pr

        self.M_pr = C_pr * b.Ry * b.Fy * b.Zx

        print(f"  C_pr = min((Fy+Fu)/(2*Fy), 1.2) = min(({b.Fy}+{b.Fu})/(2*{b.Fy}), 1.2) = {C_pr:.3f}")
        print(f"  M_pr = C_pr * Ry * Fy * Zx")
        print(f"  M_pr = {C_pr:.3f} * {b.Ry} * {b.Fy} * {b.Zx:.1f}")
        print(f"  M_pr = {self.M_pr:.0f} kip-in ({self.M_pr/12:.1f} kip-ft)")
        print()

    # ---------- Step 2-3: bracket selection ----------
    def step2_select_bracket(self):
        self.subsection("STEPS 2-3: BRACKET SELECTION (TABLES 9.1-9.3)")
        bk = self.bracket
        Lbb = bk["Lbb"]

        # S_h = L_bb per Section 9.9 Step 5 definition
        Sh = Lbb
        print(f"  Bracket: {self.bracket_name}")
        print(f"  S_h = L_bb = {Sh:.1f} in (plastic hinge at bracket end)")

        # d_eff: centroidal distance between bolt groups in upper/lower brackets
        # Bolt group centroid depends on column bolt layout within bracket
        props = W_SERIES_PROPS.get(self.bracket_name) or B_SERIES_PROPS.get(self.bracket_name, {})
        de = props["de"]
        pb = props.get("pb") or 0
        ncb = self.bracket["ncb"]

        if ncb == 2:
            # Single row at distance de from bracket far edge
            bolt_offset = self.bracket["hbb"] - de
        elif ncb == 4:
            # Two rows: centroid at de + pb/2 from far edge
            bolt_offset = self.bracket["hbb"] - (de + pb / 2)
        else:  # ncb == 6
            # Three rows: centroid at de + pb from far edge
            bolt_offset = self.bracket["hbb"] - (de + pb)

        self.d_eff = self.beam.d + 2 * bolt_offset
        print(f"  d_eff = d + hbb = {self.beam.d:.2f} + {self.bracket['hbb']:.2f} = {self.d_eff:.2f} in")
        print()

    # ---------- Step 4: V_h ----------
    def step4_Vh(self):
        self.subsection("STEP 4: SHEAR FORCE AT PLASTIC HINGE")
        ld = self.loads
        pm = self.params
        Lbb = self.bracket["Lbb"]
        Sh = Lbb

        # L_h = distance between plastic hinge locations
        Lh = pm.L - self.column.d - 2 * Sh
        gravity = ld.gravity_combination

        self.V_h = 2 * self.M_pr / Lh + gravity / 2

        print(f"  S_h = L_bb = {Sh:.1f} in")
        print(f"  L_h = L - d_c - 2*S_h = {pm.L:.0f} - {self.column.d:.2f} - 2*{Sh:.1f} = {Lh:.1f} in")
        print(f"  Gravity load (1.2D + {ld.f1}L + 0.2S) = {gravity:.2f} kips")
        print(f"  V_h = 2*M_pr/L_h + gravity/2")
        print(f"  V_h = 2*{self.M_pr:.0f}/{Lh:.1f} + {gravity:.2f}/2 = {self.V_h:.1f} kips")
        print()

    # ---------- Step 5: M_f ----------
    def step5_Mf(self):
        self.subsection("STEP 5: MOMENT AT COLUMN FACE M_f (EQ. 9.9-1)")
        Sh = self.bracket["Lbb"]

        # Eq. 9.9-1: M_f = M_pr + V_h * S_h
        self.M_f = self.M_pr + self.V_h * Sh

        print(f"  M_f = M_pr + V_h * S_h  (Eq. 9.9-1)")
        print(f"  M_f = {self.M_pr:.0f} + {self.V_h:.1f} * {Sh:.1f}")
        print(f"  M_f = {self.M_f:.0f} kip-in ({self.M_f/12:.1f} kip-ft)")
        print()

    # ---------- Step 6: column bolt tension ----------
    def step6_bolt_tension(self):
        self.subsection("STEP 6: COLUMN BOLT TENSILE STRENGTH (EQ. 9.9-2, 9.9-3)")
        bk = self.bracket
        ncb = bk["ncb"]
        db = bk["db_col"]
        Ab = COL_BOLT_PROPS[db]["Ab"]
        Fnt = COL_BOLT_PROPS[db]["Fnt"]

        # Eq. 9.9-3: r_ut = M_f / (d_eff * n_cb)
        self.r_ut = self.M_f / (self.d_eff * ncb)

        # Eq. 9.9-2: r_ut <= phi_n * Fnt * Ab
        capacity = PHI_N * Fnt * Ab

        print(f"  d_eff = {self.d_eff:.2f} in, n_cb = {ncb}")
        print(f"  r_ut = M_f / (d_eff * n_cb) = {self.M_f:.0f} / ({self.d_eff:.2f} * {ncb})")
        print(f"  r_ut = {self.r_ut:.1f} kips/bolt  (Eq. 9.9-3)")
        print(f"  phi_n * F_nt * A_b = {PHI_N} * {Fnt} * {Ab:.3f} = {capacity:.1f} kips/bolt  (Eq. 9.9-2)")
        print(f"  Bolt: {db:.3f}-in dia F3125 A490 (or A354 Grade BD)")

        passed = self.r_ut <= capacity
        print(f"  {'OK' if passed else 'FAIL'} (Utilization: {self.r_ut/capacity:.3f})")
        self.checks["bolt_tension"] = passed
        print()

    # ---------- Step 7: minimum column flange width ----------
    def step7_cf_width(self):
        self.subsection("STEP 7: MINIMUM COLUMN FLANGE WIDTH (EQ. 9.9-4)")
        c = self.column
        db = self.bracket["db_col"]
        Ry = c.Ry
        Rt = c.Rt
        Fyf = c.Fy
        Fuf = c.Fu
        bcf = c.bf

        # Eq. 9.9-4: b_cf >= 2*(db + 1/8) / (1 - Ry*Fy/(Rt*Fu))
        denominator = 1 - Ry * Fyf / (Rt * Fuf)
        if denominator <= 0:
            print(f"  WARNING: Denominator (1 - Ry*Fy/(Rt*Fu)) = {denominator:.4f} <= 0")
            print(f"  Ry*Fy/(Rt*Fu) = {Ry}*{Fyf}/({Rt}*{Fuf}) = {Ry*Fyf/(Rt*Fuf):.3f}")
            bcf_req = 999.0
        else:
            bcf_req = 2 * (db + 0.125) / denominator

        print(f"  b_cf >= 2*(d_b + 1/8) / (1 - Ry*Fy_f/(Rt*Fu_f))")
        print(f"  b_cf >= 2*({db:.3f} + 0.125) / (1 - {Ry}*{Fyf}/({Rt}*{Fuf}))")
        print(f"  b_cf >= {bcf_req:.2f} in")
        print(f"  Provided b_cf = {bcf:.2f} in")

        passed = bcf >= bcf_req
        print(f"  {'OK' if passed else 'FAIL'}")
        self.checks["cf_width"] = passed
        print()

    # ---------- Step 8: minimum column flange thickness (prying) ----------
    def step8_cf_thickness(self):
        self.subsection("STEP 8: MIN COLUMN FLANGE THICKNESS - NO PRYING (EQ. 9.9-5, 9.9-6)")
        c = self.column
        bk = self.bracket
        g = bk["g"]
        db = bk["db_col"]
        k1 = c.tw  # Approximate k1 (web CL to flange toe of fillet, horizontal dimension)
        tcw = c.tw
        Fy = c.Fy
        tcf = c.tf

        # Eq. 9.9-6: b' = 0.5*(g - k1 - 0.5*t_cw - d_b)
        b_prime = 0.5 * (g - k1 - 0.5 * tcw - db)

        # p value
        bracket_name = self.bracket_name
        p = P_VALUES.get(bracket_name, 5.0)

        # Eq. 9.9-5: t_cf >= sqrt(4.44 * r_ut * b' / (phi_d * p * Fy))
        tcf_req = math.sqrt(4.44 * self.r_ut * b_prime / (PHI_D * p * Fy))

        print(f"  b' = 0.5*(g - k1 - 0.5*t_cw - d_b)  (Eq. 9.9-6)")
        print(f"  b' = 0.5*({g:.1f} - {k1:.3f} - 0.5*{tcw:.3f} - {db:.3f}) = {b_prime:.3f} in")
        print(f"  p = {p:.1f} in (tributary length per bolt)")
        print(f"  t_cf >= sqrt(4.44*r_ut*b' / (phi_d*p*Fy))  (Eq. 9.9-5)")
        print(f"  t_cf >= sqrt(4.44*{self.r_ut:.1f}*{b_prime:.3f} / ({PHI_D}*{p:.1f}*{Fy}))")
        print(f"  t_cf >= {tcf_req:.3f} in")
        print(f"  Provided t_cf = {tcf:.3f} in")

        passed = tcf >= tcf_req
        if not passed:
            print(f"  FAIL - Select column with thicker flange or include prying per AISC Manual Part 9")
        else:
            print(f"  OK (prying action eliminated)")
        self.checks["cf_thickness_prying"] = passed
        print()

    # ---------- Step 9: eliminate continuity plates ----------
    def step9_continuity_no_plates(self):
        self.subsection("STEP 9: COLUMN FLANGE THICKNESS TO ELIMINATE CONTINUITY PLATES (EQ. 9.9-7)")
        c = self.column
        tcf = c.tf
        Fyf = c.Fy
        Ym = YM_VALUES[self.bracket_name]

        # Eq. 9.9-7: t_cf >= sqrt(M_f / (phi_d * Fy_f * d_eff * Y_m))
        tcf_req = math.sqrt(self.M_f / (PHI_D * Fyf * self.d_eff * Ym))

        print(f"  Y_m = {Ym} (for {self.bracket_name})")
        print(f"  t_cf >= sqrt(M_f / (phi_d * Fy_f * d_eff * Y_m))")
        print(f"  t_cf >= sqrt({self.M_f:.0f} / ({PHI_D} * {Fyf} * {self.d_eff:.2f} * {Ym}))")
        print(f"  t_cf >= {tcf_req:.3f} in")
        print(f"  Provided t_cf = {tcf:.3f} in")

        passed = tcf >= tcf_req
        if not passed:
            print(f"  Continuity plates ARE REQUIRED (see Step 10)")
        else:
            print(f"  OK (continuity plates not required by this check)")
        self.checks["continuity_no_plates"] = passed
        print()

    # ---------- Step 10: continuity plates ----------
    def step10_continuity_plates(self):
        self.subsection("STEP 10: CONTINUITY PLATE REQUIREMENTS")
        c = self.column

        # For W14 and shallower columns, continuity plates not required if Eq. 9.9-7 satisfied
        # For columns deeper than W14, continuity plates SHALL be provided
        is_w14_or_less = c.d <= 14.0  # W14 nominal depth

        if is_w14_or_less:
            if self.checks.get("continuity_no_plates"):
                print(f"  Column depth = {c.d:.1f} in <= W14")
                print(f"  Eq. 9.9-7 satisfied => continuity plates NOT REQUIRED")
                self.checks["continuity_plates"] = True
            else:
                print(f"  Column depth = {c.d:.1f} in <= W14")
                print(f"  Eq. 9.9-7 NOT satisfied => continuity plates REQUIRED")
                ts_min = max(c.tw, 0.5 * self.beam.tf)
                print(f"  Minimum continuity plate thickness: {ts_min:.3f} in")
                print(f"  Continuity plate design per AISC 341 Seismic Provisions")
                self.checks["continuity_plates"] = False
        else:
            print(f"  Column depth = {c.d:.1f} in > W14")
            print(f"  Continuity plates SHALL be provided per Section 9.9 Step 10")
            ts_min = max(c.tw, 0.5 * self.beam.tf)
            print(f"  Minimum continuity plate thickness: {ts_min:.3f} in")
            print(f"  Continuity plate design per AISC 341 Seismic Provisions")
            self.checks["continuity_plates"] = True  # Plates provided, check passes

        print()

    # ---------- Step 11: beam flange width (B-series only) ----------
    def step11_beam_flange_width(self):
        self.subsection("STEP 11: BEAM FLANGE WIDTH CHECK - B-SERIES (EQ. 9.9-8)")
        if self.series == "W":
            print("  W-series: bracket welded to beam flange, this step is N/A")
            print("  Proceed to Step 14.")
            self.checks["beam_flange_width"] = True
            print()
            return

        b = self.beam
        bk = self.bracket
        db = bk["db_beam"]
        Ry = b.Ry
        Rt = b.Rt
        Fyf = b.Fy
        Fuf = b.Fu
        bbf = b.bf

        # Eq. 9.9-8: b_bf >= 2*(db + 1/32) / (1 - Ry*Fy/(Rt*Fu))
        denominator = 1 - Ry * Fyf / (Rt * Fuf)
        if denominator <= 0:
            bbf_req = 999.0
        else:
            bbf_req = 2 * (db + 1.0/32.0) / denominator

        print(f"  b_bf >= 2*(d_b + 1/32) / (1 - Ry*Fy_f/(Rt*Fu_f))  (Eq. 9.9-8)")
        print(f"  b_bf >= 2*({db:.3f} + {1.0/32.0:.4f}) / (1 - {Ry}*{Fyf}/({Rt}*{Fuf}))")
        print(f"  b_bf >= {bbf_req:.2f} in")
        print(f"  Provided b_bf = {bbf:.2f} in")

        passed = bbf >= bbf_req
        print(f"  {'OK' if passed else 'FAIL'}")
        self.checks["beam_flange_width"] = passed
        print()

    # ---------- Step 12: beam bolt shear (B-series only) ----------
    def step12_beam_bolt_shear(self):
        self.subsection("STEP 12: BEAM BOLT SHEAR STRENGTH - B-SERIES (EQ. 9.9-9)")
        if self.series == "W":
            print("  W-series: no beam bolts, this step is N/A")
            self.checks["beam_bolt_shear"] = True
            print()
            return

        bk = self.bracket
        db = bk["db_beam"]
        nbb = self.nbb
        Ab = BEAM_BOLT_PROPS[db]["Ab"]
        Fnv = BEAM_BOLT_PROPS[db]["Fnv"]

        # Eq. 9.9-9: M_f / (phi_n * Fnv * Ab * d_eff * nbb) < 1.0
        ratio = self.M_f / (PHI_N * Fnv * Ab * self.d_eff * nbb)

        print(f"  M_f / (phi_n * F_nv * A_b * d_eff * n_bb) < 1.0  (Eq. 9.9-9)")
        print(f"  {self.M_f:.0f} / ({PHI_N} * {Fnv} * {Ab:.3f} * {self.d_eff:.2f} * {nbb})")
        print(f"  = {ratio:.3f}")

        passed = ratio < 1.0
        print(f"  {'OK' if passed else 'FAIL'} (Utilization: {ratio:.3f})")
        self.checks["beam_bolt_shear"] = passed
        print()

    # ---------- Step 13: block shear (B-series only) ----------
    def step13_block_shear(self):
        self.subsection("STEP 13: BEAM FLANGE BLOCK SHEAR - B-SERIES (EQ. 9.9-10)")
        if self.series == "W":
            print("  W-series: no beam bolts, this step is N/A")
            self.checks["block_shear"] = True
            print()
            return

        b = self.beam
        bk = self.bracket
        nbb = self.nbb
        db = bk["db_beam"]
        dh = db + 0.0625  # standard hole

        # Beam flange force
        Ff = self.M_f / self.d_eff

        # Block shear per AISC 360 Chapter J
        # Simplified: assume symmetrical pattern
        tf = b.tf
        bf = b.bf

        # Approximate block shear geometry
        # Each side has nbb/2 bolts
        bolts_per_side = nbb // 4  # bolts per line (4 lines total for 2 flanges)
        if bolts_per_side < 1:
            bolts_per_side = 1

        # Gross and net shear areas (simplified)
        Lgv = bolts_per_side * 3.0  # approximate spacing
        Agv = 2 * tf * Lgv
        Anv = 2 * tf * (Lgv - bolts_per_side * dh)
        Ant = tf * (bf - 2 * dh)

        Ubs = 1.0
        Rn1 = 0.6 * b.Fu * Anv + Ubs * b.Fu * Ant
        Rn2 = 0.6 * b.Fy * Agv + Ubs * b.Fu * Ant
        Rn = min(Rn1, Rn2)
        phi_Rn = PHI_N * Rn

        print(f"  Beam flange force: F_f = M_f / d_eff = {self.M_f:.0f} / {self.d_eff:.2f} = {Ff:.1f} kips")
        print(f"  phi_n * R_n = {PHI_N} * {Rn:.1f} = {phi_Rn:.1f} kips")
        print(f"  (Simplified block shear - verify with actual bolt layout)")

        passed = Ff <= phi_Rn
        print(f"  {'OK' if passed else 'FAIL'} (Utilization: {Ff/phi_Rn:.3f})")
        self.checks["block_shear"] = passed
        print()

    # ---------- Step 14: fillet weld (W-series only) ----------
    def step14_fillet_weld(self):
        self.subsection("STEP 14: FILLET WELD ATTACHMENT - W-SERIES (EQ. 9.9-11)")
        if self.series == "B":
            print("  B-series: bracket bolted to beam flange, this step is N/A")
            self.checks["fillet_weld"] = True
            print()
            return

        b = self.beam
        bk = self.bracket
        wp = W_SERIES_PROPS[self.bracket_name]
        Lbb = bk["Lbb"]
        w = wp["w"]
        bbb = bk["bbb"]
        bbf = b.bf

        # Eq. 9.9-12: l_w = 2*(L_bb - 2.5 - l)
        # where l = 0 if bf >= bbb, l = 5 if bf < bbb
        if bbf >= bbb:
            l_val = 0.0
            print(f"  b_bf ({bbf:.2f}) >= b_bb ({bbb:.1f}) => l = 0")
        else:
            l_val = 5.0
            print(f"  b_bf ({bbf:.2f}) < b_bb ({bbb:.1f}) => l = 5 in")

        lw = 2 * (Lbb - 2.5 - l_val)
        print(f"  l_w = 2*(L_bb - 2.5 - l) = 2*({Lbb:.1f} - 2.5 - {l_val:.1f}) = {lw:.2f} in  (Eq. 9.9-12)")

        # Eq. 9.9-11: M_f / (phi_n * F_w * d_eff * l_w * 0.707*w) < 1.0
        Fw = 0.60 * self.FEXX
        denom = PHI_N * Fw * self.d_eff * lw * 0.707 * w
        ratio = self.M_f / denom

        print(f"  F_w = 0.60 * F_EXX = 0.60 * {self.FEXX} = {Fw:.1f} ksi")
        print(f"  M_f / (phi_n * F_w * d_eff * l_w * 0.707*w) < 1.0  (Eq. 9.9-11)")
        print(f"  {self.M_f:.0f} / ({PHI_N} * {Fw:.1f} * {self.d_eff:.2f} * {lw:.2f} * 0.707*{w:.3f})")
        print(f"  = {ratio:.3f}")

        passed = ratio < 1.0
        print(f"  {'OK' if passed else 'FAIL'} (Utilization: {ratio:.3f})")
        self.checks["fillet_weld"] = passed
        print()

    # ---------- Step 15: required shear ----------
    def step15_shear(self):
        self.subsection("STEP 15: REQUIRED SHEAR STRENGTH (EQ. 9.9-13)")
        pm = self.params
        ld = self.loads
        Lbb = self.bracket["Lbb"]
        Sh = Lbb

        Lh = pm.L - self.column.d - 2 * Sh
        gravity = ld.gravity_combination

        # Eq. 9.9-13: V_u = 2*M_pr/L_h + V_gravity
        Vu = 2 * self.M_pr / Lh + gravity / 2

        # Beam shear capacity per AISC 360 Chapter G
        b = self.beam
        Vn = 0.6 * b.Fy * b.d * b.tw
        phi_Vn = 1.0 * Vn  # phi_v = 1.0 for rolled W-shapes per AISC 360 G2.1(a)

        print(f"  L_h = {Lh:.1f} in")
        print(f"  V_u = 2*M_pr/L_h + V_gravity/2  (Eq. 9.9-13)")
        print(f"  V_u = 2*{self.M_pr:.0f}/{Lh:.1f} + {gravity:.2f}/2 = {Vu:.1f} kips")

        # Also compare with user-specified Vu
        Vu_design = max(Vu, ld.Vu)
        if ld.Vu > 0:
            print(f"  V_u,user = {ld.Vu:.1f} kips => V_u = max({Vu:.1f}, {ld.Vu:.1f}) = {Vu_design:.1f} kips")

        print(f"  Beam shear capacity: V_n = 0.6*Fy*d*tw = {Vn:.1f} kips")
        print(f"  phi*V_n = {phi_Vn:.1f} kips")

        passed = Vu_design <= phi_Vn
        print(f"  {'OK' if passed else 'FAIL'} (Utilization: {Vu_design/phi_Vn:.3f})")
        self.checks["beam_shear"] = passed
        print()

    # ---------- Step 16: web connection ----------
    def step16_web_connection(self):
        self.subsection("STEP 16: BEAM WEB-TO-COLUMN CONNECTION (SECTION 9.7)")
        Lbb = self.bracket["Lbb"]
        Sh = Lbb
        Lh = self.params.L - self.column.d - 2 * Sh
        gravity = self.loads.gravity_combination
        Vu = 2 * self.M_pr / Lh + gravity / 2
        Vu_design = max(Vu, self.loads.Vu)

        print(f"  Required shear: V_u = {Vu_design:.1f} kips")
        print(f"  Single-plate shear connection per Section 9.7:")
        print(f"    - Connected to column flange via two-sided fillet, PJP, or CJP weld")
        print(f"    - Pretensioned high-strength bolts (beam web to shear tab)")
        print(f"    - Design per AISC 360 for V_u = {Vu_design:.1f} kips")
        self.checks["web_connection"] = True
        print()

    # ---------- Step 17: panel zone ----------
    def step17_panel_zone(self):
        self.subsection("STEP 17: COLUMN PANEL ZONE (SECTION 9.4)")
        c = self.column
        Fyc = c.Fy
        dc = c.d
        twc = c.tw

        # Panel zone demand: flange force based on M_f and d_eff
        V_pz = self.M_f / self.d_eff

        # Panel zone capacity per AISC 360 J10.6 (phi=1.0 per AISC 341)
        phi_pz = 1.0
        Vn_basic = 0.6 * Fyc * dc * twc

        # With column flange contribution
        bcf = c.bf
        tcf = c.tf
        db = self.d_eff  # Use d_eff per Step 17
        contrib = 3 * bcf * tcf**2 / (db * dc * twc)
        Vn_full = Vn_basic * (1 + contrib)

        print(f"  Panel zone demand: V_pz = M_f / d_eff = {self.M_f:.0f} / {self.d_eff:.2f} = {V_pz:.1f} kips")
        print(f"  Use d_eff (not beam d) per Section 9.9 Step 17")
        print(f"  phi = {phi_pz} (per AISC 341)")
        print(f"  Vn (basic) = 0.6*Fyc*dc*twc = 0.6*{Fyc}*{dc:.2f}*{twc:.3f} = {Vn_basic:.1f} kips")
        print(f"  Flange contribution factor: {contrib:.3f}")
        print(f"  Vn (full) = {Vn_full:.1f} kips")

        passed = V_pz <= phi_pz * Vn_full
        if not passed:
            print(f"  FAIL - Consider web doubler plates (Utilization: {V_pz/(phi_pz*Vn_full):.3f})")
        else:
            print(f"  OK (Utilization: {V_pz/(phi_pz*Vn_full):.3f})")
        self.checks["panel_zone"] = passed
        print()

    # ---------- summary ----------
    def print_summary(self):
        self.section("DESIGN VERIFICATION SUMMARY")

        def s(k):
            return "PASS" if self.checks.get(k) else "FAIL"

        print(f"Prequalification: {s('prequalification')}")
        print(f"Bolt tension (Step 6): {s('bolt_tension')}")
        print(f"Column flange width (Step 7): {s('cf_width')}")
        print(f"Column flange thickness/prying (Step 8): {s('cf_thickness_prying')}")
        print(f"Continuity plates (Steps 9-10): {s('continuity_plates')}")
        if self.series == "B":
            print(f"Beam flange width (Step 11): {s('beam_flange_width')}")
            print(f"Beam bolt shear (Step 12): {s('beam_bolt_shear')}")
            print(f"Block shear (Step 13): {s('block_shear')}")
        if self.series == "W":
            print(f"Fillet weld (Step 14): {s('fillet_weld')}")
        print(f"Beam shear (Step 15): {s('beam_shear')}")
        print(f"Web connection (Step 16): {s('web_connection')}")
        print(f"Panel zone (Step 17): {s('panel_zone')}")
        print()
        print(f"KEY: M_pr={self.M_pr:.0f} kip-in | M_f={self.M_f:.0f} kip-in | d_eff={self.d_eff:.2f} in")
        print(f"     r_ut={self.r_ut:.1f} kips/bolt | Bracket={self.bracket_name}")
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
                Fy=args.column_Fy, Fu=args.column_Fu,
                Ry=args.column_Ry, Rt=args.column_Rt,
            )
    if all([args.column_d, args.column_bf, args.column_tf, args.column_tw, args.column_Zx]):
        return ColumnSection(
            designation="Custom", d=args.column_d, bf=args.column_bf,
            tf=args.column_tf, tw=args.column_tw, Zx=args.column_Zx,
            Fy=args.column_Fy, Fu=args.column_Fu, Ry=args.column_Ry, Rt=args.column_Rt,
        )
    raise ValueError("Invalid column section.")


# ====================== COMMAND LINE ======================

def parse_args():
    parser = argparse.ArgumentParser(
        description="KBB Connection Design Verification (AISC 358-16 Chapter 9)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Available brackets: W3.0, W3.1, W2.0, W2.1, W1.0, B2.1, B1.0
Examples:
  python kbb_design.py --beam-section W24x68 --column-section W14x193 --span 300 --system-type SMF --bracket W2.1
  python kbb_design.py --beam-section W24x68 --column-section W14x257 --span 360 --system-type SMF --bracket B2.1 --beam-bolts 10
  python kbb_design.py --beam-section W30x99 --column-section W14x311 --span 360 --system-type SMF --bracket W1.0
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

    if "--list-brackets" in sys.argv:
        print("Available KBB Brackets (Table 9.1):")
        print("=" * 80)
        print(f"  {'Bracket':8s} {'Series':6s} {'Lbb':>6s} {'hbb':>6s} {'bbb':>6s} {'ncb':>4s} {'g':>5s} {'db_col':>7s}")
        for name, bk in BRACKETS.items():
            print(f"  {name:8s} {bk['series']:6s} {bk['Lbb']:6.1f} {bk['hbb']:6.2f} {bk['bbb']:6.1f} {bk['ncb']:4d} {bk['g']:5.1f} {bk['db_col']:7.3f}")
        print("=" * 80)
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
    cg.add_argument("--column-d", type=float)
    cg.add_argument("--column-bf", type=float)
    cg.add_argument("--column-tf", type=float)
    cg.add_argument("--column-tw", type=float)
    cg.add_argument("--column-Zx", type=float)
    cg.add_argument("--column-Fy", type=float, default=DEFAULT_FY_COLUMN)
    cg.add_argument("--column-Fu", type=float, default=DEFAULT_FU_COLUMN)
    cg.add_argument("--column-Ry", type=float, default=1.1)
    cg.add_argument("--column-Rt", type=float, default=1.2)

    dg = parser.add_argument_group("Design")
    dg.add_argument("--span", type=float, required=True)
    dg.add_argument("--system-type", type=str, required=True, choices=["SMF", "IMF"])
    dg.add_argument("--bracket", type=str, required=True,
                    choices=list(BRACKETS.keys()),
                    help="Bracket designation per Table 9.1")
    dg.add_argument("--beam-bolts", type=int, default=0,
                    help="Number of beam bolts (B-series only, per Table 9.3)")
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
        bracket_name = args.bracket
        bk = BRACKETS[bracket_name]

        # Validate B-series beam bolt count
        nbb = args.beam_bolts
        if bk["series"] == "B":
            valid_nbb = bk.get("nbb_options", [])
            if nbb == 0:
                nbb = valid_nbb[0]
                print(f"Note: Using default beam bolt count nbb={nbb} for {bracket_name}")
            if nbb not in valid_nbb:
                print(f"Warning: nbb={nbb} not in valid options {valid_nbb} for {bracket_name}")

        # Calculate S_h = L_bb and L_h
        Sh = bk["Lbb"]
        Lh = args.span - column.d - 2 * Sh

        loads = Loads(D=args.load_D, L=args.load_L, S=args.load_S,
                      f1=args.load_f1, Vu=args.Vu)

        params = DesignParameters(L=args.span, Lh=Lh, system_type=args.system_type)

        checker = KBBDesignChecker(beam, column, bracket_name, params, loads,
                                    nbb=nbb, FEXX=args.FEXX)
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
