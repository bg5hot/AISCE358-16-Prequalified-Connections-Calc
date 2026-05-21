# AISC 358-16 Prequalified Connection Design Verification

Python-based seismic moment connection design verification tools based on **AISC 358-16** (Prequalified Connections for Special and Intermediate Steel Moment Frames).

## Overview

This project provides complete design verification programs for **ten** types of prequalified seismic moment connections, implementing the step-by-step design procedures from AISC 358-16 Chapters 5 through 14:

| Connection | Chapter | Script | Steps | SMF | IMF |
|---|---|---|---:|:---:|:---:|
| RBS (Reduced Beam Section) | Ch. 5 | `rbs_design.py` | 11 | ✓ | ✓ |
| End-Plate (Extended) | Ch. 6 | `endplate_design.py` | 13 | ✓ | ✓ |
| BFP (Bolted Flange Plate) | Ch. 7 | `bfp_design.py` | 17 | ✓ | ✓ |
| WUF-W (Welded Unreinforced Flange) | Ch. 8 | `wufw_design.py` | 8 | ✓ | ✓ |
| KBB (Kaiser Bolted Bracket) | Ch. 9 | `kbb_design.py` | 18 | ✓ | ✓ |
| ConXL (ConXtech ConXL) | Ch. 10 | `conxl_design.py` | 11 | ✓ | ✓ |
| SidePlate | Ch. 11 | `sideplate_design.py` | 8 | ✓ | ✓ |
| SST (Simpson Strong-Tie Strong Frame) | Ch. 12 | `sst_design.py` | 19 | ✓ | ✓ |
| Double-Tee | Ch. 13 | `doubletee_design.py` | 23 | ✓ | ✓ |
| SlottedWeb™ (SW) | Ch. 14 | `slottedweb_design.py` | 10 | ✓ | — |

Each program performs all required checks including probable moment, shear, strong-column/weak-beam, continuity plates, panel zone, and connection detailing.

## Quick Start

```bash
# List available W-shapes (289 sections)
python rbs_design.py --list-sections

# RBS connection (Chapter 5)
python rbs_design.py --beam-section W30x99 --column-section W14x193 \
    --span 360 --system-type SMF

# End-plate connection (Chapter 6)
python endplate_design.py --connection-type 4E \
    --beam-section W24x68 --column-section W14x193 --span 300 --system-type SMF

# BFP connection (Chapter 7)
python bfp_design.py --beam-section W24x68 --column-section W14x120 \
    --span 300 --system-type SMF

# WUF-W connection (Chapter 8)
python wufw_design.py --beam-section W24x68 --column-section W14x311 \
    --span 360 --system-type SMF

# KBB connection (Chapter 9)
python kbb_design.py --beam-section W24x68 --column-section W14x193 \
    --span 300 --system-type SMF --bracket W2.1

# ConXL connection (Chapter 10)
python conxl_design.py --beam-section W24x68 --column-wall 0.5 \
    --span 300 --system-type SMF

# SidePlate connection (Chapter 11)
python sideplate_design.py --beam-section W36x150 --column-section W14x311 \
    --span 360 --system-type SMF --connection-type welded

# SST Strong Frame connection (Chapter 12)
python sst_design.py --beam-section W21x44 --column-section W14x145 \
    --span 300 --system-type SMF --t-stem 0.5

# Double-Tee connection (Chapter 13)
python doubletee_design.py --beam-section W21x44 --column-section W14x311 \
    --span 300 --system-type SMF --slab

# SlottedWeb connection (Chapter 14, SMF only)
python slottedweb_design.py --beam-section W24x94 --column-section W14x550 \
    --span 360 --system-type SMF
```

## Connection Types

### RBS — Reduced Beam Section (Chapter 5)

Radius-cut flange reduction creates a controlled plastic hinge away from the column face. All-welded connection.

- 11-step design procedure (Section 5.8)
- RBS geometry: a = 0.5bf–0.75bf, b = 0.65d–0.85d, c = 0.1bf–0.25bf
- SMF and IMF

### End-Plate — Extended End-Plate (Chapter 6)

Bolted end-plate connection. Supports three configurations: **4E** (unstiffened), **4ES** (stiffened), **8ES** (8-bolt stiffened).

- 13-step design procedure (Section 6.8)
- A325 or A490 tension bolts
- SMF and IMF

### BFP — Bolted Flange Plate (Chapter 7)

Flange plates welded to column, bolted to beam flanges. Bolts in **single shear** (A490/F2280 only).

- 17-step design procedure (Section 7.6)
- F_pr = M_f / (d + t_p)
- SMF and IMF

### WUF-W — Welded Unreinforced Flange (Chapter 8)

Full CJP groove welds for both flanges and web directly to column. Single-plate shear tab supplements web connection. C_pr = 1.4, S_h = 0.

- 8-step design procedure (Section 8.7)
- All CJP welds are demand critical
- SMF and IMF

### KBB — Kaiser Bolted Bracket (Chapter 9)

Proprietary bolted bracket connection. W-series (welded to beam) and B-series (bolted to beam).

- 18-step design procedure (Section 9.9)
- W3.x, W2.x, W1.0 bracket types
- SMF and IMF

### ConXL — ConXtech ConXL (Chapter 10)

Proprietary collar connection for concrete-filled square HSS or built-up box columns. C_pr = 1.1 for non-RBS beams.

- 11-step design procedure (Section 10.8)
- 16-in. square column only
- Collar bolts: 1-1/4" ASTM A574
- SMF and IMF

### SidePlate (Chapter 11)

Field-welded or field-bolted configurations. Steps 6-7 (component design) performed by SidePlate Systems Inc.

- 8-step EOR procedure (Section 11.7)
- Beam up to W40 (welded) / W44 (bolted)
- SMF and IMF

### SST — Simpson Strong-Tie Strong Frame (Chapter 12)

Proprietary PR (partially restrained) connection using Yield-Link structural fuses.

- 19-step design procedure (Section 12.9)
- φ_b = 0.90 for Eq. 12.9-1
- BRP (Buckling Restraint Plate) design
- SMF and IMF

### Double-Tee (Chapter 13)

T-stubs cut from rolled W-shapes bolted to column flanges (tension) and beam flanges (shear). FR connection with stiffness check.

- 23-step design procedure (Section 13.6)
- 4 or 8 tension bolt configurations
- FR stiffness: K_i >= 18EI/L (series spring model)
- g_tb/t_ft <= 7.0 prequalification limit
- SMF and IMF

### SlottedWeb™ — SW (Chapter 14)

Beam web slots parallel and adjacent to each flange. CJP groove welds for flanges (demand critical). Shear plate welded to column flange and beam web.

- 10-step design procedure (Section 14.8)
- l_b = half the clear span length
- Beam shear φ = 1.0 per Commentary C-14.8
- **SMF only** (not prequalified for IMF)

## Required Parameters

All programs require:

| Parameter | Description | Example |
|---|---|---|
| `--beam-section` | Beam W-shape designation | `W24x68` |
| `--column-section` | Column W-shape designation | `W14x311` |
| `--span` | Beam span, center-to-center (in) | `360` |
| `--system-type` | Frame system (`SMF` or `IMF`) | `SMF` |

End-plate additionally requires `--connection-type` (4E, 4ES, or 8ES). ConXL uses `--column-wall` instead of `--column-section`.

## Optional Parameters

### Material Properties

- `--beam-Fy` / `--column-Fy`: Yield stress (default: 50 ksi for A992)
- `--beam-Fu` / `--column-Fu`: Tensile strength (default: 65 ksi)
- `--beam-Ry` / `--column-Ry`: Overstrength factor (default: 1.1)

### Gravity Loads

- `--load-D`: Dead load (kips, total on span)
- `--load-L`: Live load (kips)
- `--load-S`: Snow load (kips)

### Column Checks

- `--Pu`: Column axial load (kips)
- `--As-col`: Column cross-section area (in²)
- `--story-above` / `--story-below`: Story heights (in)

### Connection-Specific

- End-plate: `--bolt-diameter`, `--bolt-grade`, `--plate-thickness`
- BFP: `--plate-Fy`, `--plate-Fu` (flange plate material)
- KBB: `--bracket` (W1.0, W2.x, W3.x, B1.0, B2.1), `--beam-bolts`
- ConXL: `--column-wall`, `--rbs` (optional RBS cutouts)
- SidePlate: `--connection-type` (welded/bolted), `--extension-A`
- SST: `--t-stem` (Yield-Link stem thickness)
- Double-Tee: `--tension-bolts` (4/8), `--bolt-type` (A325/A490), `--slab`
- SlottedWeb: `--l-p` (shear plate width), `--beam-T` (clear distance)

## Section Database

All programs use `aisc_w_shapes.csv` containing 289 W-shapes from the AISC Shapes Database v16.0.

To update the database from the AISC Excel file:

```bash
python extract_shapes.py  # reads aisc-shapes-database-v160-2.xlsx
```

## Units and Conventions

- US Customary units: inches (in), kips (kip), ksi
- Resistance factors per AISC 358-16 Section 2.4.1: φ_d = 1.0 (ductile), φ_n = 0.9 (nonductile)
- AISC 358-16 equation numbering referenced in code comments
- All sections read from CSV — no hardcoded section data

## Dependencies

- Python 3.6+
- openpyxl (for `extract_shapes.py` only)

## References

- **AISC 358-16**: Prequalified Connections for Special and Intermediate Steel Moment Frames
- **AISC 360-16**: Specification for Structural Steel Buildings
- **AISC 341-16**: Seismic Provisions for Structural Steel Buildings
- **AISC Shapes Database v16.0**

## License

MIT
