      
# 标准库
import os
import io
import time
import subprocess
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any

# 第三方科学计算库
import numpy as np
import pandas as pd
from scipy import ndimage, stats
from scipy.optimize import minimize, differential_evolution
from scipy.integrate import solve_ivp, odeint
import matplotlib.pyplot as plt
from matplotlib import cm


# 异步请求
import aiohttp
import requests
from io import BytesIO

# RNA 二级结构库（ViennaRNA Python 接口）

#import RNA  #python版本问题

# LangChain工具
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool
from workflow.const import Tools

# 自定义上传工具
from workflow.utils.minio_utils import upload_content_to_minio


# 测试成功
#我有一个水样品，编号 S1。保留时间和信号强度数据如下：2.1 分钟 → 1520，3.4 分钟 → 890，5.2 分钟 → 430。请用 HPLC-ICP-MS 做砷形态分析，不提供校准数据，直接用默认设置
class ArsenicSpeciationInput(BaseModel):
    sample_data: Dict[str, Dict[float, float]] = Field(
        ..., description="样品数据，格式：{sample_id: {retention_time(min): signal_intensity}}"
    )
    sample_name: Optional[str] = Field(
        "Unknown Sample", description="样品名称 (默认: Unknown Sample)"
    )
    calibration_data: Optional[Dict[str, Dict[str, float]]] = Field(
        None, description="校准数据，格式：{species: {factor: float, limit: float}}；若为 None 则使用默认值"
    )
    

async def analyze_arsenic_speciation_hplc_icpms_coroutine(
    sample_data: Dict[str, Dict[float, float]],
    sample_name: str = "Unknown Sample",
    calibration_data: Optional[Dict[str, Dict[str, float]]] = None,
  
) -> Dict[str, Any]:
    
    log = f"# Arsenic Speciation Analysis by HPLC-ICP-MS\n"
    log += f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    log += f"Sample: {sample_name}\n\n"

    log += "## 1. Sample Preparation\n"
    log += "- Filtered through 0.45 μm filter, diluted if necessary, injected into HPLC\n\n"
    log += "## 2. HPLC-ICP-MS Analysis\n"
    log += "- Column: Anion exchange, Mobile phase: 20 mM NH4H2PO4 (pH 6.0), Flow: 1 mL/min, ICP-MS m/z 75\n\n"

    arsenic_species = {
        'As(III)': 2.8, 'As(V)': 7.5,
        'MMAs(III)': 3.9, 'MMAs(V)': 6.2,
        'DMAs(III)': 4.7, 'DMAs(V)': 5.3
    }

    if calibration_data is None:
        calibration_data = {
            'As(III)': {'factor': 0.85, 'limit': 0.1},
            'As(V)': {'factor': 0.92, 'limit': 0.1},
            'MMAs(III)': {'factor': 0.78, 'limit': 0.2},
            'MMAs(V)': {'factor': 0.88, 'limit': 0.15},
            'DMAs(III)': {'factor': 0.81, 'limit': 0.2},
            'DMAs(V)': {'factor': 0.90, 'limit': 0.15}
        }

    results = {}
    for sample_id, sample in sample_data.items():
        species_conc = {}
        for sp, expected_rt in arsenic_species.items():
            closest_rt = min(sample.keys(), key=lambda rt: abs(rt - expected_rt))
            if abs(closest_rt - expected_rt) <= 0.3:
                intensity = sample[closest_rt]
                conc = intensity * calibration_data[sp]['factor']
                if conc >= calibration_data[sp]['limit']:
                    species_conc[sp] = conc
                else:
                    species_conc[sp] = f"<{calibration_data[sp]['limit']} (Below detection limit)"
            else:
                species_conc[sp] = "Not detected"
        results[sample_id] = species_conc

    results_df = pd.DataFrame.from_dict(results, orient="index")

    # Upload CSV
    buf = io.StringIO()
    results_df.to_csv(buf)
    buf.seek(0)
    csv_url = await upload_content_to_minio(
        content=buf.getvalue().encode("utf-8"),
        file_name=f"arsenic_speciation_results_{sample_name.replace(' ','_')}.csv",
        file_extension=".csv",
        content_type="text/csv",
        no_expired=True
    )

    log += "## 5. Results\n"
    log += f"Detected arsenic species saved in CSV file: {csv_url}\n\n"
    log += "## 6. Summary\n"
    for sid, spdata in results.items():
        numeric_concs = {k: v for k, v in spdata.items() if isinstance(v, (int, float))}
        if numeric_concs:
            predom = max(numeric_concs.items(), key=lambda x: x[1])
            log += f"- Sample {sid}: Predominant species {predom[0]} at {predom[1]:.2f} μg/L\n"
        else:
            log += f"- Sample {sid}: No arsenic species detected above quantification limits\n"

    return {
        "research_log": log,
        "results_csv_url": csv_url
    }

analyze_arsenic_speciation_hplc_icpms_tool = StructuredTool.from_function(
    name=Tools.analyze_arsenic_speciation_hplc_icpms,
description="""
    【领域：生物】
        "使用 HPLC-ICP-MS 对液体样品中的砷进行形态分析。\n\n"
        "输入：样品信号字典和可选的校准数据。\n"
        "返回：\n"
        "- research_log: 分析日志\n"
        "- results_csv_url: 含各形态砷浓度的结果 CSV 链接"
    """,
    args_schema=ArsenicSpeciationInput,
    coroutine=analyze_arsenic_speciation_hplc_icpms_coroutine,
    metadata={"args_schema_json": ArsenicSpeciationInput.schema()}
)




# 测试成功
#我有 1 mL 的细菌样本，初步估计浓度约 1×10⁸ CFU/mL，请用连续稀释和点样法进行 CFU 测定，稀释倍数 10，每个稀释梯度点样 3 次，稀释 8 次。请生成实验日志并输出 CSV 结果
class EnumerateCFUInput(BaseModel):
    initial_sample_volume_ml: float = Field(
        1.0, description="初始细菌样本体积 (mL)"
    )
    estimated_concentration: float = Field(
        1e8, description="样本估计初始浓度 (CFU/mL)"
    )
    dilution_factor: int = Field(
        10, description="每次稀释的倍数 (通常为10)"
    )
    num_dilutions: int = Field(
        8, description="稀释次数"
    )
    spots_per_dilution: int = Field(
        3, description="每个稀释梯度的点样数"
    )
    output_file: Optional[str] = Field(
        "cfu_enumeration_results.csv", description="输出结果CSV文件名 (上传后返回URL)"
    )

async def enumerate_cfu_coroutine(
    initial_sample_volume_ml: float = 1.0,
    estimated_concentration: float = 1e8,
    dilution_factor: int = 10,
    num_dilutions: int = 8,
    spots_per_dilution: int = 3,
    output_file: str = "cfu_enumeration_results.csv"
) -> Dict[str, Any]:
    """
    通过连续稀释与点样平板计数，估算细菌原始样本浓度 (CFU/mL)。
    """
    # ===== 日志初始化 =====
    log = "# Bacterial CFU Enumeration via Serial Dilutions and Spot Plating\n\n"
    log += "## Step 1: Serial Dilution Preparation\n"
    log += f"- Initial sample volume: {initial_sample_volume_ml} mL\n"
    log += f"- Estimated concentration: {estimated_concentration:.2e} CFU/mL\n"
    log += f"- Dilution factor: {dilution_factor}\n"
    log += f"- Number of dilutions: {num_dilutions}\n\n"

    # ===== 计算稀释浓度 =====
    dilution_concentrations = []
    for i in range(num_dilutions + 1):
        conc = estimated_concentration / (dilution_factor ** i)
        dilution_concentrations.append(conc)
        dilution_name = "Undiluted" if i == 0 else f"10^-{i}"
        log += f"  {dilution_name}: {conc:.2e} CFU/mL\n"

    # ===== 点样实验模拟 =====
    log += "\n## Step 2: Spot Plating\n"
    log += f"- Spots per dilution: {spots_per_dilution}\n"
    log += "- Spotting 10 μL from each dilution onto agar plates\n\n"

    np.random.seed(42)
    results = []

    for i in range(num_dilutions + 1):
        dilution_name = "Undiluted" if i == 0 else f"10^-{i}"
        expected_cfu_per_spot = dilution_concentrations[i] * 0.01  # 10 μL

        for spot in range(spots_per_dilution):
            if expected_cfu_per_spot > 300:
                count = "TMTC"
            elif expected_cfu_per_spot < 1:
                count = np.random.poisson(expected_cfu_per_spot)
            else:
                count = np.random.poisson(expected_cfu_per_spot)

            results.append({
                "Dilution": dilution_name,
                "Dilution_Factor": dilution_factor ** i,
                "Spot": spot + 1,
                "CFU_Count": count
            })

    df = pd.DataFrame(results)

    # ===== 统计 CFU/mL =====
    log += "## Step 3: Colony Counting and CFU Calculation\n\n"
    countable_dilutions = []

    for i in range(num_dilutions + 1):
        dilution_name = "Undiluted" if i == 0 else f"10^-{i}"
        dilution_data = df[df["Dilution"] == dilution_name]
        numeric_counts = [c for c in dilution_data["CFU_Count"] if isinstance(c, (int, float))]

        if numeric_counts:
            avg_count = sum(numeric_counts) / len(numeric_counts)
            if 3 <= avg_count <= 300:
                countable_dilutions.append({
                    "Dilution": dilution_name,
                    "Dilution_Factor": dilution_factor ** i,
                    "Average_CFU": avg_count,
                    "CFU_per_mL": avg_count * 100 * (dilution_factor ** i)  # ×100 转换 10 μL → mL
                })

    if countable_dilutions:
        countable_df = pd.DataFrame(countable_dilutions)
        for _, row in countable_df.iterrows():
            log += f"Dilution {row['Dilution']}: Average CFU per spot = {row['Average_CFU']:.1f}\n"
            log += f"  Calculated concentration: {row['CFU_per_mL']:.2e} CFU/mL\n\n"

        final_cfu = countable_df["CFU_per_mL"].mean()
        log += f"## Final Result\n"
        log += f"Original sample concentration: {final_cfu:.2e} CFU/mL\n"
    else:
        log += "No countable dilutions found. Consider adjusting the dilution series.\n"

    # ===== 上传结果 =====
# ===== 上传结果 =====
    csv_bytes = df.to_csv(index=False).encode("utf-8")  # 建议转成 bytes
    csv_url = await upload_content_to_minio(csv_bytes, output_file)

    return {
        "research_log": log,
        "result_csv_url": csv_url
    }

enumerate_cfu_tool = StructuredTool.from_function(
    name=Tools.enumerate_bacterial_cfu_by_serial_dilution,
    description="""
    【领域：生物】
        "使用连续稀释和点样法定量测定细菌浓度（CFU/mL）。\n\n"
        "返回：\n"
        "- research_log: 实验操作和计算完整日志\n"
        "- results_csv_url: 含每个稀释梯度 CFU 计算结果的 CSV 文件链接"
""",
    args_schema=EnumerateCFUInput,
    coroutine=enumerate_cfu_coroutine,
    metadata={"args_schema_json": EnumerateCFUInput.schema()}
)



#测试成功
# 我想模拟一种高生长率菌株，初始数量 5000 个细胞，生长率 1.2 /小时，清除率 0.1 /小时，生态位容量 5×10⁷ 个细胞。模拟时间设为 12 小时，每 0.05 小时输出一次结果; 使用“模拟细菌生长动力学”工具。
class BacterialGrowthDynamicsInput(BaseModel):
    initial_population: float = Field(..., description="Initial bacterial population size (CFU/ml or cells)")
    growth_rate: float = Field(..., description="Bacterial growth rate (per hour)")
    clearance_rate: float = Field(..., description="Rate at which bacteria are cleared from the system (per hour)")
    niche_size: float = Field(..., description="Maximum carrying capacity of the environment (CFU/ml or cells)")
    simulation_time: Optional[float] = Field(24, description="Total simulation time in hours (default: 24)")
    time_step: Optional[float] = Field(0.1, description="Time step for simulation output (default: 0.1)")
    
async def model_bacterial_growth_dynamics_coroutine(
    initial_population: float,
    growth_rate: float,
    clearance_rate: float,
    niche_size: float,
    simulation_time: float = 24,
    time_step: float = 0.1,
    
) -> Dict[str, Any]:
 
    # Define ODE system
    def bacterial_dynamics(t, N):
        return growth_rate * N * (1 - N / niche_size) - clearance_rate * N

    # Time points
    t_span = (0, simulation_time)
    t_eval = np.arange(0, simulation_time + time_step, time_step)

    # Solve ODE
    solution = solve_ivp(
        bacterial_dynamics,
        t_span,
        [initial_population],
        t_eval=t_eval,
        method='RK45'
    )

    # Extract results
    time_points = solution.t
    population_size = solution.y[0]

    # Metrics
    max_population = np.max(population_size)
    final_population = population_size[-1]

    last_index = int(len(population_size) * 0.9)
    population_change = abs(population_size[-1] - population_size[last_index]) / population_size[last_index]
    steady_state_reached = population_change < 0.01

    # Save results CSV
    results_df = pd.DataFrame({
        'Time (hours)': time_points,
        'Population Size': population_size
    })

    buffer = io.StringIO()
    results_df.to_csv(buffer, index=False)
    csv_url = await upload_content_to_minio(
        content=buffer.getvalue().encode("utf-8"),
        file_name="bacterial_growth_dynamics.csv",
        file_extension=".csv",
        content_type="text/csv",
        no_expired=True
    )

    # Research log
    log = f"""# Bacterial Growth Dynamics Simulation
        **Initial conditions:**
        - Starting population: {initial_population:.2e} cells
        - Growth rate: {growth_rate:.2f} per hour
        - Clearance rate: {clearance_rate:.2f} per hour
        - Niche size (carrying capacity): {niche_size:.2e} cells
        - Simulation time: {simulation_time} hours

        **Results:**
        - Maximum population reached: {max_population:.2e} cells
        - Final population: {final_population:.2e} cells
        - Steady state {"reached ✅" if steady_state_reached else "not reached ❌"}

        Complete population dynamics data saved to CSV file (URL below).
        """

    return {
        "research_log": log,
        "results_csv_url": csv_url
    }

model_bacterial_growth_dynamics_tool = StructuredTool.from_function(
    name=Tools.simulate_bacterial_growth_dynamics,
description="""
    【领域：生物】
        "模拟细菌种群在特定环境中的动态变化，考虑生长率、清除率和生态位容量。\n\n"
        "返回：\n"
        " - research_log: 模拟日志（文本）\n"
        " - results_csv_url: 种群动态模拟数据的 CSV 链接"
    """,
    args_schema=BacterialGrowthDynamicsInput,
    coroutine=model_bacterial_growth_dynamics_coroutine,
    metadata={"args_schema_json": BacterialGrowthDynamicsInput.schema()}
)



# 测试成功
# 我有三个样本的结晶紫法 OD 测定值：0.12, 0.85, 0.95。请用第一个样本作为阴性对照，量化生物膜生物量，并生成结果 CSV 文件。
class BiofilmBiomassInput(BaseModel):
    od_values: List[float] = Field(..., description="Optical density (OD) measurements from crystal violet staining assay")
    sample_names: Optional[List[str]] = Field(None, description="Names of the biofilm samples corresponding to OD values")
    control_index: Optional[int] = Field(0, description="Index of the negative control sample (default: 0)")
    
async def quantify_biofilm_biomass_crystal_violet_coroutine(
    od_values: List[float],
    sample_names: Optional[List[str]] = None,
    control_index: int = 0,
    
) -> Dict[str, Any]:


    # Initialize research log
    log = "## Biofilm Biomass Quantification using Crystal Violet Staining\n"
    log += f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    # Convert input to numpy array
    od_values = np.array(od_values, dtype=float)

    # Generate sample names if not provided
    if sample_names is None:
        sample_names = [f"Sample {i+1}" for i in range(len(od_values))]

    log += "### Samples Analyzed:\n"
    for i, name in enumerate(sample_names):
        log += f"- {name}: OD = {od_values[i]:.4f}\n"

    # Normalize by subtracting control
    control_value = od_values[control_index]
    normalized_values = od_values - control_value

    log += f"\n### Normalization:\n"
    log += f"- Control sample: {sample_names[control_index]} (OD = {control_value:.4f})\n"
    log += "- Normalized values (Control subtracted):\n"
    for i, name in enumerate(sample_names):
        if i != control_index:
            log += f"  - {name}: {normalized_values[i]:.4f}\n"

    # Statistical analysis
    mean_biomass = np.mean(normalized_values[normalized_values > 0]) if np.any(normalized_values > 0) else 0
    std_biomass = np.std(normalized_values[normalized_values > 0]) if np.any(normalized_values > 0) else 0

    log += f"\n### Statistical Analysis:\n"
    log += f"- Mean normalized biomass: {mean_biomass:.4f}\n"
    log += f"- Standard deviation: {std_biomass:.4f}\n"

    # Perform t-test for samples vs control
    log += "\n### Statistical Significance:\n"
    for i, name in enumerate(sample_names):
        if i != control_index:
            t_stat, p_val = stats.ttest_1samp([normalized_values[i]], 0)
            significance = "significant" if p_val < 0.05 else "not significant"
            log += f"- {name} vs Control: p-value = {p_val:.4f} ({significance})\n"

    # Create results dataframe
    results_df = pd.DataFrame({
        'Sample': sample_names,
        'OD_Value': od_values,
        'Normalized_Value': normalized_values
    })

    # Save CSV buffer
    buffer = io.StringIO()
    results_df.to_csv(buffer, index=False)
    csv_url = await upload_content_to_minio(
        content=buffer.getvalue().encode("utf-8"),
        file_name="biofilm_biomass_results.csv",
        file_extension=".csv",
        content_type="text/csv",
        no_expired=True
    )

    # Add conclusion
    log += "\n### Conclusion:\n"
    log += "- Crystal violet staining assay successfully quantified biofilm biomass.\n"
    log += f"- Samples showed varying levels of biofilm formation with mean biomass of {mean_biomass:.4f} ± {std_biomass:.4f}.\n"

    return {
        "research_log": log,
        "results_csv_url": csv_url
    }

quantify_biofilm_biomass_crystal_violet_tool = StructuredTool.from_function(
    name=Tools.quantify_biofilm_biomass_crystal_violet,
description="""
    【领域：生物】
        "利用结晶紫染色法的 OD 数据量化生物膜生物量。\n\n"
        "返回：\n"
        " - research_log: 分析日志，包含样本信息、归一化、统计显著性\n"
        " - results_csv_url: 含 OD 和归一化值的结果 CSV 链接"
    """,
    args_schema=BiofilmBiomassInput,
    coroutine=quantify_biofilm_biomass_crystal_violet_coroutine,
    metadata={"args_schema_json": BiofilmBiomassInput.schema()}
)



# 测试成功
# 我想用 gLV 模型模拟一个细菌种群的生长。初始丰度为 0.1，生长率为 0.5，相互作用矩阵为 [[0]]。请在 0 到 24 小时之间，每隔 1 小时计算一次丰度。
class GLVSimulationInput(BaseModel):
    initial_abundances: List[float] = Field(..., description="Initial abundances of each microbial species (1D list)")
    growth_rates: List[float] = Field(..., description="Intrinsic growth rates for each microbial species (1D list)")
    interaction_matrix: List[List[float]] = Field(..., description="Interaction matrix (2D list) where A[i,j] is effect of species j on species i")
    time_points: List[float] = Field(..., description="Time points at which to evaluate the model")
   

async def simulate_generalized_lotka_volterra_dynamics_coroutine(
    initial_abundances: List[float],
    growth_rates: List[float],
    interaction_matrix: List[List[float]],
    time_points: List[float],
    
) -> Dict[str, Any]:
 
    # Convert inputs to numpy arrays
    initial_abundances = np.array(initial_abundances, dtype=float)
    growth_rates = np.array(growth_rates, dtype=float)
    interaction_matrix = np.array(interaction_matrix, dtype=float)
    time_points = np.array(time_points, dtype=float)

    # Check dimensions
    n_species = len(initial_abundances)
    if len(growth_rates) != n_species or interaction_matrix.shape != (n_species, n_species):
        return {"research_log": "Dimension mismatch: growth_rates and interaction_matrix must match initial_abundances dimensions", 
                "simulation_csv_url": None}

    # Define gLV equations
    def glv_equations(abundances, t, growth_rates, interaction_matrix):
        return abundances * (growth_rates + np.dot(interaction_matrix, abundances))

    # Integrate ODE
    simulation_results = odeint(glv_equations, initial_abundances, time_points, args=(growth_rates, interaction_matrix))

    # Create DataFrame
    columns = [f"Species_{i+1}" for i in range(n_species)]
    results_df = pd.DataFrame(simulation_results, columns=columns)
    results_df.insert(0, "Time", time_points)

    # Upload CSV
    buffer = io.StringIO()
    results_df.to_csv(buffer, index=False)
    simulation_csv_url = await upload_content_to_minio(
        content=buffer.getvalue().encode("utf-8"),
        file_name="glv_simulation_results.csv",
        file_extension=".csv",
        content_type="text/csv",
        no_expired=True
    )

    # Summary statistics
    final_abundances = simulation_results[-1]
    dominant_species = np.argmax(final_abundances) + 1
    extinct_species = np.sum(final_abundances < 1e-6)

    # Research log
    log = f"""
# Generalized Lotka-Volterra (gLV) Model Simulation

Number of microbial species: {n_species}
Simulation time range: {time_points[0]} to {time_points[-1]}
Number of time points: {len(time_points)}

Summary of dynamics:
- Initial total abundance: {np.sum(initial_abundances):.4f}
- Final total abundance: {np.sum(final_abundances):.4f}
- Dominant species at end of simulation: Species_{dominant_species} (abundance: {final_abundances[dominant_species-1]:.4f})
- Number of species with near-zero abundance (< 1e-6): {extinct_species}

Simulation results CSV URL: {simulation_csv_url}
"""

    return {
        "research_log": log,
        "simulation_csv_url": simulation_csv_url
    }

simulate_generalized_lotka_volterra_dynamics_tool = StructuredTool.from_function(
    name=Tools.simulate_generalized_lotka_volterra_dynamics,
description="""
    【领域：生物】
        "使用广义 Lotka-Volterra (gLV) 模型模拟微生物群落动力学。\n\n"
        "返回：\n"
        "- research_log: 模拟日志，包括种群动态摘要\n"
        "- simulation_csv_url: 含各物种丰度随时间变化的 CSV 链接"
    """,
    args_schema=GLVSimulationInput,
    coroutine=simulate_generalized_lotka_volterra_dynamics_coroutine,
    metadata={"args_schema_json": GLVSimulationInput.schema()}
)




# 测试成功
# 请模拟一个细菌种群的 Logistic 增长。初始种群为 1e5，生长率 0.6 h⁻¹，清除率 0.05 h⁻¹，生态位容量为 1e9。总模拟时间 48 小时，时间步长 0.5 小时。
class MicrobialPopulationDynamicsInput(BaseModel):
    initial_populations: List[float] = Field(..., description="Initial population sizes for each species")
    growth_rates: List[float] = Field(..., description="Growth rates for each species (per hour)")
    clearance_rates: List[float] = Field(..., description="Clearance rates for each species (per hour)")
    carrying_capacities: List[float] = Field(..., description="Carrying capacities for each species")
    simulation_time: Optional[float] = Field(24.0, description="Total simulation time in hours")
    time_step: Optional[float] = Field(0.1, description="Time step for simulation output")
    

async def simulate_microbial_population_dynamics_coroutine(
    initial_populations: List[float],
    growth_rates: List[float],
    clearance_rates: List[float],
    carrying_capacities: List[float],
    simulation_time: float = 24.0,
    time_step: float = 0.1,
    
) -> Dict[str, Any]:
 

    log = "# Microbial Population Dynamics Simulation\n"

    n_species = len(initial_populations)
    if not (len(growth_rates) == len(clearance_rates) == len(carrying_capacities) == n_species):
        return {"research_log": "ERROR: Input list lengths must match for all species.",
                "simulation_csv_url": None}

    initial_populations = np.array(initial_populations, dtype=float)
    growth_rates = np.array(growth_rates, dtype=float)
    clearance_rates = np.array(clearance_rates, dtype=float)
    carrying_capacities = np.array(carrying_capacities, dtype=float)

    # Define ODE system for each species
    def population_dynamics(t, N):
        dNdt = growth_rates * N * (1 - N / carrying_capacities) - clearance_rates * N
        return dNdt

    # Time points
    t_span = (0, simulation_time)
    t_eval = np.arange(0, simulation_time + time_step, time_step)

    # Solve ODE
    solution = solve_ivp(population_dynamics, t_span, initial_populations, t_eval=t_eval, method='RK45')
    time_points = solution.t
    populations = solution.y.T  # shape: (time_points, species)

    # Create results DataFrame
    columns = [f"Species_{i+1}" for i in range(n_species)]
    results_df = pd.DataFrame(populations, columns=columns)
    results_df.insert(0, "Time", time_points)

    # Upload CSV
    buffer = io.StringIO()
    results_df.to_csv(buffer, index=False)
    simulation_csv_url = await upload_content_to_minio(
        content=buffer.getvalue().encode("utf-8"),
        file_name="microbial_population_dynamics.csv",
        file_extension=".csv",
        content_type="text/csv",
        no_expired=True
    )

    # Summary statistics
    max_populations = np.max(populations, axis=0)
    final_populations = populations[-1]
    log += f"Simulation time: 0 to {simulation_time} hours\n"
    log += f"Maximum populations reached: {max_populations}\n"
    log += f"Final populations: {final_populations}\n"
    log += f"Simulation CSV URL: {simulation_csv_url}\n"

    return {
        "research_log": log,
        "simulation_csv_url": simulation_csv_url
    }

simulate_microbial_population_dynamics_tool = StructuredTool.from_function(
    name=Tools.simulate_microbial_population_dynamics,
description="""
    【领域：生物】
        "模拟微生物群落的种群动力学，基于 Logistic 增长和清除率。\n\n"
        "返回：\n"
        "- research_log: 模拟日志，包括最大和最终种群信息\n"
        "- simulation_csv_url: 含时间序列种群数据的 CSV 链接"
    ),
    args_schema=MicrobialPopulationDynamicsInput,
    coroutine=simulate_microbial_population_dynamics_coroutine,
    metadata={"args_schema_json": MicrobialPopulationDynamicsInput.schema()}
""",
    coroutine=simulate_microbial_population_dynamics_coroutine
)

    