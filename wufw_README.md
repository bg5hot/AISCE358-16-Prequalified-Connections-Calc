# WUF-W Connection Design Verification

焊接无加劲翼缘-焊接腹板节点抗震验算程序

Based on **AISC 358-16 Chapter 8** - Prequalified Connections for Seismic Applications

## Overview

本程序按照 AISC 358-16 第 8 章要求，对焊接无加劲翼缘-焊接腹板节点（Welded Unreinforced Flange-Welded Web, WUF-W）进行抗震验算。

WUF-W 连接将梁翼缘和梁腹板通过全熔透坡口焊缝（CJP groove weld）直接焊接到柱翼缘上，并在腹板区域设置单板抗剪连接件（single-plate shear tab）作为补充。

### 连接示意

```
         Column Flange
              |
              | CJP groove weld (demand critical)
    ──────────┤──────────  Beam Top Flange
              |
              | ╱╲ Weld Access Hole (AWS D1.8 §6.11.1.2)
              |╱  ╲
              |    │
              |    │ CJP groove weld (demand critical)
              |    │ between weld access holes
              |    │
              |    │
              |╲  ╱ Single-plate shear tab
              | ╲╱  (fillet welded to web)
    ──────────┤──────────  Beam Bottom Flange
              | CJP groove weld (demand critical)
              |  - Remove backing, backgouge
              |  - 5/16" min reinforcing fillet
```

### 关键特点

- **C_pr = 1.4**（NOT 默认公式 Eq. 2.4-2，WUF-W 专用值）
- **S_h = 0**（塑性铰位于柱面处）
- **M_f = M_pr**（无剪切力放大）
- **Z_e = Z_x**（无截面削弱）
- **规定性连接构造**（非设计选择）

## Installation

No installation required. Requires Python 3.7+.

依赖 CSV 截面数据库文件：`aisc_w_shapes.csv`

## Usage

### Basic Usage

```bash
# SMF system
python wufw_design.py --beam-section W24x68 --column-section W14x311 --span 360 --system-type SMF

# IMF system
python wufw_design.py --beam-section W24x68 --column-section W14x120 --span 300 --system-type IMF
```

### List Available Sections

```bash
python wufw_design.py --list-sections
```

### Full Example with Custom Parameters

```bash
python wufw_design.py \
  --beam-section W24x68 \
  --beam-Fy 50 \
  --beam-Fu 65 \
  --column-section W14x311 \
  --span 360 \
  --system-type SMF \
  --load-D 10 \
  --load-L 20 \
  --Vu 50
```

## Design Procedure (AISC 358-16 Section 8.7)

### Prequalification Limits (Section 8.3)

| Parameter | Limit | SMF | IMF |
|-----------|-------|-----|-----|
| Beam depth | ≤ 36 in (W36) | ✓ | ✓ |
| Beam weight | ≤ 150 plf | ✓ | ✓ |
| Beam flange thickness | ≤ 1.0 in | ✓ | ✓ |
| Span/depth ratio | ≥ 7 (SMF), ≥ 5 (IMF) | ✓ | ✓ |
| Column depth | ≤ 36 in | ✓ | ✓ |

### Design Steps

| Step | Description | Key Equation |
|------|-------------|--------------|
| 1 | Probable maximum moment M_pr | M_pr = 1.4 × R_y × F_y × Z_x |
| 2 | Plastic hinge location S_h | S_h = 0 (at column face) |
| 3 | Shear force at plastic hinge V_h | V_h = 2M_pr/L_h + gravity/2 |
| 4 | Column-beam relationship | M_pc/M_pb* ≥ 1.0 (AISC 341 E3.6c) |
| 5 | Beam shear strength | V_u ≤ φ_v × V_n |
| 6 | Continuity plate requirements | Per AISC 360 Chapter J10 |
| 7 | Column panel zone check | Per AISC 341 D1.2c and AISC 360 J10.6 |
| 8 | Connection detailing | Per Sections 8.5-8.6 (prescriptive) |

### Key Differences from Other Connections

| Parameter | RBS (Ch.5) | End-Plate (Ch.6) | BFP (Ch.7) | **WUF-W (Ch.8)** |
|-----------|------------|-------------------|------------|-------------------|
| C_pr | Eq. 2.4-2 | Eq. 2.4-2 | Eq. 2.4-2 | **1.4 (fixed)** |
| S_h | a + b/2 | varies | varies | **0 (at face)** |
| Z_e | Z_RBS < Z_x | Z_x | Z_x | **Z_x (no cut)** |
| M_f | > M_pr | > M_pr | > M_pr | **= M_pr** |
| Flange connection | welded | bolted (end plate) | bolted (flange plate) | **CJP weld** |
| Web connection | welded/bolted | welded | bolted | **CJP weld + shear tab** |

## Parameters

### Required Parameters

| Parameter | Description | Example |
|-----------|-------------|---------|
| `--beam-section` | Beam section designation | `W24x68` |
| `--column-section` | Column section designation | `W14x311` |
| `--span` | Beam span, center-to-center (in) | `360` |
| `--system-type` | Frame system type (SMF/IMF) | `SMF` |

### Optional Parameters

#### Beam Parameters
- `--beam-Fy`: Beam yield stress (ksi), default: 50
- `--beam-Fu`: Beam tensile strength (ksi), default: 65
- `--beam-Ry`: Material overstrength factor, default: 1.1

#### Column Parameters
- `--column-Fy`: Column yield stress (ksi), default: 50
- `--column-Fu`: Column tensile strength (ksi), default: 65
- `--column-Ry`: Material overstrength factor, default: 1.1

#### Loads
- `--load-D`: Dead load (kips, total on span), default: 0
- `--load-L`: Live load (kips, total on span), default: 0
- `--load-S`: Snow load (kips, total on span), default: 0
- `--Vu`: Required shear strength (kips), default: calculated

## Connection Detailing Requirements

### Beam Flange-to-Column (Section 8.5)
- CJP groove weld, demand critical per AISC 341
- Weld access holes per AWS D1.8 Section 6.11.1.2
- **Bottom flange**: Remove backing bar, backgouge to sound weld metal, add 5/16" min reinforcing fillet weld
- **Top flange**: Backing bar may remain, add 5/16" min continuous fillet weld below CJP weld

### Beam Web-to-Column (Section 8.6)
- CJP groove weld between weld access holes, demand critical

### Single-Plate Shear Connection (Section 8.6(2))
- Plate thickness: t_p ≥ t_w (beam web thickness)
- Plate height: approximately full web depth between flanges
- Weld to column: designed for shear ≥ h_p × t_p × (0.6 × R_y × F_y)
- Fillet weld to beam web: size = t_p - 1/16"
- Weld termination: 1/2" to 1" from weld access hole edge

### Weld Access Hole Geometry (Figure 8.3, AWS D1.8)

```
    Beam Flange
    ══════════════════
           │╲
     a     │  ╲ c (30°±10°)
    ←─→   │    ╲
           │      ╲
    ←───→ │  b     ╲═════════  Beam Web
      d    │  ←─────→
    ←─→   │
          │
    Beam Flange
    ══════════════════
```

- `a`: 1/4" min, 1/2" max
- `b`: 1" min
- `c`: 30° ± 10°
- `d`: 2" min
- `e`: 1/2" min, 1" max (fillet weld termination)

## Key Equations

### M_pr (Step 1)
```
C_pr = 1.4  (WUF-W specific, NOT Eq. 2.4-2)
Z_e = Z_x   (no section reduction)
M_pr = C_pr × R_y × F_y × Z_x
```

### V_h (Step 3)
```
L_h = L - d_c  (S_h = 0 for WUF-W)
V_h = 2 × M_pr / L_h + V_gravity
V_u = max(V_h, user-specified Vu)
```

### Column-Beam Relationship (Step 4)
```
F_f = M_pr / (d - t_f)
M_uv = V_h × (d_c / 2)
M_pb* = M_pr + M_uv
M_pc = Z_x,c × F_y,c
Ratio = M_pc / M_pb* ≥ 1.0
```

### Panel Zone (Step 7)
```
V_pz = F_f
V_n = 0.6 × F_y,c × d_c × t_wc  (basic capacity)
V_n = V_n × (1 + 3×b_cf×t_cf² / (d_b×d_c×t_wc))  (with flange contribution)
φ = 1.0 per AISC 341
```

## Output Example

```
================================================================================
  WUF-W CONNECTION DESIGN VERIFICATION (AISC 358-16 CHAPTER 8)
================================================================================

INPUT PARAMETERS
================================================================================
BEAM: W24X68 | d=23.70 bf=8.97 tf=0.585 tw=0.415 Zx=177.0
COLUMN: W14X311 | d=17.10 bf=16.20 tf=2.260 tw=1.410
SPAN: L=360 in (30.0 ft) | SMF

DESIGN PROCEDURE (SECTION 8.7)
--------------------------------------------------------------------------------
  STEP 1: PROBABLE MAXIMUM MOMENT M_pr
  M_pr = 1.4 * 1.1 * 50.0 * 177.0 = 13629 kip-in

  STEP 2: PLASTIC HINGE LOCATION S_h = 0
  M_f = M_pr = 13629 kip-in

  STEP 3: SHEAR FORCE AT PLASTIC HINGE
  V_h = 79.5 kips

  STEP 4: COLUMN-BEAM RELATIONSHIP
  Ratio M_pc / M_pb* = 2.107 => OK

  STEP 5: BEAM SHEAR STRENGTH CHECK
  OK (Utilization: 0.299)

  STEP 6: CONTINUITY PLATE REQUIREMENTS
  Column flange adequate

  STEP 7: COLUMN PANEL ZONE CHECK
  OK (Utilization: 0.568)

  STEP 8: CONNECTION DETAILING REQUIREMENTS
  All prescriptive requirements listed

DESIGN VERIFICATION SUMMARY
================================================================================
ALL CHECKS PASSED
```

## Notes

1. **C_pr = 1.4**: This is unique to WUF-W. Other connections use Eq. 2.4-2 which typically yields 1.1-1.2.

2. **Plastic Hinge at Column Face**: S_h = 0 means no moment amplification between the plastic hinge and the column face, simplifying the calculation.

3. **Demand Critical Welds**: All CJP groove welds (flanges and web) are demand critical per AISC 341.

4. **Simplified Column-Beam Check**: The program uses a simplified check without axial load. For final design, include axial load per AISC 341 E3.6c.

5. **Resistance Factors**:
   - φ_d = 1.0 for ductile limit states
   - φ_v = 0.9 for shear
   - φ_pz = 1.0 for panel zone per AISC 341

## Files

- `wufw_design.py`: Main verification script
- `aisc_w_shapes.csv`: Section database (289 W-shapes)
- `wufw_README.md`: This documentation file
- `wufw_REVIEW_RESPONSE.md`: Review response and corrections log

## See Also

- `rbs_design.py`: RBS connection verification (AISC 358-16 Chapter 5)
- `endplate_design.py`: End-plate connection verification (AISC 358-16 Chapter 6)
- `bfp_design.py`: BFP connection verification (AISC 358-16 Chapter 7)
- `extract_shapes.py`: Utility to extract sections from AISC Excel database
