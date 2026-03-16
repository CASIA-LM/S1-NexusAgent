from pydantic import BaseModel, Field
from typing import Dict, Any
from rdkit import Chem
from rdkit.Chem import QED, Descriptors, rdMolDescriptors, FilterCatalog

from pydantic import BaseModel, Field
from typing import Dict, Any
from workflow.tools.chemistry.utils import is_multiple_smiles, split_smiles,tanimoto,is_smiles, pubchem_query2smiles
from langchain_core.tools import StructuredTool
from workflow.const import Tools
from workflow.utils.minio_utils import upload_content_to_minio
# ------------------------------
# 1. CalculateSA Tool 计算合成可及性
# ------------------------------
# delete


# ------------------------------
# 2. BrenkFilter Tool  Brenk filter 检查
# ------------------------------
class BrenkFilterInput(BaseModel):
    compound_smiles: str = Field(..., description="化合物的 SMILES 表达式")

async def brenk_filter_coroutine(compound_smiles: str) -> Dict[str, Any]:
    """使用 Brenk filter 检查分子中是否存在潜在毒性或不良片段。"""
    try:
        mol = Chem.MolFromSmiles(compound_smiles)
        if mol is None:
            return {"error": "Invalid SMILES string."}
        # params = FilterCatalogParams()
        # params.AddCatalog(FilterCatalogParams.FilterCatalogs.BRENK)
        # catalog = FilterCatalog(params)
        params = FilterCatalog.FilterCatalogParams()
        params.AddCatalog(FilterCatalog.FilterCatalogParams.FilterCatalogs.BRENK)
        catalog = FilterCatalog.FilterCatalog(params)
        entries = catalog.GetMatches(mol)
        alerts = [e.GetDescription() for e in entries]
        return {"has_alerts": len(alerts) > 0, "alerts": alerts}
    except Exception as e:
        return {"error": f"Brenk filter check failed: {str(e)}"}

brenk_filter_tool = StructuredTool.from_function(
    coroutine=brenk_filter_coroutine,
    name=Tools.BrenkFilter,
    description="""
    【领域：化学】
    使用 Brenk filter 检查分子是否含有潜在毒性或不良片段。
    输入: compound_smiles (SMILES 表达式)
    输出: has_alerts (bool), alerts (不良片段描述列表)
    """,
    args_schema=BrenkFilterInput,
    metadata={"args_schema_json": BrenkFilterInput.schema()}
)


# ------------------------------
# 3. BBBPermeant Tool  BBB 可 permeant 检查
# ------------------------------
class BBBPermeantInput(BaseModel):
    compound_smiles: str = Field(..., description="化合物的 SMILES 表达式")

async def bbb_permeant_coroutine(compound_smiles: str) -> Dict[str, Any]:
    """估算分子是否可能穿过血脑屏障 (BBB)。"""
    try:
        mol = Chem.MolFromSmiles(compound_smiles)
        if mol is None:
            return {"error": "Invalid SMILES string."}
        logp = Descriptors.MolLogP(mol)
        tpsa = rdMolDescriptors.CalcTPSA(mol)
        permeant = (logp > 2.0) and (tpsa < 90)
        return {"logP": round(float(logp), 3), "TPSA": round(float(tpsa), 2), "is_bbb_permeant": permeant}
    except Exception as e:
        return {"error": f"BBB permeability estimation failed: {str(e)}"}

bbb_permeant_tool = StructuredTool.from_function(
    coroutine=bbb_permeant_coroutine,
    name=Tools.BBBPermeant,
    description="""
    【领域：化学】
    估算分子是否可能穿过血脑屏障 (BBB)。
    输入: compound_smiles (SMILES 表达式)
    输出: logP, TPSA, is_bbb_permeant (bool)
    """,
    args_schema=BBBPermeantInput,
    metadata={"args_schema_json": BBBPermeantInput.schema()}
)


# ------------------------------
# 4. Druglikeness Tool 药物相似性检查
# ------------------------------
class DruglikenessInput(BaseModel):
    compound_smiles: str = Field(..., description="化合物的 SMILES 表达式")

async def druglikeness_coroutine(compound_smiles: str) -> Dict[str, Any]:
    """检查分子是否符合 Lipinski Rule of Five。"""
    try:
        mol = Chem.MolFromSmiles(compound_smiles)
        if mol is None:
            return {"error": "Invalid SMILES string."}
        mw = Descriptors.MolWt(mol)
        logp = Descriptors.MolLogP(mol)
        hbd = rdMolDescriptors.CalcNumHBD(mol)
        hba = rdMolDescriptors.CalcNumHBA(mol)
        lipinski = (mw < 500) and (logp < 5) and (hbd <= 5) and (hba <= 10)
        return {"MW": mw, "logP": logp, "HBD": hbd, "HBA": hba, "is_druglike": lipinski}
    except Exception as e:
        return {"error": f"Druglikeness check failed: {str(e)}"}

druglikeness_tool = StructuredTool.from_function(
    coroutine=druglikeness_coroutine,
    name=Tools.Druglikeness,
    description="""
    【领域：化学】
    根据 Lipinski Rule of Five 检查分子是否具有药物相似性。
    输入: compound_smiles (SMILES 表达式)
    输出: MW, logP, HBD, HBA, is_druglike (bool)
    """,
    args_schema=DruglikenessInput,
    metadata={"args_schema_json": DruglikenessInput.schema()}
)


# ------------------------------
# 5. GIAbsorption Tool 胃肠道吸收能力检查
# ------------------------------
class GIAbsorptionInput(BaseModel):
    compound_smiles: str = Field(..., description="化合物的 SMILES 表达式")

async def gi_absorption_coroutine(compound_smiles: str) -> Dict[str, Any]:
    """估算分子在胃肠道的吸收能力。"""
    try:
        mol = Chem.MolFromSmiles(compound_smiles)
        if mol is None:
            return {"error": "Invalid SMILES string."}
        logp = Descriptors.MolLogP(mol)
        tpsa = rdMolDescriptors.CalcTPSA(mol)
        absorption = (logp < 5) and (tpsa < 140)
        return {"logP": logp, "TPSA": tpsa, "is_high_gi_absorption": absorption}
    except Exception as e:
        return {"error": f"GI absorption estimation failed: {str(e)}"}

gi_absorption_tool = StructuredTool.from_function(
    coroutine=gi_absorption_coroutine,
    name=Tools.GIAbsorption,
    description="""
    【领域：化学】
    估算分子在胃肠道的吸收能力。
    输入: compound_smiles (SMILES 表达式)
    输出: logP, TPSA, is_high_gi_absorption (bool)
    """,
    args_schema=GIAbsorptionInput,
    metadata={"args_schema_json": GIAbsorptionInput.schema()}
)


# ------------------------------
# 6. QED Tool 定量药物相似性检查
# ------------------------------
class QEDInput(BaseModel):
    compound_smiles: str = Field(..., description="化合物的 SMILES 表达式")

async def qed_coroutine(compound_smiles: str) -> Dict[str, Any]:
    """计算分子的定量药物相似性 (QED) 值。"""
    try:
        mol = Chem.MolFromSmiles(compound_smiles)
        if mol is None:
            return {"error": "Invalid SMILES string."}
        qed_score = QED.qed(mol)
        return {"qed": round(float(qed_score), 3)}
    except Exception as e:
        return {"error": f"QED calculation failed: {str(e)}"}

qed_tool = StructuredTool.from_function(
    coroutine=qed_coroutine,
    name=Tools.QED,
    description="""
    【领域：化学】
    计算分子的定量药物相似性 (QED) 值。
    输入: compound_smiles (SMILES 表达式)
    输出: qed (0-1 之间的浮点数, 数值越高药物相似性越强)
    """,
    args_schema=QEDInput,
    metadata={"args_schema_json": QEDInput.schema()}
)


# ------------------------------
# 7. PAINSFilter Tool  PAINS filter 检查
# ------------------------------
class PAINSFilterInput(BaseModel):
    compound_smiles: str = Field(..., description="化合物的 SMILES 表达式")

async def pains_filter_coroutine(compound_smiles: str) -> Dict[str, Any]:
    """使用 PAINS filter 检查分子中是否存在假阳性片段。"""
    try:
        mol = Chem.MolFromSmiles(compound_smiles)
        if mol is None:
            return {"error": "Invalid SMILES string."}
        # params = FilterCatalogParams()
        # params.AddCatalog(FilterCatalogParams.FilterCatalogs.PAINS)
        # catalog = FilterCatalog(params)
        # 初始化 PAINS FilterCatalog
        params = FilterCatalog.FilterCatalogParams()  # 初始化参数对象
        params.AddCatalog(FilterCatalog.FilterCatalogParams.FilterCatalogs.PAINS)  # 添加 PAINS 过滤器
        catalog = FilterCatalog.FilterCatalog(params)  # 创建 FilterCatalog

        entries = catalog.GetMatches(mol)
        alerts = [e.GetDescription() for e in entries]
        return {"has_pains": len(alerts) > 0, "alerts": alerts}
    except Exception as e:
        return {"error": f"PAINS filter check failed: {str(e)}"}

pains_filter_tool = StructuredTool.from_function(
    coroutine=pains_filter_coroutine,
    name=Tools.PAINSFilter,
    description="""
    【领域：化学】
    使用 PAINS filter 检查分子中是否含有可能导致假阳性的片段。
    输入: compound_smiles (SMILES 表达式)
    输出: has_pains (bool), alerts (命中的片段描述列表)
    """,
    args_schema=PAINSFilterInput,
    metadata={"args_schema_json": PAINSFilterInput.schema()}
)

