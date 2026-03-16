      
import os
import io
import csv
import json
import tempfile
import traceback
from datetime import datetime
from typing import List, Optional, Dict, Any

import numpy as np
import pandas as pd
import cv2
from skimage import io as skio, filters, measure, segmentation, morphology, color, util
from scipy import ndimage
import matplotlib.pyplot as plt

from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool
from workflow.const import Tools
from workflow.utils.minio_utils import upload_content_to_minio


# 输入图像，跳过
class AorticGeometryInput(BaseModel):
    image_url: str = Field(..., description="URL to the cardiovascular imaging data (DICOM, JPG, PNG)")
    output_dir: Optional[str] = Field(None, description="Output directory (参数保留，实际通过上传获取链接)")

async def analyze_aortic_diameter_and_geometry_coroutine(
    image_url: str,
    output_dir: Optional[str] = None
) -> Dict[str, Any]:
    """
    Analyze aortic diameter and geometry from cardiovascular imaging data.
    """

    log = []
    log.append(f"Aortic Diameter and Geometry Analysis - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.append(f"Input image: {image_url}")

    try:
        # 下载图像到临时文件
        resp = requests.get(image_url)
        resp.raise_for_status()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            tmp.write(resp.content)
            tmp_path = tmp.name

        # 读取灰度图
        image = cv2.imread(tmp_path, cv2.IMREAD_GRAYSCALE)
        if image is None:
            return {"research_log": f"Error: Could not read image from {image_url}"}

        log.append(f"\n1. Loaded image: {image.shape[1]}x{image.shape[0]} pixels")

        # 预处理
        image = cv2.GaussianBlur(image, (5, 5), 0)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        image = clahe.apply(image)
        log.append("   - Preprocessing done (Gaussian blur + CLAHE)")

        # 分割
        thresh_val, binary = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        log.append(f"\n2. Segmentation with Otsu threshold = {thresh_val}")
        kernel = np.ones((3, 3), np.uint8)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return {"research_log": "Error: No contours detected", "annotated_image_url": None, "measurements_txt_url": None}
        aorta_contour = sorted(contours, key=cv2.contourArea, reverse=True)[0]
        log.append(f"   - Selected largest contour (area={cv2.contourArea(aorta_contour):.1f}px²)")

        # 直径测量
        M = cv2.moments(aorta_contour)
        cx, cy = (int(M["m10"]/M["m00"]), int(M["m01"]/M["m00"])) if M["m00"] != 0 else (0, 0)
        root_points = sorted(aorta_contour.reshape(-1, 2), key=lambda p: p[1], reverse=True)[:20]
        aortic_root_diameter = np.max([p[0] for p in root_points]) - np.min([p[0] for p in root_points])

        y_mid = (np.min(aorta_contour[:,:,1]) + np.max(aorta_contour[:,:,1])) // 2
        ascending_points = [p for p in aorta_contour.reshape(-1, 2) if abs(p[1] - y_mid) < 10]
        ascending_diameter = (
            np.max([p[0] for p in ascending_points]) - np.min([p[0] for p in ascending_points])
            if ascending_points else 0
        )

        log.append(f"\n3. Diameters: root={aortic_root_diameter:.2f}px, ascending={ascending_diameter:.2f}px")

        # 几何参数
        contour_length = cv2.arcLength(aorta_contour, closed=True)
        hull_points = cv2.convexHull(aorta_contour).reshape(-1, 2)
        max_dist = max(
            np.linalg.norm(hull_points[i]-hull_points[j])
            for i in range(len(hull_points)) for j in range(i+1, len(hull_points))
        )
        tortuosity = contour_length / max_dist if max_dist > 0 else 0
        dilation_index = max(aortic_root_diameter, ascending_diameter) / min(
            aortic_root_diameter, ascending_diameter
        ) if min(aortic_root_diameter, ascending_diameter) > 0 else 0
        log.append(f"\n4. Geometry: tortuosity={tortuosity:.2f}, dilation_index={dilation_index:.2f}")

        # 输出图像
        output_image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        cv2.drawContours(output_image, [aorta_contour], 0, (0, 255, 0), 2)
        cv2.circle(output_image, (cx, cy), 5, (0, 0, 255), -1)
        _, img_buf = cv2.imencode(".png", output_image)
        annotated_url = await upload_content_to_minio(
            content=img_buf.tobytes(),
            file_name="aorta_analysis.png",
            file_extension=".png",
            content_type="image/png",
            no_expired=True
        )

        # 输出测量值 txt
        measurements = (
            f"Aortic Root Diameter: {aortic_root_diameter:.2f} px\n"
            f"Ascending Aorta Diameter: {ascending_diameter:.2f} px\n"
            f"Tortuosity Index: {tortuosity:.2f}\n"
            f"Dilation Index: {dilation_index:.2f}\n"
        )
        txt_url = await upload_content_to_minio(
            content=measurements.encode("utf-8"),
            file_name="aorta_measurements.txt",
            file_extension=".txt",
            content_type="text/plain",
            no_expired=True
        )

        return {
            "research_log": "\n".join(log),
            "annotated_image_url": annotated_url,
            "measurements_txt_url": txt_url
        }

    except Exception as e:
        return {"research_log": f"Error: {traceback.format_exc()}", "annotated_image_url": None, "measurements_txt_url": None}

analyze_aortic_diameter_and_geometry_tool = StructuredTool.from_function(
    name=Tools.analyze_aortic_diameter_and_geometry,
    description=(
        "分析心血管影像（超声/CT/MRI），测量主动脉根部与升主动脉直径，"
        "并计算几何参数（弯曲度、扩张指数）。\n\n"
        "返回：\n"
        " - research_log: 完整分析日志\n"
        " - annotated_image_url: 带注释的分析结果图像 URL\n"
        " - measurements_txt_url: 含直径与几何指标的 TXT 文件 URL"
    ),
    args_schema=AorticGeometryInput,
    coroutine=analyze_aortic_diameter_and_geometry_coroutine,
    metadata={"args_schema_json": AorticGeometryInput.schema()}
)



# 输入csv文件，跳过
class ATPLuminescenceInput(BaseModel):
    data_url: str = Field(..., description="URL to CSV file containing luminescence readings with columns ['Sample_ID','Luminescence_Value']")
    standard_curve_url: str = Field(..., description="URL to CSV file with ATP standard curve data ['ATP_Concentration','Luminescence_Value']")
    normalization_method: Optional[str] = Field("cell_count", description="Normalization method: 'cell_count' or 'protein_content'")
    normalization_data_url: Optional[str] = Field(None, description="Optional URL to CSV file containing normalization data (Sample_ID + values)")

async def analyze_atp_luminescence_assay_coroutine(
    data_url: str,
    standard_curve_url: str,
    normalization_method: str = "cell_count",
    normalization_data_url: Optional[str] = None
) -> Dict[str, Any]:
    log = []
    log.append(f"ATP Content Measurement Analysis - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.append("=" * 50)

    try:
        # Step 1: 下载并加载样本数据
        resp = requests.get(data_url); resp.raise_for_status()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
            tmp.write(resp.content); data_path = tmp.name
        sample_data = pd.read_csv(data_path)
        log.append(f"Step 1: Loaded sample data from {data_url} (n={len(sample_data)})")
    except Exception:
        return {"research_log": f"Error loading sample data:\n{traceback.format_exc()}", "results_csv_url": None}

    try:
        # Step 2: 下载并加载标准曲线
        resp = requests.get(standard_curve_url); resp.raise_for_status()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
            tmp.write(resp.content); std_path = tmp.name
        std_curve_data = pd.read_csv(std_path)
        log.append(f"\nStep 2: Loaded standard curve from {standard_curve_url}")
    except Exception:
        return {"research_log": f"Error loading standard curve:\n{traceback.format_exc()}", "results_csv_url": None}

    try:
        # Step 3: 拟合标准曲线 (线性回归)
        x = std_curve_data['Luminescence_Value']
        y = std_curve_data['ATP_Concentration']
        slope, intercept = np.polyfit(x, y, 1)
        log.append(f"\nStep 3: Standard curve: ATP = {slope:.6f} × Lum + {intercept:.6f}")
    except Exception:
        return {"research_log": f"Error generating standard curve:\n{traceback.format_exc()}", "results_csv_url": None}

    try:
        # Step 4: 计算 ATP 浓度
        sample_data['ATP_Concentration_nM'] = slope * sample_data['Luminescence_Value'] + intercept
        log.append("\nStep 4: Calculated ATP concentrations for samples")
    except Exception:
        return {"research_log": f"Error calculating ATP concentrations:\n{traceback.format_exc()}", "results_csv_url": None}

    try:
        # Step 5: 归一化
        log.append(f"\nStep 5: Normalizing ATP by {normalization_method}")
        if normalization_data_url:
            resp = requests.get(normalization_data_url); resp.raise_for_status()
            with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
                tmp.write(resp.content); norm_path = tmp.name
            norm_data = pd.read_csv(norm_path)
            norm_dict = dict(zip(norm_data['Sample_ID'], norm_data[normalization_method]))
            for idx, row in sample_data.iterrows():
                sid = row['Sample_ID']
                if sid in norm_dict:
                    if normalization_method == 'cell_count':
                        sample_data.at[idx, 'ATP_pmol_per_million_cells'] = (
                            row['ATP_Concentration_nM'] / norm_dict[sid] * 1000
                        )
                    elif normalization_method == 'protein_content':
                        sample_data.at[idx, 'ATP_nmol_per_mg_protein'] = (
                            row['ATP_Concentration_nM'] / norm_dict[sid]
                        )
            log.append("Normalization applied successfully")
        else:
            log.append("No normalization data provided, reporting raw ATP concentrations")
    except Exception:
        log.append(f"Error during normalization:\n{traceback.format_exc()}")

    try:
        # Step 6: 保存结果到 CSV 并上传
        buf = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
        sample_data.to_csv(buf.name, index=False)
        with open(buf.name, "rb") as f:
            csv_url = await upload_content_to_minio(
                content=f.read(),
                file_name="atp_measurement_results.csv",
                file_extension=".csv",
                content_type="text/csv",
                no_expired=True
            )
        log.append("\nStep 6: Results uploaded as CSV")
    except Exception:
        return {"research_log": f"Error saving results:\n{traceback.format_exc()}", "results_csv_url": None}

    try:
        # Step 7: 统计总结
        log.append("\nStep 7: Summary statistics")
        log.append(f"ATP (nM) mean={sample_data['ATP_Concentration_nM'].mean():.2f}, "
                   f"median={sample_data['ATP_Concentration_nM'].median():.2f}, "
                   f"min={sample_data['ATP_Concentration_nM'].min():.2f}, "
                   f"max={sample_data['ATP_Concentration_nM'].max():.2f}")
    except Exception:
        log.append("Error generating summary statistics")

    return {"research_log": "\n".join(log), "results_csv_url": csv_url}

analyze_atp_luminescence_assay_tool = StructuredTool.from_function(
    name=Tools.analyze_atp_luminescence_assay,
    description=(
        "分析基于发光的 ATP 测定实验，利用标准曲线换算样本 ATP 浓度，"
        "并可根据细胞数或蛋白含量进行归一化。\n\n"
        "返回：\n"
        " - research_log: 完整分析日志\n"
        " - results_csv_url: 含结果的 CSV 文件链接"
    ),
    args_schema=ATPLuminescenceInput,
    coroutine=analyze_atp_luminescence_assay_coroutine,
    metadata={"args_schema_json": ATPLuminescenceInput.schema()}
)



# 输入图像，跳过
class ThrombusHistologyInput(BaseModel):
    image_url: str = Field(..., description="URL of histological thrombus image stained with H&E")
    output_dir: Optional[str] = Field(None, description="Output directory (参数保留，实际通过上传获取链接)")

async def analyze_thrombus_histology_coroutine(
    image_url: str,
    output_dir: Optional[str] = None
) -> Dict[str, Any]:
    log = f"# Thrombus Component Analysis - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    log += f"Analyzing image: {image_url}\n\n"

    # Step 1: Load and preprocess
    log += "## Step 1: Image Loading and Preprocessing\n"
    original_image = cv2.imread(image_url)
    if original_image is None:
        return {"research_log": f"Error: Could not load image from {image_url}", 
                "visualization_url": None, "results_csv_url": None}

    rgb_image = cv2.cvtColor(original_image, cv2.COLOR_BGR2RGB)
    lab_image = color.rgb2lab(rgb_image)
    log += f"- Loaded image with dimensions: {rgb_image.shape[1]}x{rgb_image.shape[0]} pixels\n"
    log += "- Converted image to LAB color space\n\n"

    # Step 2: Component masks
    log += "## Step 2: Thrombus Component Segmentation\n"
    fresh_mask = (lab_image[:,:,0] > 50) & (lab_image[:,:,1] > 15)
    lysis_mask = (lab_image[:,:,0] > 60) & (lab_image[:,:,1] < 15) & (lab_image[:,:,1] > -5) & (lab_image[:,:,2] < 10)
    endothel_mask = (lab_image[:,:,0] > 40) & (lab_image[:,:,0] < 70) & (lab_image[:,:,2] < -5)
    fibro_mask = (lab_image[:,:,0] > 70) & (lab_image[:,:,1] < 5) & (lab_image[:,:,1] > -10) & (lab_image[:,:,2] > 0)
    log += "- Created masks for each component\n"

    # Step 3: Quantification
    log += "\n## Step 3: Component Quantification\n"
    total_pixels = fresh_mask.sum() + lysis_mask.sum() + endothel_mask.sum() + fibro_mask.sum()
    if total_pixels > 0:
        fresh_percent = (fresh_mask.sum() / total_pixels) * 100
        lysis_percent = (lysis_mask.sum() / total_pixels) * 100
        endothel_percent = (endothel_mask.sum() / total_pixels) * 100
        fibro_percent = (fibro_mask.sum() / total_pixels) * 100
    else:
        fresh_percent = lysis_percent = endothel_percent = fibro_percent = 0
    log += f"- Fresh thrombus: {fresh_percent:.2f}%\n"
    log += f"- Cellular lysis: {lysis_percent:.2f}%\n"
    log += f"- Endothelialization: {endothel_percent:.2f}%\n"
    log += f"- Fibroblastic reaction: {fibro_percent:.2f}%\n\n"

    # Step 4: Visualization
    log += "## Step 4: Visualization\n"
    visualization = np.zeros_like(rgb_image)
    visualization[fresh_mask] = [255, 0, 0]
    visualization[lysis_mask] = [0, 255, 0]
    visualization[endothel_mask] = [0, 0, 255]
    visualization[fibro_mask] = [255, 255, 0]
    _, img_buf = cv2.imencode(".png", cv2.cvtColor(visualization, cv2.COLOR_RGB2BGR))
    vis_url = await upload_content_to_minio(
        content=img_buf.tobytes(),
        file_name="thrombus_components.png",
        file_extension=".png",
        content_type="image/png",
        no_expired=True
    )
    log += "- Visualization uploaded\n"

    # Step 5: Save results CSV
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow(["Component", "Percentage"])
    writer.writerow(["Fresh thrombus", f"{fresh_percent:.2f}"])
    writer.writerow(["Cellular lysis", f"{lysis_percent:.2f}"])
    writer.writerow(["Endothelialization", f"{endothel_percent:.2f}"])
    writer.writerow(["Fibroblastic reaction", f"{fibro_percent:.2f}"])
    csv_url = await upload_content_to_minio(
        content=csv_buf.getvalue().encode("utf-8"),
        file_name="thrombus_analysis.csv",
        file_extension=".csv",
        content_type="text/csv",
        no_expired=True
    )
    log += "- Quantitative results uploaded\n"

    # Step 6: Summary
    log += "## Summary\n"
    log += f"1. Fresh thrombus: {fresh_percent:.2f}%\n"
    log += f"2. Cellular lysis: {lysis_percent:.2f}%\n"
    log += f"3. Endothelialization: {endothel_percent:.2f}%\n"
    log += f"4. Fibroblastic reaction: {fibro_percent:.2f}%\n\n"

    return {
        "research_log": log,
        "visualization_url": vis_url,
        "results_csv_url": csv_url
    }

analyze_thrombus_histology_tool = StructuredTool.from_function(
    name=Tools.analyze_thrombus_histology,
    description=(
        "分析 H&E 染色的血栓组织切片，分割并量化不同成分：新鲜血栓、细胞溶解、内皮化和纤维母细胞反应。\n\n"
        "返回：\n"
        " - research_log: 完整分析日志\n"
        " - visualization_url: 成分可视化 PNG 链接\n"
        " - results_csv_url: 定量结果 CSV 链接"
    ),
    args_schema=ThrombusHistologyInput,
    coroutine=analyze_thrombus_histology_coroutine,
    metadata={"args_schema_json": ThrombusHistologyInput.schema()}
)



# 输入图像，跳过
class IntracellularCalciumInput(BaseModel):
    background_image_url: str = Field(..., description="URL of the background image (no cells)")
    control_image_url: str = Field(..., description="URL of the control image (cells without calcium stimulus)")
    sample_image_url: str = Field(..., description="URL of the sample image (cells with calcium stimulus)")
    output_dir: Optional[str] = Field(None, description="Output directory (参数保留, 实际通过上传获取链接)")

async def analyze_intracellular_calcium_coroutine(
    background_image_url: str,
    control_image_url: str,
    sample_image_url: str,
    output_dir: Optional[str] = None
) -> Dict[str, Any]:
    log = f"# Intracellular Calcium Imaging Analysis - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    # Step 1: Load images
    try:
        background = cv2.imread(background_image_url, cv2.IMREAD_GRAYSCALE).astype(float)
        control = cv2.imread(control_image_url, cv2.IMREAD_GRAYSCALE).astype(float)
        sample = cv2.imread(sample_image_url, cv2.IMREAD_GRAYSCALE).astype(float)
        log += f"- Loaded images successfully\n"
    except Exception as e:
        return {"research_log": f"Error loading images: {e}", "calcium_map_url": None}

    # Step 2: Background subtraction
    control_corrected = np.maximum(control - background, 0)
    sample_corrected = np.maximum(sample - background, 0)
    log += "- Performed background subtraction\n"

    # Step 3: Calculate mean intensity
    control_intensity = np.mean(control_corrected)
    sample_intensity = np.mean(sample_corrected)
    log += f"- Control intensity: {control_intensity:.2f} a.u.\n"
    log += f"- Sample intensity: {sample_intensity:.2f} a.u.\n"

    # Step 4: Convert to calcium concentration
    kd = 570  # nM
    f_min = control_intensity
    f_max = 2.5 * sample_intensity
    f = sample_intensity
    calcium_concentration = kd * (f - f_min) / (f_max - f) if f_max != f else float('inf')
    log += f"- Estimated mean intracellular [Ca²⁺]: {calcium_concentration:.2f} nM\n"

    # Step 5: Generate heatmap
    calcium_map = (sample_corrected - control_corrected) / (f_max - control_corrected + 1e-10) * kd
    plt.figure(figsize=(10, 8))
    plt.imshow(calcium_map, cmap='hot')
    plt.colorbar(label='[Ca²⁺] (nM)')
    plt.title('Intracellular Calcium Concentration Map')
    _, img_buf = io.BytesIO(), io.BytesIO()
    plt.savefig(_, format='png')
    plt.close()
    _.seek(0)
    img_bytes = _.read()

    # Upload heatmap
    map_url = await upload_content_to_minio(
        content=img_bytes,
        file_name="intracellular_calcium_map.png",
        file_extension=".png",
        content_type="image/png",
        no_expired=True
    )
    log += "- Calcium concentration heatmap uploaded\n"

    return {
        "research_log": log,
        "calcium_map_url": map_url,
        "mean_calcium_nM": calcium_concentration
    }

analyze_intracellular_calcium_tool = StructuredTool.from_function(
    name=Tools.analyze_intracellular_calcium_with_rhod2,
    description="""
 "使用 Rhod-2 荧光探针分析细胞内钙浓度，基于显微镜图像进行背景校正、计算平均荧光强度，"
        "并生成钙浓度热图。\n\n"
        "返回：\n"
        " - research_log: 完整分析日志\n"
        " - calcium_map_url: 钙浓度热图 PNG 链接\n"
        " - mean_calcium_nM: 平均细胞内钙浓度 (nM)""",
    args_schema=IntracellularCalciumInput,
    coroutine=analyze_intracellular_calcium_coroutine,
    metadata={"args_schema_json": IntracellularCalciumInput.schema()}
)



# 输入图像，跳过
class CornealNerveFibersInput(BaseModel):
    image_url: str = Field(..., description="URL of immunofluorescence microscopy image of corneal nerve fibers")
    marker_type: str = Field(..., description="Type of nerve fiber marker (e.g., 'βIII-tubulin', 'SP', 'L1CAM')")
    threshold_method: Optional[str] = Field('otsu', description="Thresholding method: 'otsu', 'adaptive', or 'manual'")
    output_dir: Optional[str] = Field(None, description="Output directory (参数保留, 实际通过上传获取链接)")

async def quantify_corneal_nerve_fibers_coroutine(
    image_url: str,
    marker_type: str,
    threshold_method: str = 'otsu',
    output_dir: Optional[str] = None
) -> Dict[str, Any]:
    log = f"# Corneal Nerve Fiber Analysis - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    
    try:
        image = skio.imread(image_url)
        if len(image.shape) > 2:
            image = rgb2gray(image)
        log += f"- Loaded image successfully\n"
    except Exception as e:
        return {"research_log": f"Error loading image: {e}", "segmented_image_url": None, "measurements_csv_url": None}

    # Normalize
    image_norm = (image.astype(float) - image.min()) / (image.max() - image.min())

    # Thresholding
    if threshold_method == 'otsu':
        thresh_value = filters.threshold_otsu(image_norm)
    elif threshold_method == 'adaptive':
        thresh_value = filters.threshold_local(image_norm, block_size=35)
    else:
        thresh_value = 0.5
    binary_mask = image_norm > thresh_value

    # Morphological cleanup
    cleaned_mask = morphology.remove_small_objects(binary_mask, min_size=50)
    cleaned_mask = morphology.closing(cleaned_mask, morphology.disk(2))

    # Quantification
    fiber_area = np.sum(cleaned_mask)
    total_area = cleaned_mask.size
    fiber_density = (fiber_area / total_area) * 100
    labeled_fibers = measure.label(cleaned_mask)
    fiber_props = measure.regionprops(labeled_fibers)
    fiber_count = len(fiber_props)

    if fiber_count > 0:
        avg_length = np.mean([prop.major_axis_length for prop in fiber_props])
        avg_width = np.mean([prop.minor_axis_length for prop in fiber_props])
    else:
        avg_length = avg_width = 0

    # Save segmented image
    seg_buf = io.BytesIO()
    skio.imsave(seg_buf, util.img_as_ubyte(cleaned_mask), format='png')
    seg_buf.seek(0)
    segmented_image_url = await upload_content_to_minio(
        content=seg_buf.read(),
        file_name=f"{marker_type.replace(' ', '_')}_segmented.png",
        file_extension=".png",
        content_type="image/png",
        no_expired=True
    )

    # Save measurements CSV
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow(["Metric", "Value"])
    writer.writerow(["Marker Type", marker_type])
    writer.writerow(["Fiber Area (pixels)", fiber_area])
    writer.writerow(["Total Image Area (pixels)", total_area])
    writer.writerow(["Fiber Density (%)", f"{fiber_density:.2f}"])
    writer.writerow(["Fiber Count", fiber_count])
    writer.writerow(["Average Fiber Length (pixels)", f"{avg_length:.2f}"])
    writer.writerow(["Average Fiber Width (pixels)", f"{avg_width:.2f}"])
    csv_url = await upload_content_to_minio(
        content=csv_buf.getvalue().encode("utf-8"),
        file_name=f"{marker_type.replace(' ', '_')}_measurements.csv",
        file_extension=".csv",
        content_type="text/csv",
        no_expired=True
    )

    log += (
        f"- Fiber Area: {fiber_area} pixels\n"
        f"- Total Image Area: {total_area} pixels\n"
        f"- Fiber Density: {fiber_density:.2f}%\n"
        f"- Fiber Count: {fiber_count}\n"
        f"- Average Fiber Length: {avg_length:.2f} pixels\n"
        f"- Average Fiber Width: {avg_width:.2f} pixels\n"
    )

    return {
        "research_log": log,
        "segmented_image_url": segmented_image_url,
        "measurements_csv_url": csv_url
    }

quantify_corneal_nerve_fibers_tool = StructuredTool.from_function(
    name=Tools.quantify_corneal_nerve_fibers,
    description=(
        "分析免疫荧光标记的角膜神经纤维，进行图像分割和定量计算，包括纤维面积、密度、数量及平均长度与宽度。\n\n"
        "返回：\n"
        " - research_log: 分析日志\n"
        " - segmented_image_url: 分割图像 PNG 链接\n"
        " - measurements_csv_url: 定量结果 CSV 链接"
    ),
    args_schema=CornealNerveFibersInput,
    coroutine=quantify_corneal_nerve_fibers_coroutine,
    metadata={"args_schema_json": CornealNerveFibersInput.schema()}
)



# 输入图像，跳过
class MultiplexedCellSegmentationInput(BaseModel):
    image_url: str = Field(..., description="URL of the multichannel tissue image (TIFF stack or similar)")
    markers_list: List[str] = Field(..., description="List of marker names corresponding to each channel")
    nuclear_channel_index: Optional[int] = Field(0, description="Index of the nuclear marker channel (default 0, typically DAPI)")
    output_dir: Optional[str] = Field(None, description="Output directory (参数保留, 实际通过上传获取链接)")

async def segment_and_quantify_cells_coroutine(
    image_url: str,
    markers_list: List[str],
    nuclear_channel_index: int = 0,
    output_dir: Optional[str] = None
) -> Dict[str, Any]:
    log = f"# Multiplexed Cell Segmentation & Quantification - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    try:
        image = skio.imread(image_url)
        log += f"- Loaded multichannel image successfully. Shape: {image.shape}\n"
        if len(image.shape) < 3:
            return {"research_log": f"Error: Image must be multichannel", "cell_features_csv_url": None, "segmentation_mask_url": None}
        # Determine image format
        if image.shape[0] == len(markers_list):
            # (channels, H, W)
            nuclear_channel = image[nuclear_channel_index]
        elif image.shape[-1] == len(markers_list):
            # (H, W, channels)
            nuclear_channel = image[:, :, nuclear_channel_index]
        else:
            return {"research_log": f"Error: Channels in image ({image.shape}) != markers list length ({len(markers_list)})",
                    "cell_features_csv_url": None, "segmentation_mask_url": None}
    except Exception as e:
        return {"research_log": f"Error loading image: {e}", "cell_features_csv_url": None, "segmentation_mask_url": None}

    # Segment nuclei
    thresh = filters.threshold_otsu(nuclear_channel)
    binary_nuclei = nuclear_channel > thresh
    binary_nuclei = morphology.remove_small_objects(binary_nuclei, min_size=50)
    binary_nuclei = morphology.binary_closing(binary_nuclei, morphology.disk(2))
    labeled_nuclei = measure.label(binary_nuclei)
    log += f"- Identified {np.max(labeled_nuclei)} potential nuclei\n"

    # Expand nuclei to approximate cells
    cell_masks = segmentation.watershed(
        -ndimage.distance_transform_edt(~binary_nuclei),
        labeled_nuclei,
        mask=morphology.binary_dilation(binary_nuclei, morphology.disk(10))
    )
    regions = measure.regionprops(cell_masks)
    log += f"- Segmented {len(regions)} cells\n"

    # Extract features
    log += "- Quantifying marker intensities per cell\n"
    cell_data = []
    for i, region in enumerate(regions):
        features = {
            "cell_id": i+1,
            "centroid_y": region.centroid[0],
            "centroid_x": region.centroid[1],
            "area": region.area
        }
        for idx, marker_name in enumerate(markers_list):
            marker_image = image[idx] if image.shape[0] == len(markers_list) else image[:, :, idx]
            cell_mask = cell_masks == region.label
            features[f"{marker_name}_mean_intensity"] = np.mean(marker_image[cell_mask])
        cell_data.append(features)

    cell_df = pd.DataFrame(cell_data)

    # Save CSV
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_buf = io.StringIO()
    cell_df.to_csv(csv_buf, index=False)
    csv_buf.seek(0)
    cell_features_csv_url = await upload_content_to_minio(
        content=csv_buf.getvalue().encode('utf-8'),
        file_name=f"cell_features_{timestamp}.csv",
        file_extension=".csv",
        content_type="text/csv",
        no_expired=True
    )

    # Save segmentation mask
    mask_buf = io.BytesIO()
    skio.imsave(mask_buf, cell_masks.astype(np.uint16), format='tiff')
    mask_buf.seek(0)
    segmentation_mask_url = await upload_content_to_minio(
        content=mask_buf.read(),
        file_name=f"cell_segmentation_mask_{timestamp}.tiff",
        file_extension=".tiff",
        content_type="image/tiff",
        no_expired=True
    )

    log += f"- Processed {len(regions)} cells across {len(markers_list)} markers\n"
    log += f"- Cell features CSV uploaded: {cell_features_csv_url}\n"
    log += f"- Cell segmentation mask uploaded: {segmentation_mask_url}\n"

    return {
        "research_log": log,
        "cell_features_csv_url": cell_features_csv_url,
        "segmentation_mask_url": segmentation_mask_url
    }

segment_and_quantify_cells_tool = StructuredTool.from_function(
    name=Tools.segment_and_quantify_cells_in_multiplexed_images,
    description=(
        "对多通道组织图像进行细胞分割与蛋白表达定量，包括核分割、细胞扩展、分割掩模生成以及每个细胞的标记物平均强度计算。\n\n"
        "返回：\n"
        " - research_log: 分析日志\n"
        " - cell_features_csv_url: 每个细胞定量特征 CSV 链接\n"
        " - segmentation_mask_url: 细胞分割掩模 tiff 链接"
    ),
    args_schema=MultiplexedCellSegmentationInput,
    coroutine=segment_and_quantify_cells_coroutine,
    metadata={"args_schema_json": MultiplexedCellSegmentationInput.schema()}
)



# 输入图像，跳过
class BoneMicroCTInput(BaseModel):
    image_url: str = Field(..., description="URL of the 3D micro-CT image file (TIFF stack or similar)")
    output_dir: Optional[str] = Field(None, description="Output directory (参数保留, 实际通过上传获取链接)")
    threshold_value: Optional[float] = Field(None, description="Threshold for bone segmentation; if None, Otsu's method will be used")

async def analyze_bone_microct_coroutine(
    image_url: str,
    output_dir: Optional[str] = None,
    threshold_value: Optional[float] = None
) -> Dict[str, Any]:
    log = [f"# Micro-CT Bone Morphometry Analysis - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]
    
    try:
        log.append(f"- Loading 3D micro-CT data from {image_url}")
        image_data = skio.imread(image_url)
        if image_data.ndim < 3:
            image_data = np.expand_dims(image_data, axis=0)
            log.append("- Input appears 2D; converted to 3D")
        log.append(f"- Data loaded. Dimensions: {image_data.shape}")
    except Exception as e:
        return {"research_log": f"Error loading data: {e}", "segmentation_slice_url": None, "results_json_url": None}
    
    # Preprocessing
    log.append("- Applying median filter to reduce noise")
    filtered_data = ndimage.median_filter(image_data, size=2)
    
    # Segmentation
    if threshold_value is None:
        threshold_value = filters.threshold_otsu(filtered_data)
        log.append(f"- Threshold calculated by Otsu's method: {threshold_value}")
    else:
        log.append(f"- Using provided threshold value: {threshold_value}")
    
    binary_image = filtered_data > threshold_value
    
    # Morphometry calculations
    bmd = np.mean(image_data[binary_image])
    bone_volume = np.sum(binary_image)
    total_volume = binary_image.size
    bv_tv_ratio = bone_volume / total_volume
    distance_map = ndimage.distance_transform_edt(binary_image)
    tb_th_mean = np.mean(distance_map[binary_image]) * 2
    distance_map_inv = ndimage.distance_transform_edt(~binary_image)
    tb_s_mean = np.mean(distance_map_inv[~binary_image])
    tb_n = bv_tv_ratio / tb_th_mean if tb_th_mean > 0 else 0
    
    log.append(f"- BMD: {bmd:.2f}")
    log.append(f"- Bone Volume (BV): {bone_volume}")
    log.append(f"- BV/TV Ratio: {bv_tv_ratio:.4f}")
    log.append(f"- Tb.Th: {tb_th_mean:.2f} voxels")
    log.append(f"- Tb.S: {tb_s_mean:.2f} voxels")
    log.append(f"- Tb.N: {tb_n:.4f} 1/voxel")
    
    # Save a middle slice of segmentation
    middle_slice = binary_image.shape[0] // 2
    seg_buf = io.BytesIO()
    skio.imsave(seg_buf, binary_image[middle_slice].astype(np.uint8) * 255, format='tiff')
    seg_buf.seek(0)
    segmentation_slice_url = await upload_content_to_minio(
        content=seg_buf.read(),
        file_name=f"bone_segmentation_slice_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tiff",
        file_extension=".tiff",
        content_type="image/tiff",
        no_expired=True
    )
    
    # Save morphometry results as JSON
    results = {
        "BMD": float(bmd),
        "BV": int(bone_volume),
        "BV/TV": float(bv_tv_ratio),
        "Tb.Th": float(tb_th_mean),
        "Tb.S": float(tb_s_mean),
        "Tb.N": float(tb_n)
    }
    results_buf = io.StringIO()
    json.dump(results, results_buf, indent=4)
    results_buf.seek(0)
    results_json_url = await upload_content_to_minio(
        content=results_buf.getvalue().encode('utf-8'),
        file_name=f"bone_morphometry_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        file_extension=".json",
        content_type="application/json",
        no_expired=True
    )
    
    log.append(f"- Segmentation slice uploaded: {segmentation_slice_url}")
    log.append(f"- Morphometry results JSON uploaded: {results_json_url}")
    
    return {
        "research_log": "\n".join(log),
        "segmentation_slice_url": segmentation_slice_url,
        "results_json_url": results_json_url
    }

analyze_bone_microct_tool = StructuredTool.from_function(
    name=Tools.analyze_bone_microct_morphometry,
    description=(
        "分析 3D micro-CT 图像的骨微结构参数，包括 BMD、BV、Tb.N、Tb.Th 和 Tb.S。\n\n"
        "返回：\n"
        " - research_log: 分析日志\n"
        " - segmentation_slice_url: 分割切片 tiff 链接\n"
        " - results_json_url: 数值结果 JSON 链接"
    ),
    args_schema=BoneMicroCTInput,
    coroutine=analyze_bone_microct_coroutine,
    metadata={"args_schema_json": BoneMicroCTInput.schema()}
)

    