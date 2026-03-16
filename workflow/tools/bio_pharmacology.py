import io
import sys
import re
import shutil
import tempfile
import subprocess
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple

import numpy as np
import pandas as pd
from scipy import stats
import statsmodels.api as sm
from statsmodels.formula.api import ols
from statsmodels.stats.multicomp import pairwise_tukeyhsd
import matplotlib.pyplot as plt

import requests
import pickle
import json

from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool
from workflow.const import Tools
from workflow.utils.minio_utils import upload_content_to_minio

# from tdc import Oracle




class StabilityTestInput(BaseModel):
    formulations: List[Dict[str, Any]] = Field(
        ..., description="List of formulation dictionaries with keys: name, active_ingredient, concentration, excipients, dosage_form"
    )
    storage_conditions: List[Dict[str, Any]] = Field(
        ..., description="List of storage conditions with keys: temperature (°C), humidity (%RH, optional), description"
    )
    time_points: List[int] = Field(
        ..., description="List of time points in days to evaluate stability"
    )

async def analyze_accelerated_stability_of_pharmaceutical_formulations_coroutine(
    formulations: List[Dict[str, Any]],
    storage_conditions: List[Dict[str, Any]],
    time_points: List[int]
) -> Dict[str, Any]:
    """
    Analyze the stability of pharmaceutical formulations under accelerated storage conditions.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    all_results = []

    # 遍历所有配方 & 存储条件
    for formulation in formulations:
        for condition in storage_conditions:
            results = []
            temp_c = condition["temperature"]
            accel_factor = 2 ** ((temp_c - 25) / 10)  # 经验法则：每升高10°C，速率加倍
            
            humidity_factor = 1.0
            if "humidity" in condition:
                humidity = condition["humidity"]
                if humidity > 60:
                    humidity_factor = 1.0 + (humidity - 60) / 100

            initial_content = 100.0  # 初始含量 = 100%

            for time in time_points:
                effective_time = time * accel_factor * humidity_factor
                chemical_stability = initial_content * np.exp(-0.001 * effective_time)
                physical_stability = max(1, 10 - (0.05 * effective_time))
                particle_size_change = (
                    0.2 * effective_time if "solid" in formulation.get("dosage_form", "").lower() else 0
                )

                results.append({
                    "Formulation": formulation["name"],
                    "Storage_Condition": condition["description"],
                    "Temperature_C": temp_c,
                    "Humidity_RH": condition.get("humidity", "N/A"),
                    "Time_Days": time,
                    "Chemical_Stability_Percent": round(chemical_stability, 2),
                    "Physical_Stability_Score": round(physical_stability, 1),
                    "Particle_Size_Change_Percent": round(particle_size_change, 2)
                })
            all_results.extend(results)

    # 转 DataFrame
    results_df = pd.DataFrame(all_results)

    # 上传 CSV
    csv_buf = io.StringIO()
    results_df.to_csv(csv_buf, index=False)
    results_csv_url = await upload_content_to_minio(
        content=csv_buf.getvalue().encode("utf-8"),
        file_name=f"stability_results_{timestamp}.csv",
        file_extension=".csv",
        content_type="text/csv",
        no_expired=True
    )

    # 构建日志
    log = f"# Accelerated Stability Testing of Pharmaceutical Formulations\n"
    log += f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    log += "## 1. STUDY PARAMETERS\n"
    log += f"- Number of formulations tested: {len(formulations)}\n"
    log += f"- Formulations: {', '.join([f['name'] for f in formulations])}\n"
    log += "- Storage conditions: " + ", ".join([
        f"{c['description']} ({c['temperature']}°C"
        + (f"/{c['humidity']}% RH" if 'humidity' in c else "")
        + ")"
        for c in storage_conditions
    ]) + "\n"
    log += f"- Time points evaluated (days): {', '.join(map(str, time_points))}\n\n"

    log += "## 2. METHODOLOGY\n"
    log += "- Chemical stability assessed by active ingredient content\n"
    log += "- Physical stability evaluated on a 10-point scale\n"
    log += "- Particle size changes measured where applicable\n\n"

    log += "## 3. KEY FINDINGS\n"
    final_time = max(time_points)
    final_results = results_df[results_df["Time_Days"] == final_time]

    for formulation in formulations:
        form_results = final_results[final_results["Formulation"] == formulation["name"]]
        log += f"- {formulation['name']}:\n"
        for _, row in form_results.iterrows():
            condition = row["Storage_Condition"]
            chem_stab = row["Chemical_Stability_Percent"]
            phys_stab = row["Physical_Stability_Score"]

            stability_assessment = "Stable"
            if chem_stab < 90 or phys_stab < 7:
                stability_assessment = "Potentially unstable"
            if chem_stab < 85 or phys_stab < 5:
                stability_assessment = "Unstable"

            log += f"  * {condition}: {chem_stab}% chemical stability, score {phys_stab}/10 → {stability_assessment}\n"
        log += "\n"

    log += "## 4. CONCLUSION\n"
    best_formulation, best_stability = "", 0
    for formulation in formulations:
        form_data = final_results[final_results["Formulation"] == formulation["name"]]
        avg_chem_stability = form_data["Chemical_Stability_Percent"].mean()
        if avg_chem_stability > best_stability:
            best_stability = avg_chem_stability
            best_formulation = formulation["name"]

    log += f"- Most stable formulation: {best_formulation} (avg. chemical stability: {best_stability:.2f}%)\n"
    log += f"- Detailed results saved to: {results_csv_url}\n"

    return {"research_log": log, "results_csv_url": results_csv_url}

analyze_stability_tool = StructuredTool.from_function(
    name=Tools.analyze_accelerated_stability_of_pharmaceutical_formulations,
    description="""
    【领域：生物】
        "分析药物制剂在加速储存条件下的稳定性。\n\n"
        "输入：\n"
        "- formulations: 配方信息 (name, active_ingredient, concentration, excipients, dosage_form)\n"
        "- storage_conditions: 储存条件 (temperature °C, humidity %RH 可选, description)\n"
        "- time_points: 评估时间点 (天)\n\n"
        "输出：\n"
        "- research_log: 完整分析日志\n"
        "- results_csv_url: 结果表格 CSV 链接""",
    args_schema=StabilityTestInput,
    coroutine=analyze_accelerated_stability_of_pharmaceutical_formulations_coroutine,
    metadata={"args_schema_json": StabilityTestInput.schema()}
)




class ChondrogenicAssayInput(BaseModel):
    chondrocyte_cells: Dict[str, Any] = Field(
        ..., description="Chondrocyte cell information (keys: source, passage_number, cell_density)"
    )
    test_compounds: List[Dict[str, Any]] = Field(
        ..., description="List of test compounds (keys: name, concentration, vehicle)"
    )
    culture_duration_days: int = Field(
        21, description="Total duration of culture in days (default: 21)"
    )
    measurement_intervals: int = Field(
        7, description="Interval in days between measurements (default: 7)"
    )

async def run_3d_chondrogenic_aggregate_assay_coroutine(
    chondrocyte_cells: Dict[str, Any],
    test_compounds: List[Dict[str, Any]],
    culture_duration_days: int = 21,
    measurement_intervals: int = 7
) -> Dict[str, Any]:
    """
    Generate a detailed protocol for a 3D chondrogenic aggregate assay to test compounds' effects.
    """
    experiment_id = f"CHOND3D_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    timepoints = list(range(0, culture_duration_days + 1, measurement_intervals))
    if timepoints[-1] != culture_duration_days:
        timepoints.append(culture_duration_days)

    # 生成实验方案文档
    protocol = f"# 3D Chondrogenic Aggregate Culture Assay Protocol - {experiment_id}\n\n"
    protocol += "## 1. Materials and Reagents\n\n"
    protocol += "- Chondrocyte cells\n- Chondrogenic differentiation medium\n- Transforming growth factor-β3 (TGF-β3)\n"
    protocol += "- Dexamethasone\n- Ascorbate-2-phosphate\n- 96-well V-bottom plates\n"
    protocol += "- Gaussia luciferase reporter assay kit\n- Luminometer\n- Test compounds and vehicles\n"
    protocol += "- Centrifuge\n- CO2 incubator\n- Sterile pipettes and tips\n\n"

    protocol += "## 2. Experimental Information\n\n"
    protocol += "### Cell Information:\n"
    protocol += f"- Source: {chondrocyte_cells['source']}\n"
    protocol += f"- Passage number: {chondrocyte_cells['passage_number']}\n"
    protocol += f"- Cell density: {chondrocyte_cells['cell_density']} cells/mL\n\n"

    protocol += "### Experimental Design:\n"
    protocol += f"- Culture duration: {culture_duration_days} days\n"
    protocol += f"- Measurement timepoints: {', '.join(map(str, timepoints))} days\n\n"

    protocol += "### Test Compounds:\n"
    for i, compound in enumerate(test_compounds):
        protocol += f"- Compound {i+1}: {compound['name']} at {compound['concentration']} in {compound['vehicle']}\n"
    protocol += "- Control: Vehicle only\n\n"

    protocol += "## 3. Detailed Procedure\n\n"
    protocol += "### Day 0: Setup\n\n"
    protocol += "1. Prepare differentiation medium with supplements (TGF-β3, dexamethasone, ascorbate-2-phosphate, etc.)\n"
    protocol += "2. Harvest and count chondrocyte cells\n"
    protocol += f"3. Prepare suspension at {chondrocyte_cells['cell_density']} cells/mL\n"
    protocol += "4. Form 3D aggregates in V-bottom plates (2.5×10^5 cells/well, centrifuge 500g, 5 min)\n"
    protocol += "5. Add test compounds / vehicle control\n"
    protocol += "6. Incubate at 37°C, 5% CO2\n\n"

    protocol += f"### Day 1 to {culture_duration_days}\n\n"
    protocol += "1. Change medium every 2–3 days with fresh medium + compounds\n"
    protocol += f"2. At {', '.join(map(str, timepoints))} days: collect supernatant for GLuc assay, fix aggregates for histology\n\n"

    # 上传文档
    protocol_buf = io.StringIO()
    protocol_buf.write(protocol)
    protocol_url = await upload_content_to_minio(
        content=protocol_buf.getvalue().encode("utf-8"),
        file_name=f"chondrogenic_assay_protocol_{experiment_id}.md",
        file_extension=".md",
        content_type="text/markdown",
        no_expired=True
    )

    return {"protocol_doc": protocol, "protocol_file_url": protocol_url}

run_3d_chondrogenic_aggregate_assay_tool = StructuredTool.from_function(
    name=Tools.run_3d_chondrogenic_aggregate_assay,
    description="""
    【领域：生物】
        "生成 3D 软骨细胞聚集培养实验 (chondrogenic aggregate assay) 的详细实验方案。\n\n"
        "输入：\n"
        "- chondrocyte_cells: 细胞信息 (source, passage_number, cell_density)\n"
        "- test_compounds: 测试化合物 (name, concentration, vehicle)\n"
        "- culture_duration_days: 培养总时长 (默认 21 天)\n"
        "- measurement_intervals: 测量间隔天数 (默认 7)\n\n"
        "输出：\n"
        "- protocol_doc: 实验方案文本\n"
        "- protocol_file_url: 上传后的 Markdown 文档链接""",
    args_schema=ChondrogenicAssayInput,
    coroutine=run_3d_chondrogenic_aggregate_assay_coroutine,
    metadata={"args_schema_json": ChondrogenicAssayInput.schema()}
)




class RadiolabeledAntibodyInput(BaseModel):
    time_points: List[float] = Field(..., description="Time points (hours) at which measurements were taken")
    tissue_data: Dict[str, List[float]] = Field(
        ..., description="Dictionary of tissue name -> %IA/g measurements across time points (must include 'tumor')"
    )
    output_dir: Optional[str] = Field(
        None, description="Output directory (参数保留，实际通过上传获取链接)"
    )

async def analyze_radiolabeled_antibody_biodistribution_coroutine(
    time_points: List[float],
    tissue_data: Dict[str, List[float]],
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    import numpy as np
    from scipy.optimize import curve_fit
    import io, json

    # Validate inputs
    if "tumor" not in tissue_data:
        return {
            "research_log": "Error: Tumor data must be provided in tissue_data dictionary",
            "results_json_url": None,
        }

    # Define bi-exponential model
    def bi_exp_model(t, A, alpha, B, beta):
        return A * np.exp(-alpha * t) + B * np.exp(-beta * t)

    results = {
        "tissues_analyzed": list(tissue_data.keys()),
        "pk_parameters": {},
        "tumor_to_normal_ratios": {},
        "auc_values": {},
    }

    # Analyze PK per tissue
    for tissue, measurements in tissue_data.items():
        try:
            params, _ = curve_fit(
                bi_exp_model,
                time_points,
                measurements,
                p0=[50, 0.1, 50, 0.01],
                bounds=([0, 0, 0, 0], [100, 5, 100, 1]),
            )
            A, alpha, B, beta = params
            t_half_dist = np.log(2) / alpha
            t_half_elim = np.log(2) / beta
            auc = A / alpha + B / beta
            mrt = (A / (alpha**2) + B / (beta**2)) / auc
            clearance = 1 / auc if tissue.lower() in ["blood", "plasma"] else None

            results["pk_parameters"][tissue] = {
                "A": float(A),
                "alpha": float(alpha),
                "B": float(B),
                "beta": float(beta),
                "distribution_half_life_h": float(t_half_dist),
                "elimination_half_life_h": float(t_half_elim),
                "mean_residence_time_h": float(mrt),
            }
            if clearance:
                results["pk_parameters"][tissue]["clearance"] = float(clearance)

            results["auc_values"][tissue] = float(auc)

        except Exception as e:
            results["pk_parameters"][tissue] = f"Fitting failed: {str(e)}"

    # Tumor-to-normal ratios
    for tissue in tissue_data:
        if tissue != "tumor":
            ratios = [
                t / n if n > 0 else float("inf")
                for t, n in zip(tissue_data["tumor"], tissue_data[tissue])
            ]
            results["tumor_to_normal_ratios"][tissue] = {
                "values": [float(r) for r in ratios],
                "max_ratio": float(max(ratios)),
                "max_ratio_time_point": float(time_points[np.argmax(ratios)]),
            }

    # Upload JSON results
    json_buf = io.StringIO()
    json.dump(results, json_buf, indent=2)
    results_url = await upload_content_to_minio(
        content=json_buf.getvalue().encode("utf-8"),
        file_name="biodistribution_pk_results.json",
        file_extension=".json",
        content_type="application/json",
        no_expired=True,
    )

    # Build research log
    log = "# Biodistribution and Pharmacokinetic Analysis of Radiolabeled Antibody\n\n"
    log += f"## Analysis Summary\n"
    log += f"- Analyzed biodistribution data across {len(tissue_data)} tissues\n"
    log += f"- Time points analyzed: {time_points} hours\n"
    log += f"- Performed bi-exponential pharmacokinetic modeling\n\n"

    log += "## Key Pharmacokinetic Parameters\n"
    for tissue, params in results["pk_parameters"].items():
        if isinstance(params, dict):
            log += f"\n### {tissue.capitalize()}\n"
            log += f"- Distribution half-life: {params['distribution_half_life_h']:.2f} hours\n"
            log += f"- Elimination half-life: {params['elimination_half_life_h']:.2f} hours\n"
            log += f"- Mean residence time: {params['mean_residence_time_h']:.2f} hours\n"
            if "clearance" in params:
                log += f"- Clearance: {params['clearance']:.4f} units\n"

    log += "\n## Tumor-to-Normal Tissue Ratios\n"
    for tissue, ratio_data in results["tumor_to_normal_ratios"].items():
        log += f"- {tissue.capitalize()}: Max ratio {ratio_data['max_ratio']:.2f} at {ratio_data['max_ratio_time_point']:.1f} hours\n"

    return {
        "research_log": log,
        "results_json_url": results_url,
    }

analyze_radiolabeled_antibody_biodistribution_tool = StructuredTool.from_function(
    name=Tools.analyze_radiolabeled_antibody_biodistribution,
    description="""
    【领域：生物】
        "分析放射性标记抗体的体内分布与药代动力学。执行双指数拟合，计算半衰期、平均滞留时间、AUC、清除率（血液/血浆），"
        "并生成肿瘤与正常组织的比值。\n\n"
        "返回：\n"
        "- research_log: 完整分析日志\n"
        "- results_json_url: 结果 JSON 文件链接""",
    args_schema=RadiolabeledAntibodyInput,
    coroutine=analyze_radiolabeled_antibody_biodistribution_coroutine,
    metadata={"args_schema_json": RadiolabeledAntibodyInput.schema()},
)




class AlphaParticleDosimetryInput(BaseModel):
    biodistribution_data: Dict[str, List[Tuple[float, float]]] = Field(
        ..., description="Organ/tissue biodistribution data. Each organ has a list of (time_hours, percent_injected_activity). Must include 'tumor'."
    )
    radiation_parameters: Dict[str, Any] = Field(
        ..., description="Radiation parameters: radionuclide, half_life_hours, energy_per_decay_MeV, radiation_weighting_factor, S_factors (dict of (source,target)->S-value)."
    )
    output_dir: Optional[str] = Field(
        None, description="Output directory (参数保留，实际通过上传获取链接)"
    )

async def estimate_alpha_particle_radiotherapy_dosimetry_coroutine(
    biodistribution_data: Dict[str, List[Tuple[float, float]]],
    radiation_parameters: Dict[str, Any],
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    import numpy as np
    from scipy.integrate import trapezoid
    from datetime import datetime
    import io, csv

    # Initialize log
    log = f"# Alpha-Particle Radiotherapy Dosimetry Estimation\n"
    log += f"- Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    log += f"- Radionuclide: {radiation_parameters['radionuclide']}\n"
    log += f"- Half-life: {radiation_parameters['half_life_hours']} hours\n\n"

    # Step 1: Time-integrated activity
    log += "## Step 1: Time-integrated activity (cumulated activity)\n"
    time_integrated_activity = {}
    decay_constant = np.log(2) / radiation_parameters["half_life_hours"]

    for organ, measurements in biodistribution_data.items():
        times = [m[0] for m in measurements]
        activities = [m[1] for m in measurements]
        decay_corrected_activities = [
            a * np.exp(-decay_constant * t) for a, t in zip(activities, times)
        ]
        cumulated_activity = trapezoid(decay_corrected_activities, times)
        time_integrated_activity[organ] = cumulated_activity
        log += f"- {organ}: {cumulated_activity:.4f} %IA-h\n"

    # Step 2: Absorbed dose using MIRD schema
    log += "\n## Step 2: Absorbed dose estimation (MIRD schema)\n"
    conversion_factor = 0.01  # %IA -> fraction IA
    s_factors = radiation_parameters["S_factors"]

    absorbed_doses = {}
    for target_organ in biodistribution_data.keys():
        absorbed_dose = 0
        for source_organ, cumulated_activity in time_integrated_activity.items():
            if (source_organ, target_organ) in s_factors:
                s_value = s_factors[(source_organ, target_organ)]
                organ_contribution = cumulated_activity * conversion_factor * s_value
                absorbed_dose += organ_contribution
        absorbed_dose *= radiation_parameters["radiation_weighting_factor"]
        absorbed_doses[target_organ] = absorbed_dose
        log += f"- {target_organ}: {absorbed_dose:.4f} Gy/MBq\n"

    # Step 3: Tumor-to-normal tissue ratios
    log += "\n## Step 3: Therapeutic indices (Tumor-to-normal dose ratios)\n"
    tumor_dose = absorbed_doses.get("tumor", 0)
    if tumor_dose > 0:
        for organ, dose in absorbed_doses.items():
            if organ != "tumor" and dose > 0:
                therapeutic_index = tumor_dose / dose
                log += f"- Tumor-to-{organ} ratio: {therapeutic_index:.2f}\n"

    # Save results CSV and upload
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow(["Organ", "Absorbed Dose (Gy/MBq)"])
    for organ, dose in absorbed_doses.items():
        writer.writerow([organ, f"{dose:.4f}"])

    results_url = await upload_content_to_minio(
        content=csv_buf.getvalue().encode("utf-8"),
        file_name="alpha_dosimetry_results.csv",
        file_extension=".csv",
        content_type="text/csv",
        no_expired=True,
    )

    return {
        "research_log": log,
        "results_csv_url": results_url,
    }

estimate_alpha_particle_radiotherapy_dosimetry_tool = StructuredTool.from_function(
    name=Tools.estimate_alpha_particle_radiotherapy_dosimetry,
    description="""
    【领域：生物】
        "基于 MIRD 模型估算 α 粒子放射性治疗的肿瘤和正常器官吸收剂量。\n"
        "输入小鼠体内分布数据和辐射参数，计算时间积分活度、吸收剂量、治疗指数（肿瘤/正常组织比）。\n\n"
        "返回：\n"
        "- research_log: 完整分析日志\n"
        "- results_csv_url: 剂量学结果 CSV 链接""",
    args_schema=AlphaParticleDosimetryInput,
    coroutine=estimate_alpha_particle_radiotherapy_dosimetry_coroutine,
    metadata={"args_schema_json": AlphaParticleDosimetryInput.schema()},
)




class PhysicochemicalPropertiesInput(BaseModel):
    smiles_string: str = Field(..., description="Molecular structure in SMILES format")
    output_dir: Optional[str] = Field(None, description="Output directory (参数保留，实际通过上传获取链接)")

async def calculate_physicochemical_properties_coroutine(
    smiles_string: str,
    output_dir: Optional[str] = None
) -> Dict[str, Any]:
    import io, csv
    from rdkit import Chem
    from rdkit.Chem import Descriptors, Lipinski, Crippen
    from rdkit.Chem.MolStandardize import rdMolStandardize

    # Create RDKit molecule from SMILES
    try:
        mol = Chem.MolFromSmiles(smiles_string)
        if mol is None:
            return {"research_log": "ERROR: Invalid SMILES string provided.", "properties_csv_url": None}
    except Exception as e:
        return {"research_log": f"ERROR: Failed to process SMILES string: {str(e)}", "properties_csv_url": None}

    # Calculate basic properties
    properties = {
        'SMILES': smiles_string,
        'Molecular Weight': round(Descriptors.MolWt(mol), 2),
        'cLogP': round(Descriptors.MolLogP(mol), 2),
        'TPSA': round(Descriptors.TPSA(mol), 2),
        'H-Bond Donors': Lipinski.NumHDonors(mol),
        'H-Bond Acceptors': Lipinski.NumHAcceptors(mol),
        'Rotatable Bonds': Descriptors.NumRotatableBonds(mol),
        'Heavy Atoms': mol.GetNumHeavyAtoms(),
        'Ring Count': Descriptors.RingCount(mol)
    }

    # Estimate acidic/basic groups
    uncharger = rdMolStandardize.Uncharger()
    uncharged_mol = uncharger.uncharge(mol)
    acidic_groups = sum(1 for atom in mol.GetAtoms() if atom.GetSymbol() == 'O' and 
                        any(neigh.GetSymbol() == 'C' and neigh.GetDegree() == 3 for neigh in atom.GetNeighbors()))
    basic_groups = sum(1 for atom in mol.GetAtoms() if atom.GetSymbol() == 'N' and atom.GetDegree() < 4)
    properties['Estimated Acidic Groups'] = acidic_groups
    properties['Estimated Basic Groups'] = basic_groups

    # Drug-likeness score
    properties['Drug-likeness Score'] = round(Crippen.MolMR(mol), 2)

    # logD estimate (simplified)
    properties['Estimated logD7.4'] = properties['cLogP']

    # Save results to CSV and upload
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow(['Property', 'Value'])
    for prop, value in properties.items():
        writer.writerow([prop, value])

    properties_csv_url = await upload_content_to_minio(
        content=csv_buf.getvalue().encode('utf-8'),
        file_name="physicochemical_properties.csv",
        file_extension=".csv",
        content_type="text/csv",
        no_expired=True
    )

    # Generate research log
    log = f"""Physicochemical Property Calculation Research Log:

Analyzed compound with SMILES: {smiles_string}

Key properties:
- Molecular Weight: {properties['Molecular Weight']} g/mol
- cLogP: {properties['cLogP']}
- Topological Polar Surface Area: {properties['TPSA']} Å²
- H-Bond Donors: {properties['H-Bond Donors']}
- H-Bond Acceptors: {properties['H-Bond Acceptors']}
- Rotatable Bonds: {properties['Rotatable Bonds']}
- Estimated logD (at pH 7.4): {properties['Estimated logD7.4']}
- Estimated Acidic Groups: {properties['Estimated Acidic Groups']}
- Estimated Basic Groups: {properties['Estimated Basic Groups']}
- Drug-likeness Score: {properties['Drug-likeness Score']}

Complete results saved to CSV via URL: {properties_csv_url}
"""

    return {"research_log": log, "properties_csv_url": properties_csv_url}

calculate_physicochemical_properties_tool = StructuredTool.from_function(
    name=Tools.calculate_physicochemical_properties,
    description="""
    【领域：生物】
        "计算药物分子关键理化性质（分子量、cLogP、TPSA、H-键受体/供体、可旋转键、酸/碱基团数、药物相似性评分等）。\n"
        "输入 SMILES 分子式，返回分析日志及详细结果 CSV 链接。\n\n"
        "返回：\n"
        "- research_log: 完整分析日志\n"
        "- properties_csv_url: 理化性质 CSV 链接""",
    args_schema=PhysicochemicalPropertiesInput,
    coroutine=calculate_physicochemical_properties_coroutine,
    metadata={"args_schema_json": PhysicochemicalPropertiesInput.schema()},
)


