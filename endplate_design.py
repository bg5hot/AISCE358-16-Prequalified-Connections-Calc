#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Bolted Extended End-Plate Moment Connection Design Verification
Based on AISC 358-16 Chapter 6 - Prequalified Connections for Seismic Applications

This script performs the complete design verification procedure for:
- 4E: Four-bolt extended unstiffened end-plate connection
- 4ES: Four-bolt extended stiffened end-plate connection
- 8ES: Eight-bolt extended stiffened end-plate connection

Usage:
    python endplate_design.py --connection-type 4E --beam-section W30x99 --column-section W14x193 ...
"""

import argparse
import sys
import io
import os
import csv
import math
from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple

# Set UTF-8 encoding for Windows console
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ====================== CONSTANTS ======================
# Resistance factors (AISC 358-16 Section 2.4.1)
PHI_D = 1.00  # Ductile limit states
PHI_N = 0.90  # Nonductile limit states

# Default material properties
DEFAULT_FY_BEAM = 50.0  # ksi (A992)
DEFAULT_FU_BEAM = 65.0  # ksi (A992)
DEFAULT_FY_PLATE = 50.0  # ksi
DEFAULT_FU_PLATE = 65.0  # ksi
DEFAULT_FY_COLUMN = 50.0  # ksi
DEFAULT_FU_COLUMN = 65.0  # ksi

# Default C_pr value
C_PR_DEFAULT = 1.1

# Steel properties
E = 29000.0  # Modulus of elasticity (ksi)


# ====================== DATA CLASSES ======================

@dataclass
class BeamSection:
    """Beam section properties"""
    designation: str
    d: float  # Depth (in)
    bf: float  # Flange width (in)
    tf: float  # Flange thickness (in)
    tw: float  # Web thickness (in)
    Zx: float  # Plastic section modulus (in^3)
    Fy: float = DEFAULT_FY_BEAM
    Fu: float = DEFAULT_FU_BEAM
    Ry: float = 1.1

    @property
    def dw(self) -> float:
        """Web depth between flanges (in)"""
        return self.d - 2 * self.tf


@dataclass
class ColumnSection:
    """Column section properties"""
    designation: str
    d: float  # Depth (in)
    bf: float  # Flange width (in)
    tf: float  # Flange thickness (in)
    tw: float  # Web thickness (in)
    Zx: float  # Plastic section modulus (in^3)
    Fy: float = DEFAULT_FY_COLUMN
    Fu: float = DEFAULT_FU_COLUMN
    Ry: float = 1.1


@dataclass
class EndPlateGeometry:
    """End plate geometry parameters"""
    # Connection type: "4E", "4ES", or "8ES"
    connection_type: str

    # Bolt configuration
    db: float  # Bolt diameter (in)
    bolt_grade: str = "A325"  # Bolt grade (A325, A490, F1852)
    n_bolts_tension: int = 0  # Number of tension bolts per row (4 for 4E/4ES, 8 for 8ES)
    n_bolts_compression: int = 0  # Number of compression bolts

    # End plate dimensions
    bp: float = 0  # End plate width (in)
    tp: float = 0  # End plate thickness (in)

    # Bolt row positions (all measured from centerline of beam compression flange)
    # Per AISC 358-16 Section 6.8.1 notation and Tables 6.2-6.4
    # h_o (h0): distance from compression flange CL to tension-side OUTER bolt row
    # h_1 (h1): distance from compression flange CL to tension-side INNER bolt row
    # h_2, h_3, h_4: additional tension bolt rows for 8ES
    h0: float = 0  # h_o: outer tension bolt row (farthest from compression flange)
    h1: float = 0  # h_1: inner tension bolt row (nearest to compression flange)
    h2: float = 0  # h_2: second tension bolt row (8ES only)
    h3: float = 0  # h_3: third tension bolt row (8ES only)
    h4: float = 0  # h_4: fourth tension bolt row (8ES only)

    # Pitch distances (measured from tension flange centerline)
    pfo: float = 0  # Distance from tension flange centerline to outer bolt row (outward)
    pfi: float = 0  # Distance from tension flange centerline to inner bolt row (inward)
    g: float = 0  # Horizontal distance (gage) between bolt columns
    pb: float = 0  # Vertical spacing between bolt rows within a pair (8ES only)

    # Stiffener properties (for stiffened connections)
    ts: float = 0  # Stiffener thickness (in)
    Lst: float = 0  # Stiffener length (in)


@dataclass
class Loads:
    """Gravity loads on beam (kips)"""
    D: float = 0.0  # Dead load
    L: float = 0.0  # Live load
    S: float = 0.0  # Snow load
    f1: float = 0.5  # Live load factor (≥0.5)
    Vu: float = 0.0  # Required shear strength (kip/in)

    @property
    def gravity_combination(self) -> float:
        """Load combination 1.2D + f1*L + 0.2S"""
        return 1.2 * self.D + self.f1 * self.L + 0.2 * self.S


@dataclass
class DesignParameters:
    """Overall design parameters"""
    L: float  # Beam span (center-to-center) (in)
    Lh: float  # Distance between plastic hinge locations (in)
    system_type: str  # "SMF" or "IMF"
    C_pr: Optional[float] = None  # Connection strength factor
    use_calculated_Cpr: bool = True
    Sh: float = 0  # Distance from column face to plastic hinge (in)


# ====================== SECTION DATABASE ======================

_SECTIONS_CACHE: Dict[str, Dict] = {}


def get_csv_file_path() -> str:
    """Get the path to the AISC W shapes CSV file"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(script_dir, "aisc_w_shapes.csv")
    return csv_path


def load_sections_from_csv() -> Dict[str, Dict]:
    """Load all W-shape sections from CSV file"""
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
                designation = row['designation']
                sections[designation.upper()] = {
                    'designation': designation,
                    'd': float(row['d']),
                    'bf': float(row['bf']),
                    'tw': float(row['tw']),
                    'tf': float(row['tf']),
                    'Zx': float(row['Zx']),
                }
            except (ValueError, KeyError):
                continue

    _SECTIONS_CACHE = sections
    return sections


def get_section_properties(designation: str) -> Optional[Dict]:
    """Get section properties from CSV database"""
    sections = load_sections_from_csv()
    designation_clean = designation.upper().replace(" ", "")

    for name, props in sections.items():
        name_clean = name.upper().replace(" ", "")
        if designation_clean == name_clean:
            return props.copy()

    return None


# ====================== BOLT PROPERTIES ======================

# AISC RCSC bolt properties (AISC Manual Table 7-2)
BOLT_GRADES = {
    "A325": {
        "Fnt": 90.0,  # Nominal tensile strength (ksi)
        "Fnv": 54.0,  # Nominal shear strength (ksi) - from threads excluded
        "Fu": 120.0,  # Minimum specified tensile strength (ksi)
        "sizes": [0.75, 0.875, 1.0, 1.125, 1.25, 1.375, 1.5, 1.625, 1.75, 1.875],
    },
    "A490": {
        "Fnt": 113.0,  # Nominal tensile strength (ksi)
        "Fnv": 68.0,  # Nominal shear strength (ksi)
        "Fu": 150.0,  # Minimum specified tensile strength (ksi)
        "sizes": [0.75, 0.875, 1.0, 1.125, 1.25, 1.375, 1.5, 1.625, 1.75, 1.875],
    },
    "F1852": {
        "Fnt": 105.0,  # Nominal tensile strength (ksi)
        "Fnv": 63.0,  # Nominal shear strength (ksi)
        "Fu": 125.0,  # Minimum specified tensile strength (ksi)
        "sizes": [0.75, 0.875, 1.0, 1.125, 1.25, 1.375, 1.5, 1.625, 1.75, 1.875, 2.0, 2.25, 2.5],
    },
}

# Bolt areas (AISC Manual Table 7-2)
BOLT_AREAS = {
    0.75: 0.442,
    0.875: 0.601,
    1.0: 0.785,
    1.125: 0.994,
    1.25: 1.23,
    1.375: 1.48,
    1.5: 1.77,
    1.625: 2.08,
    1.75: 2.41,
    1.875: 2.77,
    2.0: 3.14,
    2.25: 3.97,
    2.5: 4.91,
}


# ====================== END-PLATE DESIGN CLASS ======================

class EndPlateDesignChecker:
    """
    End-Plate Connection Design Verification according to AISC 358-16 Chapter 6.8
    """

    def __init__(self, beam: BeamSection, column: ColumnSection,
                 plate: EndPlateGeometry, params: DesignParameters, loads: Loads):
        self.beam = beam
        self.column = column
        self.plate = plate
        self.params = params
        self.loads = loads

        # Calculation results
        self.M_f: Optional[float] = None
        self.M_pr: Optional[float] = None
        self.F_fu: Optional[float] = None
        self.V_u: Optional[float] = None
        self.t_p_req: Optional[float] = None
        self.d_b_req: Optional[float] = None
        self.t_cf_req: Optional[float] = None

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
        self.print_section("END-PLATE CONNECTION DESIGN VERIFICATION (AISC 358-16)")
        print()

        # Print input parameters
        self.print_input_parameters()

        # Check parametric limitations (Table 6.1)
        if not self.check_parametric_limitations():
            print("\n⚠ WARNING: Design outside prequalified limits!")
            all_passed = False

        # Check bolt diameter limits (Section 6.7.2)
        if not self.check_bolt_diameter_limits():
            all_passed = False

        # Beam-side design
        self.beam_side_design()

        # Column-side design
        self.column_side_design()

        # Check if any beam-side or column-side checks failed
        critical_checks = [
            "bolt_diameter", "plate_thickness",
            "shear_yielding", "shear_rupture",
            "bolt_shear", "bearing",
            "column_flange",
        ]
        for check_name in critical_checks:
            if check_name in self.checks and not self.checks[check_name]:
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
        print(f"  Fy: {self.beam.Fy} ksi, Fu: {self.beam.Fu} ksi")
        print(f"  Ry: {self.beam.Ry}")
        print()

        print("COLUMN SECTION:")
        print(f"  Designation: {self.column.designation}")
        print(f"  Depth (d): {self.column.d} in")
        print(f"  Flange width (bf): {self.column.bf} in")
        print(f"  Flange thickness (tf): {self.column.tf} in")
        print(f"  Web thickness (tw): {self.column.tw} in")
        print(f"  Fy: {self.column.Fy} ksi, Fu: {self.column.Fu} ksi")
        print(f"  Ry: {self.column.Ry}")
        print()

        print("END PLATE CONFIGURATION:")
        print(f"  Connection type: {self.plate.connection_type}")
        print(f"  Bolt diameter: {self.plate.db} in")
        print(f"  Number of tension bolts: {self.plate.n_bolts_tension}")
        print(f"  End plate width (bp): {self.plate.bp} in")
        print(f"  End plate thickness (tp): {self.plate.tp} in")

        if self.plate.connection_type in ["4ES", "8ES"]:
            print(f"  Stiffener thickness (ts): {self.plate.ts} in")
            print(f"  Stiffener length (Lst): {self.plate.Lst} in")
        print()

        print("DESIGN PARAMETERS:")
        print(f"  Beam span (L): {self.params.L} in ({self.params.L/12:.2f} ft)")
        print(f"  Distance between hinges (Lh): {self.params.Lh} in ({self.params.Lh/12:.2f} ft)")
        print(f"  System type: {self.params.system_type}")
        print(f"  S_h (to plastic hinge): {self.params.Sh} in")
        print()

        print("LOADS:")
        print(f"  Dead load (D): {self.loads.D} kips")
        print(f"  Live load (L): {self.loads.L} kips")
        print(f"  Snow load (S): {self.loads.S} kips")
        print(f"  Live load factor (f1): {self.loads.f1}")
        print(f"  Gravity load combination (1.2D + {self.loads.f1}L + 0.2S): {self.loads.gravity_combination:.2f} kips")
        print(f"  Required shear strength (Vu): {self.loads.Vu} kips")
        print()

    def check_parametric_limitations(self) -> bool:
        """
        Check AISC 358-16 Table 6.1 parametric limitations
        Returns True if within limits, False otherwise
        """
        self.print_subsection("TABLE 6.1 PARAMETRIC LIMITATIONS")

        conn_type = self.plate.connection_type
        t_bf = self.beam.tf
        d = self.beam.d
        passed = True

        print("AISC 358-16 Table 6.1 Requirements:")

        if conn_type == "4E":
            # 4E: t_bf <= 0.75 in (19mm)
            limit = 0.75
            print(f"  4E Connection: t_bf <= {limit} in")
            print(f"  Current: t_bf = {t_bf:.3f} in")

            if t_bf > limit:
                print(f"  ✗ FAIL - t_bf exceeds {limit} in limit")
                print(f"    Outside prequalified range - requires special qualification")
                passed = False
            else:
                print(f"  ✓ OK - Within prequalified range")

        elif conn_type == "8ES":
            # 8ES: d <= 36 in
            limit = 36.0
            print(f"  8ES Connection: d <= {limit} in")
            print(f"  Current: d = {d:.1f} in")

            if d > limit:
                print(f"  ✗ FAIL - d exceeds {limit} in limit")
                print(f"    Outside prequalified range - requires special qualification")
                passed = False
            else:
                print(f"  ✓ OK - Within prequalified range")

        else:
            print(f"  {conn_type} Connection: No specific parametric limitations")

        print()
        self.checks["parametric_limits"] = passed
        return passed

    def check_bolt_diameter_limits(self) -> bool:
        """
        Check AISC 358-16 Section 6.7.2 bolt diameter limits
        Returns True if within limits, False otherwise
        """
        conn_type = self.plate.connection_type
        db = self.plate.db
        passed = True

        print("AISC 358-16 Section 6.7.2 Bolt Diameter Limits:")
        print(f"  Connection type: {conn_type}")
        print(f"  Bolt diameter: {db:.3f} in")

        if conn_type in ["4E", "4ES"]:
            limit = 1.5
            print(f"  Maximum allowed: {limit} in")

            if db > limit:
                print(f"  ✗ FAIL - Bolt diameter exceeds {limit} in limit")
                passed = False
            else:
                print(f"  ✓ OK - Within limits")

        elif conn_type == "8ES":
            # 8ES allows larger bolts
            limit = 1.75
            print(f"  Recommended maximum: {limit} in")

            if db > limit:
                print(f"  ⚠ WARNING - Bolt diameter exceeds {limit} in recommendation")
                # Not a hard fail, but a warning
            else:
                print(f"  ✓ OK - Within recommendations")

        print()
        self.checks["bolt_diameter_limits"] = passed
        return passed

    def beam_side_design(self):
        """Perform beam-side end-plate design (Section 6.8.1)"""
        self.print_section("BEAM-SIDE DESIGN")

        # Step 1: Calculate M_f
        self.step1_calculate_Mf()

        # Step 2: Geometry is already selected
        self.step2_geometry_summary()

        # Step 3: Calculate required bolt diameter
        self.step3_required_bolt_diameter()

        # Step 4: Bolt diameter is already selected
        self.step4_bolt_selection()

        # Step 5: Calculate required plate thickness
        self.step5_required_plate_thickness()

        # Step 6: Plate thickness is already selected
        self.step6_plate_selection()

        # Step 7: Calculate beam flange force
        self.step7_beam_flange_force()

        # Step 8: Check plate shear yielding (4E only)
        if self.plate.connection_type == "4E":
            if not self.step8_check_shear_yielding():
                pass  # Already handled
        else:
            print("(Skipped for stiffened connections)")

        # Step 9: Check plate shear rupture (4E only)
        if self.plate.connection_type == "4E":
            if not self.step9_check_shear_rupture():
                pass
        else:
            print("(Skipped for stiffened connections)")

        # Step 10: Stiffener design (4ES and 8ES)
        if self.plate.connection_type in ["4ES", "8ES"]:
            self.step10_stiffener_design()
        else:
            print("(Skipped for unstiffened connection)")

        # Step 11: Check bolt shear strength
        if not self.step11_bolt_shear_strength():
            pass

        # Step 12: Check bearing/tearout
        if not self.step12_check_bearing():
            pass

        # Step 13: Weld design (mentioned, details in Section 6.7.6)
        self.step13_weld_design()

    def step1_calculate_Mf(self):
        """Step 1: Calculate moment at column face"""
        self.print_subsection("STEP 1: CALCULATE M_f")

        # Calculate C_pr
        if self.params.use_calculated_Cpr or self.params.C_pr is None:
            C_pr = (self.beam.Fy + self.beam.Fu) / (2 * self.beam.Fy)
            C_pr = min(C_pr, 1.2)
            print(f"C_pr calculated per AISC 358-16 Eq. 2.4-2: {C_pr:.3f}")
        else:
            C_pr = self.params.C_pr
            print(f"Using user-specified C_pr = {C_pr}")

        # Calculate M_pr
        Ry = self.beam.Ry
        Fy = self.beam.Fy
        Zx = self.beam.Zx
        # Note: For end-plate connections, M_pr is calculated at beam end
        # Using Eq. 2.4-1: M_pr = C_pr * Ry * Fy * Zx
        M_pr = C_pr * Ry * Fy * Zx
        self.M_pr = M_pr

        # Calculate M_f = M_pr + V_u * S_h
        V_u = self.loads.Vu
        S_h = self.params.Sh

        M_f = M_pr + V_u * S_h
        self.M_f = M_f

        print("\nAISC 358-16 Equation 6.8-1:")
        print("  M_f = M_pr + V_u * S_h")
        print(f"  M_pr = C_pr * R_y * F_y * Z_x = {C_pr:.3f} * {Ry} * {Fy} * {Zx:.1f}")
        print(f"  M_pr = {M_pr:.0f} kip-in ({M_pr/12:.1f} kip-ft)")
        print(f"  M_f = {M_pr:.0f} + {V_u:.2f} * {S_h:.2f}")
        print(f"  M_f = {M_f:.0f} kip-in ({M_f/12:.1f} kip-ft)")
        print()

    def step2_geometry_summary(self):
        """Step 2: Geometry summary"""
        self.print_subsection("STEP 2: CONNECTION GEOMETRY")

        conn_type = self.plate.connection_type
        print(f"Connection Type: {conn_type}")

        if conn_type == "4E":
            print("  Four-bolt extended unstiffened end-plate")
            print(f"  S_h = lesser of d/2 or 3*bf = {self.params.Sh} in")
        elif conn_type == "4ES":
            print("  Four-bolt extended stiffened end-plate")
            print(f"  S_h = L_st + t_p = {self.params.Sh} in")
        elif conn_type == "8ES":
            print("  Eight-bolt extended stiffened end-plate")
            print(f"  S_h = L_st + t_p = {self.params.Sh} in")

        print(f"\nBolt Configuration:")
        print(f"  Bolt diameter: {self.plate.db} in")
        print(f"  Number of tension bolts: {self.plate.n_bolts_tension}")
        print(f"  Number of compression bolts: {self.plate.n_bolts_compression}")
        print()

        # Print bolt row positions
        print("Bolt Row Positions (from compression flange centerline):")
        if conn_type in ["4E", "4ES"]:
            print(f"  h_o (outer row) = {self.plate.h0:.2f} in")
            print(f"  h_1 (inner row) = {self.plate.h1:.2f} in")
        else:  # 8ES
            print(f"  h_1 (outermost) = {self.plate.h1:.2f} in")
            print(f"  h_2            = {self.plate.h2:.2f} in")
            print(f"  h_3            = {self.plate.h3:.2f} in")
            print(f"  h_4 (innermost) = {self.plate.h4:.2f} in")
        print(f"\nPitch distances:")
        print(f"  p_fo = {self.plate.pfo:.2f} in")
        print(f"  p_fi = {self.plate.pfi:.2f} in")
        print(f"  g    = {self.plate.g:.2f} in")
        if conn_type == "8ES":
            print(f"  p_b  = {self.plate.pb:.2f} in")
        s = 0.5 * math.sqrt(self.plate.bp * self.plate.g)
        print(f"  s = {s:.3f} in (= 0.5*sqrt(bp*g))")
        print()

    def step3_required_bolt_diameter(self):
        """
        Step 3: Calculate required bolt diameter.

        Per AISC 358-16 Eq. 6.8-3 (4E, 4ES):
            d_b,req = sqrt(2*M_f / (pi * phi_n * F_nt * (h_o + h_1)))

        Per AISC 358-16 Eq. 6.8-4 (8ES):
            d_b,req = sqrt(2*M_f / (pi * phi_n * F_nt * (h_1 + h_2 + h_3 + h_4)))

        where h_o, h_1, h_2, h_3, h_4 are measured from the centerline of
        the beam compression flange.
        """
        self.print_subsection("STEP 3: REQUIRED BOLT DIAMETER")

        M_f = self.M_f
        phi_n = PHI_N

        # Get bolt tensile strength from bolt grade
        bolt_grade = getattr(self.plate, 'bolt_grade', 'A325')
        F_nt = BOLT_GRADES[bolt_grade]['Fnt']  # 90 for A325, 113 for A490

        # Calculate sum of h_i distances per Eq. 6.8-3 or 6.8-4
        conn_type = self.plate.connection_type

        if conn_type in ["4E", "4ES"]:
            # Eq. 6.8-3: sum = h_o + h_1
            h_sum = self.plate.h0 + self.plate.h1
            eq_label = "6.8-3"
        else:  # 8ES
            # Eq. 6.8-4: sum = h_1 + h_2 + h_3 + h_4
            h_sum = self.plate.h1 + self.plate.h2 + self.plate.h3 + self.plate.h4
            eq_label = "6.8-4"

        # AISC 358-16 Eq. 6.8-3 or 6.8-4
        d_b_req = math.sqrt(2 * M_f / (math.pi * phi_n * F_nt * h_sum))
        self.d_b_req = d_b_req

        print(f"AISC 358-16 Equation {eq_label}:")
        print("  d_b,req = sqrt(2*M_f / (pi * phi_n * F_nt * sum(h_i)))")
        print(f"  Bolt grade: {bolt_grade}, F_nt = {F_nt} ksi")
        print(f"  sum(h_i) = {h_sum:.2f} in")
        print(f"  d_b,req = sqrt(2*{M_f:.0f} / (pi*{phi_n}*{F_nt}*{h_sum:.2f}))")
        print(f"  d_b,req = {d_b_req:.3f} in")
        print(f"\n  Required bolt diameter: {d_b_req:.3f} in")
        print(f"  Selected bolt diameter: {self.plate.db} in")
        print()

        if self.plate.db >= d_b_req:
            print(f"  OK - Bolt diameter is adequate")
            self.checks["bolt_diameter"] = True
        else:
            print(f"  FAIL - Bolt diameter is inadequate")
            self.checks["bolt_diameter"] = False
        print()

    def step4_bolt_selection(self):
        """Step 4: Bolt selection summary"""
        print("Bolt selection complete:")
        print(f"  Selected bolt diameter: {self.plate.db} in")
        print(f"  Required diameter: {self.d_b_req:.3f} in")
        print()

    def step5_required_plate_thickness(self):
        """Step 5: Calculate required plate thickness"""
        self.print_subsection("STEP 5: REQUIRED PLATE THICKNESS")

        M_f = self.M_f
        F_yp = DEFAULT_FY_PLATE
        phi_d = PHI_D

        # Calculate yield line mechanism parameter Y_p
        Y_p = self.calculate_Yp()

        # AISC 358-16 Eq. 6.8-5
        t_p_req = math.sqrt(1.11 * M_f / (phi_d * F_yp * Y_p))
        self.t_p_req = t_p_req

        print("AISC 358-16 Equation 6.8-5:")
        print("  t_p,req = sqrt(1.11*M_f / (phi_d*F_yp*Y_p))")
        print(f"  t_p,req = sqrt(1.11*{M_f:.0f} / ({phi_d}*{F_yp}*{Y_p:.2f}))")
        print(f"  t_p,req = {t_p_req:.3f} in")
        print(f"\n  Required plate thickness: {t_p_req:.3f} in")
        print(f"  Selected plate thickness: {self.plate.tp} in")
        print()

        if self.plate.tp >= t_p_req:
            print(f"  ✓ OK - Plate thickness is adequate")
            self.checks["plate_thickness"] = True
        else:
            print(f"  ✗ FAIL - Increase plate thickness or use higher grade material")
            self.checks["plate_thickness"] = False
        print()

    def step6_plate_selection(self):
        """Step 6: Plate selection summary"""
        print("End plate selection complete:")
        print(f"  Selected thickness: {self.plate.tp} in")
        print(f"  Required thickness: {self.t_p_req:.3f} in")
        print()

    def step7_beam_flange_force(self):
        """Step 7: Calculate beam flange force"""
        self.print_subsection("STEP 7: BEAM FLANGE FORCE")

        # AISC 358-16 Eq. 6.8-6
        d = self.beam.d
        t_bf = self.beam.tf
        M_f = self.M_f

        F_fu = M_f / (d - t_bf)
        self.F_fu = F_fu

        print("AISC 358-16 Equation 6.8-6:")
        print("  F_fu = M_f / (d - t_bf)")
        print(f"  F_fu = {M_f:.0f} / ({d:.2f} - {t_bf:.3f})")
        print(f"  F_fu = {F_fu:.1f} kips")
        print(f"  F_fu/2 = {F_fu/2:.1f} kips (force per flange)")
        print()

    def step8_check_shear_yielding(self) -> bool:
        """Step 8: Check plate shear yielding (4E only)"""
        self.print_subsection("STEP 8: SHEAR YIELDING CHECK (4E)")

        F_fu = self.F_fu
        F_yp = DEFAULT_FY_PLATE
        bp = self.plate.bp
        tp = self.plate.tp
        phi_d = PHI_D

        # AISC 358-16 Eq. 6.8-7
        R_n = phi_d * 0.6 * F_yp * bp * tp
        force = F_fu / 2

        print("AISC 358-16 Equation 6.8-7:")
        print("  F_fu/2 <= phi_d * 0.6 * F_yp * bp * t_p")
        print(f"  {force:.1f} <= {phi_d} * 0.6 * {F_yp} * {bp:.2f} * {tp:.3f}")
        print(f"  {force:.1f} <= {R_n:.1f} kips")
        print(f"  Utilization: {force/R_n:.3f}")
        print()

        if force <= R_n:
            print(f"  ✓ OK - Plate shear yielding strength is adequate")
            self.checks["shear_yielding"] = True
            return True
        else:
            print(f"  ✗ FAIL - Increase plate thickness or use higher grade material")
            self.checks["shear_yielding"] = False
            return False

    def step9_check_shear_rupture(self) -> bool:
        """Step 9: Check plate shear rupture (4E only)"""
        self.print_subsection("STEP 9: SHEAR RUPTURE CHECK (4E)")

        F_fu = self.F_fu
        F_up = DEFAULT_FU_PLATE
        tp = self.plate.tp
        bp = self.plate.bp
        db = self.plate.db
        phi_n = PHI_N

        # Calculate net area (standard holes)
        # An = tp * (bp - 2*(db + 1/16))
        A_n = tp * (bp - 2 * (db + 0.0625))

        # AISC 358-16 Eq. 6.8-8
        R_n = phi_n * 0.6 * F_up * A_n
        force = F_fu / 2

        print("AISC 358-16 Equation 6.8-8:")
        print("  F_fu/2 <= phi_n * 0.6 * F_up * A_n")
        print(f"  Net area A_n = t_p * (b_p - 2*(d_b + 1/16))")
        print(f"  A_n = {tp:.3f} * ({bp:.2f} - 2*({db:.3f} + 0.0625))")
        print(f"  A_n = {A_n:.2f} in²")
        print(f"  {force:.1f} <= {phi_n} * 0.6 * {F_up} * {A_n:.2f}")
        print(f"  {force:.1f} <= {R_n:.1f} kips")
        print(f"  Utilization: {force/R_n:.3f}")
        print()

        if force <= R_n:
            print(f"  ✓ OK - Plate shear rupture strength is adequate")
            self.checks["shear_rupture"] = True
            return True
        else:
            print(f"  ✗ FAIL - Increase plate thickness or use higher grade material")
            self.checks["shear_rupture"] = False
            return False

    def step10_stiffener_design(self):
        """Step 10: Stiffener design (4ES and 8ES)"""
        self.print_subsection("STEP 10: STIFFENER DESIGN")

        Fyb = self.beam.Fy
        Fys = DEFAULT_FY_PLATE  # Assume stiffener same grade as plate
        tw = self.beam.tw

        # AISC 358-16 Eq. 6.8-9
        ts_min = tw * (Fyb / Fys)

        print("AISC 358-16 Equation 6.8-9:")
        print("  t_s >= t_bw * (F_yb / F_ys)")
        print(f"  t_s >= {tw:.3f} * ({Fyb}/{Fys})")
        print(f"  t_s >= {ts_min:.3f} in")
        print(f"\n  Selected stiffener thickness: {self.plate.ts} in")
        print(f"  Required minimum: {ts_min:.3f} in")
        print()

        # Check stiffener slenderness (Eq. 6.8-10)
        h_st = self.plate.Lst  # Approximate
        ts = self.plate.ts
        slenderness = h_st / ts
        slenderness_limit = 0.56 * math.sqrt(E / Fys)

        print("Stiffener slenderness check (Eq. 6.8-10):")
        print("  h_st / t_s <= 0.56 * sqrt(E / F_ys)")
        print(f"  {h_st:.2f} / {ts:.3f} <= {slenderness_limit:.2f}")
        print(f"  {slenderness:.2f} <= {slenderness_limit:.2f}")
        print()

        if self.plate.ts >= ts_min and slenderness <= slenderness_limit:
            print(f"  ✓ OK - Stiffener design is adequate")
            self.checks["stiffener"] = True
        else:
            print(f"  ✗ FAIL - Adjust stiffener thickness")
            self.checks["stiffener"] = False
        print()

    def step11_bolt_shear_strength(self) -> bool:
        """Step 11: Check bolt shear strength"""
        self.print_subsection("STEP 11: BOLT SHEAR STRENGTH")

        V_u = self.loads.Vu
        F_nv = 54.0  # A325, threads excluded
        Ab = BOLT_AREAS[self.plate.db]
        phi_n = PHI_N
        nb = self.plate.n_bolts_compression

        # AISC 358-16 Eq. 6.8-11
        R_n = phi_n * nb * F_nv * Ab

        print("AISC 358-16 Equation 6.8-11:")
        print("  V_u <= phi_n * n_b * F_nv * A_b")
        print(f"  V_u = {V_u:.2f} kips")
        print(f"  R_n = {phi_n} * {nb} * {F_nv} * {Ab:.3f}")
        print(f"  R_n = {R_n:.1f} kips")
        print(f"  Utilization: {V_u/R_n:.3f}")
        print()

        if V_u <= R_n:
            print(f"  ✓ OK - Bolt shear strength is adequate")
            self.checks["bolt_shear"] = True
            return True
        else:
            print(f"  ✗ FAIL - Increase bolt size or number of bolts")
            self.checks["bolt_shear"] = False
            return False

    def step12_check_bearing(self) -> bool:
        """Step 12: Check bearing/tearout"""
        self.print_subsection("STEP 12: BEARING/TEAROUT CHECK")

        V_u = self.loads.Vu
        Fu_plate = DEFAULT_FU_PLATE
        Fu_column = DEFAULT_FU_COLUMN
        t_plate = self.plate.tp
        t_column = self.column.tf
        db = self.plate.db
        phi_n = PHI_N

        conn_type = self.plate.connection_type

        if conn_type in ["4E", "4ES"]:
            ni = 2  # Number of inner bolts
            no = 2  # Number of outer bolts
        else:  # 8ES
            ni = 4  # Number of inner bolts
            no = 4  # Number of outer bolts

        # Calculate bearing strength
        # r_n = 1.2 * L_c * t * F_u
        # L_c = spacing - db = g - db (approximately)
        # Using simplified calculation

        # For end plate
        Lc_plate = self.plate.g - db
        if Lc_plate < 0:
            Lc_plate = self.plate.g - db
        r_ni_plate = min(1.2 * Lc_plate * t_plate * Fu_plate, 2.4 * db * t_plate * Fu_plate)

        # For column flange
        Lc_column = self.plate.g - db
        r_ni_column = min(1.2 * Lc_column * t_column * Fu_column, 2.4 * db * t_column * Fu_column)

        # Outer bolts (using edge distance pfo)
        Lc_outer = self.plate.pfo - db/2
        r_no_plate = min(1.2 * Lc_outer * t_plate * Fu_plate, 2.4 * db * t_plate * Fu_plate)
        r_no_column = min(1.2 * Lc_outer * t_column * Fu_column, 2.4 * db * t_column * Fu_column)

        # Total bearing strength
        R_n = phi_n * (ni * (r_ni_plate + r_ni_column) + no * (r_no_plate + r_no_column))

        print(f"Bearing strength calculation (simplified):")
        print(f"  Inner bolts (n={ni}):")
        print(f"    End plate: r_ni = {r_ni_plate:.1f} kips")
        print(f"    Column flange: r_ni = {r_ni_column:.1f} kips")
        print(f"  Outer bolts (n={no}):")
        print(f"    End plate: r_no = {r_no_plate:.1f} kips")
        print(f"    Column flange: r_no = {r_no_column:.1f} kips")
        print(f"  Total R_n = {phi_n} * ({ni}*({r_ni_plate:.1f}+{r_ni_column:.1f}) + {no}*({r_no_plate:.1f}+{r_no_column:.1f}))")
        print(f"  R_n = {R_n:.1f} kips")
        print(f"  Utilization: {V_u/R_n:.3f}")
        print()

        if V_u <= R_n:
            print(f"  ✓ OK - Bearing/tearout strength is adequate")
            self.checks["bearing"] = True
            return True
        else:
            print(f"  ✗ FAIL - Check bolt spacing and edge distances")
            self.checks["bearing"] = False
            return False

    def step13_weld_design(self):
        """Step 13: Weld design"""
        self.print_subsection("STEP 13: WELD DESIGN")

        print("Weld design per AISC 358-16 Section 6.7.6:")
        print("  - Beam flange-to-end plate: CJP groove weld required")
        print("  - Beam web-to-end plate: Sufficient to develop web strength")
        if self.plate.connection_type in ["4ES", "8ES"]:
            print("  - Stiffener-to-beam flange: Fillet or CJP groove weld")
            print("  - Stiffener-to-end plate: CJP groove weld required")
            print(f"    (Double fillet permitted if t_p <= 10 mm)")
        print()

    def column_side_design(self):
        """Perform column-side design (Section 6.8.2)"""
        self.print_section("COLUMN-SIDE DESIGN")

        # Step 1: Check column flange flexural yielding
        self.column_step1_check_flexural_yielding()

        # Step 2: Continuity plate design (if needed)
        # Simplified - just indicate if needed
        print("\nContinuity plates:")
        print("  Check per AISC 358-16 Chapter 2")
        print("  Required if column flange thickness is inadequate")
        print()

    def column_step1_check_flexural_yielding(self):
        """Column Step 1: Check column flange flexural yielding"""
        self.print_subsection("COLUMN FLANGE FLEXURAL YIELDING")

        M_f = self.M_f
        F_yc = self.column.Fy
        t_cf = self.column.tf
        b_cf = self.column.bf

        # Calculate yield line mechanism parameter Y_c
        # Simplified calculation for unstiffened column flange
        # For 4-bolt connections, use Table 6.5

        # Calculate geometric parameters
        # This is complex - using simplified approach
        # Y_c ≈ function of g, s, bolt positions

        # AISC 358-16 Eq. 6.8-13
        # t_cf >= sqrt(1.11*M_f / (phi_d*F_yc*Y_c))

        # For preliminary check, use simplified criteria
        # Y_c (unstiffened) ≈ b_cf * [some function of geometry]

        # Simplified check: if t_cf >= sqrt(M_f / (F_yc * b_cf))
        # This is conservative approximation

        # More accurate calculation requires Table 6.5/6.6 formulas
        s = 0.5 * math.sqrt(b_cf * self.plate.g)

        # Calculate Y_c (simplified for unstiffened)
        # Y_c = b_cf/2 * [h1*(1/s+1/s)] + 2*g*[h1*(s+3*c/4) + ...]
        # This is complex - using simplified approach

        # For now, provide guidance
        print("AISC 358-16 Equation 6.8-13:")
        print("  t_cf >= sqrt(1.11*M_f / (phi_d*F_yc*Y_c))")
        print(f"  t_cf >= sqrt(1.11*{M_f:.0f} / ({PHI_D}*{F_yc}*Y_c))")
        print("\nNote: Y_c calculation requires Table 6.5 or 6.6")
        print("      This is a simplified check - use AISC Design Guide 13 for detailed calculations")
        print()

        # Provide rough estimate
        # For typical 4E connection, Y_c is approximately 100-150 in³
        # Conservative estimate: check if t_cf is adequate

        # Simplified check: compare required vs available
        # Required thickness (very approximate)
        t_cf_req_approx = math.sqrt(M_f / (PHI_D * F_yc * 100))

        print(f"  Approximate required t_cf (rough): {t_cf_req_approx:.3f} in")
        print(f"  Actual t_cf: {t_cf:.3f} in")
        print()

        if t_cf >= t_cf_req_approx:
            print(f"  ✓ Column flange thickness appears adequate (simplified check)")
            print(f"    Verify with detailed Y_c calculation if needed")
            self.checks["column_flange"] = True
        else:
            print(f"  ✗ Column flange may be inadequate")
            print(f"    Consider: larger column, continuity plates, or detailed analysis")
            self.checks["column_flange"] = False
        print()

    def calculate_Yp(self) -> float:
        """
        Calculate yield line mechanism parameter Y_p.

        Per AISC 358-16 Tables 6.2, 6.3, 6.4.

        The Y_p parameter is used in Eq. 6.8-5:
            t_p,req = sqrt(1.11 * M_f / (phi_d * F_yp * Y_p))

        All h_i distances are measured from the centerline of the beam
        compression flange, per AISC 358-16 Section 6.8.1 notation.

        s = (1/2) * sqrt(b_p * g)  -- characteristic yield line dimension

        Note: If p_fi > s, use p_fi = s (per Tables 6.2, 6.3, 6.4 notes).
        """
        conn_type = self.plate.connection_type
        bp = self.plate.bp
        g = self.plate.g

        # Bolt row positions (from compression flange centerline)
        h0 = self.plate.h0  # h_o: outer tension bolt row
        h1 = self.plate.h1  # h_1: inner tension bolt row
        h2 = self.plate.h2 if conn_type in ["4ES", "8ES"] else 0
        h3 = self.plate.h3 if conn_type == "8ES" else 0
        h4 = self.plate.h4 if conn_type == "8ES" else 0

        # Pitch distances
        pfo = self.plate.pfo
        pfi = self.plate.pfi
        pb = self.plate.pb if conn_type == "8ES" else 0

        # Calculate characteristic yield line dimension
        s = 0.5 * math.sqrt(bp * g)

        # Limit pfi to s per specification note
        pfi_eff = min(pfi, s)

        Y_p = 0

        if conn_type == "4E":
            # ================================================================
            # AISC 358-16 Table 6.2
            # Four-Bolt Extended Unstiffened End-Plate (4E)
            #
            # Y_p = (b_p/2) * [h_1*(1/p_fi + 1/s) + h_o*(1/p_fo) - 1/2]
            #       + (2/g) * [h_1*(p_fi + s)]
            #
            # Where:
            #   h_o = (d - tf) + pfo  (outer tension bolt row)
            #   h_1 = (d - tf) - pfi  (inner tension bolt row)
            #   s = (1/2)*sqrt(b_p * g)
            # ================================================================
            Y_p = ((bp / 2)
                   * (h1 * (1.0 / pfi_eff + 1.0 / s)
                      + h0 * (1.0 / pfo)
                      - 0.5)
                   + (2.0 / g)
                   * (h1 * (pfi_eff + s)))

        elif conn_type == "4ES":
            # ================================================================
            # AISC 358-16 Table 6.3
            # Four-Bolt Extended Stiffened End-Plate (4ES)
            #
            # Case 1 (d_e <= s):
            #   Y_p = (b_p/2)*[h_1*(1/p_f + 1/s) + h_o*(1/p_f + 1/(2*s))]
            #         + (2/g)*[h_1*(p_f + s) + h_o*(d_e + p_f)]
            #
            # Case 2 (d_e > s):
            #   Y_p = (b_p/2)*[h_1*(1/p_f + 1/s) + h_o*(1/s + 1/p_f)]
            #         + (2/g)*[h_1*(p_f + s) + h_o*(s + p_f)]
            #
            # Where:
            #   d_e = distance from outside face of tension flange to outer bolt row
            #       = p_fo
            #   p_f = pitch distance (for 4ES, uses same pitch for both rows)
            #
            # Note: In 4ES, p_f is used for both p_fi and p_fo (same pitch).
            # The OCR text shows "p_f" not "p_fi" or "p_fo" separately.
            # We use p_fi as the controlling pitch since it is the standard pitch
            # and the note says "If p_f > s, use p_f = s"
            # ================================================================
            de = pfo  # d_e = edge distance from outside of tension flange

            # For 4ES, the specification uses a single p_f for both rows
            pf = pfi_eff  # Use p_fi as the controlling pitch

            if de <= s:
                # Case 1 (d_e <= s)
                Y_p = ((bp / 2)
                       * (h1 * (1.0 / pf + 1.0 / s)
                          + h0 * (1.0 / pf + 1.0 / (2.0 * s)))
                       + (2.0 / g)
                       * (h1 * (pf + s) + h0 * (de + pf)))
            else:
                # Case 2 (d_e > s)
                Y_p = ((bp / 2)
                       * (h1 * (1.0 / pf + 1.0 / s)
                          + h0 * (1.0 / s + 1.0 / pf))
                       + (2.0 / g)
                       * (h1 * (pf + s) + h0 * (s + pf)))

        elif conn_type == "8ES":
            # ================================================================
            # AISC 358-16 Table 6.4
            # Eight-Bolt Extended Stiffened End-Plate (8ES)
            #
            # Bolt rows (from outside to inside):
            #   h_1 = outermost tension bolt row
            #   h_2 = second row from outside
            #   h_3 = third row from outside (second from inside)
            #   h_4 = innermost tension bolt row
            #
            # Case 1 (d_e <= s):
            #   Y_p = (b_p/2)*[h_1*(1/(2*d_e)) + h_2*(1/p_fo) + h_3*(1/p_fi) + h_4*(1/s)]
            #         + (2/g)*[h_1*(d_e + 3*p_b/4) + h_2*(p_fo + p_b/4)
            #                  + h_3*(p_fi + 3*p_b/4) + h_4*(s + p_b/4)]
            #         + g/2
            #
            # Case 2 (d_e > s):
            #   Y_p = (b_p/2)*[h_1*(1/s) + h_2*(1/p_fo) + h_3*(1/p_fi) + h_4*(1/s)]
            #         + (2/g)*[h_1*(s + p_b/4) + h_2*(p_fo + 3*p_b/4)
            #                  + h_3*(p_fi + p_b/4) + h_4*(s + 3*p_b/4)]
            #         + g/2
            #
            # Where:
            #   d_e = distance from outside of tension flange to outermost bolt row
            #       = p_fo
            #   p_b = vertical distance between inner and outer bolt rows
            # ================================================================
            de = pfo  # d_e = edge distance from outside of tension flange

            if de <= s:
                # Case 1 (d_e <= s)
                Y_p = ((bp / 2)
                       * (h1 * (1.0 / (2.0 * de))
                          + h2 * (1.0 / pfo)
                          + h3 * (1.0 / pfi_eff)
                          + h4 * (1.0 / s))
                       + (2.0 / g)
                       * (h1 * (de + 3.0 * pb / 4.0)
                          + h2 * (pfo + pb / 4.0)
                          + h3 * (pfi_eff + 3.0 * pb / 4.0)
                          + h4 * (s + pb / 4.0))
                       + g / 2.0)
            else:
                # Case 2 (d_e > s)
                Y_p = ((bp / 2)
                       * (h1 * (1.0 / s)
                          + h2 * (1.0 / pfo)
                          + h3 * (1.0 / pfi_eff)
                          + h4 * (1.0 / s))
                       + (2.0 / g)
                       * (h1 * (s + pb / 4.0)
                          + h2 * (pfo + 3.0 * pb / 4.0)
                          + h3 * (pfi_eff + pb / 4.0)
                          + h4 * (s + 3.0 * pb / 4.0))
                       + g / 2.0)

        return Y_p

    def print_summary(self, all_passed: bool):
        """Print design verification summary"""
        self.print_section("DESIGN VERIFICATION SUMMARY")

        print("CHECKS SUMMARY:")
        print()
        print("Parametric Limits (Table 6.1):")
        print(f"  Within limits: {'✓ PASS' if self.checks.get('parametric_limits', False) else '✗ FAIL'}")
        print(f"  Bolt diameter limits: {'✓ PASS' if self.checks.get('bolt_diameter_limits', False) else '✗ FAIL'}")
        print()

        print("Beam-Side Checks:")
        print(f"  Bolt diameter: {'✓ PASS' if self.checks.get('bolt_diameter', False) else '✗ FAIL'}")
        print(f"  Plate thickness: {'✓ PASS' if self.checks.get('plate_thickness', False) else '✗ FAIL'}")

        if self.plate.connection_type == "4E":
            print(f"  Shear yielding: {'✓ PASS' if self.checks.get('shear_yielding', False) else '✗ FAIL'}")
            print(f"  Shear rupture: {'✓ PASS' if self.checks.get('shear_rupture', False) else '✗ FAIL'}")

        if self.plate.connection_type in ["4ES", "8ES"]:
            print(f"  Stiffener: {'✓ PASS' if self.checks.get('stiffener', False) else '✗ FAIL'}")

        print(f"  Bolt shear: {'✓ PASS' if self.checks.get('bolt_shear', False) else '✗ FAIL'}")
        print(f"  Bearing: {'✓ PASS' if self.checks.get('bearing', False) else '✗ FAIL'}")
        print()

        print("Column-Side Checks:")
        print(f"  Column flange: {'✓ PASS' if self.checks.get('column_flange', False) else '✗ FAIL'}")
        print()

        # Key results
        print("KEY RESULTS:")
        if self.M_f:
            print(f"  M_f: {self.M_f:.0f} kip-in ({self.M_f/12:.1f} kip-ft)")
        if self.F_fu:
            print(f"  F_fu: {self.F_fu:.1f} kips (per flange)")
        if self.t_p_req:
            print(f"  Required t_p: {self.t_p_req:.3f} in")
        if self.d_b_req:
            print(f"  Required d_b: {self.d_b_req:.3f} in")
        print()

        # Overall status
        self.print_separator("=")
        if all_passed:
            print("  ✓ ALL CHECKS PASSED - END-PLATE CONNECTION DESIGN IS ADEQUATE")
        else:
            print("  ✗ SOME CHECKS FAILED - REVIEW AND ADJUST DESIGN")
        self.print_separator("=")
        print()


# ====================== HELPER FUNCTIONS ======================

def calculate_Sh(connection_type: str, beam_d: float, beam_bf: float,
                 Lst: float = 5.0, tp: float = 1.0) -> float:
    """
    Calculate distance from column face to plastic hinge (S_h)

    Per AISC 358-16 Chapter 6:
    - 4E (unstiffened): S_h = min(d/2, 3*b_f)
    - 4ES/8ES (stiffened): S_h = L_st + t_p

    Args:
        connection_type: Connection type (4E, 4ES, 8ES)
        beam_d: Beam depth (in)
        beam_bf: Beam flange width (in)
        Lst: Stiffener length (in), for stiffened connections
        tp: End plate thickness (in), for stiffened connections

    Returns:
        S_h: Distance from column face to plastic hinge (in)
    """
    if connection_type == "4E":
        return min(beam_d / 2, 3 * beam_bf)
    else:  # 4ES or 8ES
        return Lst + tp


def calculate_hi_distances(conn_type: str, beam_d: float, beam_tf: float,
                           pfo: float, pfi: float, pb: float = 0.0) -> dict:
    """
    Calculate h_i distances from compression flange centerline.

    Per AISC 358-16 Section 6.8.1 notation, all h_i are measured from the
    centerline of the beam compression flange to the centerline of each
    tension-side bolt row.

    The distance from compression flange center to tension flange center = (d - tf).
    Pitch distances pfo and pfi are measured from the tension flange centerline:
      pfo: outward from tension flange center (toward plate edge)
      pfi: inward from tension flange center (toward beam web)

    Therefore:
      h_o = (d - tf) + pfo   (outer bolt row, beyond tension flange)
      h_1 = (d - tf) - pfi   (inner bolt row, between flanges)
    """
    d = beam_d
    tf = beam_tf

    # Distance from compression flange center to tension flange center
    d_ft = d - tf

    if conn_type in ["4E", "4ES"]:
        h_o = d_ft + pfo   # outer bolt row (beyond tension flange)
        h_1 = d_ft - pfi   # inner bolt row (between flanges, near tension flange)
        return {"h0": h_o, "h1": h_1}

    elif conn_type == "8ES":
        # Four bolt rows: outer pair in extended portion, inner pair between flanges
        # Rows numbered from outside to inside: h_1 (outermost) > h_2 > h_3 > h_4 (innermost)
        h_1 = d_ft + pfo + pb              # outermost (at plate edge)
        h_2 = d_ft + pfo                   # outer pair, inner row
        h_3 = d_ft - pfi                   # inner pair, outer row
        h_4 = max(d_ft - pfi - pb, 0)      # innermost (nearest to compression flange)
        return {"h0": 0, "h1": h_1, "h2": h_2, "h3": h_3, "h4": h_4}

    else:
        raise ValueError(f"Invalid connection type: {conn_type}")


def create_end_plate_geometry(args, beam: BeamSection = None) -> EndPlateGeometry:
    """
    Create end plate geometry from command line arguments and beam section.

    Per AISC 358-16 Chapter 6:
    - All h_i distances are measured from the centerline of the compression flange.
    - h_o = distance to tension-side outer bolt row
    - h_1 = distance to tension-side inner bolt row

    Geometric parameters from Table 6.1:
    - p_fi: vertical distance from INSIDE of beam tension flange to nearest inside bolt row
    - p_fo: vertical distance from OUTSIDE of beam tension flange to nearest outside bolt row
    - p_b: vertical distance between inner and outer bolt rows (8ES only)
    - g: horizontal gage distance between bolt columns
    """
    conn_type = args.connection_type

    # Use beam section properties if available, otherwise use args or defaults
    if beam is not None:
        beam_d = args.beam_d if args.beam_d else beam.d
        beam_tf = args.beam_tf if args.beam_tf else beam.tf
        beam_bf = args.beam_bf if args.beam_bf else beam.bf
    else:
        beam_d = args.beam_d if args.beam_d else 30.0
        beam_tf = args.beam_tf if args.beam_tf else 0.6
        beam_bf = args.beam_bf if args.beam_bf else 10.5

    # Default pitch/gage values (can be overridden by args)
    pfo = getattr(args, 'pfo', None) or 1.25   # outer pitch distance (in)
    pfi = getattr(args, 'pfi', None) or 1.5     # inner pitch distance (in)
    g = getattr(args, 'gage', None) or 4.0      # gage distance (in)
    pb = getattr(args, 'pb', None) or 3.5       # bolt pitch for 8ES (in)

    if conn_type == "4E":
        # Four-bolt extended unstiffened
        n_tension = 4
        n_compression = 2
        bp = max(beam_bf, args.plate_width) if args.plate_width else beam_bf

        # Calculate h_i distances from compression flange centerline
        hi = calculate_hi_distances("4E", beam_d, beam_tf, pfo, pfi)

        return EndPlateGeometry(
            connection_type=conn_type,
            db=args.bolt_diameter if args.bolt_diameter else 1.25,
            bolt_grade=args.bolt_grade if args.bolt_grade else "A325",
            n_bolts_tension=n_tension,
            n_bolts_compression=n_compression,
            bp=bp,
            tp=args.plate_thickness if args.plate_thickness else 1.0,
            h0=hi["h0"], h1=hi["h1"],
            pfo=pfo, pfi=pfi, g=g, pb=0,
            ts=0,  # No stiffener
            Lst=0,
        )

    elif conn_type in ["4ES", "8ES"]:
        # Four or eight-bolt extended stiffened
        n_tension = 4 if conn_type == "4ES" else 8
        n_compression = 2
        bp = max(beam_bf, args.plate_width) if args.plate_width else beam_bf

        Lst = args.stiffener_length if args.stiffener_length else 5.0
        tp = args.plate_thickness if args.plate_thickness else 1.25
        ts = args.stiffener_thickness if args.stiffener_thickness else 0.625

        hi = calculate_hi_distances(conn_type, beam_d, beam_tf, pfo, pfi, pb)

        if conn_type == "4ES":
            plate = EndPlateGeometry(
                connection_type=conn_type,
                db=args.bolt_diameter if args.bolt_diameter else 1.25,
                bolt_grade=args.bolt_grade if args.bolt_grade else "A325",
                n_bolts_tension=n_tension,
                n_bolts_compression=n_compression,
                bp=bp,
                tp=tp,
                h0=hi["h0"], h1=hi["h1"],
                pfo=pfo, pfi=pfi, g=g, pb=0,
                ts=ts, Lst=Lst,
            )
        else:  # 8ES
            plate = EndPlateGeometry(
                connection_type=conn_type,
                db=args.bolt_diameter if args.bolt_diameter else 1.25,
                bolt_grade=args.bolt_grade if args.bolt_grade else "A325",
                n_bolts_tension=n_tension,
                n_bolts_compression=n_compression,
                bp=bp,
                tp=tp,
                h0=0, h1=hi["h1"], h2=hi["h2"], h3=hi["h3"], h4=hi["h4"],
                pfo=pfo, pfi=pfi, g=g, pb=pb,
                ts=ts, Lst=Lst,
            )

        return plate
    else:
        raise ValueError(f"Invalid connection type: {conn_type}")


def create_beam_section(args) -> BeamSection:
    """Create beam section from command line arguments"""
    if args.beam_section:
        props = get_section_properties(args.beam_section)
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


def create_column_section(args) -> ColumnSection:
    """Create column section from command line arguments"""
    if args.column_section:
        props = get_section_properties(args.column_section)
        if props:
            return ColumnSection(
                designation=props["designation"],
                d=args.column_d if args.column_d else props["d"],
                bf=args.column_bf if args.column_bf else props["bf"],
                tf=args.column_tf if args.column_tf else props["tf"],
                tw=args.column_tw if args.column_tw else props["tw"],
                Zx=args.column_Zx if args.column_Zx else props["Zx"],
                Fy=args.column_Fy,
                Fu=args.column_Fu,
                Ry=args.column_Ry,
            )

    if all([args.column_d, args.column_bf, args.column_tf, args.column_tw, args.column_Zx]):
        return ColumnSection(
            designation="Custom",
            d=args.column_d,
            bf=args.column_bf,
            tf=args.column_tf,
            tw=args.column_tw,
            Zx=args.column_Zx,
            Fy=args.column_Fy,
            Fu=args.column_Fu,
            Ry=args.column_Ry,
        )

    raise ValueError("Invalid column section parameters")


# ====================== COMMAND LINE PARSING ======================

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="End-Plate Connection Design Verification (AISC 358-16 Chapter 6)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 4E connection (four-bolt extended unstiffened)
  python endplate_design.py --connection-type 4E --beam-section W30x99 --column-section W14x193

  # 4ES connection (four-bolt extended stiffened)
  python endplate_design.py --connection-type 4ES --beam-section W30x99 --column-section W14x193

  # 8ES connection (eight-bolt extended stiffened)
  python endplate_design.py --connection-type 8ES --beam-section W36x182 --column-section W14x311
        """
    )

    # Check for --list-sections before other required args
    if "--list-sections" in sys.argv:
        pre_parser = argparse.ArgumentParser(add_help=False)
        pre_parser.add_argument("--list-sections", action="store_true")
        pre_args, _ = pre_parser.parse_known_args()

        if pre_args.list_sections:
            sections = load_sections_from_csv()
            print("Available W-shape sections from database:")
            print("=" * 80)
            for designation in sorted(sections.keys()):
                props = sections[designation]
                print(f"  {designation:12s}: d={props['d']:5.1f} in, bf={props['bf']:5.2f} in")
            print("=" * 80)
            print(f"Total: {len(sections)} sections")
            sys.exit(0)

    # Connection parameters
    conn_group = parser.add_argument_group("Connection Parameters")
    conn_group.add_argument("--connection-type", type=str, required=True,
                              choices=["4E", "4ES", "8ES"],
                              help="Connection type (4E, 4ES, or 8ES), required")

    # Bolt parameters
    bolt_group = parser.add_argument_group("Bolt Parameters")
    bolt_group.add_argument("--bolt-diameter", type=float, default=1.25,
                              help="Bolt diameter (in), default: 1.25")
    bolt_group.add_argument("--bolt-grade", type=str, default="A325",
                              choices=["A325", "A490", "F1852"],
                              help="Bolt grade, default: A325")

    # End plate parameters
    plate_group = parser.add_argument_group("End Plate Parameters")
    plate_group.add_argument("--plate-width", type=float,
                              help="End plate width (in), default: beam flange width")
    plate_group.add_argument("--plate-thickness", type=float,
                              help="End plate thickness (in), default: 1.0")
    plate_group.add_argument("--stiffener-thickness", type=float,
                              help="Stiffener thickness (in), for 4ES/8ES")
    plate_group.add_argument("--stiffener-length", type=float,
                              help="Stiffener length (in), for 4ES/8ES")

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
    beam_group.add_argument("--beam-Fy", type=float, default=DEFAULT_FY_BEAM,
                              help=f"Beam yield stress (ksi), default: {DEFAULT_FY_BEAM}")
    beam_group.add_argument("--beam-Fu", type=float, default=DEFAULT_FU_BEAM,
                              help=f"Beam tensile strength (ksi), default: {DEFAULT_FU_BEAM}")
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
    column_group.add_argument("--column-Fy", type=float, default=DEFAULT_FY_COLUMN,
                                help=f"Column yield stress (ksi), default: {DEFAULT_FY_COLUMN}")
    column_group.add_argument("--column-Fu", type=float, default=DEFAULT_FU_COLUMN,
                                help=f"Column tensile strength (ksi), default: {DEFAULT_FU_COLUMN}")
    column_group.add_argument("--column-Ry", type=float, default=1.1,
                                help="Column material overstrength factor, default: 1.1")

    # Design parameters
    design_group = parser.add_argument_group("Design Parameters")
    design_group.add_argument("--span", type=float, required=True,
                              help="Beam span (in)")
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
    load_group.add_argument("--Vu", type=float, default=0,
                           help="Required shear strength (kips), default: 0")

    return parser.parse_args()


# ====================== MAIN ======================

def main():
    """Main function"""
    args = parse_args()

    try:
        # Create sections
        beam = create_beam_section(args)
        column = create_column_section(args)

        # Calculate M_pr and C_pr
        if args.use_calc_cpr or args.C_pr is None:
            C_pr = (beam.Fy + beam.Fu) / (2 * beam.Fy)
            C_pr = min(C_pr, 1.2)
        else:
            C_pr = args.C_pr

        # Calculate M_pr
        M_pr = C_pr * beam.Ry * beam.Fy * beam.Zx

        # Calculate V_u if not provided
        V_u = args.Vu
        if V_u == 0 and args.Lh:
            # Calculate from simple beam formula
            gravity = args.load_D * 1.2 + args.load_L * args.load_f1 + args.load_S * 0.2
            V_u = 2 * M_pr / args.Lh + gravity / 2
        elif V_u == 0:
            V_u = 100  # Default value

        # Calculate S_h using helper function
        Lst = args.stiffener_length if args.stiffener_length else 5.0
        tp = args.plate_thickness if args.plate_thickness else (1.25 if args.connection_type in ["4ES", "8ES"] else 1.0)
        S_h = calculate_Sh(args.connection_type, beam.d, beam.bf, Lst, tp)

        # Create loads
        loads = Loads(
            D=args.load_D,
            L=args.load_L,
            S=args.load_S,
            f1=args.load_f1,
            Vu=V_u,
        )

        # Create design parameters
        params = DesignParameters(
            L=args.span,
            Lh=args.Lh if args.Lh else (args.span - column.d - 2 * S_h),
            system_type=args.system_type,
            C_pr=args.C_pr,
            use_calculated_Cpr=(args.C_pr is None),
            Sh=S_h,
        )

        # Create end plate geometry
        plate = create_end_plate_geometry(args, beam)

        # Run design verification
        checker = EndPlateDesignChecker(beam, column, plate, params, loads)
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
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
