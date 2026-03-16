"""Tool registry for S1-NexusAgent.

Domain tools are organised into three science areas:
  - biology_domain  — biochemistry, genomics, genetics, molecular biology, …
  - chemistry_domain — drug-likeness, cheminformatics, fingerprinting, …
  - material_domain  — Materials Project API, structure analysis, …

Plus general tools (web search, image description).
"""
import uuid
from typing import Any, Dict, List

from fastapi.encoders import jsonable_encoder
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_openai import OpenAIEmbeddings
from pydantic import BaseModel

from workflow import config as science_config

# =============================================================================
# Biology — explicit imports
# =============================================================================

from .bio_biochemistry import (
    analyze_cd_tool,
    analyze_protein_conservation_tool,
    analyze_itc_binding_thermodynamics_tool,
    analyze_protease_kinetics_tool,
    analyze_enzyme_kinetics_assay_tool,
    analyze_rna_secondary_structure_tool,
)

from .bio_engineering import (
    crispr_cas9_genome_editing_tool,
)

from .bio_genomics import (
    gene_set_enrichment_analysis_tool,
    get_supported_enrichment_databases_tool,
    annotate_celltype_scRNA_tool,
    # predict_admet_properties_tool — REMOVED: installs DeepPurpose at runtime
    # retrieve_topk_repurposing_drugs_tool — REMOVED: requires local txgnn pickle files
)

from .bio_genetics import (
    cas9_mutation_tool,
    crispr_editing_tool,
    pcr_gel_tool,
)

from .bio_systems import (
    perform_fba_tool,
)

from .bio_pharmacology import (
    analyze_stability_tool,
    run_3d_chondrogenic_aggregate_assay_tool,
    analyze_radiolabeled_antibody_biodistribution_tool,
    estimate_alpha_particle_radiotherapy_dosimetry_tool,
    calculate_physicochemical_properties_tool,
)

from .bio_immunology import (
    analyze_bacterial_growth_curve_tool,
    isolate_purify_immune_cells_tool,
    estimate_cell_cycle_phase_durations_tool,
    analyze_ebv_antibody_titers_tool,
)

from .bio_literature import (
    query_arxiv_tool,
    query_pubmed_tool,
    extract_url_content_tool,
    web_crawl_tool,
)

from .bio_micro import (
    enumerate_cfu_tool,
    model_bacterial_growth_dynamics_tool,
    quantify_biofilm_biomass_crystal_violet_tool,
    simulate_generalized_lotka_volterra_dynamics_tool,
    simulate_microbial_population_dynamics_tool,
)

from .bio_molecular import (
    get_plasmid_sequence_tool,
    align_sequences_tool,
    pcr_simple_tool,
    digest_sequence_tool,
    find_restriction_sites_tool,
    find_common_restriction_sites,
    find_sequence_mutations_tool,
    design_knockout_sgrna_tool,
    get_oligo_annealing_protocol_tool,
    get_golden_gate_assembly_protocol_tool,
    get_bacterial_transformation_protocol_tool,
    design_primer_tool,
    design_verification_primers_tool,
    design_golden_gate_oligos_tool,
)

from .biomini_eval_tools import (
    query_dbsnp_tool,
    query_ensembl_tool,
    query_pubmed_bio_tool,
    query_gwas_catalog_tool,
    query_opentarget_tool,
    query_uniprot_tool,
    query_arxiv_bio_tool,
    phen2gene_tool,
    hpo_search_tool,
)

# =============================================================================
# Chemistry — explicit imports
# =============================================================================

from .chemistry.catus import (
    brenk_filter_tool,
    bbb_permeant_tool,
    druglikeness_tool,
    gi_absorption_tool,
    qed_tool,
    pains_filter_tool,
)

from .chemistry.chemcrow import (
    mol_similarity_tool,
    smiles2weight_tool,
    func_groups_tool,
)

from .chemistry.chemistrytools import (
    get_element_information_tool,
    get_compound_CID_tool,
    convert_compound_CID_to_formula_tool,
    get_compound_charge_by_CID_tool,
    convert_compound_CID_to_IUPAC_tool,
    calculate_spectrum_similarity_tool,
)

from .chemistry.sci_agent_chem_1 import (
    calculate_MolFormula_tool,
    convert_smiles_to_inchi_tool,
    morgan_fingerprint_tool,
    rdkit_fingerprint_tool,
    pattern_fingerprint_tool,
)

from .chemistry.sci_agent_chem_2 import (
    calculate_shape_similarity_tool,
    cluster_molecules_tool,
    fingerprints_from_smiles_tool,
    fold_fingerprint_from_smiles_tool,
)

# =============================================================================
# Material science — explicit imports
# =============================================================================

from .material.mat_sci import (
    mp_surface_properties_tool,
    mp_thermo_tool,
    mp_dielectric_tool,
    get_piezoelectric_data_tool,
    mp_synthesis_tool,
    mp_electronic_structure_tool,
    mp_electronic_band_structure_tool,
    oxidation_states_tool,
    bonds_tool,
    mp_absorption_tool,
)

from .material.sci_agent_mat_1 import (
    search_materials_containing_elements_tool,
    search_materials_by_chemsys_tool,
    get_material_id_by_formula_tool,
    get_formula_by_material_id_tool,
    get_band_gap_by_material_id_tool,
    get_band_gap_by_formula_tool,
)

from .material.sci_agent_mat_2 import (
    get_density_by_material_id_tool,
    get_energy_above_hull_tool,
    get_formation_energy_per_atom_tool,
    is_stable_tool,
)

# =============================================================================
# General tools
# =============================================================================

from .normal import search_tool, image_to_desc

# =============================================================================
# Tool groups — only tools listed here are active
# =============================================================================

# ── General (2 tools) ─────────────────────────────────────────────────────────
normal_tools: List = [
    search_tool,        # Tavily web search
    image_to_desc,      # Vision-language image description
]

# ── Biology (~53 tools) ───────────────────────────────────────────────────────
bio_biochemistry_tools: List = [
    analyze_cd_tool,
    analyze_protein_conservation_tool,
    analyze_itc_binding_thermodynamics_tool,
    analyze_protease_kinetics_tool,
    analyze_enzyme_kinetics_assay_tool,
    analyze_rna_secondary_structure_tool,
]

bio_engineering_tools: List = [
    crispr_cas9_genome_editing_tool,
]

bio_genomics_tools: List = [
    gene_set_enrichment_analysis_tool,
    get_supported_enrichment_databases_tool,
    annotate_celltype_scRNA_tool,
]

bio_genetics_tools: List = [
    cas9_mutation_tool,
    crispr_editing_tool,
    pcr_gel_tool,
]

bio_systems_tools: List = [
    perform_fba_tool,
]

bio_pharmacology_tools: List = [
    analyze_stability_tool,
    run_3d_chondrogenic_aggregate_assay_tool,
    analyze_radiolabeled_antibody_biodistribution_tool,
    estimate_alpha_particle_radiotherapy_dosimetry_tool,
    calculate_physicochemical_properties_tool,
]

bio_immunology_tools: List = [
    analyze_bacterial_growth_curve_tool,
    isolate_purify_immune_cells_tool,
    estimate_cell_cycle_phase_durations_tool,
    analyze_ebv_antibody_titers_tool,
]

bio_literature_tools: List = [
    query_arxiv_tool,
    query_pubmed_tool,
    extract_url_content_tool,
    web_crawl_tool,
]

bio_micro_tools: List = [
    enumerate_cfu_tool,
    model_bacterial_growth_dynamics_tool,
    quantify_biofilm_biomass_crystal_violet_tool,
    simulate_generalized_lotka_volterra_dynamics_tool,
    simulate_microbial_population_dynamics_tool,
]

bio_molecular_tools: List = [
    get_plasmid_sequence_tool,
    align_sequences_tool,
    pcr_simple_tool,
    digest_sequence_tool,
    find_restriction_sites_tool,
    find_common_restriction_sites,
    find_sequence_mutations_tool,
    design_knockout_sgrna_tool,
    get_oligo_annealing_protocol_tool,
    get_golden_gate_assembly_protocol_tool,
    get_bacterial_transformation_protocol_tool,
    design_primer_tool,
    design_verification_primers_tool,
    design_golden_gate_oligos_tool,
]

bio_database_tools: List = [
    query_dbsnp_tool,
    query_ensembl_tool,
    query_pubmed_bio_tool,
    query_gwas_catalog_tool,
    query_opentarget_tool,
    query_uniprot_tool,
    query_arxiv_bio_tool,
    phen2gene_tool,
    hpo_search_tool,
]

biology_domain: List = (
    bio_biochemistry_tools
    + bio_engineering_tools
    + bio_genomics_tools
    + bio_genetics_tools
    + bio_systems_tools
    + bio_pharmacology_tools
    + bio_immunology_tools
    + bio_literature_tools
    + bio_micro_tools
    + bio_molecular_tools
    + bio_database_tools
)

# ── Chemistry (~24 tools) ─────────────────────────────────────────────────────
chem_druglikeness_tools: List = [
    brenk_filter_tool,
    bbb_permeant_tool,
    druglikeness_tool,
    gi_absorption_tool,
    qed_tool,
    pains_filter_tool,
]

chem_basic_tools: List = [
    mol_similarity_tool,
    smiles2weight_tool,
    func_groups_tool,
]

chem_pubchem_tools: List = [
    get_element_information_tool,
    get_compound_CID_tool,
    convert_compound_CID_to_formula_tool,
    get_compound_charge_by_CID_tool,
    convert_compound_CID_to_IUPAC_tool,
    calculate_spectrum_similarity_tool,
]

chem_fingerprint_tools: List = [
    calculate_MolFormula_tool,
    convert_smiles_to_inchi_tool,
    morgan_fingerprint_tool,
    rdkit_fingerprint_tool,
    pattern_fingerprint_tool,
    calculate_shape_similarity_tool,
    cluster_molecules_tool,
    fingerprints_from_smiles_tool,
    fold_fingerprint_from_smiles_tool,
]

chemistry_domain: List = (
    chem_druglikeness_tools
    + chem_basic_tools
    + chem_pubchem_tools
    + chem_fingerprint_tools
)

# ── Material science (~20 tools) ─────────────────────────────────────────────
mat_mp_tools: List = [
    mp_surface_properties_tool,
    mp_thermo_tool,
    mp_dielectric_tool,
    get_piezoelectric_data_tool,
    mp_synthesis_tool,
    mp_electronic_structure_tool,
    mp_electronic_band_structure_tool,
    oxidation_states_tool,
    bonds_tool,
    mp_absorption_tool,
]

mat_search_tools: List = [
    search_materials_containing_elements_tool,
    search_materials_by_chemsys_tool,
    get_material_id_by_formula_tool,
    get_formula_by_material_id_tool,
    get_band_gap_by_material_id_tool,
    get_band_gap_by_formula_tool,
]

mat_property_tools: List = [
    get_density_by_material_id_tool,
    get_energy_above_hull_tool,
    get_formation_energy_per_atom_tool,
    is_stable_tool,
]

material_domain: List = mat_mp_tools + mat_search_tools + mat_property_tools

# ── Base tools (always available, not domain-specific) ───────────────────────
base_tools: List = normal_tools

# ── All domain tools — the main retrieval registry ───────────────────────────
tools: List = normal_tools + biology_domain + chemistry_domain + material_domain

# =============================================================================
# Vector store for tool retrieval
# =============================================================================

tool_registry: Dict = {str(uuid.uuid4()): tool for tool in tools}

vector_store = InMemoryVectorStore(
    embedding=OpenAIEmbeddings(
        api_key=science_config.Qwen3Embedding.api_key,
        model=science_config.Qwen3Embedding.model,
        base_url=science_config.Qwen3Embedding.base_url,
        check_embedding_ctx_length=False,
    )
)

users_store: Dict = {}
document_ids = vector_store.add_documents([])
local_tools: List = list(tool_registry.values())


# =============================================================================
# Tool selection utilities
# =============================================================================

def select_tools_by_scene(user_tools: list, query_scene: str) -> list:
    """Return tools matching a given scene name from the local registry."""
    selected = []
    for lt in local_tools:
        if not lt.metadata:
            continue
        for sc in lt.metadata.get("scenes", []):
            if query_scene == sc.get("name"):
                selected.append(
                    {
                        "name": lt.name,
                        "description": lt.description,
                        "args": lt.args,
                        "scene": sc,
                    }
                )
                break

    for ut in user_tools or []:
        for sc in ut.get("scenes", []):
            if sc.get("name") == query_scene:
                selected.append(
                    {
                        "name": ut.get("name"),
                        "description": ut.get("description"),
                        "args": ut.get("args"),
                        "scene": sc,
                    }
                )
                break
    return selected


def select_all_tools(tools: List[Any]) -> List[Dict[str, Any]]:
    """Serialize a list of StructuredTool objects to JSON-compatible dicts."""
    selected: List[Dict[str, Any]] = []
    for ut in tools or []:
        schema_cls = getattr(ut, "args_schema", None)
        if isinstance(schema_cls, type) and issubclass(schema_cls, BaseModel):
            args = schema_cls.model_json_schema()
        elif isinstance(schema_cls, dict):
            args = schema_cls
        else:
            args = None
        selected.append(
            {
                "name": getattr(ut, "name", ""),
                "description": getattr(ut, "description", ""),
                "args": args,
            }
        )
    return jsonable_encoder(selected)


__all__ = [
    # Domain groups
    "biology_domain",
    "chemistry_domain",
    "material_domain",
    "normal_tools",
    "base_tools",
    "tools",
    # Biology sub-groups
    "bio_biochemistry_tools",
    "bio_engineering_tools",
    "bio_genomics_tools",
    "bio_genetics_tools",
    "bio_systems_tools",
    "bio_pharmacology_tools",
    "bio_immunology_tools",
    "bio_literature_tools",
    "bio_micro_tools",
    "bio_molecular_tools",
    "bio_database_tools",
    # Chemistry sub-groups
    "chem_druglikeness_tools",
    "chem_basic_tools",
    "chem_pubchem_tools",
    "chem_fingerprint_tools",
    # Material sub-groups
    "mat_mp_tools",
    "mat_search_tools",
    "mat_property_tools",
    # Registry
    "vector_store",
    "tool_registry",
    "local_tools",
    "users_store",
    # Utilities
    "select_tools_by_scene",
    "select_all_tools",
]
