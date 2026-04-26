# AISC358 Moment Connection Design Verification

## Project Overview

Python-based seismic moment connection design verification tools based on AISC 358-16. Programs perform complete design verification for prequalified connections in steel moment frames.

## Key Files

- **`rbs_design.py`** - RBS connection verification (AISC 358-16 Chapter 5)
  - Implements Section 5.8 11-step design procedure
  - Supports both SMF and IMF systems

- **`endplate_design.py`** - End-plate connection verification (AISC 358-16 Chapter 6)
  - Supports 4E, 4ES, 8ES connection types
  - Implements Section 6.8 beam-side and column-side design
  - Y_p formulas per Tables 6.2, 6.3, 6.4
  - h_i distances measured from compression flange centerline: `h = (d - tf) ± pitch`

- **`bfp_design.py`** - Bolted Flange Plate connection verification (AISC 358-16 Chapter 7)
  - Implements Section 7.6 17-step design procedure
  - Bolts in SHEAR (single shear, A490/F2280 only)
  - F_pr = M_f / (d + t_p) [not d - t_f]
  - Supports `--plate-Fy` / `--plate-Fu` for material override
  - Supports both SMF and IMF systems

- **`wufw_design.py`** - WUF-W connection verification (AISC 358-16 Chapter 8)
  - Implements Section 8.7 design procedure (8 steps)
  - C_pr = 1.4 (WUF-W specific, NOT Eq. 2.4-2)
  - S_h = 0 (plastic hinge at column face), M_f = M_pr
  - CJP groove welds for flanges and web (demand critical)
  - Single-plate shear tab for supplemental web connection
  - Supports both SMF and IMF systems

- **`extract_shapes.py`** - Utility to extract W-shape data from AISC Excel database
  - Generates `aisc_w_shapes.csv` with 289 W-shapes

- **`aisc_w_shapes.csv`** - Section database (289 W-shapes from AISC v16.0)
  - Columns: designation, d, bf, tw, tf, Zx
  - Shared by all design scripts

## Design Verification Procedures

### RBS (Chapter 5, Section 5.8) - 11 Steps

1. **RBS Geometry Limits** - Verify a, b, c dimensions satisfy code limits
2. **Calculate Z_RBS** - Plastic section modulus at reduced section
3. **Calculate M_pr** - Probable maximum moment at RBS
4. **Calculate V_RBS** - Shear force at RBS
5. **Calculate M_f** - Probable maximum moment at column face
6. **Calculate M_pe** - Plastic moment of beam
7. **Flexural Strength Check** - Verify M_f <= phi_d * M_pe
8. **Shear Strength Check** - Verify V_u <= phi_v * V_n
9. **Web Connection Design** - Per Section 5.6
10. **Continuity Plate Requirements** - Per Chapter 2
11. **Column-Beam Relationship** - Strong-column/weak-beam check

### End-Plate (Chapter 6, Section 6.8) - 13 Steps

1. **Calculate M_f** - Moment at column face (Eq. 6.8-1)
2. **Connection geometry** - h_i distances from compression flange CL
3. **Required bolt diameter** - Eq. 6.8-3 (4E/4ES) or 6.8-4 (8ES)
4. **Select bolt** - A325, A490, or F1852
5. **Required plate thickness** - Y_p from Tables 6.2-6.4 (Eq. 6.8-5)
6. **Select plate** - Verify t_p >= t_p,req
7. **Beam flange force** - F_fu = M_f / (d - t_bf) (Eq. 6.8-6)
8. **Plate shear yielding** - 4E only (Eq. 6.8-7)
9. **Plate shear rupture** - 4E only (Eq. 6.8-8)
10. **Stiffener design** - 4ES/8ES only (Eq. 6.8-9, 6.8-10)
11. **Bolt shear** - Eq. 6.8-11
12. **Bearing/tearout** - AISC 360 Chapter J
13. **Weld design** - Section 6.7.6

### WUF-W (Chapter 8, Section 8.7) - 8 Steps

1. **M_pr** - Probable maximum moment, C_pr = 1.4 (NOT Eq. 2.4-2)
2. **S_h** - Plastic hinge location = 0 (at column face)
3. **V_h** - Shear force at plastic hinge
4. **Column-beam relationship** - AISC 341 E3.6c strong-column/weak-beam
5. **Beam shear strength** - V_u <= phi_v * V_n
6. **Continuity plates** - AISC 360 Chapter J10
7. **Panel zone** - AISC 341 D1.2c and AISC 360 J10.6
8. **Connection detailing** - CJP welds, weld access holes, shear tab

### BFP (Chapter 7, Section 7.6) - 17 Steps

1. **M_pr** - Eq. 2.4-1
2. **Max bolt diameter** - Eq. 7.6-2
3. **r_n (controlling bolt shear)** - Eq. 7.6-3 (three-term minimum)
4. **Trial bolt count** - Eq. 7.6-4
5. **S_h (plastic hinge location)** - Eq. 7.6-5
6. **V_h (shear at hinge)** -
7. **M_f (moment at column face)** - Eq. 7.6-6
8. **F_pr (flange plate force)** - Eq. 7.6-7, uses (d + t_p)
9. **Confirm bolt count** - Eq. 7.6-8
10. **Plate yielding** - Eq. 7.6-9
11. **Plate rupture** - Eq. 7.6-10
12. **Block shear** - Eq. 7.6-11
13. **Compression buckling** - Eq. 7.6-12, KL = 0.65*S1
14. **Required shear** - Eq. 7.6-13
15. **Web connection** -
16. **Continuity plates** - Chapter 2
17. **Panel zone** - Section 7.4

## Key Parameters

### Section Properties (from CSV)
- `d` - Section depth (in)
- `bf` - Flange width (in)
- `tw` - Web thickness (in)
- `tf` - Flange thickness (in)
- `Zx` - Plastic section modulus (in^3)

### RBS Geometry
- `a` - Distance from column face to start of cut (0.5*bf to 0.75*bf)
- `b` - Length of cut (0.65*d to 0.85*d)
- `c` - Depth of cut at center (0.1*bf to 0.25*bf)

### End-Plate Geometry
- `pfo` - Distance from tension flange CL to outer bolt row (outward)
- `pfi` - Distance from tension flange CL to inner bolt row (inward)
- `g` - Horizontal gage between bolt columns
- `pb` - Row spacing within bolt pair (8ES only)
- `s = 0.5 * sqrt(bp * g)` - Characteristic yield line dimension

### BFP Geometry
- `S1` - Distance from column face to first bolt row
- `s` - Bolt row spacing
- `S_h = S1 + s * (n/2 - 1)` - Plastic hinge location (Eq. 7.6-5)
- `db <= 1.125 in` - Maximum bolt diameter
- A490/F2280 bolts only (NOT A325)

### WUF-W Specific Parameters
- `C_pr = 1.4` - Fixed value (NOT Eq. 2.4-2)
- `S_h = 0` - Plastic hinge at column face
- `Z_e = Z_x` - No section reduction
- `M_f = M_pr` - No shear amplification
- Beam depth <= 36 in, weight <= 150 plf, tf <= 1.0 in
- All CJP groove welds are demand critical

### Material Properties
- `Fy` - Yield stress (default: 50 ksi for A992)
- `Ry` - Material overstrength factor (1.1 for A992)
- `C_pr` - min((Fy + Fu)/(2*Fy), 1.2) per Eq. 2.4-2 (except WUF-W: C_pr = 1.4)

### Resistance Factors (AISC 358-16 Section 2.4.1)
- `phi_d = 1.0` - Ductile limit states (plate yielding, panel zone)
- `phi_n = 0.9` - Nonductile limit states (rupture, bolt, bearing, buckling)
- `phi_v = 0.9` - Shear
- `phi_pz = 1.0` - Panel zone per AISC 341

## Common Commands

```bash
# List all available sections
python rbs_design.py --list-sections

# RBS verification (auto-calculate RBS dimensions)
python rbs_design.py --beam-section W30x99 --column-section W14x193 \
    --span 360 --system-type SMF

# End-plate verification (4E)
python endplate_design.py --connection-type 4E \
    --beam-section W24x68 --column-section W14x193 --span 300 --system-type SMF

# End-plate verification (8ES with larger bolts)
python endplate_design.py --connection-type 8ES \
    --beam-section W24x68 --column-section W14x257 --span 300 --system-type SMF \
    --bolt-diameter 1.25 --plate-thickness 1.25

# BFP verification (default A572 Gr 50 plate)
python bfp_design.py --beam-section W24x68 --column-section W14x120 \
    --span 300 --system-type SMF

# BFP with A36 plate material
python bfp_design.py --beam-section W24x68 --column-section W14x120 \
    --span 300 --system-type SMF --plate-Fy 36 --plate-Fu 58

# WUF-W verification
python wufw_design.py --beam-section W24x68 --column-section W14x311 \
    --span 360 --system-type SMF

# WUF-W with gravity loads
python wufw_design.py --beam-section W24x68 --column-section W14x311 \
    --span 360 --system-type SMF --load-D 10 --load-L 20

# Custom section properties
python rbs_design.py \
    --beam-d 30 --beam-bf 10.45 --beam-tf 0.615 --beam-tw 0.36 --beam-Zx 311 \
    --column-d 15.5 --column-bf 10.7 --column-tf 1.57 --column-tw 0.91 --column-Zx 361 \
    --span 360 --system-type SMF
```

## Updating Section Database

To update the section database from the Excel file:

```bash
python extract_shapes.py
```

This reads `aisc-shapes-database-v160-2.xlsx` and generates `aisc_w_shapes.csv`.

## Code Conventions

- Use US Customary units (inches, kips, ksi)
- Follow AISC 358-16 equation numbering in comments
- All sections read from CSV - no hardcoded section data
- User must specify system type (SMF or IMF)

## Dependencies

- Python 3.6+
- openpyxl (for extract_shapes.py only)

## References

- AISC 358-16: Prequalified Connections for Special and Intermediate Steel Moment Frames
- AISC 360-16: Specification for Structural Steel Buildings
- AISC 341-16: Seismic Provisions for Structural Steel Buildings
- AISC Shapes Database v16.0
