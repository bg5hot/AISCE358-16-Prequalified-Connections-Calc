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

- **`kbb_design.py`** - Kaiser Bolted Bracket connection verification (AISC 358-16 Chapter 9)
  - Implements Section 9.9 18-step design procedure
  - W-series (welded to beam) and B-series (bolted to beam) brackets
  - S_h = L_bb (bracket length per Table 9.1)
  - Column bolts: F3125 A490 or A354 Grade BD
  - d_eff = centroidal distance between upper/lower bracket bolt groups
  - Supports both SMF and IMF systems

- **`conxl_design.py`** - ConXtech ConXL connection verification (AISC 358-16 Chapter 10)
  - Implements Section 10.8 11-step design procedure
  - Column: 16-in. square concrete-filled HSS or built-up box ONLY
  - C_pr = 1.1 for non-RBS beams (NOT Eq. 2.4-2), Eq. 2.4-2 for RBS
  - Collar bolts: 1-1/4" ASTM A574, pretension = 102 kips, n_cf = 8
  - t_collar = 7.125 in (column face to collar outside face)
  - Optional RBS cutouts to satisfy strong-column/weak-beam
  - Panel zone includes collar corner leg contribution (Eq. 10.8-19)
  - Supports both SMF and IMF systems

- **`sideplate_design.py`** - SidePlate moment connection verification (AISC 358-16 Chapter 11)
  - Two connection types: field-welded and field-bolted (Config A/B/C)
  - Implements Section 11.7 Steps 1-5 and 8 (EOR responsibilities)
  - Steps 6-7 (component design) performed by SidePlate Systems Inc.
  - Geometric compatibility per Eqs. 11.4-1a (welded) / 11.4-1b (bolted)
  - Column-beam moment ratio per Eqs. 11.4-2 through 11.4-6
  - Preliminary SCWB check per Eq. 11.7-1 (SMF only)
  - Plastic hinge at d/3 (welded) or d/6 (bolted) from side plate extension
  - Side plate extension: 0.65d to 1.0d (welded) / 1.7d (bolted)
  - Beam up to W40 (welded) / W44 (bolted), weight up to 302/400 plf
  - Supports both SMF and IMF systems

- **`doubletee_design.py`** - Double-Tee moment connection verification (AISC 358-16 Chapter 13)
  - Implements Section 13.6 23-step design procedure
  - T-stubs cut from rolled W-shapes (ASTM A992 or A913 Gr 50)
  - Supports 4 or 8 tension bolt configurations
  - FR stiffness check (K_flange, K_stem, K_slip series spring model)
  - T-stub prying action: mixed-mode, no-prying, plastic mechanism (T1, T2, T3)
  - Beam depth <= W24, weight <= 55 plf, tf <= 5/8 in
  - Column: W36 max (with slab) / W14 max (no slab)
  - g_tb/t_ft <= 7.0 prequalification limit
  - Supports both SMF and IMF systems

- **`slottedweb_design.py`** - SlottedWeb™ (SW) moment connection verification (AISC 358-16 Chapter 14)
  - Implements Section 14.8 10-step design procedure
  - Beam web slots parallel and adjacent to each flange
  - CJP groove welds for beam flanges (demand critical)
  - Shear plate welded to column flange, bolted + fillet welded to beam web
  - Plastic hinge at end of shear plate (S_h = l_p)
  - l_b = half the clear span length (per Symbols table)
  - Beam shear phi = 1.0, Cv = 1.0 per Commentary C-14.8
  - M_uv = V_beam * (l_p + d_c/2) per Eq. 14.4-1
  - Beam depth <= W36, weight <= 400 plf, tf <= 2.5 in, L/d >= 6.4
  - **SMF only** (not prequalified for IMF)

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

### KBB (Chapter 9, Section 9.9) - 18 Steps

1. **M_pr** - Eq. 2.4-1 (C_pr per Eq. 2.4-2)
2. **Bracket selection** - Per Tables 9.1-9.3
3. **V_h** - Shear at plastic hinge (S_h = L_bb)
4. **M_f** - Eq. 9.9-1
5. **Column bolt tension** - Eqs. 9.9-2, 9.9-3
6. **Column flange width** - Eq. 9.9-4 (prevent tensile rupture)
7. **Column flange thickness** - Eqs. 9.9-5, 9.9-6 (eliminate prying)
8. **Continuity plate elimination** - Eq. 9.9-7 (Y_m yield line parameter)
9. **Continuity plate requirements** - Step 10 logic
10. **Beam flange width** - Eq. 9.9-8 (B-series only)
11. **Beam bolt shear** - Eq. 9.9-9 (B-series only)
12. **Block shear** - Eq. 9.9-10 (B-series only)
13. **Fillet weld** - Eqs. 9.9-11, 9.9-12 (W-series only)
14. **Required shear** - Eq. 9.9-13
15. **Web connection** - Section 9.7
16. **Panel zone** - Section 9.4 (uses d_eff)

### ConXL (Chapter 10, Section 10.8) - 11 Steps

1. **M_pr** - Eq. 2.4-1 (C_pr = 1.1 non-RBS, Eq. 2.4-2 for RBS)
2. **V_h** - Eq. 10.8-1
3. **Column-beam ratio** - Eqs. 10.8-2, 10.8-3 (biaxial, composite column)
4. **M_bolts** - Eqs. 10.8-4 to 10.8-6
5. **Collar bolt tension** - Eqs. 10.8-7, 10.8-8 (r_ut/102 <= 1.0)
6. **Slip-critical bolt shear** - Class A, phi = 1.0
7. **Beam shear** - V_cf at collar face
8. **CWX fillet weld** - Eq. 10.8-9 (beam web to collar web extension)
9. **CC fillet weld** - Eq. 10.8-10 (collar corner to column)
10. **Panel zone demand** - Eqs. 10.8-11 to 10.8-17
11. **Panel zone capacity** - Eqs. 10.8-18, 10.8-19

### SidePlate (Chapter 11, Section 11.7) - 8 Steps (EOR: Steps 1-5, 8)

1. **Geometric compatibility** - Eqs. 11.4-1a (welded) / 11.4-1b (bolted)
2. **Frame modeling** - 100% rigid offset, 3x beam stiffness for ~0.77d
3. **Beam prequalification** - Depth, weight, tf, L_h/d limits (Section 11.3.1)
4. **Column prequalification** - Depth limits (Section 11.3.2)
5. **Design forces** - M_pr (Eq. 2.4-1), V_h (Eq. 11.4-3), M_group (Eq. 11.7-2)
6. **Column-beam ratio** - Eqs. 11.4-2 to 11.4-6 (Z_ec projection, Eq. 11.4-5)
7. **Beam shear** - AISC 360 G2.1
8. **Panel zone** - Preliminary check (AISC 360 J10.6), final by SidePlate Systems
9. **Preliminary SCWB** - Eq. 11.7-1: Sum(F_yc*Z_c) > 1.7*Sum(F_yb*Z_b) (SMF only)

### Double-Tee (Chapter 13, Section 13.6) - 23 Steps

1. **M_pr** - Eq. 2.4-1 (C_pr per Eq. 2.4-2)
2. **Shear bolt diameter** - Eq. 13.6-3 (largest bolt that satisfies net-section fracture)
3. **Design shear strength per bolt** - Eq. 13.6-4 (three-term minimum)
4. **Number of shear bolts** - Eq. 13.6-5 (even integer)
5. **Plastic hinge location** - Eqs. 13.6-6, 13.6-7 (S_h = S1 + L_vb)
6. **Shear at hinge** - V_h = 2*M_pr/L_h + V_gravity
6a. **Beam shear strength** - AISC 360 G2.1
7. **Moment at column face** - Eq. 13.6-10
7a. **Column-beam ratio** - AISC 341 E3.6c (SMF only)
8. **T-stub force** - Eq. 13.6-11 (F_pr = M_f/(1.05*d))
9. **T-stem size** - Eqs. 13.6-12 to 13.6-15 (yielding, fracture, buckling)
10. **Tension bolt size** - Eq. 13.6-16
11. **T-flange configuration** - Eqs. 13.6-17 to 13.6-27 (mixed-mode, no-prying)
12. **Select T-stub from W-shape** - match tw, tf, bf requirements
13. **FR stiffness check** - Eqs. 13.6-28 to 13.6-39 (K_flange, K_stem, K_slip)
14. **Actual flange force** - Eq. 13.6-40 (F_f = M_f/(d + t_st))
15. **Back-check shear bolts** - Eq. 13.6-41
16. **Back-check T-stem** - Eqs. 13.6-42 to 13.6-45 (yielding, fracture, buckling)
17. **Back-check T-flange** - Eqs. 13.6-46 to 13.6-54 (T1, T2, T3 modes)
18. **Bearing and tear-out** - AISC 360 Chapter J
19. **Block shear** - AISC 360 Chapter J (alternate mechanism per Fig. 13.7 exempt)
20. **Shear connection** - Single-plate shear tab (EOR responsibility)
21. **Column flange yielding** - Eqs. 13.6-55 to 13.6-61 (yield line analysis)
22. **Column web and panel zone** - AISC 360 J10.2, J10.3, J10.6 + AISC 341 D1.2c
23. **Continuity plates** - Required at all locations per Section 13.5.2

### SlottedWeb (Chapter 14, Section 14.8) - 10 Steps (SMF only)

1. **Beam web slot design** - Eqs. 14.8-1 to 14.8-4 (l_s = min of 4 limits)
2. **Shear plate design** - Eqs. 14.8-5, 14.8-6 (h = T - 2, t_p from moment demand)
3. **Plate-to-beam web weld** - Eqs. 14.8-7 to 14.8-11 (M_weld, V_weld, e_x)
4. **Plate-to-column flange weld** - Strength >= Step 3 weld group
5. **Erection bolts** - Diameter >= tw, max 6 in spacing
6. **M_f at column face** - Eq. 14.8-12 (M_f = M_pr + V_beam * l_p)
7. **Beam shear** - AISC 360 G2.1 (phi = 1.0, Cv = 1.0 per Commentary C-14.8)
8. **Continuity plates** - Section 2.4.4
9. **Panel zone** - AISC 341 D1.2c + AISC 360 J10.6
10. **Column-beam ratio** - AISC 341 E3.6c with M_uv per Eq. 14.4-1

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

### KBB Specific Parameters
- `S_h = L_bb` - Plastic hinge at bracket end (Table 9.1)
- `d_eff` - Centroidal distance between upper/lower bracket bolt groups
- W-series: welded to beam flange (5 bracket types)
- B-series: bolted to beam flange (2 bracket types)
- Column bolts: F3125 A490 or A354 Grade BD
- Beam depth <= W33, weight <= 130 plf, tf <= 1.0 in
- Column flange width >= 12 in
- `Y_m` = 5.9 (W3.x), 6.5 (W2.x/B2.1), 7.5 (W1.0/B1.0)
- `p` = 3.5 in (W1.0/B1.0), 5.0 in (all others)

### ConXL Specific Parameters
- `C_pr = 1.1` for non-RBS beams (NOT Eq. 2.4-2)
- `C_pr = min((Fy+Fu)/(2Fy), 1.2)` for RBS beams (Eq. 2.4-2)
- Column: 16-in square HSS or built-up box, concrete-filled
- `t_collar = 7.125 in` - Column face to collar outside face
- Collar bolts: 1-1/4" ASTM A574, T_b = 102 kips, n_cf = 8
- Beam depths: W30, W27, W24, W21, W18 only
- Beam flange: tf <= 1.0 in, bf <= 12 in
- Column wall >= 3/8 in, concrete f'c >= 3000 psi, weight >= 110 pcf
- `d_leg_CC = 3.5 in`, `t_leg_CC` per collar corner geometry

### SidePlate Specific Parameters
- `connection_type` - "welded" or "bolted"
- `extension_A` - Side plate extension beyond column face (0.65d to 1.0d / 1.7d)
- `hinge_ratio` - d/3 (welded) or d/6 (bolted) from end of side plate extension
- `L_h` - Hinge-to-hinge span (Eqs. 11.3-1a / 11.3-1b)
- Beam: W40 max (welded) / W44 max (bolted), up to 302/400 plf, tf <= 2.5 in
- Column: any W-shape up to W44, built-up box up to 33 in wide, HSS (A1085)
- Connection plates: ASTM A572 Gr 50 only
- Bolts: ASTM F3125 A490/A490M/F2280 or F3148, max 1-3/8 in
- L_h/d >= 4.5 (welded SMF), 4.0 (bolted SMF), 3.0 (IMF)
- Z_ec = Z_c * H / H_h (Eq. 11.4-5), where H_h = H - d_c/2
- Steps 6-7 (connection component design) by SidePlate Systems Inc.

### Double-Tee Specific Parameters
- T-stubs cut from rolled W-shapes (ASTM A992 or A913 Gr 50)
- Beam depth <= W24, weight <= 55 plf, tf <= 5/8 in, L/d >= 9
- Column: W36 max (with concrete slab) / W14 max (no slab)
- Tension bolts: 4 or 8 per T-stub, ASTM F3125 A325/A490
- Shear bolts: 2 per row, pretensioned, slip-critical
- `g_tb/t_ft <= 7.0` (prequalification limit, Section 13.5.4(5))
- FR stiffness check: K_i >= 18*E*I_beam/L (Eq. 13.6-28)
- Continuity plates required at all column locations
- Plastic hinge at shear bolts farthest from column face (S_h = S1 + L_vb)

### SlottedWeb Specific Parameters
- `l_b` = half the clear span length = (L - d_c) / 2 (per Symbols table)
- `l_s` = slot length = min(1.5*bf, 0.60*tf*sqrt(E/Fye), d/2, 3*l_b/29)
- `l_p` = shear plate width: l_s/3 <= l_p <= min(l_s/2, 6 in)
- `h` = shear plate height = T - 2 in +/- 1 in (Eq. 14.8-5)
- `t_p` = shear plate thickness per Eq. 14.8-6, min 2/3*tw or 3/8 in
- `Z_web` = tw * T^2 / 4 (Eq. 14.8-11)
- Beam flange CJP welds are demand critical
- Beam shear phi = 1.0, Cv = 1.0 per Commentary C-14.8
- M_uv = V_beam * (l_p + d_c/2) per Eq. 14.4-1
- **SMF only** -- not prequalified for IMF
- Shear plate steel: Fy = 50 ksi minimum

### Material Properties
- `Fy` - Yield stress (default: 50 ksi for A992)
- `Ry` - Material overstrength factor (1.1 for A992)
- `C_pr` - min((Fy + Fu)/(2*Fy), 1.2) per Eq. 2.4-2 (except WUF-W: 1.4, ConXL non-RBS: 1.1, SidePlate: Eq. 2.4-2)

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

# KBB verification (W-series bracket)
python kbb_design.py --beam-section W24x68 --column-section W14x193 \
    --span 300 --system-type SMF --bracket W2.1

# KBB verification (B-series bracket)
python kbb_design.py --beam-section W24x68 --column-section W14x311 \
    --span 360 --system-type SMF --bracket B2.1 --beam-bolts 10

# ConXL verification (non-RBS)
python conxl_design.py --beam-section W24x68 --column-wall 0.5 \
    --span 300 --system-type SMF

# ConXL verification (with RBS)
python conxl_design.py --beam-section W24x68 --column-wall 0.625 \
    --span 300 --system-type SMF --rbs --rbs-a 5 --rbs-b 18 --rbs-c 1.5

# ConXL with gravity loads and story heights
python conxl_design.py --beam-section W21x57 --column-wall 0.5 \
    --span 240 --system-type IMF --load-D 10 --load-L 15 \
    --story-above 156 --story-below 156 --Pu 200

# SidePlate verification (field-welded SMF)
python sideplate_design.py --beam-section W36x150 --column-section W14x311 \
    --span 360 --system-type SMF --connection-type welded

# SidePlate verification (field-bolted SMF)
python sideplate_design.py --beam-section W40x211 --column-section W14x455 \
    --span 420 --system-type SMF --connection-type bolted

# SidePlate verification (field-welded IMF with gravity loads)
python sideplate_design.py --beam-section W24x68 --column-section W14x120 \
    --span 300 --system-type IMF --connection-type welded --load-D 5 --load-L 10

# SidePlate with custom extension and column axial load
python sideplate_design.py --beam-section W36x150 --column-section W14x500 \
    --span 360 --system-type SMF --connection-type welded \
    --extension-A 30 --Pu-col 500 --As-col 150 --story-height 180

# Double-Tee verification (4-bolt, SMF with slab)
python doubletee_design.py --beam-section W21x44 --column-section W14x311 \
    --span 300 --system-type SMF --slab

# Double-Tee verification (8-bolt tension configuration)
python doubletee_design.py --beam-section W24x55 --column-section W14x311 \
    --span 360 --system-type SMF --tension-bolts 8 --bolt-type A490 --slab

# Double-Tee with gravity loads, axial load, and story heights
python doubletee_design.py --beam-section W21x44 --column-section W14x257 \
    --span 300 --system-type SMF --load-D 10 --load-L 20 \
    --Pu 300 --As-col 75.6 --story-above 156 --story-below 156 --slab

# SlottedWeb verification (SMF only)
python slottedweb_design.py --beam-section W24x94 --column-section W14x550 \
    --span 360 --system-type SMF

# SlottedWeb with gravity loads and custom beam T value
python slottedweb_design.py --beam-section W36x150 --column-section W14x455 \
    --span 420 --system-type SMF --load-D 15 --load-L 25 --beam-T 30.5

# SlottedWeb with axial load and story heights
python slottedweb_design.py --beam-section W30x173 --column-section W14x550 \
    --span 480 --system-type SMF --Pu 400 --As-col 161 --story-above 168

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
