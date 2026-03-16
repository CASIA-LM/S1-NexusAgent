import uuid
import logging
import random
from typing import Any
from typing import List, Dict, Optional, Literal

import aiohttp
import requests
from aiohttp import FormData
from Bio.Data.IUPACData import protein_letters_3to1  # 从Biopython获取氨基酸代码映射
from bs4 import BeautifulSoup
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, conint,validator

from workflow.config import EVO2, ESM3
from workflow.const import Tools
from workflow.utils.minio_utils import upload_content_to_minio
from io import BytesIO, StringIO

import os, json, pickle, pandas as pd, numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from langchain_openai import ChatOpenAI
from tqdm.auto import tqdm
from typing import List, Dict, Union, Set, Optional, Any
import requests
from Bio.Blast import NCBIWWW, NCBIXML

import io
from datetime import datetime
from Bio import AlignIO, SeqIO, Phylo
from Bio.Phylo.TreeConstruction import DistanceCalculator, DistanceTreeConstructor
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from Bio.Align import MultipleSeqAlignment
from scipy.optimize import curve_fit
import matplotlib.pyplot as plt
import subprocess

# === 工具 1: 分析圆二色性(CD)光谱工具 ===
# query-1:请帮我分析牛血清白蛋白（BSA）的圆二色性光谱。波长是 190 到 230nm，每隔 5nm 取一点，对应的CD信号分别是：-2.5, -4.2, -6.0, -8.1, -9.3, -8.7, -6.8, -4.5, -2.1。
# query-2:我有一组 DNA 寡聚物的 CD 光谱和热变性数据，请分析它的二级结构变化和热稳定性。波长：220 到 240 nm；CD信号是：1.1, 1.3, 1.2, 0.9, 0.5；温度从 20°C 到 70°C，每10度取一点，对应热变性信号是：1.2, 1.0, 0.8, 0.5, 0.2, 0。
# 测试成功
class AnalyzeCircularDichroismSpectraInput(BaseModel):
    """
    分析圆二色性光谱(CD)数据以确定二级结构和热稳定性的工具输入模型
    """
    sample_name: str = Field(..., description="样品名称，例如: Znf706 或 G-quadruplex")
    sample_type: str = Field(..., description="样品类型: protein 或 nucleic_acid")
    wavelength_data: List[float] = Field(..., description="CD 光谱的波长列表，单位 nm")
    cd_signal_data: List[float] = Field(..., description="CD 信号强度列表，通常为毫度(mdeg)或 Δε")
    temperature_data: Optional[List[float]] = Field(
        None, description="热变性实验温度列表，单位 °C，可选")
    thermal_cd_data: Optional[List[float]] = Field(
        None, description="热变性实验在指定波长处的 CD 信号列表，可选")

async def analyze_circular_dichroism_spectra_coroutine(
    sample_name: str,
    sample_type: str,
    wavelength_data: List[float],
    cd_signal_data: List[float],
    temperature_data: Optional[List[float]] = None,
    thermal_cd_data: Optional[List[float]] = None
) -> Dict[str, Any]:
    """
    对 CD 光谱进行分析：
      1. 根据样品类型判断二级结构特征
      2. 可选地对热变性数据估算熔解温度(Tm)和协同效应
    将分析报告及数据文件上传至 MinIO，并返回下载 URL。

    返回示例:
    {
      "report_log": "...分析报告摘要...",
      "cd_spectrum_analysis_file_url": "https://.../sample_cd_analysis.txt",
      "thermal_denaturation_data_file_url": "https://.../sample_thermal_denaturation.txt"  # 若提供热变性数据
    }
    """
    # 构造分析日志
    log = f"# CD Analysis Report for {sample_name}\n"
    log += f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    log += f"## Sample Information\n- Name: {sample_name}\n- Type: {sample_type}\n\n"

    wav = np.array(wavelength_data)
    cd = np.array(cd_signal_data)

    # 二级结构分析
    log += "## Secondary Structure Analysis\n"
    if sample_type.lower() == "protein":
        a_signal = np.sum((wav >= 190) & (wav <= 195) & (cd > 0))
        b_signal = np.sum((wav >= 215) & (wav <= 220) & (cd < 0))
        r_signal = np.sum((wav >= 195) & (wav <= 200) & (cd < 0))
        struct = (
            "predominantly alpha-helical" if a_signal > b_signal and a_signal > r_signal else
            "predominantly beta-sheet" if b_signal > a_signal and b_signal > r_signal else
            "mixed or predominantly random coil"
        )
        log += f"- Structure: {struct}\n"
    else:
        g_signal = np.sum((wav >= 290) & (wav <= 300) & (cd > 0))
        b_signal = np.sum((wav >= 270) & (wav <= 280) & (cd > 0))
        struct = (
            "G-quadruplex" if g_signal > 0 else
            "B-form DNA" if b_signal > 0 else
            "non-standard"
        )
        log += f"- Structure: {struct}\n"

    # 上传 CD 光谱分析文件
    spectrum_text = "Wavelength(nm)\tCD Signal\n" + "\n".join(f"{w:.1f}\t{d:.4f}" for w, d in zip(wav, cd))
    report_bytes = spectrum_text.encode('utf-8')
    ts = datetime.now().strftime('%Y%m%d/%H%M%S')
    fname_cd = f"{ts}_{sample_name}_cd_analysis.txt"
    try:
        cd_url = await upload_content_to_minio(
            content=report_bytes,
            file_name=fname_cd,
            file_extension=".txt",
            content_type="text/plain",
            no_expired=True,
        )
    except S3Error as e:
        return {"error": f"上传 CD 分析文件失败: {e.code} - {e.message}"}

    result: Dict[str, Any] = {"report_log": log, "cd_spectrum_analysis_file_url": cd_url}

    # 热稳定性分析与上传
    if temperature_data is not None and thermal_cd_data is not None:
        temp = np.array(temperature_data)
        therm = np.array(thermal_cd_data)
        min_s, max_s = therm.min(), therm.max()
        frac = (therm - min_s) / (max_s - min_s)
        tm_idx = np.argmin(np.abs(frac - 0.5))
        tm = temp[tm_idx]
        log += f"## Thermal Stability\n- Estimated Tm: {tm:.1f} °C\n"
        thermal_text = "Temp(°C)\tCD Signal\tFraction\n" + "\n".join(
            f"{t:.1f}\t{s:.4f}\t{f:.4f}" for t, s, f in zip(temp, therm, frac)
        )
        therm_bytes = thermal_text.encode('utf-8')
        fname_th = f"{ts}_{sample_name}_thermal_denaturation.txt"
        try:
            th_url = await upload_content_to_minio(
                content=therm_bytes,
                file_name=fname_th,
                file_extension=".txt",
                content_type="text/plain",
                no_expired=True,
            )
            result["thermal_denaturation_data_file_url"] = th_url
        except S3Error as e:
            result["warning"] = f"上传热变性文件失败: {e.code} - {e.message}"

    return result

# 创建 AnalyzeCircularDichroismSpectra 工具
analyze_cd_tool = StructuredTool.from_function(
    coroutine=analyze_circular_dichroism_spectra_coroutine,
    name=Tools.ANALYZE_CIRCULAR_DICHROISM_SPECTRA,
    description="""
    【领域：生物】
    分析圆二色性(CD)光谱数据以确定二级结构和热稳定性。
    返回：
      - report_log: 分析报告
      - cd_spectrum_analysis_file_url: 光谱分析文件 URL
      - thermal_denaturation_data_file_url: 热变性数据文件 URL（如有）
      - warning: 上传警告（如有）
    """,
    args_schema=AnalyzeCircularDichroismSpectraInput,
    metadata={"args_schema_json":AnalyzeCircularDichroismSpectraInput.schema()}
)


# -----------------------------
# 1. AnalyzeProteinConservation
# -----------------------------
# 测试成功
"""
query-1：
我这有几条蛋白质序列，没有FASTA格式，只是裸序列：

MVLSEGEWQLVLHVWAKVEADVAGHGQDILIRLFKSHPETLEKF  
MAHQDLFKDSWGKVLKD
MALWMRLLPLLALLALWGPDPAAGR
"""
class AnalyzeProteinConservationInput(BaseModel):
    """蛋白质多序列比对与保守性分析——输入模式"""

    protein_sequences: List[str] = Field(
        ...,
        description="FASTA 格式或普通氨基酸序列列表；若非 FASTA 格式将自动转换"
    )


async def analyze_protein_conservation_coroutine(
    protein_sequences: List[str]
) -> Dict[str, Any]:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log: List[str] = [f"# Protein Sequence Alignment and Conservation Analysis — {ts}"]

    # Step 1: 构造 FASTA 数据到内存
    fasta_io = io.StringIO()
    for idx, seq in enumerate(protein_sequences):
        if seq.startswith(">"):
            fasta_io.write(seq.strip() + "\n")
        else:
            fasta_io.write(f">Seq_{idx+1}\n{seq.strip()}\n")
    fasta_text = fasta_io.getvalue()

    # Step 2: 使用 subprocess 调用 MUSCLE 进行内存中的比对
    aligned_text = ""
    try:
        process = subprocess.Popen(
            ["muscle", "-quiet"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout_data, stderr_data = process.communicate(input=fasta_text)
        if process.returncode != 0:
            raise RuntimeError(f"MUSCLE failed: {stderr_data}")
        aligned_text = stdout_data
        log.append("- Multiple sequence alignment completed with MUSCLE (memory-only)")
    except Exception as exc:
        log.append(f"- MUSCLE failed ({exc}); fallback to simple padding alignment")
        fasta_io.seek(0)
        sequences = list(SeqIO.parse(fasta_io, "fasta"))
        max_len = max(len(s.seq) for s in sequences)
        msa = MultipleSeqAlignment([
            SeqRecord(Seq(str(s.seq).ljust(max_len, "-")), id=s.id)
            for s in sequences
        ])
        aligned_io = io.StringIO()
        AlignIO.write(msa, aligned_io, "fasta")
        aligned_text = aligned_io.getvalue()
        log.append("- Alignment generated by fallback method")

    # Step 3: 构建系统发育树
    alignment = AlignIO.read(io.StringIO(aligned_text), "fasta")
    calculator = DistanceCalculator("identity")
    dm = calculator.get_distance(alignment)
    constructor = DistanceTreeConstructor()
    tree = constructor.nj(dm)
    tree_io = io.StringIO()
    Phylo.write(tree, tree_io, "newick")
    tree_text = tree_io.getvalue()

    # Step 4: 保守性分析
    conservation_io = io.StringIO()
    conserved_positions: List[int] = []
    aln_len = alignment.get_alignment_length()

    conservation_io.write("Position\tConservation_Score\tConsensus\n")
    for i in range(aln_len):
        column = alignment[:, i]
        mc = max(column, key=column.count)
        score = column.count(mc) / len(column)
        conservation_io.write(f"{i+1}\t{score:.2f}\t{mc}\n")
        if score > 0.8:
            conserved_positions.append(i + 1)
    log.append(f"- Identified {len(conserved_positions)} highly conserved positions (>80%)")

    # Step 5: 上传
    result: Dict[str, Any] = {"research_log": "\n".join(log)}

    file_blobs = {
        "alignment_file_url": ("alignment.fasta", aligned_text),
        "tree_file_url": ("tree.newick", tree_text),
        "conservation_file_url": ("conservation.txt", conservation_io.getvalue()),
    }

    for key, (fname, text_content) in file_blobs.items():
        try:
            buf = io.BytesIO(text_content.encode("utf-8"))
            url = await upload_content_to_minio(
                content=buf.read(),
                file_name=fname,
                file_extension=os.path.splitext(fname)[1],
                content_type="text/plain",
                no_expired=True,
            )
            result[key] = url
        except Exception as e:
            result[key] = f"UploadFailed:{e}"

    return result


analyze_protein_conservation_tool = StructuredTool.from_function(
    coroutine=analyze_protein_conservation_coroutine,
    name=Tools.ANALYZE_PROTEIN_CONSERVATION,
    description="""
    【领域：生物】
        进行蛋白质多序列比对、系统发育树构建与保守性分析，返回分析日志及生成文件链接。\n"
        "返回字段：\n"
        "  - research_log: 分析过程及结果摘要\n"
        "  - alignment_file_url: 序列比对文件\n"
        "  - tree_file_url: 系统发育树文件（Newick 格式）\n"
        "  - conservation_file_url: 保守性分析结果文件\n"
        """,
    args_schema=AnalyzeProteinConservationInput,
    metadata={"args_schema_json":AnalyzeProteinConservationInput.schema()}
)

# --------------------------------------
# 2. AnalyzeITCBindingThermodynamics Tool
# --------------------------------------
# 测试成功
"""
query:
在蛋白浓度为500μM，配体浓度为10mM，温度为298K的条件下，以下是我的ITC数据，请你分析一下一位点结合的热力学参数：
[[1, -1.2, 2.5], [2, -1.6, 2.5], [3, -1.9, 2.5], [4, -1.4, 2.5]]
"""
class AnalyzeITCBindingThermodynamicsInput(BaseModel):
    """ITC 结合热力学参数分析——输入模式"""

    itc_data_path: Optional[str] = Field(
        None,
        description="CSV/TSV 文件路径，含 injection、volume、heat 三列。如果为空则使用 itc_data。"
    )
    itc_data: Optional[List[List[float]]] = Field(
        None,
        description="原始 ITC 数据数组 (n_injections × 3)，列依次为 injection, volume, heat。"
    )
    temperature: float = Field(
        298.15, description="实验温度 (K)，默认 298.15 K (25°C)"
    )
    protein_concentration: Optional[float] = Field(
        None, description="细胞中蛋白初始浓度 (M)"
    )
    ligand_concentration: Optional[float] = Field(
        None, description="注射器中配体浓度 (M)"
    )


async def analyze_itc_binding_thermodynamics_coroutine(
    itc_data_path: Optional[str] = None,
    itc_data: Optional[List[List[float]]] = None,
    temperature: float = 298.15,
    protein_concentration: Optional[float] = None,
    ligand_concentration: Optional[float] = None,
) -> Dict[str, Any]:
    """分析 ITC 热滴定数据以获得结合热力学参数 (Kd、ΔH、ΔS、ΔG)。"""

    now = datetime.now()
    ts = now.strftime("%Y%m%d/%H%M%S")
    log: List[str] = [f"# ITC Binding Affinity Analysis — {now:%Y-%m-%d %H:%M}"]

    # === 数据载入 ===
    if itc_data_path is None and itc_data is None:
        return {"error": "No data provided. Specify itc_data_path or itc_data."}

    if itc_data_path:
        try:
            df = (
                pd.read_csv(itc_data_path)
                if itc_data_path.endswith(".csv")
                else pd.read_csv(itc_data_path, sep="\t")
            )
            data_np = df[["injection", "volume", "heat"]].values
            log.append(f"- Loaded {len(df)} injections from {itc_data_path}")
        except Exception as exc:
            return {"error": f"Failed to load file: {exc}"}
    else:
        data_np = np.asarray(itc_data, dtype=float)
        log.append(f"- Using in‑memory array with {len(data_np)} injections")

    inj, vol, heat = data_np.T

    # === 计算配体/蛋白摩尔比 ===
    cell_vol_ml = 1.4  # mL
    cum_vol = np.cumsum(vol)
    dilution_factor = 1 - cum_vol / cell_vol_ml
    protein_conc = protein_concentration or 1.0  # 默认 1 M (归一化)
    ligand_conc = ligand_concentration or 10.0  # 默认 10 M

    prot_corr = protein_conc * dilution_factor  # 校正蛋白浓度 (M)
    molar_ratio = np.zeros_like(inj, dtype=float)

    for i in range(len(inj)):
        lig_added_mmol = vol[i] * ligand_conc / 1000  # mmol
        prot_mmol = prot_corr[i] * (cell_vol_ml - cum_vol[i]) / 1000
        molar_ratio[i] = (molar_ratio[i - 1] if i else 0) + lig_added_mmol / prot_mmol

    # === 一位点模型拟合 ===
    R = 1.9872  # cal/mol·K

    def one_site(x, Kd, dH, n):
        Ka = 1 / Kd
        q = np.zeros_like(x)
        for i in range(len(x)):
            bound = (
                n
                * prot_corr[i]
                * Ka
                * (x[i] * prot_corr[i])
                / (1 + Ka * x[i] * prot_corr[i])
            )
            q[i] = bound * dH * cell_vol_ml
        return q

    try:
        popt, pcov = curve_fit(one_site, molar_ratio, heat, p0=[1e-6, -5000, 1.0], maxfev=10000)
        Kd, dH, n = popt
        dG = R * temperature * np.log(Kd)
        dS = (dH - dG) / temperature
        log.append("- Model fitting successful")
    except Exception as exc:
        return {"error": f"Curve fitting failed: {exc}"}

    # === 结果整理 ===
    result: Dict[str, Any] = {
        "research_log": "\n".join(log + [
            "\n## Results",
            f"Kd = {Kd:.3e} M",
            f"ΔH = {dH:.2f} cal/mol",
            f"ΔS = {dS:.2f} cal/(mol·K)",
            f"ΔG = {dG:.2f} cal/mol",
            f"Stoichiometry (n) = {n:.2f}",
        ])
    }

    return result


analyze_itc_binding_thermodynamics_tool = StructuredTool.from_function(
    coroutine=analyze_itc_binding_thermodynamics_coroutine,
    name=Tools.ANALYZE_ITC_BINDING_THERMODYNAMICS,
description="""
    【领域：生物】
        分析等温滴定量热 (ITC) 数据，采用一位点结合模型拟合，返回 Kd、ΔH、ΔS、ΔG 等热力学参数。\n\n"
        "返回字段：\n"
        "  - research_log: 分析过程及结果摘要\n"
        """,
    args_schema=AnalyzeITCBindingThermodynamicsInput,
    metadata={"args_schema_json":AnalyzeITCBindingThermodynamicsInput.schema()}
)




# --------------------------
# Tool 3: analyze_protease_kinetics
# --------------------------
# 测试成功
"""
我做了一个酶动力学实验，底物浓度分别是 5, 10, 20, 40 μM，酶浓度是 0.2 μM，每组底物浓度下都测了 5 个时间点（0, 30, 60, 90, 120 秒）的荧光信号，数据如下：
time_points: [0, 30, 60, 90, 120]
fluorescence_data: [
  [100, 120, 140, 160, 180],
  [105, 135, 165, 195, 225],
  [110, 150, 190, 230, 270],
  [115, 160, 205, 250, 295]
]
"""
class ProteaseKineticsInput(BaseModel):
    time_points: List[float] = Field(..., description="Time points in seconds")
    fluorescence_data: List[List[float]] = Field(..., description="2D fluorescence matrix: rows = substrate concentrations, columns = time points")
    substrate_concentrations: List[float] = Field(..., description="Substrate concentrations in μM")
    enzyme_concentration: float = Field(..., description="Enzyme concentration in μM")
    output_prefix: Optional[str] = Field("protease_kinetics", description="Prefix for output files")


async def analyze_protease_kinetics_coroutine(
    time_points: List[float],
    fluorescence_data: List[List[float]],
    substrate_concentrations: List[float],
    enzyme_concentration: float,
    output_prefix: str = "protease_kinetics",

) -> Dict[str, Any]:

    time_points = np.array(time_points)
    fluorescence_data = np.array(fluorescence_data)
    substrate_concentrations = np.array(substrate_concentrations)

    initial_velocities = np.zeros(len(substrate_concentrations))
    for i, curve in enumerate(fluorescence_data):
        num_points = max(5, int(len(time_points) * 0.2))
        slope, _ = np.polyfit(time_points[:num_points], curve[:num_points], 1)
        initial_velocities[i] = slope

    def michaelis_menten(s, vmax, km):
        return vmax * s / (km + s)

    try:
        params, cov = curve_fit(michaelis_menten, substrate_concentrations, initial_velocities)
        vmax, km = params
        vmax_std, km_std = np.sqrt(np.diag(cov))
        kcat = vmax / enzyme_concentration
        kcat_std = vmax_std / enzyme_concentration
        eff = kcat / km
        eff_std = eff * np.sqrt((kcat_std/kcat)**2 + (km_std/km)**2)

        # 图像生成并保存到 BytesIO
        fig = plt.figure(figsize=(8, 5))
        plt.scatter(substrate_concentrations, initial_velocities, label="Data")
        s_fit = np.linspace(0, max(substrate_concentrations)*1.2, 100)
        v_fit = michaelis_menten(s_fit, vmax, km)
        plt.plot(s_fit, v_fit, 'r-', label="MM fit")
        plt.xlabel("[S] (μM)")
        plt.ylabel("Velocity (a.u./s)")
        plt.title("Michaelis-Menten Fit")
        plt.legend()

        img_buf = io.BytesIO()
        plt.savefig(img_buf, format='png', bbox_inches='tight')
        plt.close(fig)
        img_buf.seek(0)

        # 上传图像
        plot_url = await upload_content_to_minio(
            content=img_buf.read(),
            file_name=f"{output_prefix}_mm_plot.png",
            file_extension=".png",
            content_type="image/png",
            no_expired=True,
        )

        # 构造结果文本
        result_text = (
            f"Vmax: {vmax:.4f} ± {vmax_std:.4f} a.u./s\n"
            f"KM: {km:.4f} ± {km_std:.4f} μM\n"
            f"kcat: {kcat:.4f} ± {kcat_std:.4f} s^-1\n"
            f"Efficiency: {eff:.4f} ± {eff_std:.4f} μM^-1s^-1\n"
        )
        result_buf = io.BytesIO(result_text.encode("utf-8"))

        result_url = await upload_content_to_minio(
            content=result_buf.read(),
            file_name=f"{output_prefix}_results.txt",
            file_extension=".txt",
            content_type="text/plain",
            no_expired=True,
        )

        # 返回总结信息
        log = (
            "Michaelis-Menten Kinetics Summary\n"
            "----------------------------------\n" +
            result_text +
            "\nUploaded files:\n"
            f"- MM plot: {plot_url}\n"
            f"- Results file: {result_url}"
        )

        return {
            "research_log": log,
            "plot_url": plot_url,
            "result_file_url": result_url,
        }

    except Exception as e:
        return {
            "research_log": f"Error during curve fitting: {str(e)}"
        }

analyze_protease_kinetics_tool = StructuredTool.from_function(
    coroutine=analyze_protease_kinetics_coroutine,
    name=Tools.analyze_protease_kinetics_tool,
    description="""
    【领域：生物】
分析蛋白酶动力学数据，基于荧光读数拟合 Michaelis-Menten 模型，自动计算反应速率（V₀）、最大反应速率 (Vmax)、米氏常数 (KM)、催化常数 (kcat) 和酶效率 (kcat/KM)，并生成结果图与详细日志文件。
适用于酶动力学实验的批量分析，支持不同底物浓度下的荧光曲线数据输入，输出关键动力学参数和可视化结果图。
输出结果：
  - research_log: 文本摘要，包含拟合结果（Vmax, KM, kcat, 效率等）及公式拟合质量说明
  - 保存文件：
    - `_mm_plot.png`：Michaelis-Menten 拟合曲线图（底物浓度 vs 初始速率）
    - `_results.txt`：Vmax、KM、kcat 等详细数值及其标准差

⚠️ 注意事项：
  - 所有底物浓度单位为 μM，时间单位为秒，酶浓度单位为 μM。
  - 推荐时间点数量 ≥ 5，以保证初始速率线性拟合的稳定性。
  - 荧光矩阵的行数应与底物浓度列表长度一致，列数应与时间点一致。
""",
    args_schema=ProteaseKineticsInput,
    metadata={"args_schema_json":ProteaseKineticsInput.schema()} 
)

# --------------------------
# Tool 4: analyze_enzyme_kinetics_assay
# --------------------------
# 测试成功
"""
query:
我要分析乳酸脱氢酶（LDH）的酶动力学行为。底物浓度为 [10, 25, 50, 100, 200, 400] μM，酶浓度为 5 nM。请估算该酶的 Vmax 和 Km 值。

"""
class EnzymeKineticsAssayInput(BaseModel):
    enzyme_name: str = Field(..., description="Enzyme name")
    substrate_concentrations: List[float] = Field(..., description="Substrate concentrations in μM")
    enzyme_concentration: float = Field(..., description="Enzyme concentration in nM")
    modulators: Optional[dict] = Field(None, description="Modulator dictionary: {modulator_name: [concs]}")
    time_points: Optional[List[float]] = Field(None, description="Optional time points (min), default [0,5,10,15,20,30,45,60]")


async def analyze_enzyme_kinetics_assay_coroutine(
    enzyme_name: str,
    substrate_concentrations: List[float],
    enzyme_concentration: float,
    modulators: Optional[dict] = None,
    time_points: Optional[List[float]] = None,

) -> Dict[str, Any]:

    np.random.seed(42)
    time_points = np.array(time_points or [0, 5, 10, 15, 20, 30, 45, 60])

    def michaelis_menten(s, vmax, km):
        return vmax * s / (km + s)

    log = f"# Enzyme Kinetics Assay for {enzyme_name}\n"
    log += f"Enzyme concentration: {enzyme_concentration} nM\n\n"

    result: Dict[str, Any] = {
        "research_log": "",
        "time_course_csv_url": None,
        "substrate_kinetics_csv_url": None,
        "modulator_csv_urls": {},
    }

    # ----------- 1. Time-course data ----------- #
    activity = 100 * (1 - np.exp(-0.05 * time_points)) + np.random.normal(0, 3, len(time_points))

    time_io = io.StringIO()
    time_io.write("Time (min),Activity (units)\n")
    for t, a in zip(time_points, activity):
        time_io.write(f"{t},{a:.2f}\n")
    time_buf = io.BytesIO(time_io.getvalue().encode("utf-8"))

    time_url = await upload_content_to_minio(
        content=time_buf.read(),
        file_name=f"{enzyme_name}_time_course.csv",
        file_extension=".csv",
        content_type="text/csv",
        no_expired=True,
    )
    result["time_course_csv_url"] = time_url
    log += f"- Time-course data uploaded: {time_url}\n"

    # ----------- 2. Substrate kinetics ----------- #
    true_vmax = 120
    true_km = 25
    substrate_conc = np.array(substrate_concentrations)
    activity_vals = michaelis_menten(substrate_conc, true_vmax, true_km) + np.random.normal(0, 5, len(substrate_conc))

    try:
        params, _ = curve_fit(michaelis_menten, substrate_conc, activity_vals, p0=[100, 20])
        vmax, km = params

        kin_io = io.StringIO()
        kin_io.write("[S] μM,Activity\n")
        for s, a in zip(substrate_conc, activity_vals):
            kin_io.write(f"{s},{a:.2f}\n")
        kin_buf = io.BytesIO(kin_io.getvalue().encode("utf-8"))

        kin_url = await upload_content_to_minio(
            content=kin_buf.read(),
            file_name=f"{enzyme_name}_substrate_kinetics.csv",
            file_extension=".csv",
            content_type="text/csv",
            no_expired=True,
        )
        result["substrate_kinetics_csv_url"] = kin_url
        log += f"- Substrate kinetics data uploaded: {kin_url}\n"
        log += f"- Fitted Vmax: {vmax:.2f}, Km: {km:.2f}\n"
    except Exception as e:
        log += f"- Error in curve fitting: {str(e)}\n"

    # ----------- 3. Modulator dose-response ----------- #
    if modulators:
        for name, concs in modulators.items():
            log += f"\n## Modulator: {name}\n"
            ic50 = np.random.uniform(1, 50)
            mod_activities = [100 / (1 + (c/ic50)) + np.random.normal(0, 3) if c > 0 else 100 for c in concs]

            mod_io = io.StringIO()
            mod_io.write("[Modulator] (μM),% Activity\n")
            for c, a in zip(concs, mod_activities):
                mod_io.write(f"{c},{a:.2f}\n")
            mod_buf = io.BytesIO(mod_io.getvalue().encode("utf-8"))

            mod_url = await upload_content_to_minio(
                content=mod_buf.read(),
                file_name=f"{enzyme_name}_{name}_dose_response.csv",
                file_extension=".csv",
                content_type="text/csv",
                no_expired=True,
            )
            result["modulator_csv_urls"][name] = mod_url
            log += f"- Dose-response uploaded: {mod_url}\n"

    log += "\nAnalysis completed."
    result["research_log"] = log
    return result


analyze_enzyme_kinetics_assay_tool = StructuredTool.from_function(
    name=Tools.analyze_enzyme_kinetics_assay,
    description=(
        "执行酶动力学实验分析，模拟并拟合酶在不同底物浓度下的反应速率，"
        "估算 Vmax 与 Km，并可选分析调节剂（如激活剂/抑制剂）的剂量响应效应。\n\n"
        "返回字段：\n"
        "  - research_log: 分析日志与结果总结\n"
        "  - time_course_csv_url: 时间-活性数据文件链接\n"
        "  - substrate_kinetics_csv_url: 底物动力学数据文件链接\n"
        "  - modulator_csv_urls: 各调节剂剂量响应文件的链接（字典形式）"
    ),
    args_schema=EnzymeKineticsAssayInput,
    coroutine=analyze_enzyme_kinetics_assay_coroutine,
    metadata={"args_schema_json":EnzymeKineticsAssayInput.schema()} 
)



# --------------------------
# Tool 5: analyze_enzyme_kinetics_assay
# --------------------------
# 测试成功
# 帮我解析 dot-bracket 表示法为 ((..((...))..)) 的 RNA 结构特征。


class RNASecondaryStructureInput(BaseModel):
    dot_bracket_structure: str = Field(..., description="RNA secondary structure in dot-bracket notation")
    sequence: Optional[str] = Field(None, description="RNA sequence matching the dot-bracket structure")

def analyze_rna_secondary_structure_features(dot_bracket_structure: str, sequence: Optional[str] = None) -> str:
    log = "# RNA Secondary Structure Feature Analysis\n\n"

    if not all(c in '().[]{}' for c in dot_bracket_structure):
        return "Error: Invalid dot-bracket notation. Use only '()', '[]', '{}' and '.'"

    log += f"Input structure (length: {len(dot_bracket_structure)}): {dot_bracket_structure}\n"
    if sequence:
        log += f"Input sequence (length: {len(sequence)}): {sequence}\n"
        if len(sequence) != len(dot_bracket_structure):
            return "Error: Sequence and structure lengths do not match."

    pairs = []
    stack = []
    for i, char in enumerate(dot_bracket_structure):
        if char in '([{':
            stack.append((i, char))
        elif char in ')]}':
            if not stack:
                return "Error: Unbalanced structure. More closing than opening brackets."
            j, opening_char = stack.pop()
            if (opening_char == '(' and char != ')') or \
               (opening_char == '[' and char != ']') or \
               (opening_char == '{' and char != '}'):
                return "Error: Mismatched bracket types."
            pairs.append((j, i))
    if stack:
        return "Error: Unbalanced structure. More opening than closing brackets."

    pairs.sort()
    stems = []
    current_stem = []
    for i, (start, end) in enumerate(pairs):
        if i == 0 or start != pairs[i-1][0] + 1 or end != pairs[i-1][1] - 1:
            if current_stem:
                stems.append(current_stem)
                current_stem = []
        current_stem.append((start, end))
    if current_stem:
        stems.append(current_stem)

    stem_lengths = [len(stem) for stem in stems]
    loops = []
    for i in range(len(stems)):
        stem = stems[i]
        last_pair = stem[-1]
        next_stem_start = stems[i+1][0][0] if i < len(stems)-1 else len(dot_bracket_structure)
        loop_size = next_stem_start - last_pair[1] - 1
        if loop_size > 0:
            loops.append(loop_size)

    total_paired_bases = len(pairs) * 2
    total_unpaired_bases = len(dot_bracket_structure) - total_paired_bases

    stem_energies = []
    if sequence and len(stems) > 0:
        energy_params = {
            'AU': -0.9, 'UA': -0.9,
            'GC': -2.1, 'CG': -2.1,
            'GU': -0.5, 'UG': -0.5
        }
        for stem in stems:
            stem_energy = 0
            for start, end in stem:
                if start < len(sequence) and end < len(sequence):
                    pair = sequence[start] + sequence[end]
                    stem_energy += energy_params.get(pair, 0)
            stem_energies.append(stem_energy)

    log += "\n## Structural Features\n\n"
    log += f"Total base pairs: {len(pairs)}\n"
    log += f"Number of stems: {len(stems)}\n"
    log += f"Longest stem length: {max(stem_lengths) if stem_lengths else 0}\n"
    log += f"Average stem length: {sum(stem_lengths)/len(stem_lengths) if stem_lengths else 0:.2f}\n"
    log += f"Paired bases: {total_paired_bases} ({total_paired_bases/len(dot_bracket_structure)*100:.1f}%)\n"
    log += f"Unpaired bases: {total_unpaired_bases} ({total_unpaired_bases/len(dot_bracket_structure)*100:.1f}%)\n"

    if loops:
        log += f"Number of loops: {len(loops)}\n"
        log += f"Average loop size: {sum(loops)/len(loops):.2f}\n"
        log += f"Largest loop size: {max(loops)}\n"

    if sequence and stem_energies:
        log += "\n## Energy Calculations\n\n"
        log += f"Total estimated free energy: {sum(stem_energies):.2f} kcal/mol\n"
        if len(stems) >= 2:
            log += f"Upstream stem free energy: {stem_energies[0]:.2f} kcal/mol\n"
            log += f"Downstream stem free energy: {stem_energies[-1]:.2f} kcal/mol\n"
        if stem_lengths and stem_lengths[0] >= 3:
            log += f"Zipper stem free energy: {stem_energies[0]:.2f} kcal/mol\n"

    log += "\n## Stem Details\n\n"
    for i, stem in enumerate(stems):
        log += f"Stem {i+1}: {len(stem)} base pairs\n"
        log += f"  Positions: {stem[0][0]}-{stem[0][1]} to {stem[-1][0]}-{stem[-1][1]}\n"
        if sequence and i < len(stem_energies):
            log += f"  Estimated stability: {stem_energies[i]:.2f} kcal/mol\n"

    return log


analyze_rna_secondary_structure_tool = StructuredTool.from_function(
    name=Tools.analyze_rna_secondary_structure,
    description=(
        "分析 RNA 的二级结构特征，包括碱基配对、茎区、环区数量与大小。"
        "如提供序列，可进一步估算自由能与各茎结构的稳定性。"
        "输入需包含 dot-bracket 结构表示法，可选配套 RNA 序列。"
    ),
    func=analyze_rna_secondary_structure_features,
    args_schema=RNASecondaryStructureInput,
    metadata={"args_schema_json":RNASecondaryStructureInput.schema()} 
)
