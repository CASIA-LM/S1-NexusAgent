class Node:
    REFLECTION = "unknown_reflection"
    ROUTE = "route"
    PLANNER: str = 'unknown_planner'
    GENERAL = 'general'
    EXECUTE = 'unknown_execute'
    CLARIFY = 'clarify'
    PARSE = 'parse'
    PICKUP = 'pick_up'
    REPORT = 'unknown_report'
    SUMMARY = 'unknown_summary'
    END: str = '__end__'
    TOOOLS: str = 'tools'
    COORDINATOR: str = 'coordinator'
    TALK_CHECK: str = 'talk_check'
    USER_MCP: str = 'user_mcp'
    SCENE: str = 'scene'
    CLARIFY_TOOL: str = 'clarify_tool'
    CLARIFY_REQUIRE: str = 'clarify_require'
    CLARIFY_DEFAULT: str = 'clarify_default'
    RESEARCH: str = 'research_agent'
    SUPERVISOR: str = 'unknown_supervisor'
    TOOL_NODE: str = 'tool_node'
    SHOULD_CONTINUE: str = 'should_continue'
    CHECK_TOOL_ARGS: str = 'check_tool_args'
    FINAL_ANSWER: str = 'final_answer'
    CHECK_TOOL: str = 'unknown_check_tool'
    IDENTIFY_LANGUAGE: str = 'unknown_identify_language'
    WEB_SEARCH: str = 'web_search'
    RETRIEVAL_TOOLS: str = 'unknown_retrieval_tools'
    GENERAL: str = 'unknown_general'
    TALK_CHECK: str = 'unknown_talk_check'
    REPLAN: str = 'unknown_replan'
    INTENT_DETECT: str = 'unknown_intent_detect'
    SKILL_MATCH: str = 'skill_match'

class Tools:
    # Try not to use English for values, this will be displayed in the tool chain dialogue process
    DNA_PREDICT = "dna_sequence_completion"
    PROTEIN_COMPLETE = "protein_sequence_completion"
    GENERATE_PDB_FROM_PROTEIN = "generate_pdb_from_protein_sequence"
    GENMOL_MOLECULE_GENERATOR = "molecular_structure_generator"
    PROTEIN_DIFFUSION_GENERATOR = "protein_backbone_generator"
    PROTGPT2_PROTEIN_GENERATOR = "protgpt2_protein_generator"
    PROTGPT2_PROTEIN_PREPLEXITY_CALCULATOR = "protgpt2_protein_perplexity_calculator"
    GEN_RELATION = "gene_interaction_query"
    GEN_PROTEIN_INFO = "gene_associated_protein_query"
    PROTEIN_HOMOLOGY_EVALUATION = "protein_homology_evaluation"
    FIRECRAWL_ONE_PAGE = "single_webpage_content_scraping"
    PROTEIN_IDENTIFIER = "protein_disease_mutation_identification"
    AF2_MULTIMER = "af2_multimer_complex_prediction"
    CITATION_CONVERT = "citation_format_conversion"
    DIFFSBDD_GENERATE_LIGANDS = "diffsbdd_ligand_generation"
    ESM_FOLD_PREDICT_3D = "esm_fold_3d_structure_prediction"
    OLIGO_FORMER = "oligoformer_sirna_prediction"
    PYMOL = "pymol_interaction_analysis"
    MATTER_GEN = "crystal_material_generation"
    OPEN_BABEL_CONVERT = "openbabel_chemical_format_conversion"
    UNSTRUCTED_EXTRACT = "unstructured_data_extraction"
    RDKit_MOLECULE_PROPERTIES = "rdkit_molecule_property_prediction"
    RDKit_MOLECULE_CONVERT = "rdkit_molecule_format_conversion"
    SCIENCE_CALCULATE = "scientific_calculator"
    SPECTRUM_ANALYSIS = "spectroscopic_structure_analysis"
    BIOLOGY_ANALYSIS_PLOT = "biological_data_visualization"
    TORA_CALCULATE = "tora_mathematical_solver"
    CALCULATE_BINDING_ENERGY = "calculate_binding_energy"

    PROTEIN_ID_INFO = 'protein_id_information_query'
    GET_PROTEIN_DETAILED_INFO = 'get_protein_detailed_information'
    QUERY_PDB = 'query_pdb_database'
    QUERY_UNIPROT = 'query_uniprot_database'
    QUERY_ALPHAFOLD = 'query_alphafold_database'
    QUERY_GWAS_CATALOG = 'query_gwas_catalog_database'
    QUERY_DBSNP = 'query_dbsnp_database'
    QUERY_GEO = 'query_geo_database'
    QUERY_CLINVAR = 'query_clinvar_database'
    QUERY_UCSC = 'query_ucsc_genome_browser'
    ANALYZE_CIRCULAR_DICHROISM_SPECTRA = 'analyze_circular_dichroism_spectra'
    ANALYZE_PROTEIN_CONSERVATION = 'analyze_protein_sequence_conservation'
    ANALYZE_ITC_BINDING_THERMODYNAMICS = 'analyze_itc_binding_thermodynamics'
    analyze_protease_kinetics_tool = 'analyze_protease_kinetics'
    analyze_enzyme_kinetics_assay = 'analyze_enzyme_kinetics'
    analyze_rna_secondary_structure = 'analyze_rna_secondary_structure'
    analyze_cell_migration_metrics = 'analyze_cell_migration_metrics'
    perform_crispr_cas9_genome_editing = 'perform_crispr_cas9_genome_editing'
    analyze_calcium_imaging_data = 'analyze_calcium_imaging_data'
    get_and_analyse_area_data = 'geographical_data_analysis'
    visualize_area_data = 'geographical_data_visualization'
    PREDICT_RNA_SECONDARY_STRUCTURE = 'predict_rna_secondary_structure'
    QUERY_KEGG = 'query_kegg_database'
    QUERY_STRINGDB = 'query_stringdb_database'
    QUERY_REACTOME = 'query_reactome_database'
    QUERY_PDB_IDENTIFIERS = 'query_pdb_identifiers'
    QUERY_OPENTARGETS_GENETICS = 'query_opentargets_genetics_database'
    QUERY_INTERPRO = 'query_interpro_database'

    RETRIEVE_TOPK_REPURPOSING_DRUGS = 'retrieve_topk_repurposing_drugs'
    retrieve_topk_repurposing_drugs_from_disease_txgnn = 'txgnn_disease_drug_repositioning'
    design_knockout_sgrna = 'design_knockout_sgrna'
    annotate_celltype_scRNA = 'scrna_cell_type_annotation'
    predict_admet_properties = 'predict_admet_properties'
    get_gene_set_enrichment_analysis_supported_database_list = 'query_gsea_supported_databases'
    gene_set_enrichment_analysis = "gene_set_enrichment_analysis"
    smiles_property = 'smiles_molecule_property_prediction'
    to_smiles = 'mass_spec_to_smiles_conversion'
    # bio_literature
    query_arxiv = 'query_arxiv_database'
    QUERY_PUBMED = 'query_pubmed_database'
    extract_url_content = 'extract_webpage_content'
    query_scholar = 'query_google_scholar_database'

    # bio_immunology
    analyze_bacterial_growth_curve = 'analyze_bacterial_growth_curve'
    ISOLATE_PURIFY_IMMUNE_CELLS = 'isolate_purify_immune_cells'
    estimate_cell_cycle_phase_durations = 'estimate_cell_cycle_phase_durations'
    analyze_ebv_antibody_titers = 'analyze_ebv_antibody_titers'

    # bio_micro
    optimize_anaerobic_digestion_process = 'optimize_anaerobic_digestion_process'
    annotate_bacterial_genome = 'annotate_bacterial_genome'
    analyze_arsenic_speciation_hplc_icpms = 'analyze_arsenic_speciation_hplc_icpms'
    enumerate_bacterial_cfu_by_serial_dilution = 'enumerate_bacterial_cfu_serial_dilution'
    simulate_bacterial_growth_dynamics = 'simulate_bacterial_growth_dynamics'
    quantify_biofilm_biomass_crystal_violet = 'quantify_biofilm_biomass_crystal_violet'
    simulate_generalized_lotka_volterra_dynamics = 'simulate_generalized_lotka_volterra_dynamics'
    simulate_microbial_population_dynamics = 'simulate_microbial_population_dynamics'

    # bio_molecular
    get_gene_coding_sequence = 'get_gene_coding_sequence'
    get_oligo_annealing_protocol = 'get_oligo_annealing_protocol'
    # design_knockout_sgrna (Duplicate, already present)
    get_golden_gate_assembly_protocol = 'get_golden_gate_assembly_protocol'
    get_bacterial_transformation_protocol = 'get_bacterial_transformation_protocol'
    design_primer = 'design_primer'
    design_golden_gate_oligos = 'design_golden_gate_oligos'
    get_plasmid_sequence = 'get_plasmid_sequence'
    align_sequences = 'sequence_alignment'
    digest_sequence = 'sequence_restriction_analysis'
    find_restriction_sites = 'find_restriction_enzyme_sites'
    find_common_restriction_sites = 'find_common_restriction_enzyme_sites'
    find_sequence_mutations = 'find_sequence_mutation_sites'
    design_verification_primers = 'design_verification_primers'
    pcr_simple = 'routine_pcr'
    golden_gate_assembly = 'golden_gate_assembly'

    # bio_genetics
    CAS9_MUTATION_ANALYSIS = 'cas9_gene_mutation_analysis'
    CRISPR_GENOME_EDITING = 'crispr_genome_editing'
    DEMOGRAPHY_SIMULATION = 'population_dynamics_simulation'
    TF_BINDING_SITE = 'transcription_factor_binding_site_prediction'
    PCR_GEL_TOOL = 'pcr_gel_electrophoresis_analysis'

    # bio_chemistry
    ANALYZE_CIRCULAR_DICHROISM_SPECTRA_BMN = 'analyze_circular_dichroism_spectra_bmn'
    ANALYZE_PROTEIN_CONSERVATION_BMN = 'analyze_protein_conservation_bmn'
    analyze_protease_kinetics_tool_BMN = 'analyze_protease_kinetics_bmn'
    analyze_enzyme_kinetics_assay_BMN = 'analyze_enzyme_kinetics_assay_bmn'
    analyze_rna_secondary_structure_BMN = 'analyze_rna_secondary_structure_bmn'

    # bio_systems
    perform_fba = 'perform_flux_balance_analysis'
    simulate_ras = 'simulate_ras_protein_signaling_pathway'
    # bio_engineering
    perform_crispr_cas9_genome_editing_bmn = 'perform_crispr_cas9_genome_editing_bmn'
    analyze_in_vitro_drug_release_bmn = 'analyze_in_vitro_drug_release_bmn'
    # bio_pharmacology
    analyze_accelerated_stability_of_pharmaceutical_formulations = 'analyze_accelerated_stability_of_pharmaceutical_formulations'
    run_3d_chondrogenic_aggregate_assay = 'run_3d_chondrogenic_aggregate_assay'
    analyze_radiolabeled_antibody_biodistribution = 'analyze_radiolabeled_antibody_biodistribution'
    estimate_alpha_particle_radiotherapy_dosimetry = 'estimate_alpha_particle_radiotherapy_dosimetry'
    calculate_physicochemical_properties = 'calculate_physicochemical_properties'

    # bio_pathlogy


    # chemistry
    # catus
    GIAbsorption = 'gi_absorption_prediction'
    BrenkFilter = 'brenk_filter'
    PAINSFilter = 'pains_filter'
    QED = 'quantitative_estimate_of_druglikeness'
    BBBPermeant = 'bbb_permeability_prediction'
    Druglikeness = 'druglikeness_assessment'

    # chemcrow
    MolSimilarity = 'molecular_similarity_calculation'
    SMILES2Weight = 'smiles_to_molecular_weight_conversion'
    FuncGroups = 'functional_group_analysis'

    # chemistrytools
    CALCULATE_SPECTRUM_SIMILARITY = 'calculate_spectrum_similarity'
    CONVERT_CID_TO_IUPAC = 'convert_pubchem_cid_to_iupac_name'
    GET_COMPOUND_CHARGE_BY_CID = 'get_compound_charge_by_pubchem_cid'
    CONVERT_CID_TO_FORMULA = 'convert_pubchem_cid_to_chemical_formula'
    GET_COMPOUND_CID = 'get_compound_pubchem_cid'
    GET_ELEMENT_INFORMATION = 'get_element_information'


    # sci_agent_chem_1
    search_materials_containing_elements = 'search_materials_containing_elements'
    search_materials_by_chemsys = 'search_materials_by_chemical_system'
    get_material_id_by_formula = 'get_material_id_by_formula'
    get_formula_by_material_id = 'get_formula_by_material_id'
    get_band_gap_by_material_id = 'get_band_gap_by_material_id'
    CONVERT_SMILES_TO_INCHI = 'convert_smiles_to_inchi'
    SHOW_MOL = 'show_molecular_structure'
    ADD_HYDROGENS = 'add_hydrogens'
    REMOVE_HYDROGENS = 'remove_hydrogens'
    KEKULIZE = 'kekulize_molecule'
    SET_AROMATICITY = 'set_aromaticity'
    PATTERN_FINGERPRINT = 'calculate_pattern_fingerprint'
    MORGAN_FINGERPRINT = 'calculate_morgan_fingerprint'
    RDKIT_FINGERPRINT = 'calculate_rdkit_fingerprint'
    CALCULATE_MOL_FORMULA = 'calculate_molecular_formula'
    get_band_gap_by_formula = 'get_band_gap_by_formula'

    # sci_agent_chem_2
    SAFETY_REPORT = 'safety_information_summary'
    cluster_molecules = 'cluster_molecules'
    calculate_distance_matrix = 'calculate_distance_matrix'
    calculate_shape_similarity = 'calculate_shape_similarity'
    fold_fingerprint_from_smiles = 'fold_fingerprint_from_smiles'
    process_fingerprint_mol = 'process_molecular_fingerprint'
    fingerprints_from_smiles = 'calculate_fingerprints_from_smiles'


    # material
    # my_material
    MATTER_EVAL = "crystal_material_property_evaluation"
    CREATE_CUBIC_LATTICE = "create_cubic_lattice"
    CREATE_STRUCTURE = "create_crystal_structure"
    MODIFY_STRUCTURE = "modify_crystal_structure"
    CREATE_IMMUTABLE_STRUCTURE = "create_immutable_structure"
    FETCH_AND_SAVE_STRUCTURE = "fetch_and_save_structure_file"
    ANALYZE_SYMMETRY = 'crystal_symmetry_analysis'
    GET_ATOMIC_MASS = 'get_atomic_mass'
    GET_COMPOSITION_PROPERTIES = 'get_composition_properties'
    CREATE_PHASE_DIAGRAM = 'create_phase_diagram'
    GET_E_ABOVE_HULL = 'calculate_material_thermodynamic_stability'
    SYNTHETIC_FEASIBILITY = 'synthetic_feasibility_analysis'
    ADMET_TOX_PREDICTION = 'admet_toxicity_prediction'
    FETCH_MRNA_SEQUENCE2 = 'fetch_mrna_sequence'
    FETCH_AND_SAVE_ENTRIES = "database_entry_retrieval_and_saving"

    # sci_agent_mat_2
    CREATE_DEFECT = 'create_defect'
    GET_ELEMENTS_BY_MATERIAL_ID = 'get_elements_by_material_id'
    GET_COMPOSITION_BY_MATERIAL_ID = 'get_composition_by_material_id'
    GET_STRUCTURE_GRAPH = 'get_structure_graph'
    PLOT_ADJACENCY_MATRIX = 'plot_adjacency_matrix'
    CHECK_EXPLOSIVENESS = 'check_explosiveness'
    GET_DENSITY_BY_MATERIAL_ID = 'get_density_by_material_id'
    GET_VOLUME_BY_MATERIAL_ID = 'get_volume_by_material_id'
    GET_VOLUME_BY_FORMULA = 'get_volume_by_formula'
    GET_ENERGY_ABOVE_HULL = 'get_energy_above_hull'
    GET_FORMATION_ENERGY_PER_ATOM = 'get_formation_energy_per_atom'
    IS_STABLE = 'check_stability'

    # mat_sci
    MaterialsProjectSurfaceProperties = 'materials_project_surface_properties'
    MaterialsProjectThermo = 'materials_project_thermodynamic_properties'
    MaterialsProjectDielectric = 'materials_project_dielectric_properties'
    MaterialsProjectPiezoelectric = 'materials_project_piezoelectric_properties'
    MaterialsProjectSynthesis = 'materials_project_synthesis_information'
    MaterialsProjectElectronicStructure = 'materials_project_electronic_structure'
    MaterialsProjectElectronicBandStructure = 'materials_project_electronic_band_structure'
    MaterialsProjectOxidationStates = 'materials_project_oxidation_states'
    MaterialsProjectBonds = 'materials_project_bonding_information'
    MaterialsProjectAbsorption = 'materials_project_absorption_properties'




class Flag:
    REFLECTION_SUCCESS = "Execution process appropriate"
    EXECUTE_ERROR = 'Please try again later'
    NO_THINK = 'Non-reasoning mode'
    PASSING_SCORE = 50
    TO_SUMMARY_SCORE = 40
    CLARIFY_COMPLETE = 'Clarification completed'
