from typing import List, Optional, Literal
from enum import Enum
from pydantic import BaseModel, Field

# --- 1. 核心枚举 (用于路由和优先级) ---

class ScientificDomain(str, Enum):
    """
    科学领域分类，用于 LangGraph 的顶级路由 (Top-level Routing)。
    """
    # --- 生命科学类 ---
    BIOLOGY = "biology"               # 基因、蛋白、细胞、生态
    MEDICINE = "medicine"             # 临床、药理、病理、影像
    
    # --- 物质科学类 ---
    CHEMISTRY = "chemistry"           # 合成、分析、化工
    PHYSICS = "physics"               # 力学、光学、量子、粒子
    MATERIALS_SCIENCE = "materials"   # 晶体、纳米材料、半导体
    
    # --- 地球与空间 ---
    EARTH_SCIENCE = "earth_science"   # 地质、气象、环境科学
    ASTRONOMY = "astronomy"           # 天文、天体物理
    
    # --- 形式科学与工具 ---
    MATHEMATICS = "mathematics"       # 纯数、应用数学、符号计算
    DATA_SCIENCE = "data_science"     # 纯粹的数据分析、统计、绘图（不依赖特定领域知识）
    COMPUTER_SCIENCE = "cs"           # 算法设计、代码生成、系统架构
    
    # --- 特殊类型 ---
    LITERATURE_RESEARCH = "literature" # 纯文献调研任务（不涉及计算或推理）
    INTERDISCIPLINARY = "interdisciplinary" # 跨学科/多模态任务（需要 Orchestrator 拆解）
    OTHER = "other"                   # 无法分类

class Priority(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"

# --- 2. 紧凑组件 ---

class DataArtifact(BaseModel):
    """统一输入/输出的数据实体描述"""
    name: str = Field(..., description="数据名称/概念，如 'GWAS汇总统计量'")
    specification: str = Field(..., description="格式或约束说明，如 'CSV格式，包含P值列'")
    is_mandatory: bool = Field(True, description="是否为必须项")

class TaskConstraint(BaseModel):
    """用户的显式约束（工具偏好、方法限定）"""
    constraint: str = Field(..., description="具体的约束条件，如 '必须使用AlphaFold2' 或 '置信度需>90%'")
    type: Literal["Method", "Tool", "Resource"] = Field(..., description="约束类型")

class SubGoal(BaseModel):
    """简化的子目标"""
    description: str = Field(..., description="子任务的简明描述")
    priority: Priority = Field(Priority.MEDIUM, description="执行优先级")

# --- 3. 主输出模型 (LangGraph State 的核心载荷) ---

class IntentSchema(BaseModel):
    """
    通用科学 Agent 的意图理解标准输出。
    设计目标：轻量、可路由、为 Planner 提供核心上下文。
    """
    
    # 1. 领域路由核心 (Router Key)
    domain: str = Field(description="简短描述意图涉及的主题领域")

    # 2. 目标定义
    summary: str = Field(..., description="用户意图的一句话总结")
    core_objective: str = Field(..., description="清晰定义的科学任务目标（What to do）")
    
    # 3. 初步分解 (为 Planner 提供参考，不必过度详细)
    key_steps: List[SubGoal] = Field(
        default_factory=list, 
        description="识别出的关键步骤或子目标列表"
    )

    # 4. 数据契约 (I/O Contract)
    inputs: List[DataArtifact] = Field(
        default_factory=list, 
        description="任务执行所需的关键输入数据，禁止出现具体数据内容，只需描述其格式和要求"
    )
    outputs: List[DataArtifact] = Field(
        default_factory=list, 
        description="用户期望的交付物"
    )

    # 5. 边界与约束 (Constraints)
    constraints: List[TaskConstraint] = Field(
        default_factory=list, 
        description="用户指定的特殊方法、工具或资源限制"
    )

    # 6. 人在回路 (Human-in-the-loop)
    ambiguities: List[str] = Field(
        default_factory=list, 
        description="阻碍任务进行的模糊点，需要反问用户的问题列表"
    )

    # 7. 元数据
    confidence: float = Field(..., description="意图理解置信度 0-1")
    reasoning: str = Field(..., description="简短的思维链：为什么归为此领域？为什么需要这些输入？")