from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from langchain_core.tools import StructuredTool
import gget  # 假设 gget 已正确安装
import gseapy
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import scanpy as sc
import numpy as np
import pandas as pd
from langchain_core.prompts import PromptTemplate
import os
from langchain_openai import ChatOpenAI
import json
from workflow.const import Tools
from workflow import config as science_config


def get_llm(
    model: str = science_config.DeepSeekV3.model,
    temperature: float = 0.3,
    stop_sequences: list[str] | None = None,
    source: str | None = None,  # 不再使用，但保留参数防止接口报错
    base_url: str = science_config.DeepSeekV3_2.base_url,  # 不再使用，但保留参数防止接口报错
    api_key: str = science_config.DeepSeekV3_2.api_key,
) -> ChatOpenAI:
    """
    Get a DeepSeekV3 model instance only.
    """
    return ChatOpenAI(
        model=model,
        base_url=base_url,
        temperature=temperature,
        stop_sequences=stop_sequences,
        api_key=api_key,
    )



# 测试成功
# qurey：“请帮我用 GO Biological Process 数据库分析基因列表 TP53, BRCA1, MYC, EGFR，返回 top 5 的富集结果。”
class GeneSetEnrichmentAnalysisInput(BaseModel):
    genes: List[str] = Field(..., description="待分析的基因列表，例如 ['TP53', 'BRCA1']")
    top_k: int = Field(10, description="返回的通路数量 top-K，默认为 10")
    database: str = Field(
        "ontology",
        description="""
    【领域：生物】使用的富集数据库名称，例如：
- 'pathway' (KEGG_2021_Human)
- 'transcription' (ChEA_2016)
- 'ontology' (GO_Biological_Process_2021)
- 'diseases_drugs' (GWAS_Catalog_2019)
- 'celltypes' (PanglaoDB_Augmented_2021)
- 'kinase_interactions' (KEA_2015)
"""
    )
    background_list: Optional[List[str]] = Field(
        None, description="可选的背景基因列表，用于背景校正"
    )
    plot: bool = Field(False, description="是否绘图，默认为 False")

async def gene_set_enrichment_analysis_coroutine(
    genes: List[str],
    top_k: int = 10,
    database: str = "ontology",
    background_list: Optional[List[str]] = None,
    plot: bool = False,
) -> Dict[str, Any]:
    """
    对基因列表执行基因集富集分析，返回分析步骤日志及前 K 个结果。
    """
    try:
        steps_log = (
            f"Starting enrichment analysis for genes: {', '.join(genes)} using {database} database and top_k: {top_k}\n"
        )

        if background_list:
            steps_log += f"Using background list with {len(background_list)} genes.\n"

        steps_log += "Performing enrichment analysis using gget.enrichr...\n"
        df = gget.enrichr(
            genes,
            database=database,
            background_list=background_list,
            plot=plot
        )

        steps_log += f"Filtering the top {top_k} enrichment results...\n"
        df = df.head(top_k)

        results = []
        for _, row in df.iterrows():
            results.append({
                "rank": row["rank"],
                "path_name": row["path_name"],
                "p_val": f"{row['p_val']:.2e}",
                "z_score": round(row["z_score"], 6),
                "combined_score": round(row["combined_score"], 6),
                "overlapping_genes": row["overlapping_genes"],
                "adj_p_val": f"{row['adj_p_val']:.2e}",
                "database": row["database"]
            })

        return {
            "success": True,
            "log": steps_log,
            "results": results
        }

    except Exception as e:
        return {"success": False, "error": f"Enrichment analysis failed: {str(e)}"}

gene_set_enrichment_analysis_tool = StructuredTool.from_function(
    coroutine=gene_set_enrichment_analysis_coroutine,
    name=Tools.gene_set_enrichment_analysis,
    description="""
    【领域：生物】Perform enrichment analysis for a list of genes, with optional background gene set and plotting functionality.


    - background_list (list, optional): List of background genes to use for enrichment analysis.
    - plot (bool, optional): If True, generates a bar plot of the top K enrichment results.

    Returns
    -------
    - str: The steps performed and the top K enrichment results.

    """,
    args_schema=GeneSetEnrichmentAnalysisInput,
    metadata={"args_schema_json":GeneSetEnrichmentAnalysisInput.schema()} 
)



# 测试成功
# qurey：能按物种显示富集数据库吗？比如 Yeast
# 无参数输入模型
class GetSupportedEnrichmentDatabasesInput(BaseModel):
    pass

# coroutine 函数封装
async def get_supported_enrichment_databases_coroutine() -> Dict[str, Any]:
    """
    返回 gene set enrichment analysis 支持的数据库名称列表。
    """
    try:
        db_list = gseapy.get_library_name()
        return {"success": True, "databases": db_list}
    except Exception as e:
        return {"success": False, "error": f"Failed to retrieve database list: {str(e)}"}

# tool 封装
get_supported_enrichment_databases_tool = StructuredTool.from_function(
    coroutine=get_supported_enrichment_databases_coroutine,
    name=Tools.get_gene_set_enrichment_analysis_supported_database_list,
    description="Returns a list of supported databases for gene set enrichment analysis.",
    args_schema=GetSupportedEnrichmentDatabasesInput,
    metadata={"args_schema_json":GetSupportedEnrichmentDatabasesInput.schema()} 
)

# 1111111111111111111111111111111111111111111111111111111111111111111


#测试未通过
class AnnotateCelltypeInput(BaseModel):
    adata_filename: str = Field(..., description="包含 scRNA-seq 数据的 AnnData 文件名，如 'sample.h5ad'")
    data_dir: str = Field(..., description="包含 AnnData 文件的目录路径")
    data_info: str = Field(..., description="关于数据的描述信息，如 'homo sapiens, brain tissue, normal'")
    data_lake_path: str = Field(..., description="包含参考细胞类型数据库 parquet 文件的目录路径")
    cluster: str = Field("leiden", description="用于聚类分组的列名，默认是 'leiden'")
    llm: str = Field("claude-3-5-sonnet-20241022", description="用于注释的语言模型名称")
    composition_path: Optional[str] = Field(None, description="可选的细胞类型组成信息 CSV 路径，用于辅助注释")

async def annotate_celltype_scRNA_coroutine(
    adata_filename: str,
    data_dir: str,
    data_info: str,
    data_lake_path: str,
    cluster: str = "leiden",
    llm: str = "claude-3-5-sonnet-20241022",
    composition_path: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        steps = []
        steps.append(f"Loading AnnData from {data_dir}/{adata_filename}")
        adata = sc.read_h5ad(f"{data_dir}/{adata_filename}")

        # 加载可选组成信息
        composition = pd.read_csv(composition_path, index_col=0) if composition_path else None

        # 差异表达分析
        steps.append(f"Identifying marker genes for clusters defined by {cluster}.")
        sc.tl.rank_genes_groups(adata, groupby=cluster, method="wilcoxon", use_raw=False)
        genes = pd.DataFrame(adata.uns["rank_genes_groups"]["names"]).head(20)
        scores = pd.DataFrame(adata.uns["rank_genes_groups"]["scores"]).head(20)

        markers = {}
        for i in range(genes.shape[1]):
            gene_names = genes.iloc[:, i].tolist()
            gene_scores = scores.iloc[:, i].tolist()
            markers[i] = list(np.array(gene_names)[np.array(gene_scores) > 0])

        # 加载参考细胞类型名
        df = pd.read_parquet(data_lake_path + "/czi_census_datasets_v4.parquet")
        czi_celltype_set = {cell_type.strip() for cell_types in df["cell_type"] for cell_type in str(cell_types).split(";")}
        czi_celltype = ", ".join(sorted(czi_celltype_set))

        # 构建 LLM prompt
        def _cluster_info(cluster_id, marker_genes, composition_df=None):
            if composition_df is None:
                return f"The enriched genes in this cluster are: {', '.join(marker_genes)}."
            info = [
                f"The enriched genes in this cluster are: {', '.join(marker_genes)}.",
                f"For a starting point, the transferred reference cell type composition {cluster_id} is:",
            ]
            cluster_comp = []
            for celltype, proportion in composition_df.loc[cluster_id].items():
                if proportion > 0:
                    cluster_comp.append(f"{celltype}:{proportion:.2f}")
            return "\n".join(info) + " " + "; ".join(cluster_comp) + "\n"

        prompt_template = f"""
Please think carefully, and identify the cell type in {data_info} based on the gene markers.
Optionally refer to the transferred cell type information but do not trust it when the percentage is lower than 0.5.

{{{{cluster_info}}}}

The cell type names should come from cell ontology: {czi_celltype}.
Only provide the cell type name, confidence score (0-1), and detailed reason.
Output format: "name; score; reason".
No numbers before name or spaces before number.
"""
        prompt = PromptTemplate(input_variables=["cluster_info"], template=prompt_template)
        llm_chain = prompt | get_llm(llm)

        cluster_annotations = {}
        annotation_reasons = []

        steps.append("Annotating clusters using LLM...")
        for i in range(len(adata.obs[cluster].unique())):
            info = _cluster_info(str(i), markers[i], composition)
            while True:
                response = llm_chain.invoke({"cluster_info": info})
                if hasattr(response, "content"):
                    response = response.content
                elif isinstance(response, dict) and "text" in response:
                    response = response["text"]
                elif not isinstance(response, str):
                    response = str(response)
                try:
                    predicted_celltype, confidence, reason = [x.strip() for x in response.split(";", 2)]
                    if predicted_celltype in czi_celltype_set or predicted_celltype.lower() in czi_celltype_set:
                        cluster_annotations[str(i)] = predicted_celltype
                        annotation_reasons.append((predicted_celltype, reason))
                        break
                    else:
                        info += "\nAssigned cell type name must be in cell ontology!"
                except ValueError:
                    info += "\nPlease follow the format: name; score; reason"

        reason_dict = {}
        for celltype, reason in annotation_reasons:
            reason_dict.setdefault(celltype, []).append(reason)
        reason_dict = {k: "\n".join(v) for k, v in reason_dict.items()}

        adata.obs["cell_type"] = adata.obs[cluster].map(cluster_annotations)
        adata.obs["cell_type_reason"] = adata.obs["cell_type"].map(reason_dict).astype(str)

        output_path = f"{data_dir}/annotated.h5ad"
        steps.append(f"Saving annotated AnnData to {output_path}")
        adata.write(output_path, compression="gzip")

        return {
            "success": True,
            "steps": steps,
            "output_file": output_path
        }

    except Exception as e:
        return {"success": False, "error": f"Cell type annotation failed: {str(e)}"}

annotate_celltype_scRNA_tool = StructuredTool.from_function(
    coroutine=annotate_celltype_scRNA_coroutine,
    name=Tools.annotate_celltype_scRNA,
    description="""
    【领域：生物】Annotate cell types based on gene markers and transferred labels using LLM.
    After leiden clustering, annotate clusters using differentially expressed genes
    and optionally incorporate transferred labels from reference datasets.
    Returns:
    - str: Steps performed and file paths where results were saved

    """,
    args_schema=AnnotateCelltypeInput,
    metadata={"args_schema_json":AnnotateCelltypeInput.schema()} 
)
