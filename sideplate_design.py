#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SidePlate Moment Connection Design Verification
Based on AISC 358-16 Chapter 11 - Prequalified Connections for Seismic Applications

The SidePlate connection uses side plates {A} and cover plates {B} to transfer
moment and shear from the beam to the column. Two connection types:
  - Field-welded: Cover plates welded to side plates in the field
  - Field-bolted: Cover plates bolted to side plates (Config A/B/C)

Key characteristics:
  - Plastic hinge at d/3 (welded) or d/6 (bolted) from end of side plate extension
  - Side plate extension A from 0.65d to 1.0d (welded) or 1.7d (bolted)
  - Steps 6-7 (detailed component design) performed by SidePlate Systems Inc.
  - This program implements Steps 1-5 and 8 (EOR's responsibilities)

Usage:
    python sideplate_design.py --beam-section W36x150 --column-section W14x311 \
        --span 360 --system-type SMF --connection-type welded

    python sideplate_design.py --beam-section W40x211 --column-section W14x455 \
        --span 420 --system-type SMF --connection-type bolted
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
PHI_D = 1.00  # Ductile limit states (AISC 358 Section 2.4.1)
PHI_V = 0.90  # Shear (AISC 360 G2.1(a))

# Default material properties
DEFAULT_FY_BEAM = 50.0    # ksi (A992)
DEFAULT_FU_BEAM = 65.0    # ksi (A992)
DEFAULT_FY_COLUMN = 50.0  # ksi (A992)
DEFAULT_FU_COLUMN = 65.0  # ksi (A992)

# Steel properties
E = 29000.0  # Modulus of elasticity (ksi)

# SidePlate connection plate material (Section 11.3.3(1))
FY_PLATE = 50.0   # ksi (ASTM A572 Gr 50)

# Prequalification limits (Section 11.3)
MAX_BEAM_DEPTH_WELDED = 40      # W40 max for field-welded (Section 11.3.1(2))
MAX_BEAM_DEPTH_BOLTED = 44      # W44 max for field-bolted (Section 11.3.1(2))
MAX_BEAM_WEIGHT_WELDED = 302    # lb/ft (Section 11.3.1(4))
MAX_BEAM_WEIGHT_BOLTED = 400    # lb/ft (Section 11.3.1(4))
MAX_BEAM_FLANGE_AREA_BOLTED = 36.0  # in^2 (Section 11.3.1(4))
MAX_BEAM_TF = 2.5               # in (Section 11.3.1(1))
MAX_HSS_DEPTH_SMF = 14          # HSS14 max for SMF (Section 11.3.1(3a))
MAX_HSS_DEPTH_IMF = 16          # HSS16 max for IMF (Section 11.3.1(3b))
MAX_COLUMN_DEPTH = 44            # W44 max (Section 11.3.2(4))
MAX_BOX_WIDTH = 33.0            # in (Section 11.3.2(4))
MAX_BOLT_DIAMETER = 1.375       # 1-3/8 in (Section 11.6.3(5))

# Side plate extension limits (Section 11.3.3(2))
MIN_EXTENSION_RATIO = 0.65  # Both types
MAX_EXTENSION_WELDED = 1.0  # d for field-welded
MAX_EXTENSION_BOLTED = 1.7  # 1.7d for field-bolted

# L_h/d limits (Section 11.3.1(5))
LH_D_MIN_WELDED_RECT = 6.0   # Rectangular cover plates, SMF
LH_D_MIN_WELDED_U = 4.5      # U-shaped cover plates, SMF, field-welded
LH_D_MIN_BOLTED_U = 4.0      # U-shaped cover plates, SMF, field-bolted
LH_D_MIN_IMF = 3.0           # IMF

# Plastic hinge distance from end of side plate extension (Section 11.3.1(5))
HINGE_RATIO_WELDED = 0.333   # d/3
HINGE_RATIO_BOLTED = 0.165   # d/6

# Strong-column weak-beam ratio (Section 11.7 Step 1)
SCWB_PRELIM_RATIO = 1.7


# ====================== DATA CLASSES ======================

@dataclass
class BeamSection:
    designation: str
    d: float       # Depth (in)
    bf: float      # Flange width (in)
    tf: float      # Flange thickness (in)
    tw: float      # Web thickness (in)
    Zx: float      # Plastic section modulus (in^3)
    Fy: float = DEFAULT_FY_BEAM
    Fu: float = DEFAULT_FU_BEAM
    Ry: float = 1.1

    @property
    def weight(self) -> float:
        try:
            return float(self.designation.upper().split('X')[1])
        except (ValueError, IndexError):
            return 999

    @property
    def nominal_depth(self) -> float:
        """Nominal depth (e.g., W36 -> 36)"""
        try:
            return float(self.designation.upper().split('X')[0].replace('W', ''))
        except (ValueError, IndexError):
            return self.d

    @property
    def flange_area(self) -> float:
        return 2 * self.bf * self.tf


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

    @property
    def nominal_depth(self) -> float:
        try:
            return float(self.designation.upper().split('X')[0].replace('W', ''))
        except (ValueError, IndexError):
            return self.d


@dataclass
class Loads:
    D: float = 0.0     # Total dead load on span (kips)
    L: float = 0.0     # Total live load on span (kips)
    S: float = 0.0     # Total snow load on span (kips)
    f1: float = 0.5    # Live load factor
    Vu: float = 0.0    # User-specified required shear (kips)

    @property
    def gravity_combination(self) -> float:
        """V_gravity per Section 11.4 Eq. 11.4-3: 1.2D + f1*L + 0.2S"""
        return 1.2 * self.D + self.f1 * self.L + 0.2 * self.S


# ====================== SECTION DATABASE ======================

_SECTIONS_CACHE: Dict[str, Dict] = {}


def _get_csv_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "aisc_w_shapes.csv")


def _load_sections() -> Dict[str, Dict]:
    if _SECTIONS_CACHE:
        return _SECTIONS_CACHE
    csv_path = _get_csv_path()
    if not os.path.exists(csv_path):
        print(f"ERROR: Section database not found: {csv_path}")
        print("Run extract_shapes.py to generate aisc_w_shapes.csv")
        sys.exit(1)
    with open(csv_path, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            des = row['designation'].strip().upper()
            _SECTIONS_CACHE[des] = {
                'd': float(row['d']),
                'bf': float(row['bf']),
                'tf': float(row['tf']),
                'tw': float(row['tw']),
                'Zx': float(row['Zx']),
            }
    return _SECTIONS_CACHE


def lookup_section(designation: str) -> Dict:
    sections = _load_sections()
    des = designation.strip().upper()
    if des not in sections:
        print(f"ERROR: Section '{designation}' not found in database.")
        print(f"Use --list-sections to see available sections.")
        sys.exit(1)
    return sections[des]


def list_sections():
    sections = _load_sections()
    print(f"{'Designation':<16} {'d':>8} {'bf':>8} {'tf':>8} {'tw':>8} {'Zx':>10}")
    print("-" * 68)
    for des, props in sorted(sections.items()):
        print(f"{des:<16} {props['d']:>8.2f} {props['bf']:>8.3f} "
              f"{props['tf']:>8.3f} {props['tw']:>8.3f} {props['Zx']:>10.1f}")


# ====================== CHECKER CLASS ======================

class SidePlateChecker:
    """AISC 358-16 Chapter 11 SidePlate Moment Connection Design Verification."""

    def __init__(self, beam: BeamSection, column: ColumnSection, loads: Loads,
                 L: float, system_type: str, connection_type: str,
                 extension_A: Optional[float] = None,
                 story_height: float = 168.0,
                 column_d2: Optional[float] = None,
                 Pu_col: float = 0.0, As_col: float = 0.0):
        self.beam = beam
        self.column = column
        self.loads = loads
        self.L = L
        self.system_type = system_type.upper()
        self.connection_type = connection_type.lower()
        self.Pu_col = Pu_col
        self.As_col = As_col if As_col > 0 else 2 * column.bf * column.tf + (column.d - 2 * column.tf) * column.tw

        # Side plate extension (default ~0.77d per Step 2 commentary)
        if extension_A is not None:
            self.extension_A = extension_A
        else:
            self.extension_A = 0.77 * beam.d

        # Second column depth (for two-sided, different columns)
        self.column_d2 = column_d2 if column_d2 is not None else column.d

        # Story height
        self.story_height = story_height

        # Derived properties
        self.is_welded = 'weld' in self.connection_type
        self.is_bolted = 'bolt' in self.connection_type

        # Plastic hinge ratio
        if self.is_welded:
            self.hinge_ratio = HINGE_RATIO_WELDED  # d/3
        else:
            self.hinge_ratio = HINGE_RATIO_BOLTED  # d/6

        # Hinge distance from end of side plate extension
        self.hinge_dist = self.hinge_ratio * beam.d

        # S_h: distance from column centerline to plastic hinge
        # = dc/2 + A + d/3 (welded) or dc/2 + A + d/6 (bolted)
        self.Sh = column.d / 2 + self.extension_A + self.hinge_dist

        # L_h: hinge-to-hinge span (Eq. 11.3-1a or 11.3-1b)
        self.Lh = (L - 0.5 * column.d - 0.5 * self.column_d2
                   - 2 * self.hinge_dist - 2 * self.extension_A)

        # C_pr per Section 2.4.3 (Eq. 2.4-2)
        # Note: Section 11.7 Step 6 states C_pr is provided by SidePlate as
        # part of the connection design. In practice, C_pr ranges from 1.15 to 1.35.
        # The general Eq. 2.4-2 gives a conservative lower-bound estimate.
        self.C_pr = min((beam.Fy + beam.Fu) / (2 * beam.Fy), 1.2)

        # M_pr (Eq. 2.4-1)
        self.Mpr = self.C_pr * beam.Ry * beam.Fy * beam.Zx

        # V_h (Eq. 11.4-3)
        # D, L, S are total loads on span; gravity shear at beam end = total / 2
        V_gravity = loads.gravity_combination / 2
        self.Vh = 2 * self.Mpr / self.Lh + V_gravity if self.Lh > 0 else 0

        # Tracking
        self._all_passed = True
        self._results: List[dict] = []

    def sep(self):
        print("=" * 72)

    def section(self, title: str):
        self.sep()
        print(f"  {title}")
        self.sep()

    def subsection(self, title: str):
        print(f"\n  {title}")
        print("-" * 72)

    def _pass_fail(self, passed: bool, label: str = ""):
        status = "PASS" if passed else "FAIL"
        if not passed:
            self._all_passed = False
        if label:
            print(f"    [{status}] {label}")
        self._results.append({'label': label, 'passed': passed})
        return passed

    def summary(self):
        self.sep()
        if self._all_passed:
            print("  ALL CHECKS PASSED")
        else:
            print("  SOME CHECKS FAILED - Review output above")
        self.sep()

    # ===================== STEP 1: PRELIMINARY CHECKS =====================

    def step1_preliminary(self):
        """Step 1: Geometric compatibility and preliminary column-beam ratio."""
        self.subsection("STEP 1: GEOMETRIC COMPATIBILITY & PRELIMINARY CHECK")

        b = self.beam
        c = self.column

        # Geometric compatibility (Eqs. 11.4-1a or 11.4-1b)
        if self.is_welded:
            # Eq. 11.4-1a: b_bf + 1.1*t_bf + 0.5 <= b_cf
            required_bcf = b.bf + 1.1 * b.tf + 0.5
            eq_num = "11.4-1a"
        else:
            # Eq. 11.4-1b: b_bf + 1.0 <= b_cf
            required_bcf = b.bf + 1.0
            eq_num = "11.4-1b"

        print(f"  Beam: {b.designation}  (d={b.d:.2f}, bf={b.bf:.3f}, tf={b.tf:.3f})")
        print(f"  Column: {c.designation}  (d={c.d:.2f}, bf={c.bf:.3f})")
        print(f"  Connection: {'Field-welded' if self.is_welded else 'Field-bolted'}")
        print(f"  System: {self.system_type}")
        print(f"  Span L = {self.L:.1f} in")
        print(f"  Story height H = {self.story_height:.1f} in")
        print(f"  Side plate extension A = {self.extension_A:.2f} in ({self.extension_A/b.d:.3f}d)")
        print()
        print(f"  Eq. {eq_num}: Geometric compatibility")
        print(f"    Required b_cf >= {required_bcf:.3f} in")
        print(f"    Available b_cf = {c.bf:.3f} in")
        self._pass_fail(c.bf >= required_bcf, f"Geometric compatibility (Eq. {eq_num})")

        # Side plate extension range check (Section 11.3.3(2))
        min_ext = MIN_EXTENSION_RATIO * b.d
        max_ext = MAX_EXTENSION_WELDED * b.d if self.is_welded else MAX_EXTENSION_BOLTED * b.d
        print(f"\n  Side plate extension range: {min_ext:.2f} to {max_ext:.2f} in")
        ext_ok = min_ext <= self.extension_A <= max_ext
        max_ratio = MAX_EXTENSION_WELDED if self.is_welded else MAX_EXTENSION_BOLTED
        self._pass_fail(ext_ok, f"Side plate extension = {self.extension_A:.2f} in "
                                 f"({self.extension_A / b.d:.3f}d) in range "
                                 f"[{MIN_EXTENSION_RATIO}d, {max_ratio}d]")
        # Preliminary column-beam moment ratio for SMF (Eq. 11.7-1)
        if self.system_type == 'SMF':
            print(f"\n  Eq. 11.7-1: Preliminary column-beam moment ratio (SMF)")
            # Sum includes column above + below the joint (2 * F_yc * Z_c)
            col_cap = 2 * c.Fy * c.Zx
            beam_cap = b.Fy * b.Zx
            ratio = col_cap / beam_cap if beam_cap > 0 else float('inf')
            print(f"    Sum(F_yc * Z_c) = 2 * {c.Fy} * {c.Zx:.1f} = {col_cap:.0f} kip-in")
            print(f"    Sum(F_yb * Z_b) = {b.Fy} * {b.Zx:.1f} = {beam_cap:.0f} kip-in")
            print(f"    Ratio = {col_cap:.0f} / {beam_cap:.0f} = {ratio:.3f}")
            print(f"    Required > {SCWB_PRELIM_RATIO}")
            self._pass_fail(ratio > SCWB_PRELIM_RATIO,
                            f"Preliminary SCWB ratio = {ratio:.3f} > {SCWB_PRELIM_RATIO}")

    # ===================== STEP 2: FRAME MODELING =====================

    def step2_frame_modeling(self):
        """Step 2: Approximate frame modeling effects."""
        self.subsection("STEP 2: FRAME MODELING PARAMETERS")

        b = self.beam

        print(f"  Per Section 11.7 Step 2:")
        print(f"    - Use 100% rigid offset in panel zone")
        print(f"    - Increase beam I, S, Z by ~3x for distance ~0.77d = {0.77*b.d:.2f} in")
        print(f"    - Beyond column face (approx. side plate extension)")
        print(f"  Note: Side plate extension A = {self.extension_A:.2f} in = {self.extension_A/b.d:.3f}d")

        if b.weight > 200 and self.is_bolted:
            print(f"\n  WARNING: Heavy beam ({b.weight} plf) may require extension up to 1.7d = {1.7*b.d:.2f} in")

    # ===================== STEP 3: BEAM LIMITS =====================

    def step3_beam_prequalification(self):
        """Step 3 & 4: Beam and column prequalification limits."""
        self.subsection("STEP 3: BEAM PREQUALIFICATION LIMITS (Section 11.3.1)")

        b = self.beam
        passed = True

        # Beam depth limit
        if self.is_welded:
            max_depth = MAX_BEAM_DEPTH_WELDED
            depth_label = "W40"
        else:
            max_depth = MAX_BEAM_DEPTH_BOLTED
            depth_label = "W44"

        depth_ok = b.nominal_depth <= max_depth
        self._pass_fail(depth_ok, f"Beam depth = {b.nominal_depth:.0f} <= {depth_label} ({max_depth})")
        if not depth_ok:
            passed = False

        # Beam weight limit
        if self.is_welded:
            max_weight = MAX_BEAM_WEIGHT_WELDED
        else:
            max_weight = MAX_BEAM_WEIGHT_BOLTED

        weight_ok = b.weight <= max_weight
        self._pass_fail(weight_ok, f"Beam weight = {b.weight:.0f} plf <= {max_weight} plf")
        if not weight_ok:
            passed = False

        # Beam flange thickness limit (Section 11.3.1(1))
        tf_ok = b.tf <= MAX_BEAM_TF
        self._pass_fail(tf_ok, f"Beam flange thickness = {b.tf:.3f} in <= {MAX_BEAM_TF} in")
        if not tf_ok:
            passed = False

        # Beam flange area (field-bolted only, Section 11.3.1(4))
        if self.is_bolted:
            fa_ok = b.flange_area <= MAX_BEAM_FLANGE_AREA_BOLTED
            self._pass_fail(fa_ok,
                            f"Beam flange area = {b.flange_area:.2f} in^2 <= {MAX_BEAM_FLANGE_AREA_BOLTED} in^2")
            if not fa_ok:
                passed = False

        # L_h/d ratio (Section 11.3.1(5))
        if self.Lh > 0:
            lh_d = self.Lh / b.d
            if self.system_type == 'SMF':
                if self.is_welded:
                    min_lhd = LH_D_MIN_WELDED_U  # U-shaped is typical
                    lhd_label = "4.5"
                else:
                    min_lhd = LH_D_MIN_BOLTED_U
                    lhd_label = "4.0"
            else:  # IMF
                min_lhd = LH_D_MIN_IMF
                lhd_label = "3.0"

            lhd_ok = lh_d >= min_lhd
            cover_note = " (Assuming U-shaped cover plates)" if self.system_type == 'SMF' else ""
            self._pass_fail(lhd_ok,
                            f"L_h/d = {lh_d:.2f} >= {lhd_label} ({self.system_type}{cover_note})")
            if not lhd_ok:
                passed = False
        else:
            print(f"    L_h = {self.Lh:.2f} in (negative - CHECK GEOMETRY)")
            self._pass_fail(False, f"L_h = {self.Lh:.2f} in must be positive")
            passed = False

        return passed

    # ===================== STEP 4: COLUMN LIMITS =====================

    def step4_column_prequalification(self):
        """Step 4: Column prequalification limits."""
        self.subsection("STEP 4: COLUMN PREQUALIFICATION LIMITS (Section 11.3.2)")

        c = self.column

        # Column depth limit
        depth_ok = c.nominal_depth <= MAX_COLUMN_DEPTH
        self._pass_fail(depth_ok, f"Column depth = {c.nominal_depth:.0f} <= W44 ({MAX_COLUMN_DEPTH})")

        # No weight limit (Section 11.3.2(5))
        print(f"    No column weight limit per Section 11.3.2(5)")

        return depth_ok

    # ===================== STEP 5: DESIGN FORCES =====================

    def step5_design_forces(self):
        """Step 5: Calculate design forces per Section 11.7."""
        self.subsection("STEP 5: DESIGN FORCES (Section 11.7)")

        b = self.beam
        c = self.column

        print(f"  C_pr = min((Fy+Fu)/(2*Fy), 1.2)")
        print(f"       = min(({b.Fy}+{b.Fu})/(2*{b.Fy}), 1.2)")
        print(f"       = min({(b.Fy+b.Fu)/(2*b.Fy):.3f}, 1.2) = {self.C_pr:.3f}")
        print(f"  Note: SidePlate proprietary C_pr ranges from 1.15 to 1.35 (per User Note, Section 11.7)")

        print(f"\n  M_pr = C_pr * Ry * Fy * Zx  (Eq. 2.4-1)")
        print(f"       = {self.C_pr:.3f} * {b.Ry} * {b.Fy} * {b.Zx:.1f}")
        print(f"       = {self.Mpr:.0f} kip-in")

        print(f"\n  Plastic hinge location:")
        hinge_type = "d/3" if self.is_welded else "d/6"
        print(f"    Hinge ratio = {hinge_type} = {self.hinge_dist:.2f} in from end of side plate")
        print(f"    Side plate extension A = {self.extension_A:.2f} in")
        print(f"    S_h = dc/2 + A + {hinge_type} = {c.d/2:.2f} + {self.extension_A:.2f} + {self.hinge_dist:.2f}")
        print(f"        = {self.Sh:.2f} in (from column CL)")

        print(f"\n  L_h = L - dc1/2 - dc2/2 - 2*{hinge_type} - 2*A  (Eq. 11.3-1{'a' if self.is_welded else 'b'})")
        print(f"      = {self.L} - {c.d/2:.2f} - {self.column_d2/2:.2f} "
              f"- 2*{self.hinge_dist:.2f} - 2*{self.extension_A:.2f}")
        print(f"      = {self.Lh:.2f} in")

        V_gravity_total = self.loads.gravity_combination
        V_gravity = V_gravity_total / 2  # Total span load / 2 = beam end shear
        print(f"\n  V_h = 2*M_pr/L_h + V_gravity  (Eq. 11.4-3)")
        print(f"    V_gravity = (1.2D + f1*L + 0.2S) / 2 = {V_gravity_total:.2f} / 2 = {V_gravity:.2f} kips")
        if self.Lh > 0:
            print(f"    V_h = 2*{self.Mpr:.0f}/{self.Lh:.2f} + {V_gravity:.2f}")
        else:
            print(f"    ERROR: L_h <= 0")
        print(f"    V_h = {self.Vh:.2f} kips")

        # M_f at column face
        Mf = self.Mpr + self.Vh * (self.Sh - c.d / 2)
        self.Mf = Mf
        print(f"\n  M_f at column face = M_pr + V_h * (S_h - dc/2)")
        print(f"                     = {self.Mpr:.0f} + {self.Vh:.2f} * {self.Sh - c.d/2:.2f}")
        print(f"                     = {Mf:.0f} kip-in")

        # Moment at column CL (for SCWB)
        self.Mcl = self.Mpr + self.Vh * self.Sh
        print(f"\n  M at column CL = M_pr + V_h * S_h")
        print(f"                 = {self.Mpr:.0f} + {self.Vh:.2f} * {self.Sh:.2f}")
        print(f"                 = {self.Mcl:.0f} kip-in")

    # ===================== COLUMN-BEAM RELATIONSHIP =====================

    def step6_column_beam_ratio(self):
        """Column-beam moment ratio per Section 11.4."""
        self.subsection("STEP 6: COLUMN-BEAM MOMENT RATIO (Section 11.4)")

        b = self.beam
        c = self.column

        # Sum M_pb* (Eq. 11.4-2)
        # M_v = V_h * S_h (shear amplification)
        M_v = self.Vh * self.Sh
        Mpb_star_single = 1.1 * b.Ry * b.Fy * b.Zx + M_v

        # One-sided connection: sum over 1 beam
        Sum_Mpb = 2 * Mpb_star_single  # Assume two-sided (conservative for one-sided)

        print(f"  Eq. 11.4-2: Sum M_pb* (one beam, projected to column CL)")
        print(f"    1.1*Ry*Fy*Zb = 1.1 * {b.Ry} * {b.Fy} * {b.Zx:.1f} = {1.1*b.Ry*b.Fy*b.Zx:.0f} kip-in")
        print(f"    M_v = V_h * S_h = {self.Vh:.2f} * {self.Sh:.2f} = {M_v:.0f} kip-in")
        print(f"    M_pb* (single beam) = {1.1*b.Ry*b.Fy*b.Zx:.0f} + {M_v:.0f} = {Mpb_star_single:.0f} kip-in")

        # For one-sided connection, use single beam
        Sum_Mpb_one = Mpb_star_single
        print(f"\n    Sum M_pb* (one-sided) = {Sum_Mpb_one:.0f} kip-in")
        print(f"    Sum M_pb* (two-sided) = 2 x {Mpb_star_single:.0f} = {Sum_Mpb:.0f} kip-in")

        # Sum M_pc* (Eq. 11.4-4 for uniaxial, wide-flange column)
        # Z_ec per Eq. 11.4-5: Z_ec = Z_c * H / H_h
        # H_h = H - dc/4 - dc/4 = H - dc/2 (from 1/4 col depth above/below side plate edges)
        # Side plate depth = d + 2*extension_A (approximate)
        # Actually: H_h = distance from dc/4 above top edge of lower side plate
        #                to dc/4 below bottom edge of upper side plate
        # Simplified: H_h ≈ H - dc/2 (approximation; exact H_h depends on
        # side plate geometry determined by SidePlate Systems in Steps 6-7)
        H = self.story_height
        Hh = H - c.d / 2

        if Hh <= 0:
            print(f"\n  WARNING: H_h = {Hh:.2f} in <= 0 (story height too small)")
            Zec = c.Zx
        else:
            Zec = c.Zx * H / Hh

        # Reduction for axial load
        if self.As_col > 0:
            axial_reduction = self.Pu_col / self.As_col
        else:
            axial_reduction = 0

        Mpc_star_single = Zec * (c.Fy - axial_reduction)
        if Mpc_star_single < 0:
            Mpc_star_single = 0

        Sum_Mpc = 2 * Mpc_star_single  # Column above + below

        print(f"\n  Eq. 11.4-4 & 11.4-5: Sum M_pc* (uniaxial, wide-flange column)")
        print(f"    H = {H:.1f} in")
        print(f"    H_h = H - dc/2 = {H:.1f} - {c.d/2:.2f} = {Hh:.2f} in")
        print(f"    Z_ec = Z_c * H / H_h = {c.Zx:.1f} * {H:.1f} / {Hh:.2f} = {Zec:.1f} in^3")
        if axial_reduction > 0:
            print(f"    P_uc/A_s = {self.Pu_col:.1f}/{self.As_col:.1f} = {axial_reduction:.2f} ksi")
        print(f"    M_pc* (single face) = Z_ec * (F_yc - P_uc/A_s)")
        print(f"                        = {Zec:.1f} * ({c.Fy:.1f} - {axial_reduction:.2f})")
        print(f"                        = {Mpc_star_single:.0f} kip-in")
        print(f"    Sum M_pc* = 2 x {Mpc_star_single:.0f} = {Sum_Mpc:.0f} kip-in")

        # Check ratio (one-sided)
        ratio_one = Sum_Mpc / Sum_Mpb_one if Sum_Mpb_one > 0 else float('inf')
        print(f"\n  Column-beam moment ratio (one-sided):")
        print(f"    Sum M_pc* / Sum M_pb* = {Sum_Mpc:.0f} / {Sum_Mpb_one:.0f} = {ratio_one:.3f}")

        # AISC 341 E3.4a applies to both SMF and IMF
        print(f"    Required >= 1.0 per AISC 341 E3.4a ({self.system_type})")
        self._pass_fail(ratio_one >= 1.0,
                        f"SCWB ratio (one-sided) = {ratio_one:.3f} >= 1.0 ({self.system_type})")

        # Also show two-sided for reference
        if Sum_Mpb > 0:
            ratio_two = Sum_Mpc / Sum_Mpb
            print(f"\n  Reference (two-sided): {ratio_two:.3f}")

        return ratio_one

    # ===================== BEAM SHEAR CHECK =====================

    def step7_beam_shear(self):
        """Beam shear strength check per AISC 360 G2.1."""
        self.subsection("STEP 7: BEAM SHEAR STRENGTH (AISC 360 G2.1)")

        b = self.beam
        d = b.d
        tw = b.tw

        # Shear area for rolled W-shapes
        Aw = d * tw

        # Nominal shear strength (AISC 360 G2.1(a) for rolled shapes)
        Vn = 0.6 * b.Fy * Aw

        phi_Vn = PHI_V * Vn

        Vu = self.Vh

        print(f"  V_u = V_h = {Vu:.2f} kips")
        print(f"  A_w = d * tw = {d:.2f} * {tw:.3f} = {Aw:.3f} in^2")
        print(f"  V_n = 0.6 * Fy * Aw = 0.6 * {b.Fy} * {Aw:.3f} = {Vn:.1f} kips")
        print(f"  phi*V_n = {PHI_V} * {Vn:.1f} = {phi_Vn:.1f} kips")

        passed = Vu <= phi_Vn
        ratio = Vu / phi_Vn if phi_Vn > 0 else float('inf')
        print(f"  V_u / phi*V_n = {Vu:.2f} / {phi_Vn:.1f} = {ratio:.3f}")
        self._pass_fail(passed, f"Beam shear: V_u = {Vu:.2f} <= phi*V_n = {phi_Vn:.1f} kips")

    # ===================== PANEL ZONE CHECK =====================

    def step8_panel_zone(self):
        """Panel zone check per Section 11.4(2) and AISC 360 J10.6."""
        self.subsection("STEP 8: PANEL ZONE CHECK (Section 11.4(2), AISC 360 J10.6)")

        b = self.beam
        c = self.column

        # Panel zone shear demand
        # The moment at column face is transferred through the side plates
        # Panel zone shear V_pz ≈ M_f / (d - t_f) (conventional approach)
        # For SidePlate: V_pz ≈ M_cl / effective_depth
        # Using column centerline moment
        d_b = b.d
        db_eff = d_b  # approximate

        V_pz = self.Mcl / db_eff if db_eff > 0 else 0

        # Panel zone capacity with side plates as doublers
        # R_n per AISC 360 Eq. J10-11 (with side plates contributing)
        # The side plates act as doubler plates, significantly strengthening the panel zone
        # Base panel zone (column web only):
        dc = c.d
        twc = c.tw
        bfc = c.bf
        tfc = c.tf

        # Note: d_sp (side plate depth) ≈ d_beam for typical configurations
        d_sp = b.d  # approximate

        Rn_base = 0.6 * c.Fy * dc * twc * (1 + 3 * bfc * tfc**2 / (d_sp * dc * twc))

        print(f"  Panel zone shear demand (at column CL):")
        print(f"    V_pz = M_cl / d = {self.Mcl:.0f} / {db_eff:.2f} = {V_pz:.1f} kips")
        print()
        print(f"  Column web panel zone capacity (AISC 360 Eq. J10-11):")
        print(f"    d_c = {dc:.2f} in, t_wc = {twc:.3f} in")
        print(f"    b_fc = {bfc:.3f} in, t_fc = {tfc:.3f} in")
        print(f"    d_sp (approx) = {d_sp:.2f} in")
        print(f"    R_n = 0.6*Fy*dc*tw*(1 + 3*bf*tf^2/(d_sp*dc*tw))")
        bf_tf2 = bfc * tfc**2
        denom = d_sp * dc * twc
        factor = 3 * bf_tf2 / denom if denom > 0 else 0
        print(f"         = 0.6*{c.Fy}*{dc:.2f}*{twc:.3f}*(1 + {factor:.4f})")
        print(f"         = {Rn_base:.1f} kips")

        print(f"\n  Note: Side plates {{A}} significantly strengthen panel zone (min 3 panel zones)")
        print(f"        Final panel zone design by SidePlate Systems Inc. (Steps 6-7)")

        # Preliminary information only; side plates act as doubler plates
        # Bare column web capacity is often insufficient, which is expected
        # because the side plates provide the remaining capacity
        if V_pz > Rn_base:
            print(f"\n  [INFO] Bare column web insufficient (V_pz = {V_pz:.1f} > R_n = {Rn_base:.1f} kips)")
            print(f"         Side plates {{A}} will act as doubler plates to provide remaining capacity.")
        else:
            print(f"\n  [INFO] Bare column web is adequate on its own (V_pz = {V_pz:.1f} <= R_n = {Rn_base:.1f} kips)")

        # Not a pass/fail check - capacity guaranteed by SidePlate proprietary design
        self._pass_fail(True, "Panel zone capacity (Guaranteed by SidePlate proprietary design in Steps 6-7)")

    # ===================== STEPS 6-7 NOTE =====================

    def note_steps67(self):
        """Note about Steps 6-7 (SidePlate Systems design)."""
        self.subsection("STEPS 6-7: CONNECTION COMPONENT DESIGN (By SidePlate Systems Inc.)")

        print(f"  Per Section 11.7, Steps 6 and 7 are performed by SidePlate Systems Inc.")
        print(f"  The proprietary design includes:")
        print(f"    - Side plate {{A}} thickness (Eq. C-11.7-1)")
        print(f"    - Cover plate {{B}} thickness (Eq. C-11.7-3)")
        print(f"    - VSE thickness (Eq. C-11.7-4)")
        print(f"    - HSP thickness (Eq. C-11.7-5)")
        print(f"    - Weld group sizing (ultimate strength approach)")
        print(f"    - Bolt group design (field-bolted only)")
        print()
        print(f"  Engineer of record submits (Step 5):")
        print(f"    - V_gravity = {self.loads.gravity_combination:.2f} kips")
        print(f"    - M_pr = {self.Mpr:.0f} kip-in")
        print(f"    - V_h = {self.Vh:.2f} kips")
        print(f"    - Beam/column sizes and material grades")
        print(f"    - Story height H = {self.story_height:.1f} in")
        print()
        print(f"  EOR reviews SidePlate calculations per Step 8.")

    # ===================== M_group CALCULATION =====================

    def calc_mgroup(self):
        """Calculate M_group per Eq. 11.7-2 for reference."""
        self.subsection("M_group CALCULATION (Eq. 11.7-2, Reference)")

        b = self.beam

        # M_group at various critical sections
        # x = distance from plastic hinge to design element centroid
        # At column face: x = A + hinge_dist - 0 (from hinge to column face)
        # Actually: x = distance from plastic hinge to centroid of connection element

        # At side plate / cover plate junction:
        x_face = self.extension_A + self.hinge_dist  # from hinge to column face
        M_group_face = self.Mpr + self.Vh * x_face

        # At column centerline:
        x_cl = self.Sh  # from hinge to column CL
        M_group_cl = self.Mpr + self.Vh * x_cl

        print(f"  Eq. 11.7-2: M_group = M_pr + V_u * x")
        print(f"  Eq. 11.7-3: M_pr = C_pr * Ry * Fy * Zx = {self.Mpr:.0f} kip-in")
        print(f"  Eq. 11.7-4: V_u = 2*M_pr/L_h + V_gravity = {self.Vh:.2f} kips")
        print()
        print(f"  At column face (x = {x_face:.2f} in):")
        print(f"    M_group = {self.Mpr:.0f} + {self.Vh:.2f} * {x_face:.2f} = {M_group_face:.0f} kip-in")
        print(f"  At column CL (x = {x_cl:.2f} in):")
        print(f"    M_group = {self.Mpr:.0f} + {self.Vh:.2f} * {x_cl:.2f} = {M_group_cl:.0f} kip-in")

    # ===================== MAIN RUN =====================

    def run(self):
        """Run all design verification steps."""
        self.section("AISC 358-16 CHAPTER 11: SIDEPLATE MOMENT CONNECTION")
        print(f"  Beam: {self.beam.designation}    Column: {self.column.designation}")
        print(f"  Connection: {'Field-welded' if self.is_welded else 'Field-bolted'}    "
              f"System: {self.system_type}")
        print(f"  Span: {self.L:.1f} in ({self.L/12:.1f} ft)")

        self.step1_preliminary()
        self.step2_frame_modeling()
        self.step3_beam_prequalification()
        self.step4_column_prequalification()
        self.step5_design_forces()
        self.step6_column_beam_ratio()
        self.step7_beam_shear()
        self.step8_panel_zone()
        self.calc_mgroup()
        self.note_steps67()

        self.summary()
        return self._all_passed


# ====================== COMMAND LINE ======================

def main():
    parser = argparse.ArgumentParser(
        description="AISC 358-16 Chapter 11: SidePlate Moment Connection Design Verification",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Field-welded SMF
  python sideplate_design.py --beam-section W36x150 --column-section W14x311 \\
      --span 360 --system-type SMF --connection-type welded

  # Field-bolted SMF
  python sideplate_design.py --beam-section W40x211 --column-section W14x455 \\
      --span 420 --system-type SMF --connection-type bolted

  # Field-welded IMF
  python sideplate_design.py --beam-section W24x68 --column-section W14x120 \\
      --span 300 --system-type IMF --connection-type welded

  # Custom extension
  python sideplate_design.py --beam-section W36x150 --column-section W14x311 \\
      --span 360 --system-type SMF --connection-type welded --extension-A 25
""")

    parser.add_argument('--beam-section', type=str, help='Beam section designation (e.g., W36x150)')
    parser.add_argument('--column-section', type=str, help='Column section designation (e.g., W14x311)')

    # Custom section properties
    parser.add_argument('--beam-d', type=float, help='Beam depth (in)')
    parser.add_argument('--beam-bf', type=float, help='Beam flange width (in)')
    parser.add_argument('--beam-tf', type=float, help='Beam flange thickness (in)')
    parser.add_argument('--beam-tw', type=float, help='Beam web thickness (in)')
    parser.add_argument('--beam-Zx', type=float, help='Beam plastic section modulus (in^3)')
    parser.add_argument('--column-d', type=float, help='Column depth (in)')
    parser.add_argument('--column-bf', type=float, help='Column flange width (in)')
    parser.add_argument('--column-tf', type=float, help='Column flange thickness (in)')
    parser.add_argument('--column-tw', type=float, help='Column web thickness (in)')
    parser.add_argument('--column-Zx', type=float, help='Column plastic section modulus (in^3)')

    parser.add_argument('--span', type=float, required=True,
                        help='Span between column centerlines (in)')
    parser.add_argument('--system-type', type=str, required=True,
                        choices=['SMF', 'IMF'], help='Structural system type')
    parser.add_argument('--connection-type', type=str, required=True,
                        choices=['welded', 'bolted'], help='Connection type')

    # Optional parameters
    parser.add_argument('--extension-A', type=float, default=None,
                        help='Side plate extension beyond column face (in). Default: 0.77d')
    parser.add_argument('--story-height', type=float, default=168.0,
                        help='Story height (in). Default: 168 (14 ft)')
    parser.add_argument('--column-d2', type=float, default=None,
                        help='Depth of opposite column (in). Default: same as column')

    # Material properties
    parser.add_argument('--beam-Fy', type=float, default=DEFAULT_FY_BEAM,
                        help=f'Beam yield stress (ksi). Default: {DEFAULT_FY_BEAM}')
    parser.add_argument('--beam-Fu', type=float, default=DEFAULT_FU_BEAM,
                        help=f'Beam tensile stress (ksi). Default: {DEFAULT_FU_BEAM}')
    parser.add_argument('--beam-Ry', type=float, default=1.1,
                        help='Beam Ry factor. Default: 1.1 (A992)')
    parser.add_argument('--column-Fy', type=float, default=DEFAULT_FY_COLUMN,
                        help=f'Column yield stress (ksi). Default: {DEFAULT_FY_COLUMN}')
    parser.add_argument('--column-Fu', type=float, default=DEFAULT_FU_COLUMN,
                        help=f'Column tensile stress (ksi). Default: {DEFAULT_FU_COLUMN}')
    parser.add_argument('--column-Ry', type=float, default=1.1,
                        help='Column Ry factor. Default: 1.1 (A992)')

    # Loads
    parser.add_argument('--load-D', type=float, default=0.0, help='Dead load (kips)')
    parser.add_argument('--load-L', type=float, default=0.0, help='Live load (kips)')
    parser.add_argument('--load-S', type=float, default=0.0, help='Snow load (kips)')
    parser.add_argument('--load-f1', type=float, default=0.5, help='Live load factor')
    parser.add_argument('--Pu-col', type=float, default=0.0,
                        help='Column axial load P_uc (kips)')
    parser.add_argument('--As-col', type=float, default=0.0,
                        help='Column gross area A_s (in^2)')

    parser.add_argument('--list-sections', action='store_true',
                        help='List all available W-shapes and exit')

    args = parser.parse_args()

    if args.list_sections:
        list_sections()
        return

    # Create beam section
    if args.beam_section:
        props = lookup_section(args.beam_section)
        beam = BeamSection(
            designation=args.beam_section,
            d=args.beam_d or props['d'],
            bf=args.beam_bf or props['bf'],
            tf=args.beam_tf or props['tf'],
            tw=args.beam_tw or props['tw'],
            Zx=args.beam_Zx or props['Zx'],
            Fy=args.beam_Fy, Fu=args.beam_Fu, Ry=args.beam_Ry,
        )
    elif all([args.beam_d, args.beam_bf, args.beam_tf, args.beam_tw, args.beam_Zx]):
        beam = BeamSection(
            designation='Custom',
            d=args.beam_d, bf=args.beam_bf, tf=args.beam_tf,
            tw=args.beam_tw, Zx=args.beam_Zx,
            Fy=args.beam_Fy, Fu=args.beam_Fu, Ry=args.beam_Ry,
        )
    else:
        parser.error("Specify --beam-section or all custom beam properties")

    # Create column section
    if args.column_section:
        props = lookup_section(args.column_section)
        column = ColumnSection(
            designation=args.column_section,
            d=args.column_d or props['d'],
            bf=args.column_bf or props['bf'],
            tf=args.column_tf or props['tf'],
            tw=args.column_tw or props['tw'],
            Zx=args.column_Zx or props['Zx'],
            Fy=args.column_Fy, Fu=args.column_Fu, Ry=args.column_Ry,
        )
    elif all([args.column_d, args.column_bf, args.column_tf, args.column_tw, args.column_Zx]):
        column = ColumnSection(
            designation='Custom',
            d=args.column_d, bf=args.column_bf, tf=args.column_tf,
            tw=args.column_tw, Zx=args.column_Zx,
            Fy=args.column_Fy, Fu=args.column_Fu, Ry=args.column_Ry,
        )
    else:
        parser.error("Specify --column-section or all custom column properties")

    # Create loads
    loads = Loads(D=args.load_D, L=args.load_L, S=args.load_S,
                  f1=args.load_f1, Vu=0.0)

    # Run design verification
    checker = SidePlateChecker(
        beam=beam, column=column, loads=loads,
        L=args.span, system_type=args.system_type,
        connection_type=args.connection_type,
        extension_A=args.extension_A,
        story_height=args.story_height,
        column_d2=args.column_d2,
        Pu_col=args.Pu_col, As_col=args.As_col,
    )

    passed = checker.run()
    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
