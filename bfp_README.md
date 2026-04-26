# BFP (Bolted Flange Plate) Connection Design Verification

螺栓翼缘板节点抗震验算程序

Based on **AISC 358-16 Chapter 7, Section 7.6** - 17-Step Design Procedure

## Overview

BFP 连接使用翼缘板将梁翼缘连接到柱翼缘。翼缘板一端通过 CJP 坡口焊缝焊接于柱翼缘，另一端通过螺栓连接于梁翼缘。弯矩通过翼缘板拉压和螺栓抗剪传递。

### 连接示意

```
         Column       Flange Plate         Beam
         Flange                             Flange
           |  ╔═══════════════════════╗
           |  ║  CJP groove weld     ║---○---○---○---
           |  ║  (demand critical)   ║   b1   b2   b3
           |  ╚═══════════════════════╝
           |         |<-- S1 -->|<-s->|<-ed->|
           |
           |  ╔═══════════════════════╗
           |  ║  CJP groove weld     ║---○---○---○---
           |  ║                       ║
           |  ╚═══════════════════════╝
```

### 关键特点

- **柱侧**: CJP 坡口焊缝（要求切除垫板并反面焊接）
- **梁侧**: 高强螺栓（A490/F2280，螺纹排除剪切面）
- 螺栓受**剪切**（非拉伸，与端板连接不同）
- F_pr = M_f / **(d + t_p)**（注意是加号，不是减号）

## Usage

### Basic

```bash
python bfp_design.py --beam-section W24x68 --column-section W14x120 --span 300 --system-type SMF
```

### Custom Plate

```bash
python bfp_design.py --beam-section W24x68 --column-section W14x257 --span 360 --system-type SMF \
    --plate-width 12 --plate-thickness 1.0 --n-bolts 10 --bolt-diameter 1.0 --bolt-spacing 3.0
```

### List Sections

```bash
python bfp_design.py --list-sections
```

## 17-Step Design Procedure (AISC 358-16 Section 7.6)

| Step | Description | Equation |
|------|-------------|----------|
| 1 | Calculate M_pr | Eq. 2.4-1 |
| 2 | Max bolt diameter (prevent tensile rupture) | Eq. 7.6-2 |
| 3 | Controlling bolt shear strength r_n | Eq. 7.6-3 |
| 4 | Trial number of bolts | Eq. 7.6-4 |
| 5 | Plastic hinge location S_h | Eq. 7.6-5 |
| 6 | Shear at plastic hinge | - |
| 7 | Moment at column face M_f | Eq. 7.6-6 |
| 8 | Flange plate force F_pr | Eq. 7.6-7 |
| 9 | Confirm bolt count | Eq. 7.6-8 |
| 10 | Plate thickness (yielding) | Eq. 7.6-9 |
| 11 | Plate tensile rupture | Eq. 7.6-10 |
| 12 | Beam flange block shear | Eq. 7.6-11 |
| 13 | Compression plate buckling | Eq. 7.6-12 |
| 14 | Required shear strength | Eq. 7.6-13 |
| 15 | Web connection design | - |
| 16 | Continuity plate check | Chapter 2 |
| 17 | Column panel zone | Section 7.4 |

## Key Equations

### F_pr (Step 8)
```
F_pr = M_f / (d + t_p)     ← 注意: d + t_p，不是 d - t_f
```

### r_n (Step 3) - 三项取小
```
r_n = min(1.0 * Fnv * Ab,
          2.4 * Fub * db * tf,
          2.4 * Fup * db * tp)
```

### S_h (Step 5)
```
S_h = S_1 + s * (n/2 - 1)
```

### Trial bolts (Step 4)
```
n >= 1.25 * M_pr / (phi_n * r_n * (d + tp))    ← 1.25 empirical factor
```

## Prequalification Limits (Section 7.3)

| Parameter | Limit |
|-----------|-------|
| Beam depth | W36 max |
| Beam weight | 150 plf max |
| Beam flange tf | 1.0 in max |
| Span/depth (SMF) | >= 9 |
| Span/depth (IMF) | >= 7 |
| Bolt grade | A490 or F2280 only |
| Bolt diameter | 5/8" to 1-1/8" |
| Plate Fy | A36 or A572 Gr 50 (<= 55 ksi) |
| Bolt count | Even number |
| Bolt layout | Max 2 per row |

## Parameters

### Required
- `--beam-section`, `--column-section`, `--span`, `--system-type`

### Flange Plate
- `--plate-width`: Plate width (default: bf + 2")
- `--plate-thickness`: Plate thickness (default: 0.75*tf)
- `--n-bolts`: Bolts per flange, even (default: 6)
- `--bolt-diameter`: 5/8" to 1-1/8" (default: 1.0)
- `--bolt-grade`: A490 only (default)
- `--bolt-spacing`: Row spacing s (default: 3.0")
- `--bolt-offset`: Col face to first bolt S1 (default: 3.0")

### Material
- `--beam-Fy`, `--beam-Fu`, `--beam-Ry`, `--beam-Rt`
- `--plate material defaults to A36 (Fy=36, Fu=58 ksi)`

## Design Notes

1. **Bolt grade**: A490/F2280 only - A325 is NOT prequalified for BFP
2. **F_pr denominator**: Uses (d + t_p), not (d - t_f) as in other connections
3. **1.25 factor**: Empirical factor in Step 4 for initial bolt estimate
4. **Compression buckling**: KL = 0.65 * S1 (from Commentary)
5. **Block shear**: Checked on beam flange (not plate)

## Resistance Factors

| Factor | Value | Application |
|--------|-------|-------------|
| phi_d | 1.0 | Plate yielding |
| phi_n | 0.9 | Rupture, bolt shear, bearing, block shear, buckling |

## Files

- `bfp_design.py` - Main verification script
- `aisc_w_shapes.csv` - Section database (shared)
- `bfp_README.md` - This documentation

## See Also

- `rbs_design.py` - RBS connection (Chapter 5)
- `endplate_design.py` - End-plate connection (Chapter 6)
