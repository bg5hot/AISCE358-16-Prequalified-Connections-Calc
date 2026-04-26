# End-Plate Connection Design Verification

外伸端板节点抗震验算程序

Based on **AISC 358-16 Chapter 6** - Prequalified Connections for Seismic Applications

## Overview

本程序按照 AISC 358-16 第 6 章要求，对外伸端板节点（Extended End-Plate Moment Connection）进行抗震验算。支持三种连接类型：

- **4E**: Four-bolt extended unstiffened end-plate (四螺栓外伸非加劲端板)
- **4ES**: Four-bolt extended stiffened end-plate (四螺栓外伸加劲端板)
- **8ES**: Eight-bolt extended stiffened end-plate (八螺栓外伸加劲端板)

## Installation

No installation required. Requires Python 3.7+.

依赖 CSV 截面数据库文件：`aisc_w_shapes.csv`

## Usage

### Basic Usage

```bash
# 4E Connection (Four-bolt extended unstiffened)
python endplate_design.py --connection-type 4E --beam-section W30x99 --column-section W14x193 --span 360 --system-type SMF

# 4ES Connection (Four-bolt extended stiffened)
python endplate_design.py --connection-type 4ES --beam-section W30x99 --column-section W14x193 --span 360 --system-type SMF --stiffener-thickness 0.625 --stiffener-length 5.0

# 8ES Connection (Eight-bolt extended stiffened)
python endplate_design.py --connection-type 8ES --beam-section W36x182 --column-section W14x311 --span 360 --system-type SMF --plate-thickness 1.5 --bolt-diameter 1.5
```

### List Available Sections

```bash
python endplate_design.py --list-sections
```

### Full Example with Custom Parameters

```bash
python endplate_design.py \
  --connection-type 4E \
  --beam-section W30x99 \
  --beam-Fy 50 \
  --beam-Fu 65 \
  --column-section W14x193 \
  --bolt-diameter 1.25 \
  --bolt-grade A325 \
  --plate-width 12.0 \
  --plate-thickness 1.125 \
  --span 360 \
  --system-type SMF \
  --use-calc-cpr \
  --load-D 10 \
  --load-L 20 \
  --Vu 50
```

## Connection Types

### 4E: Four-Bolt Extended Unstiffened

```
        ┌─────────────────────┐
        │                     │
    ────┤                     ├────
        │                     │
        │   ○           ○     │ ← 4 tension bolts
        │                     │
        │                     │
        │                     │
    ────┤                     ├────
        │                     │
        └─────────────────────┘
```

Typical applications:
- SMF/IMF intermediate moment frames
- Moderate beam sizes

### 4ES: Four-Bolt Extended Stiffened

```
        ┌─────────────────────┐
        │                     │
    ────┤  ┃               ┃  ├────
        │  ┃ (stiffener)  ┃  │
        │   ○           ○     │ ← 4 tension bolts
        │  ┃               ┃  │
        │  ┃               ┃  │
    ────┤  ┃               ┃  ├────
        │                     │
        └─────────────────────┘
```

Typical applications:
- SMF special moment frames
- Larger moment demands

### 8ES: Eight-Bolt Extended Stiffened

```
        ┌─────────────────────┐
        │                     │
    ────┤  ┃               ┃  ├────
        │  ┃               ┃  │
        │   ○  ○       ○  ○   │ ← 8 tension bolts
        │  ┃               ┃  │
        │  ┃               ┃  │
        │   ○  ○       ○  ○   │
    ────┤  ┃               ┃  ├────
        │                     │
        └─────────────────────┘
```

Typical applications:
- SMF special moment frames
- Large beams with high moment demands

## Geometry Convention

### h_i Distances (Critical)

All h_i distances are measured from the **centerline of the beam compression flange** to the centerline of each tension-side bolt row. The reference point is NOT the beam mid-depth.

```
                    Outer bolt row ○  ← h_o = (d - tf) + pfo
                                   |
Tension flange center ─────────────── ← d - tf from comp flange CL
                                   |
                    Inner bolt row ○  ← h_1 = (d - tf) - pfi
                                   |
              (beam web region)       |
                                   |
Compression flange CL ─────────────── ← Reference point (h = 0)
```

**4E / 4ES (two bolt rows):**
- `h_o = (d - tf) + pfo` — outer tension bolt row
- `h_1 = (d - tf) - pfi` — inner tension bolt row

**8ES (four bolt rows):**
- `h_1 = (d - tf) + pfo + pb` — outermost
- `h_2 = (d - tf) + pfo` — outer pair inner row
- `h_3 = (d - tf) - pfi` — inner pair outer row
- `h_4 = (d - tf) - pfi - pb` — innermost

### Pitch Distances

- `pfo` — distance from tension flange centerline to outer bolt row (outward)
- `pfi` — distance from tension flange centerline to inner bolt row (inward)
- `pb` — spacing between bolt rows within a pair (8ES only)
- `g` — horizontal gage between bolt columns
- `s = 0.5 * sqrt(bp * g)` — characteristic yield line dimension

## Design Procedure (AISC 358-16 Section 6.8)

### Beam-Side Design (Section 6.8.1)

| Step | Description | Equation |
|------|-------------|----------|
| 1 | Calculate moment at column face M_f | Eq. 6.8-1 |
| 2 | Select connection geometry | - |
| 3 | Calculate required bolt diameter | Eq. 6.8-3 (4E/4ES), 6.8-4 (8ES) |
| 4 | Select bolt diameter | - |
| 5 | Calculate required plate thickness (Y_p) | Eq. 6.8-5 |
| 6 | Select plate thickness | - |
| 7 | Calculate beam flange force | Eq. 6.8-6 |
| 8 | Check plate shear yielding (4E only) | Eq. 6.8-7 |
| 9 | Check plate shear rupture (4E only) | Eq. 6.8-8 |
| 10 | Stiffener design (4ES/8ES) | Eq. 6.8-9, 6.8-10 |
| 11 | Check bolt shear strength | Eq. 6.8-11 |
| 12 | Check bearing/tearout | - |
| 13 | Weld design | Section 6.7.6 |

### Column-Side Design (Section 6.8.2)

| Step | Description | Equation |
|------|-------------|----------|
| 1 | Check column flange flexural yielding | Eq. 6.8-13 |
| 2 | Continuity plate design (if needed) | Chapter 2 |

## Parameters

### Required Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `--connection-type` | Connection type (4E, 4ES, 8ES) | `4E` |
| `--beam-section` | Beam section designation | `W30x99` |
| `--column-section` | Column section designation | `W14x193` |
| `--span` | Beam span, center-to-center (in) | `360` |
| `--system-type` | Frame system type (SMF/IMF) | `SMF` |

### Optional Parameters

#### Bolt Parameters
- `--bolt-diameter`: Bolt diameter (in), default: 1.25
- `--bolt-grade`: Bolt grade (A325, A490, F1852), default: A325

#### End Plate Parameters
- `--plate-width`: End plate width (in), default: beam flange width
- `--plate-thickness`: End plate thickness (in), default: 1.0
- `--stiffener-thickness`: Stiffener thickness (in), for 4ES/8ES
- `--stiffener-length`: Stiffener length (in), for 4ES/8ES

#### Beam Parameters
- `--beam-Fy`: Beam yield stress (ksi), default: 50
- `--beam-Fu`: Beam tensile strength (ksi), default: 65
- `--beam-Ry`: Material overstrength factor, default: 1.1

#### Column Parameters
- `--column-Fy`: Column yield stress (ksi), default: 50
- `--column-Fu`: Column tensile strength (ksi), default: 65
- `--column-Ry`: Material overstrength factor, default: 1.1

#### Design Parameters
- `--Lh`: Distance between plastic hinges (in)
- `--C-pr`: Connection strength factor (default: calculate per Eq. 2.4-2)
- `--use-calc-cpr`: Calculate C_pr from Fy and Fu

#### Loads
- `--load-D`: Dead load (kips), default: 0
- `--load-L`: Live load (kips), default: 0
- `--load-S`: Snow load (kips), default: 0
- `--load-f1`: Live load factor, default: 0.5
- `--Vu`: Required shear strength (kips), default: calculated

## Output Example

```
================================================================================
  END-PLATE CONNECTION DESIGN VERIFICATION (AISC 358-16)
================================================================================

INPUT PARAMETERS
================================================================================
BEAM SECTION:
  Designation: W30x99
  Depth (d): 29.70 in
  Flange width (bf): 10.45 in
  ...

END PLATE CONFIGURATION:
  Connection type: 4E
  Bolt diameter: 1.25 in
  End plate width: 12.00 in
  End plate thickness: 1.125 in
  ...

--------------------------------------------------------------------------------
  STEP 1: CALCULATE M_f
--------------------------------------------------------------------------------
C_pr calculated per AISC 358-16 Eq. 2.4-2: 1.150
M_f = 12,450 kip-in (1,037.5 kip-ft)
...

--------------------------------------------------------------------------------
  STEP 3: REQUIRED BOLT DIAMETER
--------------------------------------------------------------------------------
d_b,req = 1.125 in
  ✓ OK - Bolt diameter is adequate

--------------------------------------------------------------------------------
  STEP 5: REQUIRED PLATE THICKNESS
--------------------------------------------------------------------------------
t_p,req = 0.987 in
  ✓ OK - Plate thickness is adequate
...

DESIGN VERIFICATION SUMMARY
================================================================================
CHECKS SUMMARY:
Beam-Side Checks:
  Bolt diameter: ✓ PASS
  Plate thickness: ✓ PASS
  Shear yielding: ✓ PASS
  Shear rupture: ✓ PASS
  Bolt shear: ✓ PASS
  Bearing: ✓ PASS

Column-Side Checks:
  Column flange: ✓ PASS

================================================================================
  ✓ ALL CHECKS PASSED - END-PLATE CONNECTION DESIGN IS ADEQUATE
================================================================================
```

## Design Guidelines

### Selecting Connection Type

| Factor | 4E | 4ES | 8ES |
|--------|----|-----|-----|
| Moment capacity | Moderate | High | Very High |
| Fabrication complexity | Low | Medium | High |
| Bolt access | Good | Good | Limited |
| Cost | Low | Medium | High |

### Bolt Diameter Selection

Typical bolt sizes for each connection type:
- **4E**: 1-1/4" to 1-1/2" (A325 or A490)
- **4ES**: 1-1/4" to 1-1/2" (A325 or A490)
- **8ES**: 1-1/2" to 1-3/4" (A490 recommended)

### Plate Thickness Guidelines

Required plate thickness is calculated per Eq. 6.8-5:
```
t_p,req = sqrt(1.11 * M_f / (phi_d * F_yp * Y_p))
```

Typical values:
- **4E**: 3/4" to 1-1/4"
- **4ES**: 1" to 1-1/2"
- **8ES**: 1-1/4" to 2"

## Key Equations

### Y_p (Yield Line Mechanism Parameter)

#### 4E (Table 6.2)
```
Y_p = (bp/2) * [h1*(1/pfi + 1/s) + ho*(1/pfo) - 1/2]
    + (2/g) * [h1*(pfi + s)]

NOTE: -1/2 is a standalone edge correction term inside the bracket,
      NOT multiplied by h_o.
```

#### 4ES (Table 6.3)
Two cases depending on d_e vs s:
```
d_e = pfo (edge distance to outer bolt row)

Case 1 (d_e <= s):
  Y_p = (bp/2)*[h1*(1/pf + 1/s) + ho*(1/pf + 1/(2s))]
        + (2/g)*[h1*(pf + s) + ho*(de + pf)]

Case 2 (d_e > s):
  Y_p = (bp/2)*[h1*(1/pf + 1/s) + ho*(1/s + 1/pf)]
        + (2/g)*[h1*(pf + s) + ho*(s + pf)]
```

#### 8ES (Table 6.4)
Two cases depending on d_e vs s:
```
Case 1 (d_e <= s):
  Y_p = (bp/2)*[h1/(2*de) + h2/pfo + h3/pfi + h4/s]
        + (2/g)*[h1*(de + 3pb/4) + h2*(pfo + pb/4)
                 + h3*(pfi + 3pb/4) + h4*(s + pb/4)]
        + g/2

Case 2 (d_e > s):
  Y_p = (bp/2)*[h1/s + h2/pfo + h3/pfi + h4/s]
        + (2/g)*[h1*(s + pb/4) + h2*(pfo + 3pb/4)
                 + h3*(pfi + pb/4) + h4*(s + 3pb/4)]
        + g/2
```

### Required Bolt Diameter (Step 3)
```
4E/4ES: db,req = sqrt(2*Mf / (pi * phi_n * Fnt * (ho + h1)))    -- Eq. 6.8-3
8ES:    db,req = sqrt(2*Mf / (pi * phi_n * Fnt * (h1+h2+h3+h4))) -- Eq. 6.8-4
```

## AISC 358-16 References

- **Section 6.1**: General Requirements
- **Section 6.7**: Design Provisions
- **Section 6.8**: Design Procedure
- **Table 6.2-6.4**: Yield Line Mechanism Parameters (Y_p)

## Notes

1. **C_pr Calculation**: The program automatically calculates C_pr per Equation 2.4-2:
   ```
   C_pr = (F_y + F_u) / (2*F_y) ≤ 1.2
   ```
   Use `--C-pr` to override with a fixed value.

2. **Resistance Factors**:
   - φ_d = 1.0 for ductile limit states (plate yielding)
   - φ_n = 0.9 for nonductile limit states (bolt rupture, bearing)

3. **Plastic Hinge Location**:
   - 4E: S_h = lesser of d/2 or 3*b_f
   - 4ES/8ES: S_h = L_st + t_p

4. **Weld Requirements**:
   - Beam flange-to-end plate: CJP groove weld required
   - Beam web-to-end plate: Fillet weld sufficient for web strength
   - Stiffener-to-end plate: CJP groove weld (4ES/8ES)

## Files

- `endplate_design.py`: Main verification script
- `aisc_w_shapes.csv`: Section database (289 W-shapes)
- `endplate_README.md`: This documentation file
- `endplate_REVIEW_V2_RESPONSE.md`: Review V2 response and corrections log

## See Also

- `rbs_design.py`: RBS connection verification (AISC 358-16 Chapter 5)
- `bfp_design.py`: BFP connection verification (AISC 358-16 Chapter 7)
- `extract_shapes.py`: Utility to extract sections from AISC Excel database
