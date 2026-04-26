# AISC 358-16 Yield Line Mechanism Parameter (Y_p) Formulas

## Reference
AISC 358-16 Chapter 6, Tables 6.2, 6.3, 6.4

These formulas are used in Eq. 6.8-5 to determine the required end-plate thickness:

    t_p,req = sqrt(1.11 * M_f / (phi_d * F_yp * Y_p))

where phi_d = 1.00 and F_yp = yield stress of end-plate material.

---

## Common Definitions

All h_i distances are measured from the **centerline of the beam compression flange**
upward to the centerline of each tension bolt row.

### Geometric Parameters

| Symbol | Definition | Units |
|--------|-----------|-------|
| b_p | Width of end-plate (not greater than beam flange width + 1 in) | in |
| g | Horizontal gage distance between bolt columns | in |
| p_fi | Vertical distance from INSIDE of beam tension flange to nearest INSIDE bolt row | in |
| p_fo | Vertical distance from OUTSIDE of beam tension flange to nearest OUTSIDE bolt row | in |
| p_b | Vertical distance between inner and outer bolt rows (8ES only) | in |
| s | Characteristic yield line dimension = (1/2) * sqrt(b_p * g) | in |
| d | Depth of beam | in |
| t_bf | Thickness of beam flange | in |
| d_e | Edge distance from outside of tension flange to outer bolt row = p_fo | in |

### h_i Distance Calculations (from compression flange centerline)

For all connection types, the compression flange centerline is at the mid-thickness
of the bottom flange (for a simply-supported beam with tension on top).

**4E and 4ES:**
```
h_o = d/2 + p_fo       (outer tension bolt row, near plate edge)
h_1 = d/2 - t_bf + p_fi  (inner tension bolt row, near tension flange)
```

**8ES:**
```
h_1 = d/2 + p_fo + p_b     (outermost row)
h_2 = d/2 + p_fo            (outer pair inner row)
h_3 = d/2 - t_bf + p_fi     (inner pair outer row)
h_4 = d/2 - t_bf + p_fi - p_b  (innermost row)
```

### Key Constraint
If p_fi > s, use p_fi = s in the Y_p formula (per Tables 6.2, 6.3, 6.4 notes).

---

## Table 6.2: Four-Bolt Extended Unstiffened (4E)

### Y_p Formula

```
Y_p = (b_p/2) * [h_1 * (1/p_fi + 1/s) + h_o * (1/p_fo) - 1/2]
    + (2/g) * [h_1 * (p_fi + s)]
```

### Parameter Notes
- s = (1/2) * sqrt(b_p * g)
- If p_fi > s, use p_fi = s
- The "-1/2" is an edge correction term within the b_p/2 bracket
- h_o is used in bolt diameter equation: d_b,req = sqrt(2*M_f / (pi * phi_n * F_nt * (h_o + h_1)))

---

## Table 6.3: Four-Bolt Extended Stiffened (4ES)

### Case Distinction
- **Case 1**: d_e <= s  (edge distance is small relative to yield line dimension)
- **Case 2**: d_e > s   (edge distance is large)

where d_e = p_fo (distance from outside of tension flange to outer bolt row).

Note: For 4ES, a single pitch p_f is used for both rows (the OCR text shows "p_f"
rather than separate p_fi/p_fo). In the implementation, p_fi is used as the
controlling pitch, limited to s per the note.

### Case 1 (d_e <= s)

```
Y_p = (b_p/2) * [h_1 * (1/p_f + 1/s) + h_o * (1/p_f + 1/(2*s))]
    + (2/g) * [h_1 * (p_f + s) + h_o * (d_e + p_f)]
```

### Case 2 (d_e > s)

```
Y_p = (b_p/2) * [h_1 * (1/p_f + 1/s) + h_o * (1/s + 1/p_f)]
    + (2/g) * [h_1 * (p_f + s) + h_o * (s + p_f)]
```

---

## Table 6.4: Eight-Bolt Extended Stiffened (8ES)

### Bolt Row Numbering (from farthest to nearest to compression flange)
- h_1: outermost tension bolt row (near plate edge)
- h_2: second row from outside
- h_3: third row from outside
- h_4: innermost tension bolt row (near tension flange)

### Case Distinction
- **Case 1**: d_e <= s
- **Case 2**: d_e > s

where d_e = p_fo.

### Case 1 (d_e <= s)

```
Y_p = (b_p/2) * [h_1 * (1/(2*d_e)) + h_2 * (1/p_fo) + h_3 * (1/p_fi) + h_4 * (1/s)]
    + (2/g) * [h_1 * (d_e + 3*p_b/4) + h_2 * (p_fo + p_b/4)
             + h_3 * (p_fi + 3*p_b/4) + h_4 * (s + p_b/4)]
    + g/2
```

### Case 2 (d_e > s)

```
Y_p = (b_p/2) * [h_1 * (1/s) + h_2 * (1/p_fo) + h_3 * (1/p_fi) + h_4 * (1/s)]
    + (2/g) * [h_1 * (s + p_b/4) + h_2 * (p_fo + 3*p_b/4)
             + h_3 * (p_fi + p_b/4) + h_4 * (s + 3*p_b/4)]
    + g/2
```

---

## OCR Decoding Notes

The formulas above were decoded from OCR-extracted text of AISC 358-16 Tables 6.2-6.4.
Key OCR artifacts that were resolved:

1. "bP" was read as "b_p" (end-plate width)
2. "Pb" was read as "p_b" (bolt pitch in 8ES)
3. "pf" context-dependently resolved to p_fi or p_fo based on which bolt row
4. Table 6.2: "h0(1/pf)-1/2" decoded as "h_o * (1/p_fo) - 1/2" (edge correction)
5. Table 6.4 Case 1: "h1(d+3Pb/4)" decoded as "h_1 * (d_e + 3*p_b/4)"
6. The "+g/2" trailing term in Table 6.4 formulas is a web-side yield line contribution

## Bolt Diameter Equations (Eq. 6.8-3 and 6.8-4)

For 4E and 4ES (Eq. 6.8-3):
```
d_b,req = sqrt(2 * M_f / (pi * phi_n * F_nt * (h_o + h_1)))
```

For 8ES (Eq. 6.8-4):
```
d_b,req = sqrt(2 * M_f / (pi * phi_n * F_nt * (h_1 + h_2 + h_3 + h_4)))
```

where phi_n = 0.90 and F_nt = nominal bolt tensile strength (90 ksi for A325, 113 ksi for A490).

---

## Sources
- AISC 358-16 Tables 6.2, 6.3, 6.4 (OCR text from specification)
- AISC 358-16 Section 6.8.1 notation (h_i, h_o definitions)
- AISC 358-16 Table 6.1 (parametric limitations and variable definitions)
- AISC 358-16 Commentary Section 6.8 (Borgsmiller and Murray 1995 basis)
- AISC Design Guide 4, 2nd Ed. (Murray and Sumner, 2003) - example calculations
