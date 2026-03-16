
from typing import Any
from typing import List, Dict, Optional, Literal

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
# 标准库
import io
from datetime import datetime
from typing import Any, List, Dict
# 科学计算
from scipy.optimize import curve_fit

# 图像处理
import matplotlib.pyplot as plt
# LangChain
from langchain_core.tools import StructuredTool
# Pydantic
from pydantic import BaseModel, Field

# 项目内部模块
from workflow.const import Tools
from workflow.utils.minio_utils import upload_content_to_minio


# 图像处理

import matplotlib.pyplot as plt
from tqdm.auto import tqdm
from typing import List, Dict, Union, Set, Optional, Any
import requests

import io
from datetime import datetime
from scipy.optimize import curve_fit
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
# Tool 1: Cell Migration Metrics
# 需tif文件,未测试
class CellMigrationMetricsInput(BaseModel):
    image_sequence_path: str = Field(..., description="Path to directory of time-lapse images or multi-frame TIFF file")
    pixel_size_um: float = Field(1.0, description="Conversion factor from pixels to micrometers (default: 1.0)")
    time_interval_min: float = Field(1.0, description="Time between frames in minutes (default: 1.0)")
    min_track_length: int = Field(10, description="Minimum frames a cell must be tracked to include (default: 10)")


async def analyze_cell_migration_metrics(
    image_sequence_path: str,
    pixel_size_um: float = 1.0,
    time_interval_min: float = 1.0,
    min_track_length: int = 10,
   
) -> Dict[str, Any]:
    """
    从时间序列显微镜图像中分析细胞迁移行为，计算并上传以下结果：
      1. 原始检测结果（CSV）
      2. 全部轨迹（CSV）
      3. 过滤后轨迹（CSV）
      4. 细胞迁移指标（CSV）

    返回包含各文件链接和分析日志的字典。
    """
    import os
    import numpy as np
    import pandas as pd
    import io
    import trackpy as tp
    from skimage import io as skio
    from upload import upload_content_to_minio

    log = f"# Cell Migration Analysis Log for {image_sequence_path}\n"

    # Load frames
    if os.path.isdir(image_sequence_path):
        files = sorted([f for f in os.listdir(image_sequence_path) if f.lower().endswith(('.tif','.tiff','.png','.jpg'))])
        frames = [skio.imread(os.path.join(image_sequence_path, f)) for f in files]
    else:
        frames = skio.imread(image_sequence_path)
        if frames.ndim != 3:
            return {"research_log": f"Error: 无效的图像序列", "raw_detections_csv_url": None}
    num_frames = len(frames)
    log += f"Loaded {num_frames} frames\n\n"

    # Step 1: Detect cells
    features_list = []
    for i, frame in enumerate(frames):
        feats = tp.locate(frame, diameter=15, minmass=100)
        if feats is not None and not feats.empty:
            feats['frame'] = i
            features_list.append(feats)
    if not features_list:
        return {"research_log": "Error: 未检测到细胞", "raw_detections_csv_url": None}
    all_features = pd.concat(features_list)

    # Upload raw detections
    buf = io.StringIO(); all_features.to_csv(buf, index=False)
    raw_url = await upload_content_to_minio(
        content=buf.getvalue().encode('utf-8'),
        file_name="raw_cell_detections.csv",
        file_extension=".csv",
        content_type="text/csv",
        no_expired=True
    )
    log += f"- Raw detections uploaded: {raw_url}\n"

    # Step 2: Link trajectories
    traj = tp.link_df(all_features, search_range=10, memory=3).reset_index(drop=True)
    buf = io.StringIO(); traj.to_csv(buf, index=False)
    all_traj_url = await upload_content_to_minio(
        content=buf.getvalue().encode('utf-8'),
        file_name="all_trajectories.csv",
        file_extension=".csv",
        content_type="text/csv",
        no_expired=True
    )
    log += f"- All trajectories uploaded: {all_traj_url}\n"

    # Step 3: Filter trajectories
    filt = tp.filter_stubs(traj, threshold=min_track_length)
    if filt.empty:
        return {"research_log": "No complete tracks found", "raw_detections_csv_url": raw_url}
    filt = filt.reset_index(drop=True)
    buf = io.StringIO(); filt.to_csv(buf, index=False)
    filt_url = await upload_content_to_minio(
        content=buf.getvalue().encode('utf-8'),
        file_name="filtered_trajectories.csv",
        file_extension=".csv",
        content_type="text/csv",
        no_expired=True
    )
    log += f"- Filtered trajectories uploaded: {filt_url}\n"

    # Step 4: Compute metrics
    metrics = []
    for cid in filt['particle'].unique():
        tr = filt[filt['particle']==cid].sort_values('frame')
        tr['x_um'] = tr['x'] * pixel_size_um
        tr['y_um'] = tr['y'] * pixel_size_um
        dx, dy = np.diff(tr['x_um']), np.diff(tr['y_um'])
        steps = np.sqrt(dx**2 + dy**2)
        path = steps.sum()
        disp = np.hypot(tr.iloc[-1]['x_um']-tr.iloc[0]['x_um'], tr.iloc[-1]['y_um']-tr.iloc[0]['y_um'])
        duration = (tr['frame'].max()-tr['frame'].min())*time_interval_min
        speed = path/duration if duration>0 else 0
        dir_ratio = disp/path if path>0 else 0
        metrics.append({
            'cell_id': cid,
            'frames_tracked': len(tr),
            'speed_um_per_min': speed,
            'directionality': dir_ratio,
            'displacement_um': disp,
            'path_length_um': path
        })
    mdf = pd.DataFrame(metrics)
    buf = io.StringIO(); mdf.to_csv(buf, index=False)
    metrics_url = await upload_content_to_minio(
        content=buf.getvalue().encode('utf-8'),
        file_name="cell_migration_metrics.csv",
        file_extension=".csv",
        content_type="text/csv",
        no_expired=True
    )
    log += f"- Metrics uploaded: {metrics_url}\n"

    return {
        "research_log": log,
        "raw_detections_csv_url": raw_url,
        "all_trajectories_csv_url": all_traj_url,
        "filtered_trajectories_csv_url": filt_url,
        "metrics_csv_url": metrics_url
    }

cell_migration_metrics_tool = StructuredTool.from_function(
    name=Tools.analyze_cell_migration_metrics,
   description="""
    【领域：生物】
        "分析细胞迁移速率与行为特征，支持从目录或多帧 TIFF 图像序列中检测、追踪细胞，"
        "并计算关键迁移指标，包括速度、位移、方向性比率等。\n\n"
        "返回字段：\n"
        "  - research_log: 分析日志与结果总结\n"
        "  - raw_detections_csv_url: 原始检测结果文件链接\n"
        "  - all_trajectories_csv_url: 全部轨迹文件链接\n"
        "  - filtered_trajectories_csv_url: 过滤后轨迹文件链接\n"
        "  - metrics_csv_url: 迁移指标文件链接"
    """,
    args_schema=CellMigrationMetricsInput,
    coroutine=analyze_cell_migration_metrics,
    metadata={"args_schema_json":CellMigrationMetricsInput.schema()} 
)

# Tool 2: CRISPR-Cas9 Genome Editing
# 测试成功
# query:我想模拟对 HeLa 细胞中 BRCA1 基因进行 CRISPR 编辑，向导 RNA 为 GACCGAGCTGTTACCGGACG，目标序列为 GACCGAGCTGTTACCGGACGAGG，请评估其编辑效率与可能结果。
class CrisprCas9EditingInput(BaseModel):
    guide_rna_sequences: List[str] = Field(..., description="20nt guide RNA 序列列表，用于定位目标位点")
    target_genomic_loci: str = Field(..., description="目标基因组序列，用于匹配向导 RNA 和 PAM")
    cell_tissue_type: str = Field(..., description="细胞或组织类型，影响递送效率")

async def perform_crispr_cas9_genome_editing(
    guide_rna_sequences: List[str],
    target_genomic_loci: str,
    cell_tissue_type: str
) -> str:
    """
    模拟 CRISPR-Cas9 基因组编辑流程，包括：
      1. 向导 RNA 验证 (20nt、ATGC 验证与 GC 含量)
      2. 目标位点识别 (匹配序列及 PAM NGG 检查)
      3. 递送效率模拟 (基于细胞类型设定)
      4. 编辑效果预测 (切割位点与 indel 模拟)
      5. 编辑结果分析与文件保存

    参数：
    - guide_rna_sequences: 向导 RNA 序列列表 (20nt)
    - target_genomic_loci: 被编辑的基因组序列 (含 PAM 位点)
    - cell_tissue_type: 编辑细胞/组织类型

    返回：
    - research_log: 编辑流程日志与结果汇总 (字符串)
    """
    import os, random
    from datetime import datetime

    log = f"CRISPR-Cas9 Genome Editing Research Log\n"
    log += f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    log += f"Cell/Tissue Type: {cell_tissue_type}\n\n"

    # Step 1: Validate guide RNAs
    valid_guides = []
    log += "STEP 1: Guide RNA Validation\n"
    for i, guide in enumerate(guide_rna_sequences):
        if len(guide) != 20 or not all(n in 'ATGC' for n in guide.upper()):
            log += f"  Guide {i+1}: INVALID ({guide})\n"
            continue
        gc = (guide.upper().count('G') + guide.upper().count('C')) / 20 * 100
        quality = 'Optimal' if 40 <= gc <= 60 else 'Suboptimal'
        log += f"  Guide {i+1}: VALID ({guide}, GC: {gc:.1f}% - {quality})\n"
        valid_guides.append((guide, 1 if quality=='Optimal' else 0))
    if not valid_guides:
        return log + "\nNo valid guide RNAs. Process aborted."

    # Step 2: Identify target sites
    log += "\nSTEP 2: Target Site Identification\n"
    matches = []
    seq = target_genomic_loci.upper()
    for guide, score in valid_guides:
        pos = seq.find(guide)
        pam = 'Found' if pos>=0 and seq[pos+20:pos+23].endswith('GG') else 'Not found'
        log += f"  Guide {guide}: Position {pos if pos>=0 else 'NA'} (PAM: {pam})\n"
        if pos>=0: matches.append((guide,pos,score+ (2 if pam=='Found' else 0)))
    if not matches:
        return log + "\nNo matching target sites. Process aborted."

    # Step 3: Delivery simulation
    log += "\nSTEP 3: Delivery Efficiency Simulation\n"
    eff_map = {'hek293':0.85,'hela':0.75,'ipsc':0.6}
    key = cell_tissue_type.lower().replace(' ','_')
    eff = eff_map.get(key,0.5)
    log += f"  Delivery for {cell_tissue_type}: {eff*100:.1f}%\n"

    # Step 4: Editing simulation
    log += "\nSTEP 4: Editing Simulation\n"
    best = max(matches, key=lambda x: x[2])
    cut = best[1] + 17
    indel = random.randint(1,5)
    mod_seq = seq[:cut] + seq[cut+indel:]
    success = eff * (0.5 + best[2]*0.1)
    log += f"  Guide {best[0]} cut at {cut}, indel {indel}bp, efficiency {success*100:.1f}%\n"

    # Step 5: Outcome analysis
    log += "\nSTEP 5: Outcome Analysis\n"
    log += f"  Orig len: {len(seq)}, Mod len: {len(mod_seq)}\n"
    os.makedirs('crispr_results',exist_ok=True)
    orig, mod = 'crispr_results/original.txt','crispr_results/modified.txt'
    open(orig,'w').write(seq)
    open(mod,'w').write(mod_seq)
    log += f"  Files: {orig}, {mod}\n"
    log += "\nSUMMARY: Simulation completed."
    return log

crispr_cas9_genome_editing_tool = StructuredTool.from_function(
    name=Tools.perform_crispr_cas9_genome_editing,
   description="""
    【领域：生物】
        "模拟 CRISPR-Cas9 基因组编辑流程，包含向导RNA验证、目标位点识别、递送效率与编辑结果模拟。\n\n"
        "返回：\n"
        "  - research_log: 完整实验过程与结果日志"
    """,
    args_schema=CrisprCas9EditingInput,
    coroutine=perform_crispr_cas9_genome_editing,
    metadata={"args_schema_json":CrisprCas9EditingInput.schema()} 
)



# Tool 3: Calcium Imaging Data Analysis
# 需tif文件,未测试
class CalciumImagingInput(BaseModel):
    image_stack_path: str = Field(..., description="Path to time-series fluorescence image stack (TIFF)")


async def analyze_calcium_imaging_data_coroutine(
    image_stack_path: str,
  
) -> Dict[str, Any]:
    import io, os
    import numpy as np
    from skimage import io as skio, filters, segmentation, feature, measure
    from scipy import ndimage, signal
    from scipy.optimize import curve_fit
    import pandas as pd
    
    from upload import upload_content_to_minio

    log = "# Calcium Imaging Analysis Log\n"
    # Load stack
    try:
        stack = skio.imread(image_stack_path)
        frames, h, w = stack.shape
        log += f"Loaded {frames} frames ({h}x{w}) from {image_stack_path}\n\n"
    except Exception as e:
        return {"research_log": f"Error loading stack: {e}",
                "metrics_csv_url": None,
                "time_series_csv_url": None}

    # Preprocessing & segmentation
    mean_img = np.mean(stack, axis=0)
    smooth = filters.gaussian(mean_img, sigma=2)
    dist = ndimage.distance_transform_edt(smooth)
    coords = feature.peak_local_max(dist, min_distance=10)
    if len(coords)==0:
        mask = smooth > filters.threshold_otsu(smooth)
        markers = measure.label(mask)
    else:
        lm = np.zeros_like(dist, bool)
        for y,x in coords: lm[y,x]=True
        markers = measure.label(lm)
    segments = segmentation.watershed(-smooth, markers, mask=smooth>filters.threshold_otsu(smooth))
    regions = measure.regionprops(segments)
    n_cells = len(regions)
    log += f"Detected {n_cells} neurons\n\n"

    # Extract time-series
    ts_data = []
    for reg in regions:
        mask = (segments==reg.label)
        ts = [np.mean(frame[mask]) for frame in stack]
        ts_data.append(ts)
    ts_arr = np.array(ts_data)

    # Calculate metrics
    def exp_decay(x,a,tau,c): return a*np.exp(-x/tau)+c
    rates, taus, snrs = [],[],[]
    for ts in ts_data:
        base = np.percentile(ts,20)
        norm = (ts-base)/base
        thresh = norm.std()*2
        evs=[];in_ev=False
        for i,val in enumerate(norm):
            if not in_ev and val>thresh: evs.append(i);in_ev=True
            elif in_ev and val<thresh: in_ev=False
        rec_min = frames/10/60
        rates.append(len(evs)/rec_min)
        dtimes=[]
        for st in evs:
            if st+30<len(norm):
                segw = norm[st:st+30]
                try:
                    p,_=curve_fit(exp_decay, np.arange(len(segw)), segw, p0=[segw[0],5,segw[-1]], bounds=([0,0,0],[np.inf,np.inf,np.inf]))
                    dtimes.append(p[1]/10)
                except: pass
        taus.append(np.nanmean(dtimes) if dtimes else np.nan)
        sig = np.mean([norm[i] for i in evs]) if evs else 0
        noi = np.std([norm[i] for i in range(len(norm)) if all(abs(i-e)>5 for e in evs)])
        snrs.append(sig/noi if noi>0 else 0)

    # Compile DataFrames
    metrics_df = pd.DataFrame({
        'Cell_ID': list(range(1,n_cells+1)),
        'Event_Rate_per_min': rates,
        'Decay_Time_sec': taus,
        'SNR': snrs
    })
    ts_df = pd.DataFrame(ts_arr.T, columns=[f"Cell_{i+1}" for i in range(n_cells)])

    # Upload CSVs
    metrics_buf = io.StringIO(); metrics_df.to_csv(metrics_buf, index=False)
    metrics_url = await upload_content_to_minio(content=metrics_buf.getvalue().encode('utf-8'),
                                               file_name="calcium_metrics.csv",
                                               file_extension=".csv",
                                               content_type="text/csv",
                                               no_expired=True)
    ts_buf = io.StringIO(); ts_df.to_csv(ts_buf, index=False)
    ts_url = await upload_content_to_minio(content=ts_buf.getvalue().encode('utf-8'),
                                           file_name="calcium_time_series.csv",
                                           file_extension=".csv",
                                           content_type="text/csv",
                                           no_expired=True)

    # Summary
    log += f"Average event rate: {np.nanmean(rates):.2f} ev/min\n"
    log += f"Average decay time: {np.nanmean(taus):.2f} s\n"
    log += f"Average SNR: {np.nanmean(snrs):.2f}\n"

    return {
        "research_log": log,
        "metrics_csv_url": metrics_url,
        "time_series_csv_url": ts_url
    }

analyze_calcium_imaging_data_tool = StructuredTool.from_function(
    name=Tools.analyze_calcium_imaging_data,
   description="""
    【领域：生物】
        "处理 GCaMP 荧光成像序列，分割神经元并提取时间序列，计算事件率、衰减时间常数与信噪比等指标。\n\n"
        "返回：\n"
        "  - research_log: 完整分析日志\n"
        "  - metrics_csv_url: 神经元活动指标 CSV 链接\n"
        "  - time_series_csv_url: 时间序列数据 CSV 链接""",
    args_schema=CalciumImagingInput,
    coroutine=analyze_calcium_imaging_data_coroutine,
    metadata={"args_schema_json":CalciumImagingInput.schema()} 
)
#测试成功
class CrisprCas9EditingInput(BaseModel):
    guide_rna_sequences: List[str] = Field(..., description="20nt guide RNA 序列列表，用于定位目标位点")
    target_genomic_loci: str = Field(..., description="目标基因组序列，用于匹配向导 RNA 和 PAM")
    cell_tissue_type: str = Field(..., description="细胞或组织类型，影响递送效率")

async def perform_crispr_cas9_genome_editing(
    guide_rna_sequences: List[str],
    target_genomic_loci: str,
    cell_tissue_type: str
) -> str:
    """
    模拟 CRISPR-Cas9 基因组编辑流程，包括：
      1. 向导 RNA 验证 (20nt、ATGC 验证与 GC 含量)
      2. 目标位点识别 (匹配序列及 PAM NGG 检查)
      3. 递送效率模拟 (基于细胞类型设定)
      4. 编辑效果预测 (切割位点与 indel 模拟)
      5. 编辑结果分析与文件保存

    参数：
    - guide_rna_sequences: 向导 RNA 序列列表 (20nt)
    - target_genomic_loci: 被编辑的基因组序列 (含 PAM 位点)
    - cell_tissue_type: 编辑细胞/组织类型

    返回：
    - research_log: 编辑流程日志与结果汇总 (字符串)
    """
    import os, random
    from datetime import datetime

    log = f"CRISPR-Cas9 Genome Editing Research Log\n"
    log += f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    log += f"Cell/Tissue Type: {cell_tissue_type}\n\n"

    # Step 1: Validate guide RNAs
    valid_guides = []
    log += "STEP 1: Guide RNA Validation\n"
    for i, guide in enumerate(guide_rna_sequences):
        if len(guide) != 20 or not all(n in 'ATGC' for n in guide.upper()):
            log += f"  Guide {i+1}: INVALID ({guide})\n"
            continue
        gc = (guide.upper().count('G') + guide.upper().count('C')) / 20 * 100
        quality = 'Optimal' if 40 <= gc <= 60 else 'Suboptimal'
        log += f"  Guide {i+1}: VALID ({guide}, GC: {gc:.1f}% - {quality})\n"
        valid_guides.append((guide, 1 if quality=='Optimal' else 0))
    if not valid_guides:
        return log + "\nNo valid guide RNAs. Process aborted."

    # Step 2: Identify target sites
    log += "\nSTEP 2: Target Site Identification\n"
    matches = []
    seq = target_genomic_loci.upper()
    for guide, score in valid_guides:
        pos = seq.find(guide)
        pam = 'Found' if pos>=0 and seq[pos+20:pos+23].endswith('GG') else 'Not found'
        log += f"  Guide {guide}: Position {pos if pos>=0 else 'NA'} (PAM: {pam})\n"
        if pos>=0: matches.append((guide,pos,score+ (2 if pam=='Found' else 0)))
    if not matches:
        return log + "\nNo matching target sites. Process aborted."

    # Step 3: Delivery simulation
    log += "\nSTEP 3: Delivery Efficiency Simulation\n"
    eff_map = {'hek293':0.85,'hela':0.75,'ipsc':0.6}
    key = cell_tissue_type.lower().replace(' ','_')
    eff = eff_map.get(key,0.5)
    log += f"  Delivery for {cell_tissue_type}: {eff*100:.1f}%\n"

    # Step 4: Editing simulation
    log += "\nSTEP 4: Editing Simulation\n"
    best = max(matches, key=lambda x: x[2])
    cut = best[1] + 17
    indel = random.randint(1,5)
    mod_seq = seq[:cut] + seq[cut+indel:]
    success = eff * (0.5 + best[2]*0.1)
    log += f"  Guide {best[0]} cut at {cut}, indel {indel}bp, efficiency {success*100:.1f}%\n"

    # Step 5: Outcome analysis
    log += "\nSTEP 5: Outcome Analysis\n"
    log += f"  Orig len: {len(seq)}, Mod len: {len(mod_seq)}\n"
    os.makedirs('crispr_results',exist_ok=True)
    orig, mod = 'crispr_results/original.txt','crispr_results/modified.txt'
    open(orig,'w').write(seq)
    open(mod,'w').write(mod_seq)
    log += f"  Files: {orig}, {mod}\n"
    log += "\nSUMMARY: Simulation completed."
    return log

bmn_crispr_cas9_genome_editing_tool = StructuredTool.from_function(
    name=Tools.perform_crispr_cas9_genome_editing_bmn,
   description="""
    【领域：生物】
    模拟 CRISPR-Cas9 基因组编辑流程，包含向导RNA验证、目标位点识别、递送效率与编辑结果模拟。\n\n"
        "返回：\n"
        "  - research_log: 完整实验过程与结果日志"""
       ,
    args_schema=CrisprCas9EditingInput,
    coroutine=perform_crispr_cas9_genome_editing,
    metadata={"args_schema_json":CrisprCas9EditingInput.schema()} 
)



#测试成功
class AnalyzeDrugReleaseInput(BaseModel):
    time_points: List[float] = Field(..., description="药物浓度测量的时间点（小时）")
    concentration_data: List[float] = Field(..., description="对应时间点的药物浓度")
    drug_name: str = Field("Drug", description="药物名称，默认 'Drug'")
    total_drug_loaded: float = Field(None, description="初始装载药物总量。如果为空，则使用最大浓度作为100%")

async def analyze_in_vitro_drug_release_coroutine(
    time_points: List[float],
    concentration_data: List[float],
    drug_name: str = "Drug",
    total_drug_loaded: float = None,
) -> Dict[str, Any]:
    """
    分析体外药物释放动力学：
    - 计算累积释放百分比
    - 拟合零阶、一级、Higuchi 和 Korsmeyer-Peppas 模型
    - 输出最佳拟合模型和半衰期
    - 结果文件（CSV + 图像）上传到 MinIO
    """
    try:
        time_points = np.array(time_points)
        concentration_data = np.array(concentration_data)
        
        if len(time_points) != len(concentration_data):
            raise ValueError(f"时间点数量({len(time_points)})与浓度数据数量({len(concentration_data)})不匹配")
        
        if total_drug_loaded is None:
            total_drug_loaded = np.max(concentration_data)
        
        cumulative_release = (concentration_data / total_drug_loaded) * 100
        
        release_df = pd.DataFrame({
            'Time (hours)': time_points,
            'Concentration': concentration_data,
            'Cumulative Release (%)': cumulative_release
        })
        release_df['Release Rate'] = np.gradient(release_df['Cumulative Release (%)'], release_df['Time (hours)'])

        # 定义模型
        def zero_order(t, k): return k * t
        def first_order(t, k): return 100 * (1 - np.exp(-k * t))
        def higuchi(t, k): return k * np.sqrt(t)

        models, r2_values = {}, {}

        def fit_model(func, x, y, bounds=(-np.inf, np.inf)):
            try:
                params, _ = curve_fit(func, x, y, bounds=bounds, maxfev=5000)
                y_pred = func(x, *params)
                ss_total = np.sum((y - np.mean(y))**2)
                ss_res = np.sum((y - y_pred)**2)
                r2 = 1 - (ss_res / ss_total) if ss_total > 0 else 0
                return {'params': params, 'pred': y_pred}, r2
            except Exception as e:
                print(f"模型拟合失败: {e}")
                return {'params': None, 'pred': None}, 0

        # 模型拟合
        models['Zero-order'], r2_values['Zero-order'] = fit_model(zero_order, time_points, cumulative_release)
        models['First-order'], r2_values['First-order'] = fit_model(first_order, time_points, cumulative_release, bounds=(0, [1]))
        models['Higuchi'], r2_values['Higuchi'] = fit_model(higuchi, time_points, cumulative_release)

        # Korsmeyer-Peppas
        mask = (cumulative_release <= 60) & (time_points > 0)
        if sum(mask) >= 3:
            time_kp, release_kp = time_points[mask], cumulative_release[mask]
            release_kp_norm = release_kp / 100.0
            def korsmeyer_peppas_norm(t, k, n): return k * (t ** n)
            try:
                params, _ = curve_fit(korsmeyer_peppas_norm, time_kp, release_kp_norm, bounds=([0.001, 0.1], [2.0, 2.0]), maxfev=5000)
                y_pred_norm = korsmeyer_peppas_norm(time_kp, *params)
                y_pred = y_pred_norm * 100
                ss_total = np.sum((release_kp - np.mean(release_kp))**2)
                ss_res = np.sum((release_kp - y_pred)**2)
                r2 = 1 - (ss_res / ss_total) if ss_total > 0 else 0
                models['Korsmeyer-Peppas'] = {'params': params, 'pred': y_pred}
                r2_values['Korsmeyer-Peppas'] = r2
            except Exception as e:
                print(f"Korsmeyer-Peppas 拟合失败: {e}")
                models['Korsmeyer-Peppas'] = {'params': None, 'pred': None}
                r2_values['Korsmeyer-Peppas'] = 0
        else:
            models['Korsmeyer-Peppas'] = {'params': None, 'pred': None}
            r2_values['Korsmeyer-Peppas'] = 0

        valid_r2 = {k: v for k, v in r2_values.items() if v > 0}
        best_model = max(valid_r2, key=valid_r2.get) if valid_r2 else "None"

        # 半衰期
        try:
            if best_model == 'Zero-order' and models[best_model]['params'] is not None:
                k = models[best_model]['params'][0]
                half_life = 50 / k if k > 0 else float('inf')
            elif best_model == 'First-order' and models[best_model]['params'] is not None:
                k = models[best_model]['params'][0]
                half_life = -np.log(0.5) / k if k > 0 else float('inf')
            elif best_model == 'Higuchi' and models[best_model]['params'] is not None:
                k = models[best_model]['params'][0]
                half_life = (50 / k)**2 if k > 0 else float('inf')
            elif best_model == 'Korsmeyer-Peppas' and models[best_model]['params'] is not None:
                k, n = models[best_model]['params']
                half_life = (0.5**(1/n)) / k if k > 0 and n > 0 else float('inf')
            else:
                half_life = "Not calculated"
        except:
            half_life = "Could not calculate"

        # === 文件上传到 MinIO ===
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # CSV
        csv_buffer = io.StringIO()
        release_df.to_csv(csv_buffer, index=False)
        csv_url = await upload_content_to_minio(
            content=csv_buffer.getvalue(),
            file_name=f"drug_release_data_{timestamp}.csv",
            file_extension=".csv",
            content_type="text/csv"
        )

        # 图像
        plt.rcParams['font.sans-serif'] = ['SimHei']  # 支持中文
        plt.rcParams['axes.unicode_minus'] = False
        plt.figure(figsize=(12, 8))
        plt.subplot(2, 1, 1)
        plt.plot(time_points, cumulative_release, 'o-', linewidth=2, markersize=8, label='Experimental Data')
        colors = ['red', 'blue', 'green', 'orange']
        for i, (model_name, data) in enumerate(models.items()):
            if data['pred'] is not None:
                if model_name == 'Korsmeyer-Peppas':
                    plt.plot(time_points[mask], data['pred'], '--',
                             color=colors[i % len(colors)], linewidth=2,
                             label=f"{model_name} (R²={r2_values[model_name]:.4f})")
                else:
                    plt.plot(time_points, data['pred'], '--',
                             color=colors[i % len(colors)], linewidth=2,
                             label=f"{model_name} (R²={r2_values[model_name]:.4f})")
        plt.xlabel('Time (hours)')
        plt.ylabel('Cumulative Release (%)')
        plt.title(f'Drug Release Profile of {drug_name}')
        plt.legend()
        plt.grid(True, linestyle='--', alpha=0.7)

        plt.subplot(2, 1, 2)
        plt.plot(time_points, release_df['Release Rate'], 'o-', linewidth=2, markersize=8, color='purple')
        plt.xlabel('Time (hours)')
        plt.ylabel('Release Rate (%/hour)')
        plt.title(f'Release Rate of {drug_name}')
        plt.grid(True, linestyle='--', alpha=0.7)

        plt.tight_layout()
        img_buffer = io.BytesIO()
        plt.savefig(img_buffer, format="png", dpi=300, bbox_inches='tight')
        plt.close()
        img_url = await upload_content_to_minio(
            content=img_buffer.getvalue(),
            file_name=f"drug_release_plot_{timestamp}.png",
            file_extension=".png",
            content_type="image/png"
        )
        
        return {
            "success": True,
            "best_model": best_model,
            "half_life": half_life,
            "r2_values": r2_values,
            "csv_file": csv_url,
            "plot_file": img_url,
            "total_drug_loaded": total_drug_loaded,
            "drug_name": drug_name
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}  

bmn_analyze_in_vitro_drug_release_tool = StructuredTool.from_function(
    coroutine=analyze_in_vitro_drug_release_coroutine,
    name=Tools.analyze_in_vitro_drug_release_bmn,
   description="""
    【领域：生物】
分析体外药物释放动力学：
- 输入时间点和对应浓度
- 拟合零阶、一级、Higuchi、Korsmeyer-Peppas 模型
- 返回最佳拟合模型、半衰期、R² 值
- 保存图表和 CSV
""",
    args_schema=AnalyzeDrugReleaseInput,
    metadata={"args_schema_json":AnalyzeDrugReleaseInput.schema()} 
)

