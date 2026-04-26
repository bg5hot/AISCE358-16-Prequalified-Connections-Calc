#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RBS (Reduced Beam Section) Moment Connection Design Calculator
Based on AISC 358-16 Chapter 5 - Prequalified Connections for Seismic Applications

This script performs the complete RBS connection design verification procedure
according to Section 5.8 of AISC 358-16.

Usage:
    python rbs_design.py
    # Modify input parameters in the INPUT PARAMETERS section or use command line arguments
"""

import argparse
import sys
import io
import os
import csv
from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict, List
import math

# Set UTF-8 encoding for Windows console
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ====================== CONSTANTS ======================
# Resistance factors from AISC 358-16 Section 2.4.1
PHI_D = 1.00  # Resistance factor for ductile limit states (RBS plastic hinge formation)
PHI_N = 0.90  # Resistance factor for nonductile limit states
PHI_V = 0.90  # Resistance factor for shear (LRFD, from AISC 360)

# Default C_pr value (connection strength factor)
# Typically 1.1-1.2 for RBS connections
C_PR_DEFAULT = 1.1

# Material overstrength factors from AISC 341 Table A3.1
RY_VALUES = {
    "A36": 1.5,
    "A992": 1.1,
    "A572": 1.1,
    "A500": 1.3,
    "A53": 1.3,
}


# ====================== DATA CLASSES ======================

@dataclass
class BeamSection:
    """Beam section properties"""
    designation: str  # e.g., "W30x99"
    d: float  # Depth (in)
    bf: float  # Flange width (in)
    tf: float  # Flange thickness (in)
    tw: float  # Web thickness (in)
    Zx: float  # Plastic section modulus (in^3)
    Fy: float = 50.0  # Yield stress (ksi)
    Fu: float = 65.0  # Tensile strength (ksi) - for C_pr calculation per AISC 358-16 Eq. 2.4-2
    Ry: float = 1.1  # Material overstrength factor

    @property
    def area(self) -> float:
        """Gross area of beam (in^2)"""
        return 2 * self.bf * self.tf + (self.d - 2 * self.tf) * self.tw

    @property
    def plastic_modulus_web(self) -> float:
        """Plastic modulus of web about x-axis (in^3)"""
        dw = self.d - 2 * self.tf
        return dw * self.dw / 4

    @property
    def dw(self) -> float:
        """Web depth between flanges (in)"""
        return self.d - 2 * self.tf


@dataclass
class ColumnSection:
    """Column section properties"""
    designation: str  # e.g., "W14x193"
    d: float  # Depth (in)
    bf: float  # Flange width (in)
    tf: float  # Flange thickness (in)
    tw: float  # Web thickness (in)
    Zx: float  # Plastic section modulus (in^3)
    Fy: float = 50.0  # Yield stress (ksi)
    Ry: float = 1.1  # Material overstrength factor


@dataclass
class RBSGeometry:
    """RBS cut geometry parameters"""
    a: float  # Distance from column face to start of cut (in)
    b: float  # Length of cut (in)
    c: float  # Depth of cut at center (in)


@dataclass
class Loads:
    """Gravity loads on beam (kip)"""
    D: float = 0.0  # Dead load
    L: float = 0.0  # Live load
    S: float = 0.0  # Snow load
    f1: float = 0.5  # Live load factor (not less than 0.5)

    @property
    def gravity_combination(self) -> float:
        """Load combination 1.2D + f1*L + 0.2S"""
        return 1.2 * self.D + self.f1 * self.L + 0.2 * self.S


@dataclass
class DesignParameters:
    """Overall design parameters"""
    L: float  # Beam span (center-to-center) (in)
    Lh: float  # Distance between plastic hinge locations (in)
    system_type: str = "SMF"  # "SMF" or "IMF"
    C_pr: Optional[float] = None  # Connection strength factor (None = calculate per Eq. 2.4-2)
    use_calculated_Cpr: bool = True  # If True, calculate C_pr; if False, use provided C_pr value


# ====================== RBS DESIGN CLASS ======================

class RBSDesignChecker:
    """
    RBS Connection Design Verification according to AISC 358-16 Section 5.8
    """

    def __init__(self, beam: BeamSection, column: ColumnSection,
                 rbs: RBSGeometry, params: DesignParameters, loads: Loads):
        self.beam = beam
        self.column = column
        self.rbs = rbs
        self.params = params
        self.loads = loads

        # Calculation results
        self.Z_RBS: Optional[float] = None
        self.M_pr: Optional[float] = None
        self.V_RBS: Optional[float] = None
        self.S_h: Optional[float] = None
        self.M_f: Optional[float] = None
        self.M_pe: Optional[float] = None
        self.V_u: Optional[float] = None
        self.V_gravity: Optional[float] = None

        # Check results
        self.checks: dict = {}

    def print_separator(self, char: str = "=", length: int = 80):
        """Print a separator line"""
        print(char * length)

    def print_section(self, title: str):
        """Print a section header"""
        self.print_separator("=")
        print(f"  {title}")
        self.print_separator("=")

    def print_subsection(self, title: str):
        """Print a subsection header"""
        self.print_separator("-")
        print(f"  {title}")
        self.print_separator("-")

    def run_all_checks(self) -> bool:
        """Run all design verification steps"""
        all_passed = True

        # Print header
        self.print_section("RBS MOMENT CONNECTION DESIGN VERIFICATION (AISC 358-16)")
        print()

        # Print input parameters
        self.print_input_parameters()

        # Step 1: RBS Geometry Limits
        if not self.step1_check_rbs_geometry():
            all_passed = False

        # Step 2: Calculate Z_RBS
        self.step2_calculate_ZRBS()

        # Step 3: Calculate M_pr
        self.step3_calculate_Mpr()

        # Step 4: Calculate V_RBS
        self.step4_calculate_VRBS()

        # Step 5: Calculate M_f
        self.step5_calculate_Mf()

        # Step 6: Calculate M_pe
        self.step6_calculate_Mpe()

        # Step 7: Check flexural strength at column face
        if not self.step7_check_flexural_strength():
            all_passed = False

        # Step 8: Calculate and check shear strength
        if not self.step8_check_shear_strength():
            all_passed = False

        # Step 9: Beam web-to-column connection
        self.step9_web_connection()

        # Step 10: Continuity plate requirements
        self.step10_continuity_plates()

        # Step 11: Column-beam relationship
        if not self.step11_column_beam_relationship():
            all_passed = False

        # Print summary
        self.print_summary(all_passed)

        return all_passed

    def print_input_parameters(self):
        """Print all input parameters"""
        self.print_section("INPUT PARAMETERS")

        print("BEAM SECTION:")
        print(f"  Designation: {self.beam.designation}")
        print(f"  Depth (d): {self.beam.d} in")
        print(f"  Flange width (bf): {self.beam.bf} in")
        print(f"  Flange thickness (tf): {self.beam.tf} in")
        print(f"  Web thickness (tw): {self.beam.tw} in")
        print(f"  Plastic modulus (Zx): {self.beam.Zx} in³")
        print(f"  Yield stress (Fy): {self.beam.Fy} ksi")
        print(f"  Overstrength factor (Ry): {self.beam.Ry}")
        print()

        print("COLUMN SECTION:")
        print(f"  Designation: {self.column.designation}")
        print(f"  Depth (dc): {self.column.d} in")
        print(f"  Flange width (bcf): {self.column.bf} in")
        print(f"  Flange thickness (tcf): {self.column.tf} in")
        print(f"  Web thickness (tcw): {self.column.tw} in")
        print(f"  Plastic modulus (Zcx): {self.column.Zx} in³")
        print(f"  Yield stress (Fyc): {self.column.Fy} ksi")
        print(f"  Overstrength factor (Ryc): {self.column.Ry}")
        print()

        print("RBS GEOMETRY:")
        print(f"  a (distance to start of cut): {self.rbs.a} in")
        print(f"  b (length of cut): {self.rbs.b} in")
        print(f"  c (depth of cut): {self.rbs.c} in")
        print()

        print("DESIGN PARAMETERS:")
        print(f"  Beam span (L): {self.params.L} in ({self.params.L/12:.2f} ft)")
        print(f"  Distance between hinges (Lh): {self.params.Lh} in ({self.params.Lh/12:.2f} ft)")
        print(f"  System type: {self.params.system_type}")
        print(f"  C_pr (connection factor): {self.params.C_pr}")
        print()

        print("LOADS:")
        print(f"  Dead load (D): {self.loads.D} kips")
        print(f"  Live load (L): {self.loads.L} kips")
        print(f"  Snow load (S): {self.loads.S} kips")
        print(f"  Live load factor (f1): {self.loads.f1}")
        print(f"  Gravity load combination (1.2D + {self.loads.f1}L + 0.2S): {self.loads.gravity_combination:.2f} kips")
        print()

    def step1_check_rbs_geometry(self) -> bool:
        """Step 1: Check RBS geometry limits per Equations 5.8-1, 5.8-2, 5.8-3"""
        self.print_subsection("STEP 1: RBS GEOMETRY LIMITS CHECK")

        passed = True
        bf = self.beam.bf
        d = self.beam.d
        a = self.rbs.a
        b = self.rbs.b
        c = self.rbs.c

        print("AISC 358-16 Equation 5.8-1: 0.5*bf <= a <= 0.75*bf")
        a_min = 0.5 * bf
        a_max = 0.75 * bf
        print(f"  Required: {a_min:.3f} <= a <= {a_max:.3f} in")
        print(f"  Provided: a = {a:.3f} in")
        if a_min <= a <= a_max:
            print(f"  ✓ OK - a is within acceptable range")
            self.checks["5.8-1"] = True
        else:
            print(f"  ✗ FAIL - a is NOT within acceptable range")
            passed = False
            self.checks["5.8-1"] = False
        print()

        print("AISC 358-16 Equation 5.8-2: 0.65*d <= b <= 0.85*d")
        b_min = 0.65 * d
        b_max = 0.85 * d
        print(f"  Required: {b_min:.3f} <= b <= {b_max:.3f} in")
        print(f"  Provided: b = {b:.3f} in")
        if b_min <= b <= b_max:
            print(f"  ✓ OK - b is within acceptable range")
            self.checks["5.8-2"] = True
        else:
            print(f"  ✗ FAIL - b is NOT within acceptable range")
            passed = False
            self.checks["5.8-2"] = False
        print()

        print("AISC 358-16 Equation 5.8-3: 0.1*bf <= c <= 0.25*bf")
        c_min = 0.1 * bf
        c_max = 0.25 * bf
        print(f"  Required: {c_min:.3f} <= c <= {c_max:.3f} in")
        print(f"  Provided: c = {c:.3f} in")
        if c_min <= c <= c_max:
            print(f"  ✓ OK - c is within acceptable range")
            self.checks["5.8-3"] = True
        else:
            print(f"  ✗ FAIL - c is NOT within acceptable range")
            passed = False
            self.checks["5.8-3"] = False
        print()

        # Calculate flange reduction percentage
        reduction_pct = (c / bf) * 100
        print(f"Flange reduction: {reduction_pct:.1f}%")
        print(f"  (This affects elastic drift calculation)")
        print()

        return passed

    def step2_calculate_ZRBS(self):
        """Step 2: Calculate plastic section modulus at reduced beam section"""
        self.print_subsection("STEP 2: PLASTIC SECTION MODULUS AT RBS")

        # Equation 5.8-4: Z_RBS = Z_x - 2*c*t_bf*(d - t_bf)
        Zx = self.beam.Zx
        c = self.rbs.c
        tf = self.beam.tf
        d = self.beam.d

        self.Z_RBS = Zx - 2 * c * tf * (d - tf)

        reduction = Zx - self.Z_RBS
        reduction_pct = (reduction / Zx) * 100

        print("AISC 358-16 Equation 5.8-4:")
        print("  Z_RBS = Z_x - 2*c*t_bf*(d - t_bf)")
        print(f"  Z_RBS = {Zx:.1f} - 2*{c:.3f}*{tf:.3f}*({d:.3f} - {tf:.3f})")
        print(f"  Z_RBS = {Zx:.1f} - {2*c*tf*(d-tf):.1f}")
        print(f"  Z_RBS = {self.Z_RBS:.1f} in³")
        print()
        print(f"  Reduction in Z: {reduction:.1f} in³ ({reduction_pct:.1f}%)")
        print()

    def calculate_Cpr(self) -> float:
        """
        Calculate connection strength factor C_pr per AISC 358-16 Equation 2.4-2

        C_pr = (F_y + F_u) / (2*F_y) <= 1.2

        Returns:
            C_pr value (not exceeding 1.2)
        """
        Fy = self.beam.Fy
        Fu = self.beam.Fu
        cpr = (Fy + Fu) / (2 * Fy)
        return min(cpr, 1.2)

    def step3_calculate_Mpr(self):
        """Step 3: Calculate probable maximum moment at RBS"""
        self.print_subsection("STEP 3: PROBABLE MAXIMUM MOMENT AT RBS")

        # Determine C_pr value
        if self.params.use_calculated_Cpr or self.params.C_pr is None:
            C_pr = self.calculate_Cpr()
            print("C_pr calculated per AISC 358-16 Equation 2.4-2:")
            print(f"  C_pr = (F_y + F_u) / (2*F_y)")
            print(f"  C_pr = ({self.beam.Fy} + {self.beam.Fu}) / (2*{self.beam.Fy})")
            print(f"  C_pr = {C_pr:.3f} (limited to 1.2)")
        else:
            C_pr = self.params.C_pr
            print(f"Using user-specified C_pr = {C_pr}")

        print()

        # Equation 5.8-5: M_pr = C_pr * R_y * F_y * Z_RBS
        Ry = self.beam.Ry
        Fy = self.beam.Fy
        Z_RBS = self.Z_RBS

        self.M_pr = C_pr * Ry * Fy * Z_RBS

        print("AISC 358-16 Equation 5.8-5:")
        print("  M_pr = C_pr * R_y * F_y * Z_RBS")
        print(f"  M_pr = {C_pr:.3f} * {Ry} * {Fy} * {Z_RBS:.1f}")
        print(f"  M_pr = {self.M_pr:.0f} kip-in")
        print(f"  M_pr = {self.M_pr/12:.1f} kip-ft")
        print()

    def step4_calculate_VRBS(self):
        """Step 4: Calculate shear force at RBS"""
        self.print_subsection("STEP 4: SHEAR FORCE AT RBS")

        # Calculate shear force at RBS from free-body diagram
        #
        # V_RBS = 2*M_pr/L_h + V_gravity
        #
        # Where:
        # - 2*M_pr/L_h is the seismic shear component (from plastic moments at both ends)
        # - V_gravity is the shear due to gravity loads at the RBS location
        #
        # Note: The current implementation assumes the user provides total gravity loads
        # (D, L, S) as point loads or total distributed loads. For a simply supported beam:
        # - If loads are total distributed loads: V_gravity = w_total * L_h / 2
        # - The current calculation uses: V_gravity = (1.2D + f1*L + 0.2S) / 2
        #   This assumes the user inputs are equivalent point loads at midspan
        #
        # For more accurate distributed load calculations, users should manually calculate
        # the gravity shear component and ensure it matches their loading conditions.

        # Calculate gravity shear component
        # Current assumption: User inputs are total loads, divide by 2 for max shear in simple beam
        V_gravity = self.loads.gravity_combination / 2
        self.V_gravity = V_gravity

        # Calculate V_RBS from free body diagram
        self.V_RBS = 2 * self.M_pr / self.params.Lh + V_gravity

        print("Shear at RBS from free-body diagram:")
        print("  V_RBS = 2*M_pr/L_h + V_gravity")
        print(f"  V_RBS = 2*{self.M_pr:.0f}/{self.params.Lh:.1f} + {V_gravity:.2f}")
        print(f"  V_RBS = {2*self.M_pr/self.params.Lh:.2f} + {V_gravity:.2f}")
        print(f"  V_RBS = {self.V_RBS:.2f} kips")
        print()
        print(f"  Gravity shear: {V_gravity:.2f} kips")
        print(f"  Seismic shear component: {2*self.M_pr/self.params.Lh:.2f} kips")
        print()
        print(f"  Note: Gravity load combination = {self.loads.gravity_combination:.2f} kips")
        print(f"        (1.2D + {self.loads.f1}L + 0.2S)")
        print()

    def step5_calculate_Mf(self):
        """Step 5: Calculate probable maximum moment at column face"""
        self.print_subsection("STEP 5: PROBABLE MAXIMUM MOMENT AT COLUMN FACE")

        # Calculate distance from column face to plastic hinge
        self.S_h = self.rbs.a + self.rbs.b / 2

        # Equation 5.8-6: M_f = M_pr + V_RBS * S_h
        self.M_f = self.M_pr + self.V_RBS * self.S_h

        print("Distance from column face to plastic hinge:")
        print("  S_h = a + b/2")
        print(f"  S_h = {self.rbs.a:.2f} + {self.rbs.b:.2f}/2")
        print(f"  S_h = {self.S_h:.2f} in")
        print()

        print("AISC 358-16 Equation 5.8-6:")
        print("  M_f = M_pr + V_RBS * S_h")
        print(f"  M_f = {self.M_pr:.0f} + {self.V_RBS:.2f}*{self.S_h:.2f}")
        print(f"  M_f = {self.M_f:.0f} kip-in")
        print(f"  M_f = {self.M_f/12:.1f} kip-ft")
        print()

    def step6_calculate_Mpe(self):
        """Step 6: Calculate plastic moment of beam"""
        self.print_subsection("STEP 6: PLASTIC MOMENT OF BEAM")

        # Equation 5.8-7: M_pe = R_y * F_y * Z_x
        Ry = self.beam.Ry
        Fy = self.beam.Fy
        Zx = self.beam.Zx

        self.M_pe = Ry * Fy * Zx

        print("AISC 358-16 Equation 5.8-7:")
        print("  M_pe = R_y * F_y * Z_x")
        print(f"  M_pe = {Ry} * {Fy} * {Zx:.1f}")
        print(f"  M_pe = {self.M_pe:.0f} kip-in")
        print(f"  M_pe = {self.M_pe/12:.1f} kip-ft")
        print()

    def step7_check_flexural_strength(self) -> bool:
        """Step 7: Check flexural strength at column face"""
        self.print_subsection("STEP 7: FLEXURAL STRENGTH CHECK AT COLUMN FACE")

        # Equation 5.8-8: M_f <= φ_d * M_pe
        phi_d = PHI_D
        M_pe = self.M_pe
        M_f = self.M_f
        phi_Mpe = phi_d * M_pe
        ratio = M_f / phi_Mpe

        print("AISC 358-16 Equation 5.8-8:")
        print("  M_f <= φ_d * M_pe")
        print(f"  M_f = {M_f:.0f} kip-in")
        print(f"  φ_d * M_pe = {phi_d} * {M_pe:.0f} = {phi_Mpe:.0f} kip-in")
        print(f"  Utilization ratio: {ratio:.3f}")
        print()

        if M_f <= phi_Mpe:
            print(f"  ✓ OK - Flexural strength is adequate")
            self.checks["5.8-8"] = True
            return True
        else:
            print(f"  ✗ FAIL - Flexural strength is NOT adequate")
            print(f"  Required: {M_f:.0f} kip-in")
            print(f"  Available: {phi_Mpe:.0f} kip-in")
            self.checks["5.8-8"] = False
            return False

    def step8_check_shear_strength(self) -> bool:
        """Step 8: Check shear strength"""
        self.print_subsection("STEP 8: SHEAR STRENGTH CHECK")

        # Equation 5.8-9: V_u = 2*M_pr/L_h + V_gravity
        Lh = self.params.Lh
        M_pr = self.M_pr
        V_gravity = self.V_gravity

        self.V_u = 2 * M_pr / Lh + V_gravity

        print("AISC 358-16 Equation 5.8-9:")
        print("  V_u = 2*M_pr/L_h + V_gravity")
        print(f"  V_u = 2*{M_pr:.0f}/{Lh:.1f} + {V_gravity:.2f}")
        print(f"  V_u = {self.V_u:.2f} kips")
        print()

        # Calculate shear strength per AISC 360 Chapter G
        # V_n = 0.6*F_y*d_w*t_w for webs of rolled I-shaped shapes
        Fy = self.beam.Fy
        dw = self.beam.dw
        tw = self.beam.tw
        Vn = 0.6 * Fy * dw * tw
        phi_Vn = PHI_V * Vn
        ratio = self.V_u / phi_Vn

        print("Shear strength per AISC 360 Chapter G:")
        print("  V_n = 0.6*F_y*d_w*t_w")
        print(f"  V_n = 0.6*{Fy}*{dw:.3f}*{tw:.3f}")
        print(f"  V_n = {Vn:.2f} kips")
        print(f"  φ_v * V_n = {PHI_V} * {Vn:.2f} = {phi_Vn:.2f} kips")
        print(f"  Utilization ratio: {ratio:.3f}")
        print()

        if self.V_u <= phi_Vn:
            print(f"  ✓ OK - Shear strength is adequate")
            self.checks["shear"] = True
            return True
        else:
            print(f"  ✗ FAIL - Shear strength is NOT adequate")
            print(f"  Required: {self.V_u:.2f} kips")
            print(f"  Available: {phi_Vn:.2f} kips")
            self.checks["shear"] = False
            return False

    def step9_web_connection(self):
        """Step 9: Beam web-to-column connection requirements"""
        self.print_subsection("STEP 9: BEAM WEB-TO-COLUMN CONNECTION")

        print(f"System type: {self.params.system_type}")
        print()

        if self.params.system_type == "SMF":
            print("For SMF systems (Section 5.6.2.a):")
            print("  - Beam web shall be connected using CJP groove weld")
            print("  - Single-plate shear connection shall extend between weld access holes")
            print("  - Minimum plate thickness: 3/8 in. (10 mm)")
            print("  - Weld tabs are not required at ends of CJP groove weld")
        else:  # IMF
            print("For IMF systems (Section 5.6.2.b):")
            print("  - Beam web shall be connected using CJP groove weld (same as SMF)")
            print("  Exception: Bolted single-plate shear connection is permitted")
            print("    - Connection shall be slip-critical")
            print("    - Design based on shear yielding and shear rupture")
            print("    - Plate welded to column flange (CJP or double fillet welds)")
        print()

        print(f"Required shear strength for web connection: V_u = {self.V_u:.2f} kips")
        print(f"  Design web connection for this shear force per AISC 360")
        print()

    def step10_continuity_plates(self):
        """Step 10: Continuity plate requirements"""
        self.print_subsection("STEP 10: CONTINUITY PLATE REQUIREMENTS")

        print("Continuity plates shall be provided per Chapter 2 of AISC 358-16")
        print("  when required based on column flange thickness and force transfer")
        print()

        # Check if continuity plates might be required
        # This is a simplified check - refer to Chapter 2 for detailed requirements
        print("Refer to AISC 358-16 Chapter 2 for detailed continuity plate requirements:")
        print("  - Panel zone strength")
        print("  - Column flange bending")
        print("  - Force transfer through column flange")
        print()

    def step11_column_beam_relationship(self) -> bool:
        """Step 11: Check column-beam relationship limitations"""
        self.print_subsection("STEP 11: COLUMN-BEAM RELATIONSHIP LIMITATIONS")

        print(f"System type: {self.params.system_type}")
        print()

        # Calculate ΣM_pb* for column-beam moment ratio check
        # ΣM_pb* = Σ(M_pr + M_uv)
        # M_uv = V_RBS * (a + b/2 + d_c/2)

        # M_uv for one beam
        Sh_total = self.rbs.a + self.rbs.b/2 + self.column.d/2
        M_uv = self.V_RBS * Sh_total

        # M_pb* for one beam (assuming beams on both sides of column)
        M_pb_star = self.M_pr + M_uv

        print("Column-beam moment ratio check (Section 5.4):")
        print(f"  M_pr = {self.M_pr:.0f} kip-in")
        print(f"  Distance a + b/2 + dc/2 = {Sh_total:.2f} in")
        print(f"  M_uv = V_RBS * (a + b/2 + dc/2)")
        print(f"  M_uv = {self.V_RBS:.2f} * {Sh_total:.2f} = {M_uv:.0f} kip-in")
        print(f"  M_pb* = M_pr + M_uv = {M_pb_star:.0f} kip-in")
        print()

        if self.params.system_type == "SMF":
            print("For SMF systems:")
            print("  ΣM_nc >= ΣM_pb* (AISC Seismic Provisions)")
            print("  where ΣM_pb* is calculated as shown above")
            print("  ΣM_pb* for both sides of column = 2 * M_pb*")
            print(f"    = 2 * {M_pb_star:.0f} = {2*M_pb_star:.0f} kip-in")
            print()
            print("  Column must be designed for strong-column/weak-beam requirement")
            print("  per AISC Seismic Provisions")
        else:
            print("For IMF systems:")
            print("  Column-beam moment ratio shall conform to AISC Seismic Provisions")
        print()

        # Check column depth limitation
        max_depth = 36  # W36 maximum for rolled shape columns
        if self.column.d <= max_depth:
            print(f"  ✓ Column depth ({self.column.d} in) is within W36 limitation")
            self.checks["column_depth"] = True
        else:
            print(f"  ✗ Column depth ({self.column.d} in) exceeds W36 limitation")
            self.checks["column_depth"] = False

        print()
        return self.checks.get("column_depth", True)

    def print_summary(self, all_passed: bool):
        """Print design verification summary"""
        self.print_section("DESIGN VERIFICATION SUMMARY")

        print("CHECKS SUMMARY:")
        print()

        # RBS Geometry Limits
        print("RBS Geometry Limits:")
        print(f"  Equation 5.8-1 (a limits): {'✓ PASS' if self.checks.get('5.8-1', True) else '✗ FAIL'}")
        print(f"  Equation 5.8-2 (b limits): {'✓ PASS' if self.checks.get('5.8-2', True) else '✗ FAIL'}")
        print(f"  Equation 5.8-3 (c limits): {'✓ PASS' if self.checks.get('5.8-3', True) else '✗ FAIL'}")
        print()

        # Strength Checks
        print("Strength Checks:")
        print(f"  Flexural strength at column face (Eq. 5.8-8): {'✓ PASS' if self.checks.get('5.8-8', True) else '✗ FAIL'}")
        print(f"    Utilization: {self.M_f/(PHI_D*self.M_pe):.2f}" if self.M_f and self.M_pe else "")
        print(f"  Shear strength: {'✓ PASS' if self.checks.get('shear', True) else '✗ FAIL'}")
        print(f"    Utilization: {self.V_u/(PHI_V*0.6*self.beam.Fy*self.beam.dw*self.beam.tw):.2f}" if self.V_u else "")
        print()

        # Key Results
        print("KEY RESULTS:")
        if self.Z_RBS:
            print(f"  Z_RBS: {self.Z_RBS:.1f} in³")
        if self.M_pr:
            print(f"  M_pr: {self.M_pr:.0f} kip-in ({self.M_pr/12:.1f} kip-ft)")
        if self.M_f:
            print(f"  M_f: {self.M_f:.0f} kip-in ({self.M_f/12:.1f} kip-ft)")
        if self.V_u:
            print(f"  V_u: {self.V_u:.2f} kips")
        print()

        # Overall Status
        self.print_separator("=")
        if all_passed:
            print("  ✓ ALL CHECKS PASSED - RBS CONNECTION DESIGN IS ADEQUATE")
        else:
            print("  ✗ SOME CHECKS FAILED - REVIEW AND ADJUST DESIGN")
        self.print_separator("=")
        print()


# ====================== SECTION DATABASE (FROM CSV) ======================

# Global variable to hold loaded sections
_SECTIONS_CACHE: Dict[str, Dict] = {}


def get_csv_file_path() -> str:
    """Get the path to the AISC W shapes CSV file"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(script_dir, "aisc_w_shapes.csv")
    return csv_path


def load_sections_from_csv() -> Dict[str, Dict]:
    """
    Load all W-shape sections from CSV file

    Returns:
        Dictionary mapping designation to properties
    """
    global _SECTIONS_CACHE

    if _SECTIONS_CACHE:
        return _SECTIONS_CACHE

    csv_path = get_csv_file_path()

    if not os.path.exists(csv_path):
        raise FileNotFoundError(
            f"Section database file not found: {csv_path}\n"
            f"Please ensure aisc_w_shapes.csv is in the same directory as this script."
        )

    sections = {}
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                designation = row['designation']
                sections[designation.upper()] = {
                    'designation': designation,
                    'd': float(row['d']),
                    'bf': float(row['bf']),
                    'tw': float(row['tw']),
                    'tf': float(row['tf']),
                    'Zx': float(row['Zx']),
                }
            except (ValueError, KeyError) as e:
                # Skip invalid rows
                continue

    _SECTIONS_CACHE = sections
    return sections


def get_all_sections() -> Dict[str, Dict]:
    """Get all available sections from CSV file"""
    return load_sections_from_csv()


def get_section_properties(designation: str, section_type: str = "beam") -> Optional[Dict]:
    """
    Get section properties from CSV database

    Args:
        designation: Section designation (e.g., "W30x99", "W30X99")
        section_type: "beam" or "column" (both use the same database)

    Returns:
        Dictionary with section properties or None if not found
    """
    # Load sections from CSV
    sections = load_sections_from_csv()

    # Clean up designation for matching (convert to uppercase)
    designation_clean = designation.upper().replace(" ", "")

    # Try exact match (case-insensitive)
    for name, props in sections.items():
        name_clean = name.upper().replace(" ", "")
        if designation_clean == name_clean:
            return props.copy()

    # Try partial match - if user provides partial designation
    for name, props in sections.items():
        name_clean = name.upper().replace(" ", "")
        if designation_clean in name_clean or name_clean in designation_clean:
            return props.copy()

    return None


def list_available_sections() -> List[str]:
    """List all available section designations"""
    sections = load_sections_from_csv()
    return sorted(sections.keys())


def create_beam_from_args(args):
    """Create BeamSection from command line arguments"""
    if args.beam_section:
        props = get_section_properties(args.beam_section, "beam")
        if props:
            return BeamSection(
                designation=props["designation"],
                d=args.beam_d if args.beam_d else props["d"],
                bf=args.beam_bf if args.beam_bf else props["bf"],
                tf=args.beam_tf if args.beam_tf else props["tf"],
                tw=args.beam_tw if args.beam_tw else props["tw"],
                Zx=args.beam_Zx if args.beam_Zx else props["Zx"],
                Fy=args.beam_Fy,
                Fu=args.beam_Fu,
                Ry=args.beam_Ry,
            )

    # Use provided values
    if all([args.beam_d, args.beam_bf, args.beam_tf, args.beam_tw, args.beam_Zx]):
        return BeamSection(
            designation="Custom",
            d=args.beam_d,
            bf=args.beam_bf,
            tf=args.beam_tf,
            tw=args.beam_tw,
            Zx=args.beam_Zx,
            Fy=args.beam_Fy,
            Fu=args.beam_Fu,
            Ry=args.beam_Ry,
        )

    raise ValueError("Invalid beam section parameters")


def create_column_from_args(args):
    """Create ColumnSection from command line arguments"""
    if args.column_section:
        props = get_section_properties(args.column_section, "column")
        if props:
            return ColumnSection(
                designation=props["designation"],
                d=args.column_d if args.column_d else props["d"],
                bf=args.column_bf if args.column_bf else props["bf"],
                tf=args.column_tf if args.column_tf else props["tf"],
                tw=args.column_tw if args.column_tw else props["tw"],
                Zx=args.column_Zx if args.column_Zx else props["Zx"],
                Fy=args.column_Fy,
                Ry=args.column_Ry,
            )

    # Use provided values
    if all([args.column_d, args.column_bf, args.column_tf, args.column_tw, args.column_Zx]):
        return ColumnSection(
            designation="Custom",
            d=args.column_d,
            bf=args.column_bf,
            tf=args.column_tf,
            tw=args.column_tw,
            Zx=args.column_Zx,
            Fy=args.column_Fy,
            Ry=args.column_Ry,
        )

    raise ValueError("Invalid column section parameters")


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="RBS Connection Design Verification (AISC 358-16)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Using section database
  python rbs_design.py --beam-section W30x99 --column-section W14x193

  # Custom section properties
  python rbs_design.py --beam-d 30 --beam-bf 10.45 --beam-tf 0.615 --beam-tw 0.36 --beam-Zx 311

  # With RBS geometry
  python rbs_design.py --beam-section W30x99 --column-section W14x193 --rbs-a 6 --rbs-b 22 --rbs-c 1.5

  # List all available sections
  python rbs_design.py --list-sections
        """
    )

    # List sections option
    parser.add_argument("--list-sections", action="store_true",
                        help="List all available W-shape sections from database")

    # Beam parameters
    beam_group = parser.add_argument_group("Beam Parameters")
    beam_group.add_argument("--beam-section", type=str,
                            help="Beam section designation (e.g., W30x99)")
    beam_group.add_argument("--beam-d", type=float,
                            help="Beam depth (in)")
    beam_group.add_argument("--beam-bf", type=float,
                            help="Beam flange width (in)")
    beam_group.add_argument("--beam-tf", type=float,
                            help="Beam flange thickness (in)")
    beam_group.add_argument("--beam-tw", type=float,
                            help="Beam web thickness (in)")
    beam_group.add_argument("--beam-Zx", type=float,
                            help="Beam plastic section modulus (in^3)")
    beam_group.add_argument("--beam-Fy", type=float, default=50.0,
                            help="Beam yield stress (ksi), default: 50")
    beam_group.add_argument("--beam-Fu", type=float, default=65.0,
                            help="Beam tensile strength (ksi), default: 65 (for C_pr calculation)")
    beam_group.add_argument("--beam-Ry", type=float, default=1.1,
                            help="Beam material overstrength factor, default: 1.1")

    # Column parameters
    column_group = parser.add_argument_group("Column Parameters")
    column_group.add_argument("--column-section", type=str,
                              help="Column section designation (e.g., W14x193)")
    column_group.add_argument("--column-d", type=float,
                              help="Column depth (in)")
    column_group.add_argument("--column-bf", type=float,
                              help="Column flange width (in)")
    column_group.add_argument("--column-tf", type=float,
                              help="Column flange thickness (in)")
    column_group.add_argument("--column-tw", type=float,
                              help="Column web thickness (in)")
    column_group.add_argument("--column-Zx", type=float,
                              help="Column plastic section modulus (in^3)")
    column_group.add_argument("--column-Fy", type=float, default=50.0,
                              help="Column yield stress (ksi), default: 50")
    column_group.add_argument("--column-Ry", type=float, default=1.1,
                              help="Column material overstrength factor, default: 1.1")

    # RBS geometry
    rbs_group = parser.add_argument_group("RBS Geometry")
    rbs_group.add_argument("--rbs-a", type=float,
                           help="Distance from column face to start of cut (in)")
    rbs_group.add_argument("--rbs-b", type=float,
                           help="Length of cut (in)")
    rbs_group.add_argument("--rbs-c", type=float,
                           help="Depth of cut at center (in)")

    # Design parameters
    design_group = parser.add_argument_group("Design Parameters")
    design_group.add_argument("--span", type=float, default=360,
                              help="Beam span (in), default: 360 (30 ft)")
    design_group.add_argument("--Lh", type=float,
                              help="Distance between plastic hinges (in)")
    design_group.add_argument("--system-type", type=str, required=True,
                              choices=["SMF", "IMF"],
                              help="System type (SMF or IMF), required")
    design_group.add_argument("--C-pr", type=float, default=None,
                              help="Connection strength factor (default: calculate per Eq. 2.4-2)")
    design_group.add_argument("--use-calc-cpr", action="store_true",
                              help="Calculate C_pr from Fy and Fu (Eq. 2.4-2), overrides --C-pr")

    # Loads
    load_group = parser.add_argument_group("Loads")
    load_group.add_argument("--load-D", type=float, default=0,
                           help="Dead load (kips), default: 0")
    load_group.add_argument("--load-L", type=float, default=0,
                           help="Live load (kips), default: 0")
    load_group.add_argument("--load-S", type=float, default=0,
                           help="Snow load (kips), default: 0")
    load_group.add_argument("--load-f1", type=float, default=0.5,
                           help="Live load factor, default: 0.5")

    return parser.parse_args()


# ====================== MAIN ======================

def main():
    """Main function"""
    # Check for --list-sections before parsing all arguments
    if "--list-sections" in sys.argv:
        # Parse only the list-sections argument
        pre_parser = argparse.ArgumentParser(add_help=False)
        pre_parser.add_argument("--list-sections", action="store_true")
        pre_args, _ = pre_parser.parse_known_args()

        print("Available W-shape sections from database:")
        print("=" * 80)
        sections = get_all_sections()
        for designation in sorted(sections.keys()):
            props = sections[designation]
            print(f"  {designation:12s}: d={props['d']:5.1f} in, bf={props['bf']:5.2f} in, "
                  f"tw={props['tw']:5.3f} in, tf={props['tf']:5.3f} in, Zx={props['Zx']:6.1f} in³")
        print("=" * 80)
        print(f"Total: {len(sections)} W-shape sections")
        sys.exit(0)

    # Parse command line arguments
    args = parse_args()

    try:
        # Create beam section
        beam = create_beam_from_args(args)

        # Create column section
        column = create_column_from_args(args)

        # Calculate or get RBS geometry
        if args.rbs_a and args.rbs_b and args.rbs_c:
            rbs = RBSGeometry(a=args.rbs_a, b=args.rbs_b, c=args.rbs_c)
        else:
            # Calculate initial RBS dimensions (use mid-range of limits)
            rbs = RBSGeometry(
                a=0.625 * beam.bf,  # Mid-range of 0.5-0.75
                b=0.75 * beam.d,     # Mid-range of 0.65-0.85
                c=0.175 * beam.bf    # Mid-range of 0.1-0.25
            )
            print(f"Note: Using calculated RBS geometry (a={rbs.a:.2f}, b={rbs.b:.2f}, c={rbs.c:.2f})")
            print("      Use --rbs-a, --rbs-b, --rbs-c to specify custom values")
            print()

        # Calculate Lh if not provided
        # Lh = distance between plastic hinge locations
        # = L - d_c - 2*(a + b/2), where L is center-to-center span
        if args.Lh:
            Lh = args.Lh
        else:
            Lh = args.span - column.d - 2 * (rbs.a + rbs.b/2)

        # Create design parameters
        # Determine whether to calculate C_pr or use fixed value
        if args.use_calc_cpr:
            use_calc_cpr = True
        elif args.C_pr is not None:
            use_calc_cpr = False
        else:
            # Default: calculate C_pr
            use_calc_cpr = True

        params = DesignParameters(
            L=args.span,
            Lh=Lh,
            system_type=args.system_type,
            C_pr=args.C_pr,
            use_calculated_Cpr=use_calc_cpr,
        )

        # Create loads
        loads = Loads(
            D=args.load_D,
            L=args.load_L,
            S=args.load_S,
            f1=args.load_f1,
        )

        # Run design verification
        checker = RBSDesignChecker(beam, column, rbs, params, loads)
        all_passed = checker.run_all_checks()

        # Return exit code
        sys.exit(0 if all_passed else 1)

    except ValueError as e:
        print(f"Error: {e}")
        print()
        print("Tip: Use --help for usage information")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
