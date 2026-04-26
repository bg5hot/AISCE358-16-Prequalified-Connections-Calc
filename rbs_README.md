# RBS (Reduced Beam Section) 节点验算程序

基于 AISC 358-16 第5章的RBS节点验算程序，按照规范规定的流程对每一步骤进行验算，并输出详细验算结果。

详细的验算流程说明请参考 [RBS.md](RBS.md) 文件。

## 功能特点

- 完整的AISC 358-16 Section 5.8验算流程
- 从AISC官方数据库CSV文件读取截面参数（289个W型钢）
- 支持命令行参数输入
- 详细的验算过程输出
- 自动验算各项限制条件
- 输出关键设计结果和验算通过/失败状态

## 文件说明

- `rbs_design.py` - 主程序文件
- `extract_shapes.py` - Excel数据提取脚本（生成CSV文件）
- `aisc_w_shapes.csv` - W型钢截面数据库（从AISC v16.0提取）
- `aisc-shapes-database-v160-2.xlsx` - AISC官方截面数据库
- `README.md` - 使用说明
- `RBS.md` - 详细的验算流程说明
- `AISC-358-16.md` - 规范原文

## 安装

需要Python 3.6或更高版本：

```bash
# 确保Python已安装
python --version

# 安装openpyxl库（用于读取Excel文件）
pip install openpyxl
```

## 使用方法

### 1. 列出所有可用截面

```bash
python rbs_design.py --list-sections
```

### 2. 使用截面数据库进行验算

```bash
# 基本用法 - 使用自动计算的RBS尺寸
python rbs_design.py --beam-section W30x99 --column-section W14x193 --span 360 --system-type SMF

# 指定RBS尺寸
python rbs_design.py --beam-section W30x99 --column-section W14x193 \
    --rbs-a 6 --rbs-b 22 --rbs-c 1.5 --span 360 --system-type SMF

# 带重力荷载
python rbs_design.py --beam-section W30x99 --column-section W14x193 \
    --rbs-a 6 --rbs-b 22 --rbs-c 1.5 --span 360 --system-type SMF \
    --load-D 20 --load-L 30 --load-S 10

# IMF系统
python rbs_design.py --beam-section W24x76 --column-section W14x193 \
    --system-type IMF --span 300
```

### 3. 使用自定义截面参数

当数据库中没有所需截面时，可以手动输入所有参数：

```bash
python rbs_design.py \
    --beam-d 30 --beam-bf 10.45 --beam-tf 0.615 --beam-tw 0.36 --beam-Zx 311 \
    --column-d 15.5 --column-bf 10.7 --column-tf 1.57 --column-tw 0.91 --column-Zx 361 \
    --rbs-a 6 --rbs-b 22 --rbs-c 1.5 \
    --span 360 --system-type SMF
```

### 4. 查看帮助信息

```bash
python rbs_design.py --help
```

## 参数说明

### 梁参数 (Beam Parameters)
| 参数 | 说明 | 单位 | 默认值 |
|------|------|------|--------|
| --beam-section | 梁截面型号（如W30x99） | - | - |
| --beam-d | 梁截面高度 | in | - |
| --beam-bf | 梁翼缘宽度 | in | - |
| --beam-tf | 梁翼缘厚度 | in | - |
| --beam-tw | 梁腹板厚度 | in | - |
| --beam-Zx | 梁塑性截面模量 | in³ | - |
| --beam-Fy | 梁屈服强度 | ksi | 50 |
| --beam-Ry | 梁材料超强系数 | - | 1.1 |

### 柱参数 (Column Parameters)
| 参数 | 说明 | 单位 | 默认值 |
|------|------|------|--------|
| --column-section | 柱截面型号（如W14x193） | - | - |
| --column-d | 柱截面高度 | in | - |
| --column-bf | 柱翼缘宽度 | in | - |
| --column-tf | 柱翼缘厚度 | in | - |
| --column-tw | 柱腹板厚度 | in | - |
| --column-Zx | 柱塑性截面模量 | in³ | - |
| --column-Fy | 柱屈服强度 | ksi | 50 |
| --column-Ry | 柱材料超强系数 | - | 1.1 |

### RBS几何参数 (RBS Geometry)
| 参数 | 说明 | 单位 | 默认值 |
|------|------|------|--------|
| --rbs-a | 柱面到削弱区起点的距离 | in | 0.625×bf |
| --rbs-b | 削弱区长度 | in | 0.75×d |
| --rbs-c | 削弱区中心深度 | in | 0.175×bf |

### 设计参数 (Design Parameters)
| 参数 | 说明 | 单位 | 默认值 |
|------|------|------|--------|
| --span | 梁跨度(中到中) | in | 360 |
| --Lh | 塑性铰间距 | in | 自动计算 |
| --system-type | 体系类型（必需） | - | - |
| --C-pr | 连接承载力系数 | - | 1.1 |

### 荷载参数 (Loads)
| 参数 | 说明 | 单位 | 默认值 |
|------|------|------|--------|
| --load-D | 恒载 | kips | 0 |
| --load-L | 活载 | kips | 0 |
| --load-S | 雪载 | kips | 0 |
| --load-f1 | 活载系数 | - | 0.5 |

## 截面数据库

程序使用AISC Shapes Database v16.0中的W型钢数据，包含289个截面：

- **数据来源**: AISC Shapes Database v16.0
- **覆盖范围**: W4到W44系列
- **提取脚本**: `extract_shapes.py`
- **数据文件**: `aisc_w_shapes.csv`

### 从Excel更新数据库

如果需要更新截面数据库：

```bash
# 运行提取脚本
python extract_shapes.py
```

这将读取`aisc-shapes-database-v160-2.xlsx`并生成`aisc_w_shapes.csv`文件。

### 2. 使用自定义截面参数

当数据库中没有所需截面时，可以手动输入所有参数：

```bash
python rbs_design.py \
    --beam-d 30 --beam-bf 10.45 --beam-tf 0.615 --beam-tw 0.36 --beam-Zx 311 \
    --column-d 15.5 --column-bf 10.7 --column-tf 1.57 --column-tw 0.91 --column-Zx 361 \
    --rbs-a 6 --rbs-b 22 --rbs-c 1.5 \
    --span 360
```

### 3. 查看帮助信息

```bash
python rbs_design.py --help
```

## 参数说明

### 梁参数 (Beam Parameters)
| 参数 | 说明 | 单位 | 默认值 |
|------|------|------|--------|
| --beam-section | 梁截面型号（如W30x99） | - | - |
| --beam-d | 梁截面高度 | in | - |
| --beam-bf | 梁翼缘宽度 | in | - |
| --beam-tf | 梁翼缘厚度 | in | - |
| --beam-tw | 梁腹板厚度 | in | - |
| --beam-Zx | 梁塑性截面模量 | in³ | - |
| --beam-Fy | 梁屈服强度 | ksi | 50 |
| --beam-Ry | 梁材料超强系数 | - | 1.1 |

### 柱参数 (Column Parameters)
| 参数 | 说明 | 单位 | 默认值 |
|------|------|------|--------|
| --column-section | 柱截面型号（如W14x193） | - | - |
| --column-d | 柱截面高度 | in | - |
| --column-bf | 柱翼缘宽度 | in | - |
| --column-tf | 柱翼缘厚度 | in | - |
| --column-tw | 柱腹板厚度 | in | - |
| --column-Zx | 柱塑性截面模量 | in³ | - |
| --column-Fy | 柱屈服强度 | ksi | 50 |
| --column-Ry | 柱材料超强系数 | - | 1.1 |

### RBS几何参数 (RBS Geometry)
| 参数 | 说明 | 单位 | 默认值 |
|------|------|------|--------|
| --rbs-a | 柱面到削弱区起点的距离 | in | 0.625×bf |
| --rbs-b | 削弱区长度 | in | 0.75×d |
| --rbs-c | 削弱区中心深度 | in | 0.175×bf |

### 设计参数 (Design Parameters)
| 参数 | 说明 | 单位 | 默认值 |
|------|------|------|--------|
| --span | 梁跨度(中到中) | in | 360 |
| --Lh | 塑性铰间距 | in | 自动计算 |
| --system-type | 体系类型（必需） | - | - |
| --C-pr | 连接承载力系数 | - | 1.1 |

### 荷载参数 (Loads)
| 参数 | 说明 | 单位 | 默认值 |
|------|------|------|--------|
| --load-D | 恒载 | kips | 0 |
| --load-L | 活载 | kips | 0 |
| --load-S | 雪载 | kips | 0 |
| --load-f1 | 活载系数 | - | 0.5 |

## 验算流程

程序按照AISC 358-16 Section 5.8的11个步骤进行验算：

| Step | 验算内容 | 说明 |
|------|----------|------|
| 1 | RBS几何尺寸验算 | 验证a, b, c是否满足规范限制 |
| 2 | 计算削弱截面塑性模量 | Z_RBS = Z_x - 2×c×t_bf×(d - t_bf) |
| 3 | 计算可能最大弯矩 | M_pr = C_pr × R_y × F_y × Z_RBS |
| 4 | 计算RBS处剪力 | V_RBS = 2×M_pr/L_h + V_gravity |
| 5 | 计算柱面处弯矩 | M_f = M_pr + V_RBS × S_h |
| 6 | 计算梁塑性弯矩 | M_pe = R_y × F_y × Z_x |
| 7 | 柱面处抗弯验算 | M_f ≤ φ_d × M_pe |
| 8 | 抗剪验算 | V_u ≤ φ_v × V_n |
| 9 | 梁腹板连接设计 | SMF: CJP焊 / IMF: 螺栓或焊 |
| 10 | 连续板要求 | 参考Chapter 2 |
| 11 | 柱梁关系验算 | 强柱弱梁验算 |

详细的验算流程请参考 [RBS.md](RBS.md) 文件。

## 输出示例

```
================================================================================
  RBS MOMENT CONNECTION DESIGN VERIFICATION (AISC 358-16)
================================================================================

================================================================================
  INPUT PARAMETERS
================================================================================
BEAM SECTION:
  Designation: W30x99
  Depth (d): 30.0 in
  Flange width (bf): 10.45 in
  Flange thickness (tf): 0.615 in
  Web thickness (tw): 0.36 in
  Plastic modulus (Zx): 311 in³
  ...

--------------------------------------------------------------------------------
  STEP 1: RBS GEOMETRY LIMITS CHECK
--------------------------------------------------------------------------------
AISC 358-16 Equation 5.8-1: 0.5*bf <= a <= 0.75*bf
  Required: 5.225 <= a <= 7.837 in
  Provided: a = 6.000 in
  ✓ OK - a is within acceptable range
  ...

================================================================================
  DESIGN VERIFICATION SUMMARY
================================================================================
CHECKS SUMMARY:
  Equation 5.8-1 (a limits): ✓ PASS
  Equation 5.8-2 (b limits): ✓ PASS
  Equation 5.8-3 (c limits): ✓ PASS
  Flexural strength at column face (Eq. 5.8-8): ✓ PASS
    Utilization: 0.95
  Shear strength: ✓ PASS
    Utilization: 0.40

================================================================================
  ✓ ALL CHECKS PASSED - RBS CONNECTION DESIGN IS ADEQUATE
================================================================================
```

## 截面数据库覆盖范围

从AISC v16.0数据库中提取了289个W型钢截面，包括：

| 系列 | 深度范围 | 重量范围 | 截面数量 |
|------|----------|----------|----------|
| W44 | 43.3-44.8 in | 230-408 plf | 6 |
| W40 | 38.6-43.6 in | 167-655 plf | 18 |
| W36 | 35.5-38.0 in | 135-279 plf | 9 |
| W33 | 33.1-37.8 in | 118-354 plf | 13 |
| W30 | 29.5-34.9 in | 90-391 plf | 16 |
| W27 | 26.7-27.3 in | 84-114 plf | 4 |
| W24 | 23.7-24.7 in | 68-117 plf | 6 |
| W21 | 20.7-24.4 in | 44-284 plf | 22 |
| W18 | 18.0-19.0 in | 50-119 plf | 7 |
| W16 | 15.7-18.3 in | 40-100 plf | 11 |
| W14 | 13.7-23.6 in | 61-873 plf | 48 |
| W12 | 11.9-16.8 in | 14-336 plf | 29 |
| W10 | 9.9-10.8 in | 12-88 plf | 18 |
| W8 | 7.9-9.0 in | 10-67 plf | 12 |
| W6 | 5.8-6.3 in | 8.5-25 plf | 7 |
| W5 | 5.0-5.2 in | 16-19 plf | 2 |
| W4 | 4.2 in | 8-13 plf | 2 |

使用 `--list-sections` 选项查看完整列表。

## 注意事项

1. **单位**: 程序使用美制单位 (inches, kips, ksi)
2. **RBS尺寸**: 如果不指定，程序会自动计算（取范围中间值）
3. **Lh计算**: 如果不指定，Lh = L - 2×(a + b/2)
4. **抗力系数**: φ_d = 0.9 (抗弯), φ_v = 0.9 (抗剪)
5. **退出码**: 验算全部通过返回0，有失败项返回1

## 设计建议

### RBS尺寸选择

| 参数 | 推荐值 | 范围 |
|------|--------|------|
| a | 0.625×bf | 0.5~0.75×bf |
| b | 0.75×d | 0.65~0.85×d |
| c | 0.175×bf | 0.1~0.25×bf |

### 材料参数

| 材料 | Fy (ksi) | Ry |
|------|----------|-----|
| A36 | 36 | 1.5 |
| A992 | 50 | 1.1 |
| A572-50 | 50 | 1.1 |

### 常见问题

**1. 抗弯验算不通过 (M_f > φ_d×M_pe)**
- 减小c值（减小削弱深度）
- 减小a值（减小力臂）
- 增大梁截面

**2. 抗剪验算不通过 (V_u > φ_v×V_n)**
- 增大梁截面
- 增大腹板厚度

**3. RBS几何不满足限制**
- 检查输入参数是否在允许范围内
- 调整RBS尺寸

## 规范参考

- AISC 358-16: Prequalified Connections for Special and Intermediate Steel Moment Frames for Seismic Applications
- AISC 360-16: Specification for Structural Steel Buildings
- AISC 341-16: Seismic Provisions for Structural Steel Buildings

## 项目文件

- `rbs_design.py` - 主程序文件
- `RBS.md` - 详细的验算流程说明
- `AISC-358-16.md` - AISC 358-16规范原文

## 许可证

MIT License

## 更新日志

### v1.0.0 (2026-04-25)
- 初始版本
- 完整的AISC 358-16 Section 5.8验算流程
- 内置常用型钢截面数据库
- 命令行参数支持
