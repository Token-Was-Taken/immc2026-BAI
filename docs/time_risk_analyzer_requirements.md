# 时序风险对比分析脚本 - 需求文档

## 1. 项目概述

### 1.1 项目名称
`time_risk_analyzer.py` - 时序风险对比分析工具

### 1.2 项目目标
开发一个命令行脚本，一键分析四种时间组合（Day/DRY、Day/RAINY、Night/DRY、Night/RAINY）的风险热力图，输出独立的归一化/原始风险热力图以及四象限对比图。

### 1.3 用户场景
- 研究人员需要对比不同时段和季节的风险分布差异
- 野生动物保护管理者需要了解全年的风险变化规律
- 优化资源部署前需要进行全面的风险评估

## 2. 功能需求

### 2.1 核心功能

#### F1: 四场景风险计算
- 输入：单个 input JSON 文件（基础地图和物种配置）
- 自动生成四种时间组合：
  - Day + DRY（白天旱季）
  - Day + RAINY（白天雨季）
  - Night + DRY（夜间旱季）
  - Night + RAINY（夜间雨季）
- 对每种组合计算：
  - 归一化风险热力图
  - 原始风险热力图

#### F2: 输出文件生成
每个场景生成两个文件：
- `{场景标识}_normalized_risk.png` - 归一化风险热力图
- `{场景标识}_raw_risk.png` - 原始风险热力图

场景标识格式：`{hour}_{season}`，例如 `day_dry`、`night_rainy`

#### F3: 四象限对比图
- 布局：2x2 网格
  - 左上：Day + DRY
  - 右上：Day + RAINY
  - 左下：Night + DRY
  - 右下：Night + RAINY
- 颜色尺：统一使用原始风险值
- 颜色尺范围：[0, max_raw_risk]，其中 max_raw_risk 为四个场景中原始风险最大值

#### F4: 命令行参数支持
- 输入 JSON 路径（必填）
- 输出目录（可选，默认 `./time_risk_analysis`）
- 颜色尺范围（可选，自动计算）
- 图片 DPI（可选，默认 150）
- grid_dpi（可选，自动计算）

### 2.2 输出文件清单

```
{out_dir}/
├── day_dry_normalized_risk.png      # 白天旱季 - 归一化风险
├── day_dry_raw_risk.png             # 白天旱季 - 原始风险
├── day_rainy_normalized_risk.png     # 白天雨季 - 归一化风险
├── day_rainy_raw_risk.png           # 白天雨季 - 原始风险
├── night_dry_normalized_risk.png    # 夜间旱季 - 归一化风险
├── night_dry_raw_risk.png           # 夜间旱季 - 原始风险
├── night_rainy_normalized_risk.png  # 夜间雨季 - 归一化风险
├── night_rainy_raw_risk.png         # 夜间雨季 - 原始风险
├── risk_comparison_4panel.png       # 四象限原始风险对比图
└── time_risk_summary.txt            # 分析摘要（可选）
```

### 2.3 性能需求
- 单个场景风险计算时间 < 5 秒
- 四个场景 + 对比图总生成时间 < 30 秒
- 支持的最大网格数：无限制（受限于内存）

## 3. 数据需求

### 3.1 输入数据
- 基础地图配置（网格、地形、道路、水源等）
- 物种配置（权重、季节系数）
- 资源约束（可选，用于风险计算）
- 风险模型参数（从输入 JSON 读取，使用默认值）

### 3.2 输出数据
- PNG 格式的热力图图片
- 统一的六边形网格可视化
- 包含颜色条和图例

## 4. 用户交互需求

### 4.1 命令行接口
```bash
python time_risk_analyzer.py input.json
python time_risk_analyzer.py input.json -o ./output
python time_risk_analyzer.py input.json --dpi 200 --grid_dpi 100
```

### 4.2 错误处理
- 输入文件不存在：提示错误并退出
- 输入 JSON 格式错误：提示具体错误位置
- 缺少必需字段：使用默认值或提示警告

### 4.3 输出信息
- 进度提示（当前处理的场景）
- 计算完成后的统计信息
- 输出文件路径列表

## 5. 验收标准

### 5.1 功能验收
- [ ] 输入单个 JSON 文件，输出 9 个 PNG 文件
- [ ] 四个场景的归一化风险图颜色范围一致 [0, 1]
- [ ] 四象限对比图使用统一的颜色尺
- [ ] 颜色尺上界为四个场景中原始风险最大值

### 5.2 质量验收
- [ ] 热力图清晰可读（六边形网格可见）
- [ ] 颜色条显示正确
- [ ] 图片尺寸适合地图大小
- [ ] 无内存泄漏

### 5.3 性能验收
- [ ] 10x12 网格地图：< 10 秒完成
- [ ] 50x60 网格地图：< 60 秒完成

## 6. 依赖项

### 6.1 Python 包
- `matplotlib` >= 3.5.0
- `numpy` >= 1.21.0
- `argparse` (标准库)

### 6.2 内部模块
- `grid_model.py` - 网格模型
- `risk_calculator.py` - 风险计算
- `visualize_output.py` - 可视化工具

## 7. 限制与约束

### 7.1 输入约束
- 输入 JSON 必须包含基础地图配置
- 网格必须使用六边形坐标系统
- 物种配置中必须包含 weight 字段

### 7.2 输出约束
- 图片格式：PNG
- 坐标系：保持与输入一致的六边形轴坐标系
- 文件命名：固定的场景标识格式
