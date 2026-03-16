      
# 标准库
import os
import io
import tempfile
import shutil
import subprocess
import time
from datetime import datetime
from math import log
from typing import Any, Dict, List, Optional

# 科学计算
import numpy as np
import pandas as pd
from scipy import optimize
from scipy.optimize import curve_fit
import matplotlib.pyplot as plt
from workflow.const import Tools
# 图像处理与跟
import uuid
from urllib.parse import quote
# 网络与上传
from urllib.request import urlopen
from workflow.utils.minio_utils import upload_content_to_minio

# LangChain / LangGraph
from langchain_core.tools import StructuredTool
from workflow.const import Tools

# Pydantic
from pydantic import BaseModel, Field


# 测试成功
"""
query:我在实验里培养了大肠杆菌 DH5α，在 0 到 12 小时之间每隔 1 小时测了 OD600，数值分别是 [0.05, 0.07, 0.11, 0.18, 0.32, 0.58, 0.95, 1.42, 1.80, 2.05, 2.10, 2.08, 2.05]。请帮我分析它的生长曲线，计算倍增时间和延迟期，并画出生长曲线图。
"""
class BacterialGrowthCurveInput(BaseModel):
    time_points: List[float] = Field(..., description="Time points of measurements in hours")
    od_values: List[float] = Field(..., description="Optical density (OD600) values corresponding to each time point")
    strain_name: str = Field(..., description="Name of the bacterial strain being analyzed")
    output_dir: Optional[str] = Field(None, description="Output directory (参数保留，实际通过上传获取链接)")

async def analyze_bacterial_growth_curve_coroutine(
    time_points: List[float],
    od_values: List[float],
    strain_name: str,
    
) -> Dict[str, Any]:


    # Convert inputs
    time_points = np.array(time_points)
    od_values = np.array(od_values)
    growth_data = pd.DataFrame({"Time_h": time_points, "OD": od_values})

    # Logistic growth model
    def logistic_growth(t, k, n0, r):
        return k / (1 + ((k - n0) / n0) * np.exp(-r * t))

    # Initial estimates
    p0 = [max(od_values), od_values[0], 0.5]

    try:
        # Fit model
        popt, _ = curve_fit(logistic_growth, time_points, od_values, p0=p0)
        k_fit, n0_fit, r_fit = popt

        # Growth metrics
        doubling_time = log(2) / r_fit
        lag_phase = (np.log((k_fit / n0_fit) - 1) - np.log((k_fit / (0.05 * k_fit)) - 1)) / r_fit
        lag_phase = max(0, lag_phase)

        # Generate fitted curve
        time_fine = np.linspace(min(time_points), max(time_points), 100)
        od_fitted = logistic_growth(time_fine, *popt)

        # Plot
        plt.figure(figsize=(8, 6))
        plt.scatter(time_points, od_values, label="Observed OD")
        plt.plot(time_fine, od_fitted, "r-", label="Fitted logistic curve")
        plt.xlabel("Time (hours)")
        plt.ylabel("Optical Density (OD)")
        plt.title(f"Growth Curve for {strain_name}")
        plt.legend()
        plt.grid(True, alpha=0.3)

        # Save to buffer and upload
        buf = io.BytesIO()
        plt.savefig(buf, format="png")
        plt.close()
        buf.seek(0)

        # ✅ 使用 UUID 文件名，避免中文/特殊字符问题
        safe_file_name = f"{uuid.uuid4().hex}_growth_curve.png"

        plot_url = await upload_content_to_minio(
            content=buf.getvalue(),
            file_name=safe_file_name,
            file_extension=".png",
            content_type="image/png",
            no_expired=True
        )

        # Build research log
        log_text = f"""
            # Bacterial Growth Curve Analysis Log

            **Strain**: {strain_name}

            ## Data Summary
            - Number of time points: {len(time_points)}
            - Time range: {min(time_points):.1f} – {max(time_points):.1f} hours
            - Initial OD: {od_values[0]:.4f}
            - Final OD: {od_values[-1]:.4f}

            ## Growth Model
            - Model: Logistic growth
            - Parameters:
            - K (carrying capacity): {k_fit:.4f}
            - N0 (initial OD): {n0_fit:.4f}
            - r (growth rate): {r_fit:.4f} per hour

            ## Growth Metrics
            - Doubling time: {doubling_time:.2f} h
            - Lag phase: {lag_phase:.2f} h
            - Maximum OD: {k_fit:.4f}

            ## Output
            - Growth curve plot: '{plot_url}'

            ✅ Analysis completed successfully.
            """

        return {
            "research_log": log_text,
            "growth_curve_plot_url": plot_url
        }

    except RuntimeError:
        return {
            "research_log": f"Error: Could not fit growth model to data for {strain_name}. Please check input data.",
            "growth_curve_plot_url": None
        }

analyze_bacterial_growth_curve_tool = StructuredTool.from_function(
    name=Tools.analyze_bacterial_growth_curve,
    description="""
    【领域：生物】
        "Analyze bacterial growth curve data from OD600 measurements.\n\n"
        "输入:\n"
        "  - time_points: 时间点 (小时)\n"
        "  - od_values: OD600 数值\n"
        "  - strain_name: 菌株名称\n\n"
        "输出:\n"
        "  - research_log: 生长曲线分析日志 (包含拟合参数、倍增时间、延迟期等)\n"
        "  - growth_curve_plot_url: 生长曲线图 PNG 链接""",
    args_schema=BacterialGrowthCurveInput,
    coroutine=analyze_bacterial_growth_curve_coroutine,
    metadata={"args_schema_json": BacterialGrowthCurveInput.schema()}
)



#测试成功
# 我想要从脂肪组织里分离白细胞，酶消化时间 30 分钟，不指定 MACS 抗体，请你给出分离日志并生成 CSV 文件
class IsolatePurifyImmuneCellsInput(BaseModel):
    tissue_type: str = Field(..., description="Type of tissue sample (e.g., 'adipose', 'kidney', 'liver', 'lung', 'spleen')")
    target_cell_type: str = Field(..., description="Immune cell population to isolate (e.g., 'macrophages', 'leukocytes', 'T cells')")
    enzyme_type: str = Field(default="collagenase", description="Enzyme used for tissue digestion")
    macs_antibody: Optional[str] = Field(default=None, description="Specific antibody for MACS. If not provided, auto-selected based on target cell type")
    digestion_time_min: int = Field(default=45, description="Tissue digestion time in minutes")

async def isolate_purify_immune_cells_coroutine(
    tissue_type: str,
    target_cell_type: str,
    enzyme_type: str = "collagenase",
    macs_antibody: Optional[str] = None,
    digestion_time_min: int = 45,
):
    """
    Simulates the isolation and purification of immune cells from tissue samples.
    Returns research log and uploads cell count CSV to MinIO.
    """
    # Initialize log
    log = []
    log.append(f"CELL ISOLATION AND PURIFICATION LOG - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.append(f"Tissue type: {tissue_type}")
    log.append(f"Target cell population: {target_cell_type}")
    log.append("-" * 50)

    # Auto-assign antibody
    if macs_antibody is None:
        if target_cell_type.lower() == "macrophages":
            macs_antibody = "CD11b"
        elif target_cell_type.lower() == "t cells":
            macs_antibody = "CD3"
        elif target_cell_type.lower() == "b cells":
            macs_antibody = "CD19"
        else:
            macs_antibody = "CD45"

    # Step 1: Tissue prep
    log.append("1. TISSUE PREPARATION")
    log.append(f"   - {tissue_type.capitalize()} tissue collected and minced in cold PBS")

    # Step 2: Digestion
    log.append("\n2. ENZYMATIC DIGESTION")
    log.append(f"   - Incubated with {enzyme_type} at 37°C for {digestion_time_min} min")
    initial_cell_count = np.random.randint(1e6, 1e7)
    log.append(f"   - Cell count after digestion: {initial_cell_count:,}")

    # Step 3: Filtration
    post_filtration_count = int(initial_cell_count * np.random.uniform(0.7, 0.9))
    log.append("\n3. FILTRATION")
    log.append(f"   - Cell count after filtration: {post_filtration_count:,}")

    # Step 4: Density gradient
    post_gradient_count = int(post_filtration_count * np.random.uniform(0.3, 0.6))
    log.append("\n4. DENSITY GRADIENT")
    log.append(f"   - Cell count after gradient: {post_gradient_count:,}")

    # Step 5: MACS
    final_cell_count = int(post_gradient_count * np.random.uniform(0.1, 0.3))
    purity = np.random.uniform(0.85, 0.98)
    log.append("\n5. MACS")
    log.append(f"   - Final cell count: {final_cell_count:,}")
    log.append(f"   - Estimated purity: {purity:.1%}")

    # Step 6: QC
    viability = np.random.uniform(0.85, 0.98)
    log.append("\n6. QUALITY ASSESSMENT")
    log.append(f"   - Viability: {viability:.1%}")

    # Build CSV
    df = pd.DataFrame({
        "Process Step": ["Initial", "Post-Filtration", "Post-Gradient", "Final Purified"],
        "Cell Count": [initial_cell_count, post_filtration_count, post_gradient_count, final_cell_count],
        "Viability (%)": [
            np.random.uniform(0.7, 0.9) * 100,
            np.random.uniform(0.75, 0.92) * 100,
            np.random.uniform(0.8, 0.95) * 100,
            viability * 100,
        ],
    })

    # Upload CSV
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    csv_url = await upload_content_to_minio(
        content=csv_bytes,
        file_name=f"{tissue_type}_{target_cell_type}_isolation_data.csv",
        file_extension=".csv",
        content_type="text/csv",
        no_expired=True
    )


    log.append(f"\nCell count data uploaded: {csv_url}")
    log.append("\nPURIFICATION COMPLETE")

    return "\n".join(log)

isolate_purify_immune_cells_tool = StructuredTool.from_function(
    coroutine=isolate_purify_immune_cells_coroutine,
    name=Tools.ISOLATE_PURIFY_IMMUNE_CELLS,
    description="""
    【领域：生物】
    模拟免疫细胞的分离与纯化流程。  
    输入组织类型、目标细胞类型、消化酶及时间，可选择指定或自动匹配的 MACS 抗体。  
    输出包括：  
    - 分离/纯化过程日志（含实验条件与关键步骤）  
    - 细胞数量与存活率的 CSV 文件下载链接  
""",
    args_schema=IsolatePurifyImmuneCellsInput,
    metadata={"args_schema_json": IsolatePurifyImmuneCellsInput.schema()},
)



# 测试成功
"""
我做了一个 EdU/BrdU 双脉冲标记流式细胞实验，在 0、2、4、6、8、10 小时采集数据。
结果显示：
EdU⁺ 细胞比例依次是 5.0%、18.5%、32.0%、28.5%、15.0%、6.5%；
BrdU⁺ 细胞比例依次是 4.8%、20.2%、30.5%、27.8%、16.2%、7.1%；
双阳性 EdU⁺BrdU⁺ 细胞比例依次是 1.2%、8.5%、15.3%、14.8%、7.5%、2.0%。
我想用工具估算细胞周期各阶段时长，初始估算值是：
G1 期：6 小时
S 期：8 小时
G2/M 期：4 小时
死亡率：0.01 (每小时 1%)”
"""
class CellCycleEstimationInput(BaseModel):
    flow_cytometry_data: Dict[str, List[float]] = Field(
        ...,
        description="""
    【领域：生物】Dictionary containing experimental flow cytometry data with EdU and BrdU labeling.
        Expected keys:
        - 'time_points': list of time points (hours),
        - 'edu_positive': list of percentages of EdU+ cells,
        - 'brdu_positive': list of percentages of BrdU+ cells,
        - 'double_positive': list of percentages of EdU+BrdU+ cells"""
    )
    initial_estimates: Dict[str, float] = Field(
        ...,
        description="""
    【领域：生物】Initial estimates for cell cycle phase durations and death rate.
        Expected keys:
        - 'g1_duration' (float, hours),
        - 's_duration' (float, hours),
        - 'g2m_duration' (float, hours),
        - 'death_rate' (float, fraction per hour)"""
    )

async def estimate_cell_cycle_phase_durations_coroutine(
    flow_cytometry_data: Dict[str, List[float]],
    initial_estimates: Dict[str, float]
) -> str:
    """
    Estimate cell cycle phase durations using dual-nucleoside pulse labeling data and mathematical modeling.
    """

    # ---- helper function: simulate cell population ----
    def simulate_cell_population(time_points, g1_duration, s_duration, g2m_duration, death_rate):
        edu_positive, brdu_positive, double_positive = [], [], []
        total_cycle_time = g1_duration + s_duration + g2m_duration
        for t in time_points:
            s_fraction = s_duration / total_cycle_time
            g2m_fraction = g2m_duration / total_cycle_time

            edu_pos = s_fraction * np.exp(-death_rate * t)
            brdu_pos = s_fraction * (1 - np.exp(-t / s_duration))
            double_pos = s_fraction * np.exp(-death_rate * t) * (1 - np.exp(-t / s_duration))

            edu_positive.append(min(edu_pos, 1.0) * 100)
            brdu_positive.append(min(brdu_pos, 1.0) * 100)
            double_positive.append(min(double_pos, 1.0) * 100)
        return {
            "edu_positive": edu_positive,
            "brdu_positive": brdu_positive,
            "double_positive": double_positive,
        }

    # ---- helper function: objective for optimization ----
    def objective_function(params):
        g1_duration, s_duration, g2m_duration, death_rate = params
        simulated_results = simulate_cell_population(
            flow_cytometry_data["time_points"],
            g1_duration, s_duration, g2m_duration, death_rate
        )
        edu_error = np.sum((np.array(simulated_results["edu_positive"]) - np.array(flow_cytometry_data["edu_positive"])) ** 2)
        brdu_error = np.sum((np.array(simulated_results["brdu_positive"]) - np.array(flow_cytometry_data["brdu_positive"])) ** 2)
        double_error = np.sum((np.array(simulated_results["double_positive"]) - np.array(flow_cytometry_data["double_positive"])) ** 2)
        return edu_error + brdu_error + double_error

    # ---- research log ----
    log = "# Cell Cycle Phase Duration Estimation Research Log\n\n"
    log += f"Analysis started at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    log += "## Input Data Summary\n"
    log += f"- Number of time points: {len(flow_cytometry_data['time_points'])}\n"
    log += f"- Time range: {min(flow_cytometry_data['time_points'])} to {max(flow_cytometry_data['time_points'])} hours\n"
    log += f"- Initial estimates: G1={initial_estimates['g1_duration']}h, S={initial_estimates['s_duration']}h, "
    log += f"G2/M={initial_estimates['g2m_duration']}h, Death rate={initial_estimates['death_rate']}\n\n"

    # ---- optimization ----
    initial_params = [
        initial_estimates["g1_duration"],
        initial_estimates["s_duration"],
        initial_estimates["g2m_duration"],
        initial_estimates["death_rate"],
    ]
    bounds = [(0.1, 50.0), (0.1, 30.0), (0.1, 20.0), (0.0, 1.0)]

    log += "## Optimization Process\n"
    log += "Starting parameter optimization using SciPy's L-BFGS-B algorithm...\n\n"

    optimization_start = time.time()
    result = optimize.minimize(objective_function, initial_params, method="L-BFGS-B", bounds=bounds)
    optimization_time = time.time() - optimization_start

    optimized_g1, optimized_s, optimized_g2m, optimized_death = result.x
    final_error = result.fun

    # ---- log results ----
    log += "## Optimization Results\n"
    log += f"- Optimization completed in {optimization_time:.2f} seconds\n"
    log += f"- Optimization success: {result.success}\n"
    log += f"- Final error value: {final_error:.4f}\n\n"

    log += "## Estimated Cell Cycle Phase Durations\n"
    log += f"- G1 phase: {optimized_g1:.2f} hours\n"
    log += f"- S phase: {optimized_s:.2f} hours\n"
    log += f"- G2/M phase: {optimized_g2m:.2f} hours\n"
    log += f"- Total cell cycle time: {optimized_g1 + optimized_s + optimized_g2m:.2f} hours\n"
    log += f"- Cell death rate: {optimized_death:.4f} per hour\n\n"

    log += "## Comparison with Initial Estimates\n"
    log += f"- G1 phase: {optimized_g1:.2f}h (initial: {initial_estimates['g1_duration']}h)\n"
    log += f"- S phase: {optimized_s:.2f}h (initial: {initial_estimates['s_duration']}h)\n"
    log += f"- G2/M phase: {optimized_g2m:.2f}h (initial: {initial_estimates['g2m_duration']}h)\n"
    log += f"- Death rate: {optimized_death:.4f} (initial: {initial_estimates['death_rate']})\n\n"

    log += "## Conclusion\n"
    log += "The mathematical modeling and optimization estimated the cell cycle phase durations "
    log += "based on dual-nucleoside pulse labeling data, providing insight into proliferation dynamics.\n\n"
    log += f"Analysis completed at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"

    return log

estimate_cell_cycle_phase_durations_tool = StructuredTool.from_function(
    coroutine=estimate_cell_cycle_phase_durations_coroutine,
    name=Tools.estimate_cell_cycle_phase_durations,
    description="""
    【领域：生物】基于双核苷（EdU/BrdU）脉冲标记的流式细胞术数据，估算细胞周期各阶段（G1、S、G2/M）的时长，以及细胞死亡率
        输出结果：- research_log: 分析日志（包括拟合参数、优化过程和最终估算值）
        - phase_durations: 各细胞周期阶段的时长及死亡率的最终估算结果
    """,
    args_schema=CellCycleEstimationInput,
    metadata={"args_schema_json": CellCycleEstimationInput.schema()},
)




# 测试成功
"""
请分析以下 EBV 抗体滴度实验数据：
原始 OD 数据：
S1 样本：VCA_IgG=1.25, VCA_IgM=0.32, EA_IgG=0.85, EA_IgM=0.20, EBNA1_IgG=1.10, EBNA1_IgM=0.15
S2 样本：VCA_IgG=0.95, VCA_IgM=0.45, EA_IgG=0.70, EA_IgM=0.25, EBNA1_IgG=0.90, EBNA1_IgM=0.18
标准曲线数据：
VCA_IgG: [(0,0.05),(10,0.30),(50,0.80),(100,1.20)]
VCA_IgM: [(0,0.04),(10,0.25),(50,0.70),(100,1.10)]
EA_IgG: [(0,0.06),(10,0.28),(50,0.75),(100,1.15)]
EA_IgM: [(0,0.05),(10,0.22),(50,0.68),(100,1.05)]
EBNA1_IgG: [(0,0.07),(10,0.32),(50,0.82),(100,1.18)]
EBNA1_IgM: [(0,0.06),(10,0.26),(50,0.72),(100,1.08)]
样本元数据：
S1: group=Patient, collection_date=2023-05-12
S2: group=Control, collection_date=2023-05-14
请根据这些输入，输出完整的 EBV 抗体滴度分析日志和结果 CSV 文件
"""
class EBVAntibodyInput(BaseModel):
    raw_od_data: Dict[str, Dict[str, float]] = Field(
        ..., description="Raw OD readings for each sample. "
                         "Format: {sample_id: {'VCA_IgG': float, 'VCA_IgM': float, 'EA_IgG': float, 'EA_IgM': float, 'EBNA1_IgG': float, 'EBNA1_IgM': float}}"
    )
    standard_curve_data: Dict[str, list] = Field(
        ..., description="Standard curve data for each antibody type. "
                         "Format: {antibody_type: [(concentration, OD), ...]}"
    )
    sample_metadata: Dict[str, Dict[str, str]] = Field(
        ..., description="Metadata for each sample. "
                         "Format: {sample_id: {'group': str, 'collection_date': str}}"
    )

async def analyze_ebv_antibody_titers_coroutine(
    raw_od_data: Dict[str, Dict[str, float]],
    standard_curve_data: Dict[str, list],
    sample_metadata: Dict[str, Dict[str, str]],
) -> Dict[str, Any]:

    research_log = [
        "## EBV Antibody Titer Quantification Analysis",
        f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"Number of samples: {len(raw_od_data)}",
        ""
    ]

    # Create dataframe for results
    results_df = pd.DataFrame(columns=['Sample_ID', 'Group', 'Collection_Date', 
                                       'VCA_IgG', 'VCA_IgM', 'EA_IgG', 'EA_IgM', 
                                       'EBNA1_IgG', 'EBNA1_IgM'])

    research_log.append("### 1. Data Preprocessing")
    research_log.append("- Checking for missing values in OD readings")

    # Check for missing values
    missing_values = False
    for sample_id, readings in raw_od_data.items():
        for antibody_type in ['VCA_IgG','VCA_IgM','EA_IgG','EA_IgM','EBNA1_IgG','EBNA1_IgM']:
            if antibody_type not in readings:
                missing_values = True
                research_log.append(f"  - Warning: Missing {antibody_type} for sample {sample_id}")
    if not missing_values:
        research_log.append("  - No missing values detected")

    research_log.append("\n### 2. Standard Curve Fitting")
    standard_curves = {}
    for antibody_type, curve_data in standard_curve_data.items():
        concentrations, ods = zip(*curve_data)
        slope, intercept = np.polyfit(ods, concentrations, 1)
        standard_curves[antibody_type] = (slope, intercept)
        research_log.append(f"  - {antibody_type}: slope={slope:.4f}, intercept={intercept:.4f}")

    research_log.append("\n### 3. Antibody Titer Quantification")
    for sample_id, readings in raw_od_data.items():
        sample_data = {'Sample_ID': sample_id}
        if sample_id in sample_metadata:
            sample_data['Group'] = sample_metadata[sample_id].get('group', 'Unknown')
            sample_data['Collection_Date'] = sample_metadata[sample_id].get('collection_date', 'Unknown')
        else:
            sample_data['Group'] = 'Unknown'
            sample_data['Collection_Date'] = 'Unknown'

        for antibody_type in ['VCA_IgG','VCA_IgM','EA_IgG','EA_IgM','EBNA1_IgG','EBNA1_IgM']:
            if antibody_type in readings:
                od = readings[antibody_type]
                slope, intercept = standard_curves[antibody_type]
                concentration = slope * od + intercept
                sample_data[antibody_type] = concentration
            else:
                sample_data[antibody_type] = np.nan
        results_df = pd.concat([results_df, pd.DataFrame([sample_data])], ignore_index=True)

    research_log.append("\n### 4. Results Summary")
    summary_stats = results_df.groupby('Group')[['VCA_IgG','VCA_IgM','EA_IgG','EA_IgM','EBNA1_IgG','EBNA1_IgM']].agg(['mean','std'])
    for group in summary_stats.index:
        research_log.append(f"#### Group: {group}")
        for antibody in ['VCA_IgG','VCA_IgM','EA_IgG','EA_IgM','EBNA1_IgG','EBNA1_IgM']:
            mean = summary_stats.loc[group,(antibody,'mean')]
            std = summary_stats.loc[group,(antibody,'std')]
            research_log.append(f"- {antibody}: {mean:.2f} ± {std:.2f} U/mL")
        research_log.append("")

    # Save results CSV and upload
    csv_buf = io.StringIO()
    results_df.to_csv(csv_buf, index=False)
    results_csv_url = await upload_content_to_minio(
        content=csv_buf.getvalue().encode('utf-8'),
        file_name="ebv_antibody_titers_results.csv",
        file_extension=".csv",
        content_type="text/csv",
        no_expired=True
    )
    research_log.append(f"\nFull results CSV uploaded: {results_csv_url}")

    return {"research_log": "\n".join(research_log), "results_csv_url": results_csv_url}

analyze_ebv_antibody_titers_tool = StructuredTool.from_function(
    name=Tools.analyze_ebv_antibody_titers,
    description="""
    【领域：生物】
        "分析 EBV 抗体 (VCA/EA/EBNA1, IgG/IgM) 滴度，输入原始 OD 数据、标准曲线和样本元数据，"
        "输出分析日志和 CSV 结果文件。"
    """,
    args_schema=EBVAntibodyInput,
    coroutine=analyze_ebv_antibody_titers_coroutine,
    metadata={"args_schema_json": EBVAntibodyInput.schema()}
)


