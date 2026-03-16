"""
Sandbox执行环境提示词
用于execute node,告诉agent如何在sandbox中保存文件和使用Bash命令
"""

SANDBOX_EXECUTION_PROMPT = """
## 🔧 Sandbox执行环境说明

你的代码在隔离的AIO Sandbox环境中运行。

### 📁 文件系统结构
```
/home/work/
├── workspace/     # 临时工作区(可读写)
├── uploads/       # 用户上传的文件(只读)
├── outputs/       # 持久化输出文件(可写)
└── tools/         # 工具代码目录(只读)
```

### 💾 文件保存决策规则(CRITICAL)

**大多数结果应直接 `print()` 输出，只有以下三类才需要保存到 `/home/work/outputs/`：**

| 内容类型 | 处理方式 | 示例 |
|---------|---------|------|
| 📊 **图表/图片** | ✅ 必须保存为图片文件 | `.png`, `.jpg`, `.svg` |
| 📄 **长文本报告** (>500字) | ✅ 保存为 `.md` 文件 | 分析报告、方法说明 |
| 🗄️ **结构化数据集** | ✅ 保存为 `.csv`/`.xlsx` | 大型数据表格 |
| 💬 **简短结果/数值/状态** | ❌ **直接 print()，禁止保存** | 计算结果、查询结果、布尔值 |

**禁止保存的场景（直接 print 即可）：**
```python
# ❌ 错误：把简单结果写成txt文件
with open('/home/work/outputs/result.txt', 'w') as f:
    f.write("浮力 = 9.8 N")

# ✅ 正确：直接打印
print("浮力 = 9.8 N")
print(f"结果: {value}")
```

### ✅ 需要保存的示例

```python
<execute>
import matplotlib.pyplot as plt

# 图表 → 必须保存
plt.figure(figsize=(10, 6))
plt.plot(x, y)
plt.savefig('/home/work/outputs/chart.png', dpi=300)
print("图表已保存: /home/work/outputs/chart.png")
</execute>
```

```python
<execute>
import pandas as pd

# 大型数据集 → 保存为csv
df.to_csv('/home/work/outputs/result.csv', index=False)
print(f"数据已保存: {len(df)} 行")
</execute>
```

```python
<execute>
# 长文本报告（>500字）→ 保存为md
report = "# 分析报告\\n\\n## 方法\\n..."  # 大段内容
with open('/home/work/outputs/report.md', 'w') as f:
    f.write(report)
print("报告已保存: /home/work/outputs/report.md")
</execute>
```

### ⚠️ 重要限制

1. **禁止文件操作工具**: 不要使用`upload_content_to_minio`等文件上传工具
2. **路径规范**: 使用绝对路径 `/home/work/outputs/`，不要使用相对路径
3. **文件命名**: 有意义的英文文件名，避免中文和特殊字符
4. **禁止保存**: 普通文本结果、数值、状态信息 → 直接 print()

### 🐚 Bash命令支持

Sandbox完全支持Bash命令: `ls`, `cat`, `grep`, `wget`, `curl`, `tar`, `pip` 等。
"""


def get_sandbox_execution_prompt() -> str:
    """
    获取sandbox执行环境提示词

    Returns:
        完整的sandbox提示词
    """
    return SANDBOX_EXECUTION_PROMPT
