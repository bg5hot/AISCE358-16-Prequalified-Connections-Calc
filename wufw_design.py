#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Welded Unreinforced Flange-Welded Web (WUF-W) Connection Design Verification
Based on AISC 358-16 Chapter 8 - Prequalified Connections for Seismic Applications

WUF-W connections use complete joint penetration (CJP) groove welds for both
beam flanges and beam web directly to the column flange. A single-plate shear
tab supplements the web weld.

Key characteristics (unique to WUF-W):
  - C_pr = 1.4 (NOT the default Eq. 2.4-2 formula)
  - S_h = 0 (plastic hinge at column face)
  - M_f = M_pr (no shear amplification from S_h)
  - Prescriptive connection details (not design choices)

Usage:
    python wufw_design.py --beam-section W24x68 --column-section W14x120 \
        --span 300 --system-type SMF
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
# Resistance factors
PHI_D = 1.00  # Ductile limit states (AISC 358 Section 2.4.1)
PHI_V = 1.00  # Shear (AISC 360 G2.1(a), phi=1.0 for rolled W-shapes)

# Default material properties
DEFAULT_FY_BEAM = 50.0    # ksi (A992)
DEFAULT_FU_BEAM = 65.0    # ksi (A992)
DEFAULT_FY_COLUMN = 50.0  # ksi (A992)
DEFAULT_FU_COLUMN = 65.0  # ksi (A992)

# Steel properties
E = 29000.0  # Modulus of elasticity (ksi)

# WUF-W specific constants
CPR_WUFW = 1.4   # C_pr for WUF-W per Section 8.7 Step 1 (NOT Eq. 2.4-2)
SH_WUFW = 0.0    # S_h for WUF-W per Section 8.7 Step 2 (at column face)


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


@dataclass
class Loads:
    D: float = 0.0     # Total dead load on span (kips)
    L: float = 0.0     # Total live load on span (kips)
    S: float = 0.0     # Total snow load on span (kips)
    f1: float = 0.5    # Live load factor
    Vu: float = 0.0    # User-specified required shear (kips)

    @property
    def gravity_combination(self) -> float:
        return 1.2 * self.D + self.f1 * self.L + 0.2 * self.S


@dataclass
class DesignParameters:
    L: float
    Lh: float
    system_type: str
    C_pr: float = CPR_WUFW
    Sh: float = SH_WUFW


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


# ====================== WUF-W DESIGN CHECKER ======================

class WUFWDesignChecker:
    """WUF-W Connection Design per AISC 358-16 Section 8.7 (6 steps)"""

    def __init__(self, beam: BeamSection, column: ColumnSection,
                 params: DesignParameters, loads: Loads):
        self.beam = beam
        self.column = column
        self.params = params
        self.loads = loads
        self.M_pr = 0.0
        self.V_h = 0.0
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
        self.section("WUF-W CONNECTION DESIGN VERIFICATION (AISC 358-16 CHAPTER 8)")
        print()
        self.print_input()

        self.step0_prequalification()
        self.section("DESIGN PROCEDURE (SECTION 8.7)")
        print("  Note: Steps 1-4 correspond to AISC 358-16 Section 8.7 Steps 1-6.")
        print("  Steps 5-8 are explicit checks for requirements referenced in the procedure.")
        self.step1_Mpr()
        self.step2_Sh()
        self.step3_Vh()
        self.step4_column_beam()
        self.step5_beam_shear()
        self.step6_continuity_plates()
        self.step7_panel_zone()
        self.step8_connection_details()

        self.print_summary()
        return all(v for v in self.checks.values() if v is not None)

    # ---------- input ----------
    def print_input(self):
        self.section("INPUT PARAMETERS")
        b, c, pm, ld = self.beam, self.column, self.params, self.loads
        print(f"BEAM: {b.designation} | d={b.d:.2f} bf={b.bf:.2f} tf={b.tf:.3f} tw={b.tw:.3f} Zx={b.Zx:.1f}")
        print(f"      Fy={b.Fy} Fu={b.Fu} Ry={b.Ry}")
        print(f"COLUMN: {c.designation} | d={c.d:.2f} bf={c.bf:.2f} tf={c.tf:.3f} tw={c.tw:.3f}")
        print(f"        Fy={c.Fy} Fu={c.Fu} Ry={c.Ry}")
        print(f"SPAN: L={pm.L:.0f} in ({pm.L/12:.1f} ft) | {pm.system_type}")
        print(f"      L_h={pm.Lh:.1f} in ({pm.Lh/12:.1f} ft)")
        print(f"      C_pr={pm.C_pr} (WUF-W specific) | S_h={pm.Sh} in")
        print(f"LOADS: D={ld.D} L={ld.L} S={ld.S} | Vu={ld.Vu:.2f}")
        print()

    # ---------- Step 0: prequalification ----------
    def step0_prequalification(self):
        self.subsection("PREQUALIFICATION LIMITS (SECTION 8.3)")
        passed = True
        st = self.params.system_type
        b = self.beam

        # Beam depth <= W36
        print(f"  Beam depth: d = {b.d:.1f} in <= 36 in (W36 max): ", end="")
        if b.d > 36:
            print("FAIL"); passed = False
        else:
            print("OK")

        # Beam weight <= 150 plf
        wt = b.weight
        print(f"  Beam weight: {wt:.0f} plf <= 150 plf: ", end="")
        if wt > 150:
            print("FAIL"); passed = False
        else:
            print("OK")

        # Flange thickness <= 1.0 in
        print(f"  Flange thickness: tf = {b.tf:.3f} in <= 1.0 in: ", end="")
        if b.tf > 1.0:
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

        # Column depth <= W36
        print(f"  Column depth: d_c = {self.column.d:.1f} in <= 36 in: ", end="")
        if self.column.d > 36:
            print("FAIL"); passed = False
        else:
            print("OK")

        # C_pr override check
        print(f"  C_pr = {self.params.C_pr} (WUF-W: must be 1.4): ", end="")
        if abs(self.params.C_pr - 1.4) > 0.01:
            print("WARNING - WUF-W requires C_pr = 1.4")
        else:
            print("OK")

        # Lateral bracing requirement
        print(f"  Lateral bracing required at d to 1.5d from column face")
        print(f"    = {b.d:.1f} to {1.5*b.d:.1f} in from column face")
        print(f"  Protected zone: column face to d = {b.d:.1f} in from column face")

        self.checks["prequalification"] = passed
        print()

    # ---------- Step 1: M_pr ----------
    def step1_Mpr(self):
        self.subsection("STEP 1: PROBABLE MAXIMUM MOMENT M_pr (SECTION 8.7)")

        # WUF-W uses C_pr = 1.4 (NOT Eq. 2.4-2)
        C_pr = self.params.C_pr
        Ry = self.beam.Ry
        Fy = self.beam.Fy
        Zx = self.beam.Zx

        self.M_pr = C_pr * Ry * Fy * Zx

        print(f"  WUF-W specific: C_pr = {C_pr} (per Section 8.7 Step 1)")
        print(f"  Z_e = Z_x = {Zx:.1f} in^3 (no reduction)")
        print(f"  M_pr = C_pr * Ry * Fy * Zx")
        print(f"  M_pr = {C_pr} * {Ry} * {Fy} * {Zx:.1f}")
        print(f"  M_pr = {self.M_pr:.0f} kip-in ({self.M_pr/12:.1f} kip-ft)")
        print()

    # ---------- Step 2: S_h ----------
    def step2_Sh(self):
        self.subsection("STEP 2: PLASTIC HINGE LOCATION S_h (SECTION 8.7)")

        print(f"  WUF-W specific: S_h = 0 (plastic hinge at column face)")
        print(f"  Therefore: M_f = M_pr = {self.M_pr:.0f} kip-in")
        print(f"  (No moment amplification from shear at S_h)")
        print()

    # ---------- Step 3: V_h ----------
    def step3_Vh(self):
        self.subsection("STEP 3: SHEAR FORCE AT PLASTIC HINGE (SECTION 8.7)")

        # V_h from free body diagram
        # V_h = 2*M_pr/L_h + V_gravity
        Lh = self.params.Lh
        gravity = self.loads.gravity_combination

        self.V_h = 2 * self.M_pr / Lh + gravity / 2
        Vu = max(self.V_h, self.loads.Vu)

        print(f"  L_h = {Lh:.1f} in ({Lh/12:.1f} ft)")
        print(f"  Gravity load (1.2D + {self.loads.f1}L + 0.2S) = {gravity:.2f} kips (total on span)")
        print(f"  V_h = 2*M_pr/L_h + gravity/2")
        print(f"  V_h = 2*{self.M_pr:.0f}/{Lh:.1f} + {gravity:.2f}/2")
        print(f"  V_h = {self.V_h:.1f} kips")
        print(f"  V_u = max(V_h, user Vu) = max({self.V_h:.1f}, {self.loads.Vu:.2f}) = {Vu:.1f} kips")
        print()

    # ---------- Step 4: column-beam relationship ----------
    def step4_column_beam(self):
        self.subsection("STEP 4: COLUMN-BEAM RELATIONSHIP (SECTION 8.4)")

        b = self.beam
        c = self.column
        st = self.params.system_type

        # Beam flange force
        F_f = self.M_pr / (b.d - b.tf)

        print(f"  Beam flange force: F_f = M_pr / (d - tf)")
        print(f"  F_f = {self.M_pr:.0f} / ({b.d:.2f} - {b.tf:.3f}) = {F_f:.1f} kips")
        print()

        # --- Strong-Column / Weak-Beam Check (AISC 341 E3.6c for SMF) ---
        if st == "SMF":
            print("  Strong-Column / Weak-Beam Check (AISC 341 Section E3.6c):")
            # M_pb* = M_pr (probable max moment at column face, for WUF-W S_h=0)
            # M_uv = V_h * (d_c / 2)  (column shear contribution)
            # Sum(M_pb*) = Sum(M_pr + M_uv)  for beams framing into column
            M_uv = self.V_h * (c.d / 2)
            M_pb_star = self.M_pr + M_uv

            # Column moment capacity (both above and below)
            # M_pc* = Z_c * F_yc  (simplified, ignoring axial load effects)
            M_pc = c.Zx * c.Fy

            # For one-sided frame with identical beams top and bottom:
            # Ratio = 2 * M_pc / (2 * M_pb*) = M_pc / M_pb*
            ratio = M_pc / M_pb_star

            print(f"    M_pr = {self.M_pr:.0f} kip-in")
            print(f"    M_uv = V_h * (d_c/2) = {self.V_h:.1f} * {c.d/2:.2f} = {M_uv:.0f} kip-in")
            print(f"    M_pb* = M_pr + M_uv = {M_pb_star:.0f} kip-in")
            print(f"    M_pc = Zx_c * Fy_c = {c.Zx:.1f} * {c.Fy} = {M_pc:.0f} kip-in")
            print(f"    Ratio M_pc / M_pb* = {ratio:.3f}")

            passed = ratio >= 1.0
            if not passed:
                print(f"    => FAIL (ratio < 1.0) - Increase column size")
            else:
                print(f"    => OK")
            print()
            print(f"    Note: Simplified check (no axial load, one-sided frame).")
            print(f"    For final design, include axial load per AISC 341 E3.6c.")
            self.checks["column_beam"] = passed
        else:
            print("  IMF: Column-beam relationship per AISC 341 seismic provisions")
            print("  (Strong-column/weak-beam ratio may not be required for IMF)")
            self.checks["column_beam"] = True

        print()

    # ---------- Step 5: beam shear ----------
    def step5_beam_shear(self):
        self.subsection("STEP 5: BEAM SHEAR STRENGTH CHECK")

        Vu = max(self.V_h, self.loads.Vu)
        b = self.beam

        # AISC 360 Section G2.1
        Vn = 0.6 * b.Fy * b.d * b.tw
        phi_Vn = PHI_V * Vn

        print(f"  V_u = {Vu:.1f} kips")
        print(f"  V_n = 0.6*Fy*d*tw = 0.6*{b.Fy}*{b.d:.2f}*{b.tw:.3f} = {Vn:.1f} kips")
        print(f"  phi*V_n = {PHI_V}*{Vn:.1f} = {phi_Vn:.1f} kips")

        passed = Vu <= phi_Vn
        print(f"  {'OK' if passed else 'FAIL'} (Utilization: {Vu/phi_Vn:.3f})")
        self.checks["beam_shear"] = passed
        print()

    # ---------- Step 6: continuity plates ----------
    def step6_continuity_plates(self):
        self.subsection("STEP 6: CONTINUITY PLATE REQUIREMENTS (SECTION 2.4.4)")

        c = self.column
        b = self.beam

        # Flange force from M_pr
        F_f = self.M_pr / (b.d - b.tf)

        # Simplified check: compare required vs available column flange thickness
        # Per AISC 341, continuity plates are needed when column flange is too thin
        # to distribute the concentrated flange force
        tcf = c.tf
        Fyc = c.Fy
        bcf = c.bf

        # AISC 360 Section J10.1 - flange local bending
        # phi*R_n >= F_f => 0.9*6.25*t_cf^2*Fyc >= F_f
        # t_cf >= sqrt(F_f / (0.9 * 6.25 * Fyc))
        tcf_req_bending = math.sqrt(F_f / (0.9 * 6.25 * Fyc))

        # Web local yielding check
        k_det = c.tf  # Approximate (k_det is usually close to tf for W-shapes)
        twc_req = F_f / (PHI_D * 5 * Fyc * k_det) if k_det > 0 else 999

        print(f"  Flange force: F_f = {F_f:.1f} kips")
        print(f"  Column flange t_cf = {tcf:.3f} in")
        print()
        print(f"  Flange local bending check (AISC 360 J10.1):")
        print(f"    t_cf >= sqrt(F_f/(0.9*6.25*Fyc)) = sqrt({F_f:.1f}/({0.9*6.25*Fyc:.1f})) = {tcf_req_bending:.3f} in")

        need_plates = tcf < tcf_req_bending
        if need_plates:
            ts_min = max(c.tw, 0.5 * b.tf)
            print(f"    => Continuity plates RECOMMENDED (ts >= {ts_min:.3f} in)")
        else:
            print(f"    => Column flange appears adequate (simplified check)")

        self.checks["continuity_plates"] = not need_plates
        print()

    # ---------- Step 7: panel zone ----------
    def step7_panel_zone(self):
        self.subsection("STEP 7: COLUMN PANEL ZONE CHECK (SECTION 8.4)")

        c = self.column
        b = self.beam

        # Panel zone demand from M_pr
        F_f = self.M_pr / (b.d - b.tf)
        V_pz = F_f  # One-sided frame

        # Panel zone capacity per AISC 360 J6.2 (phi = 1.0 per AISC 341)
        # Vn = 0.6*Fyc*dc*twc (basic, no contribution from column flanges)
        phi_pz = 1.0
        dc = c.d
        twc = c.tw
        Fyc = c.Fy
        Vn = 0.6 * Fyc * dc * twc

        # phi = 1.0 for panel zone per AISC 341
        print(f"  Panel zone demand: V_pz = F_f = {V_pz:.1f} kips (Assuming exterior/one-sided connection)")
        print(f"  phi = {phi_pz} (per AISC 341)")
        print(f"  Capacity (basic): Vn = 0.6*Fyc*dc*twc")
        print(f"  Vn = 0.6*{Fyc}*{dc:.2f}*{twc:.3f} = {Vn:.1f} kips")

        # Check with column flange contribution (AISC 360 J6.2)
        # Vn_full = 0.6*Fyc*dc*twc*(1 + 3*bcf*tc^2/(db*dc*twc))
        bcf = c.bf
        tcf = c.tf
        db = b.d
        contribution = 3 * bcf * tcf**2 / (db * dc * twc)
        Vn_full = Vn * (1 + contribution)

        print(f"  Capacity (with flange contribution):")
        print(f"    3*bcf*tc^2/(db*dc*twc) = 3*{bcf:.2f}*{tcf:.3f}^2/({db:.2f}*{dc:.2f}*{twc:.3f}) = {contribution:.3f}")
        print(f"    Vn = {Vn:.1f} * (1 + {contribution:.3f}) = {Vn_full:.1f} kips")

        passed = V_pz <= Vn_full
        if not passed:
            print(f"  FAIL - Consider web doubler plates (Utilization: {V_pz/Vn_full:.3f})")
        else:
            print(f"  OK (Utilization: {V_pz/Vn_full:.3f})")
        self.checks["panel_zone"] = passed
        print()

    # ---------- Step 8: connection details ----------
    def step8_connection_details(self):
        self.subsection("STEP 8: CONNECTION DETAILING REQUIREMENTS (SECTIONS 8.5-8.6)")

        b = self.beam
        tw = b.tw

        print("  BEAM FLANGE-TO-COLUMN (Section 8.5):")
        print("    - CJP groove weld, demand critical per AISC 341")
        print("    - Weld access hole per AWS D1.8 Section 6.11.1.2")
        print("    - Bottom flange backing: remove, backgouge, 5/16\" min reinforcing fillet")
        print("    - Top flange backing: may remain, 5/16\" continuous fillet below CJP")
        print()

        print("  BEAM WEB-TO-COLUMN (Section 8.6):")
        print("    - CJP groove weld between weld access holes, demand critical")
        print()

        # Single-plate shear connection
        hp = b.dw  # plate height approximately = clear web depth
        tp = tw    # plate thickness >= tw
        Fyp = b.Fy

        weld_demand = hp * tp * (0.6 * b.Ry * Fyp)
        fillet_size = tp - 1.0/16.0

        print("  SINGLE-PLATE SHEAR CONNECTION (Section 8.6(2)):")
        print(f"    Plate thickness t_p >= t_w = {tw:.3f} in")
        print(f"    Plate height h_p ~ {hp:.2f} in (web depth between flanges)")
        print(f"    Plate extends 2 in minimum beyond weld access hole")
        print(f"    Weld to column: design shear >= h_p*t_p*(0.6*R_y*F_y)")
        print(f"      = {hp:.2f}*{tp:.3f}*(0.6*{b.Ry}*{Fyp})")
        print(f"      = {weld_demand:.1f} kips")
        print(f"    Fillet weld to beam web: size = t_p - 1/16 = {fillet_size:.3f} in")
        print(f"    Fillet weld termination: 1/2 in to 1 in from weld access hole edge")
        print()

        print("  WELD ACCESS HOLE GEOMETRY (Figure 8.3, AWS D1.8):")
        print("    a = 1/4 in min, 1/2 in max")
        print("    b = 1 in min")
        print("    c = 30 deg (+/- 10 deg)")
        print("    d = 2 in min")
        print("    e = 1/2 in min, 1 in max (fillet weld termination)")

        self.checks["connection_details"] = True
        print()

    # ---------- summary ----------
    def print_summary(self):
        self.section("DESIGN VERIFICATION SUMMARY")

        def s(k):
            return "PASS" if self.checks.get(k) else "FAIL"

        print(f"Prequalification: {s('prequalification')}")
        print(f"Column-beam: {s('column_beam')}")
        print(f"Beam shear: {s('beam_shear')}")
        print(f"Continuity plates: {s('continuity_plates')}")
        print(f"Panel zone: {s('panel_zone')}")
        print(f"Connection details: {s('connection_details')}")
        print()
        print(f"KEY: M_pr={self.M_pr:.0f} kip-in | V_h={self.V_h:.1f} kips | C_pr={self.params.C_pr} | S_h={self.params.Sh}")
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
                Ry=args.beam_Ry,
            )
    if all([args.beam_d, args.beam_bf, args.beam_tf, args.beam_tw, args.beam_Zx]):
        return BeamSection(
            designation="Custom", d=args.beam_d, bf=args.beam_bf,
            tf=args.beam_tf, tw=args.beam_tw, Zx=args.beam_Zx,
            Fy=args.beam_Fy, Fu=args.beam_Fu, Ry=args.beam_Ry,
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
        description="WUF-W Connection Design Verification (AISC 358-16 Chapter 8)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python wufw_design.py --beam-section W24x68 --column-section W14x120 --span 300 --system-type SMF
  python wufw_design.py --beam-section W30x99 --column-section W14x193 --span 360 --system-type SMF --load-D 20 --load-L 30
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

        # WUF-W: S_h = 0, so L_h = L - d_c
        L_h = args.span - column.d

        loads = Loads(D=args.load_D, L=args.load_L, S=args.load_S,
                      f1=args.load_f1, Vu=args.Vu)

        params = DesignParameters(
            L=args.span, Lh=L_h, system_type=args.system_type,
            C_pr=CPR_WUFW, Sh=SH_WUFW,
        )

        checker = WUFWDesignChecker(beam, column, params, loads)
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
