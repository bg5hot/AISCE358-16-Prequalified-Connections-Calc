# AISC 358-16 Prequalified Connection Design Verification

Python-based seismic moment connection design verification tools based on **AISC 358-16** (Prequalified Connections for Special and Intermediate Steel Moment Frames).

## Overview

This project provides complete design verification programs for four types of prequalified seismic moment connections, implementing the step-by-step design procedures from AISC 358-16:

| Connection                         | Chapter | Script               | Steps |
| ---------------------------------- | ------- | -------------------- | ----- |
| RBS (Reduced Beam Section)         | Ch. 5   | `rbs_design.py`      | 11    |
| End-Plate (Extended)               | Ch. 6   | `endplate_design.py` | 13    |
| BFP (Bolted Flange Plate)          | Ch. 7   | `bfp_design.py`      | 17    |
| WUF-W (Welded Unreinforced Flange) | Ch. 8   | `wufw_design.py`     | 8     |

Each program performs all required checks including probable moment, shear, strong-column/weak-beam, continuity plates, panel zone, and connection detailing.

## Quick Start

```bash
# List available W-shapes (289 sections)
python rbs_design.py --list-sections

# RBS connection
python rbs_design.py --beam-section W30x99 --column-section W14x193 \
    --span 360 --system-type SMF

# End-plate connection (4E / 4ES / 8ES)
python endplate_design.py --connection-type 4E \
    --beam-section W24x68 --column-section W14x193 --span 300 --system-type SMF

# BFP connection
python bfp_design.py --beam-section W24x68 --column-section W14x120 \
    --span 300 --system-type SMF

# WUF-W connection
python wufw_design.py --beam-section W24x68 --column-section W14x311 \
    --span 360 --system-type SMF
```

## Connection Types

### RBS — Reduced Beam Section (Chapter 5)

Radius-cut flange reduction creates a controlled plastic hinge away from the column face. All-welded connection.

```
    Column        ╲     RBS cut     ╱        Beam
    Flange         ╲_______________╱        Flange
      │           ──╲             ╱──
      │              ╲___________╱
      │                 (c)
      │              ──╱     ╲──
      │           ──╱         ╲──
      │              a    b
      │         |←--→|←-----→|
```

### End-Plate — Extended End-Plate (Chapter 6)

Bolted end-plate connection. Supports three configurations: **4E** (unstiffened), **4ES** (stiffened), **8ES** (8-bolt stiffened).

```
              ┌─────────────────────┐
              │                     │
          ────┤  ┃               ┃  ├────
              │  ┃ (stiffener)  ┃  │
              │   ○           ○     │ ← tension bolts
              │                     │
          ────┤                     ├────
              └─────────────────────┘
                    End Plate
```

### BFP — Bolted Flange Plate (Chapter 7)

Flange plates welded to column, bolted to beam flanges. Bolts in **single shear** (A490/F2280 only).

```
     Column       Flange Plate         Beam
     Flange                             Flange
       │  ╔═══════════════════════╗
       │  ║  CJP groove weld     ║───○───○───○───
       │  ╚═══════════════════════╝
       │         |<-- S1 -->|<-s->|
```

### WUF-W — Welded Unreinforced Flange (Chapter 8)

Full CJP groove welds for both flanges and web directly to column. Single-plate shear tab supplements web connection.

Key parameters: **C_pr = 1.4** (not Eq. 2.4-2), **S_h = 0** (hinge at column face).

## Required Parameters

All programs require:

| Parameter          | Description                      | Example   |
| ------------------ | -------------------------------- | --------- |
| `--beam-section`   | Beam W-shape designation         | `W24x68`  |
| `--column-section` | Column W-shape designation       | `W14x311` |
| `--span`           | Beam span, center-to-center (in) | `360`     |
| `--system-type`    | Frame system (`SMF` or `IMF`)    | `SMF`     |

End-plate additionally requires `--connection-type` (4E, 4ES, or 8ES).

## Optional Parameters

### Material Properties

- `--beam-Fy` / `--column-Fy`: Yield stress (default: 50 ksi for A992)
- `--beam-Fu` / `--column-Fu`: Tensile strength (default: 65 ksi)
- `--beam-Ry` / `--column-Ry`: Overstrength factor (default: 1.1)

### Gravity Loads

- `--load-D`: Dead load (kips, total on span)
- `--load-L`: Live load (kips)
- `--load-S`: Snow load (kips)
- `--Vu`: Required shear strength (kips)

### Connection-Specific

- End-plate: `--bolt-diameter`, `--bolt-grade`, `--plate-thickness`, `--plate-width`
- BFP: `--plate-Fy`, `--plate-Fu` (flange plate material)

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

## References

- **AISC 358-16**: Prequalified Connections for Special and Intermediate Steel Moment Frames
- **AISC 360-16**: Specification for Structural Steel Buildings
- **AISC 341-16**: Seismic Provisions for Structural Steel Buildings
- **AISC Shapes Database v16.0**

## License

MIT
