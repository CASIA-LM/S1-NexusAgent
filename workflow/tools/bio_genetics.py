# 标准库
import os
import io
import json
import pickle
import tempfile
import subprocess
import re
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Literal
import requests

# 科学计算
import numpy as np
import pandas as pd
from scipy import linalg
from scipy.stats import norm
import matplotlib.pyplot as plt


# 生物信息学
import warnings
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", module="Bio.pairwise2")
    from Bio import SeqIO, AlignIO, Phylo, pairwise2, motifs
from Bio.Seq import Seq



# LangChain / LangGraph
from langchain_core.tools import StructuredTool
from workflow.const import Tools
# Pydantic
from pydantic import BaseModel, Field, ConfigDict,field_validator
from workflow.utils.minio_utils import upload_content_to_minio



def upload_content_to_minio_sync(*args, **kwargs):
    return asyncio.run(upload_content_to_minio(*args, **kwargs))



def safe_get_schema(model_class):
    """安全地获取模型的 JSON Schema"""
    try:
        return model_class.model_json_schema()
    except Exception as e:
        print(f"Warning: Failed to generate JSON schema: {e}")
        return {
            "type": "object",
            "title": model_class.__name__,
            "properties": {},
            "description": "Schema generation fallback"
        }




#测试成功
class Cas9MutationAnalysisInput(BaseModel):
    reference_sequences: Dict[str, str] = Field(..., description="Dictionary of reference DNA sequences {seq_id: sequence}")
    edited_sequences: Dict[str, Dict[str, str]] = Field(..., description="Nested dict {seq_id: {read_id: edited_sequence}}")
    cell_line_info: Optional[Dict[str, str]] = Field(None, description="Optional cell line info for each sequence")
    output_prefix: Optional[str] = Field("cas9_mutation_analysis", description="Prefix for output files")

def cas9_mutation_analysis_coroutine(
    reference_sequences: Dict[str, str],
    edited_sequences: Dict[str, Dict[str, str]],
    cell_line_info: Optional[Dict[str, str]] = None,
    output_prefix: str = "cas9_mutation_analysis"
) -> str:

    # --- Initialize log and mutation storage ---
    log = "# Cas9-Induced Mutation Outcome Analysis\n\n"
    log += f"Analyzing {len(reference_sequences)} target sites...\n"
    results = []
    mutation_counts = defaultdict(lambda: defaultdict(int))

    categories = {
        "no_mutation": "No mutation detected",
        "short_deletion": "Short deletion (1-10 bp)",
        "medium_deletion": "Medium deletion (11-30 bp)",
        "long_deletion": "Long deletion (>30 bp)",
        "single_insertion": "Single base insertion",
        "longer_insertion": "Longer insertion (>1 bp)",
        "indel": "Insertion and deletion"
    }

    # --- Process each reference sequence ---
    for seq_id, ref_seq in reference_sequences.items():
        cell_line = cell_line_info.get(seq_id, "Unknown") if cell_line_info else "Unknown"
        site_results = []
        site_mutation_counts = defaultdict(int)
        total_reads = len(edited_sequences.get(seq_id, {}))
        if total_reads == 0:
            log += f"No edited sequences for {seq_id}\n"
            continue
        for read_id, edited_seq in edited_sequences.get(seq_id, {}).items():
            alignments = pairwise2.align.globalms(ref_seq, edited_seq, 2, -1, -2, -0.5)
            if not alignments:
                continue
            ref_aligned, edited_aligned, _, _, _ = alignments[0]

            # Detect indels
            deletions, insertions, del_count, ins_count = [], [], 0, 0
            i, j = 0, 0
            while i < len(ref_aligned) and j < len(edited_aligned):
                if ref_aligned[i] == '-':
                    ins_start = j
                    while i < len(ref_aligned) and ref_aligned[i] == '-':
                        i += 1
                        j += 1
                    insertions.append((ins_start, j - ins_start))
                    ins_count += j - ins_start
                elif edited_aligned[j] == '-':
                    del_start = i
                    while j < len(edited_aligned) and edited_aligned[j] == '-':
                        i += 1
                        j += 1
                    deletions.append((del_start, i - del_start))
                    del_count += i - del_start
                else:
                    i += 1
                    j += 1

            # Categorize mutation
            mutation_type = "no_mutation"
            if del_count > 0 and ins_count > 0:
                mutation_type = "indel"
            elif del_count > 0:
                mutation_type = "short_deletion" if del_count <= 10 else "medium_deletion" if del_count <= 30 else "long_deletion"
            elif ins_count > 0:
                mutation_type = "single_insertion" if ins_count == 1 else "longer_insertion"

            site_results.append({
                "sequence_id": seq_id,
                "read_id": read_id,
                "cell_line": cell_line,
                "mutation_type": mutation_type,
                "deletion_count": del_count,
                "insertion_count": ins_count
            })
            site_mutation_counts[mutation_type] += 1
            mutation_counts[cell_line][mutation_type] += 1

        log += f"### {seq_id} ({cell_line}) mutation distribution:\n"
        for mut_type, count in site_mutation_counts.items():
            log += f"- {categories[mut_type]}: {count}/{total_reads}\n"
        results.extend(site_results)

    # Save results
    results_df = pd.DataFrame(results)
    results_file = f"{output_prefix}_detailed_results.csv"
    results_df.to_csv(results_file, index=False)
    log += f"Detailed results saved: {results_file}\n"

    return log

cas9_mutation_tool = StructuredTool.from_function(
    func=cas9_mutation_analysis_coroutine,
    name=Tools.CAS9_MUTATION_ANALYSIS,
    description="""
    【领域：生物】Analyzes Cas9-induced mutations across multiple target sites with detailed logging""",
    args_schema=Cas9MutationAnalysisInput,
    metadata={"args_schema_json": Cas9MutationAnalysisInput.schema()}
)



#测试成功
class CrisprGenomeEditingInput(BaseModel):
    original_sequence: str = Field(..., description="Original DNA sequence")
    edited_sequence: str = Field(..., description="Edited DNA sequence after CRISPR-Cas9")
    guide_rna: str = Field(..., description="Guide RNA sequence")
    repair_template: Optional[str] = Field(None, description="Optional HDR repair template")

def crispr_genome_editing_coroutine(
    original_sequence: str,
    edited_sequence: str,
    guide_rna: str,
    repair_template: Optional[str] = None
) -> str:

    log = [f"CRISPR-Cas9 Genome Editing Analysis - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]
    target_site = original_sequence.find(guide_rna)
    if target_site == -1:
        rev_comp = str(Seq(guide_rna).reverse_complement())
        target_site = original_sequence.find(rev_comp)
        guide_rna = rev_comp if target_site != -1 else guide_rna

    alignments = pairwise2.align.globalms(original_sequence, edited_sequence, 2, -1, -2, -0.5)
    aligned_orig, aligned_edit = alignments[0][0], alignments[0][1]

    mutations, indels = [], []
    for i in range(len(aligned_orig)):
        if aligned_orig[i] != aligned_edit[i]:
            pos = len(aligned_orig[:i].replace('-', ''))
            if aligned_orig[i] == '-':
                indels.append(f"Insertion {aligned_edit[i]} at {pos}")
            elif aligned_edit[i] == '-':
                indels.append(f"Deletion {aligned_orig[i]} at {pos}")
            else:
                mutations.append(f"{aligned_orig[i]}→{aligned_edit[i]} at {pos}")

    log.append(f"Substitutions: {mutations if mutations else 'None'}")
    log.append(f"Indels: {indels if indels else 'None'}")

    if repair_template:
        marker = repair_template[len(repair_template)//2-2:len(repair_template)//2+2]
        if marker in edited_sequence and marker not in original_sequence:
            log.append("HDR template incorporation detected")
        else:
            log.append("No HDR template detected")

    return "\n".join(log)

crispr_editing_tool = StructuredTool.from_function(
    func=crispr_genome_editing_coroutine,
    name=Tools.CRISPR_GENOME_EDITING,
    description="""
    【领域：生物】Analyzes CRISPR-Cas9 genome editing outcomes, including substitutions, indels, and HDR""",
    args_schema=CrisprGenomeEditingInput,
    metadata={"args_schema_json": CrisprGenomeEditingInput.schema()}
)




#测试成功
class TFBindingSiteInput(BaseModel):
    sequence: str = Field(..., description="Genomic DNA sequence to analyze")
    tf_name: str = Field(..., description="Transcription factor name (e.g., Hsf1, GATA1)")
    threshold: float = Field(0.8, description="Minimum score threshold for reporting binding sites (0.0-1.0)")

def identify_transcription_factor_binding_sites_sync(
    sequence: str,
    tf_name: str,
    threshold: float = 0.8
) -> str:
    log = f"# Transcription Factor Binding Site Analysis: {tf_name}\n"
    log += f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    log += "## Step 1: Retrieving transcription factor PWM\n"
    try:
        # 使用 requests 替代 aiohttp
        jaspar_url = f"https://jaspar.genereg.net/api/v1/matrix/?name={tf_name}"
        response = requests.get(jaspar_url)
        tf_data = response.json()
        
        if not tf_data['results']:
            log += f"No PWM found for {tf_name} in JASPAR database.\n"
            return log

        matrix_id = tf_data['results'][0]['matrix_id']
        log += f"Found PWM with ID: {matrix_id}\n"

        pwm_url = f"https://jaspar.genereg.net/api/v1/matrix/{matrix_id}.pfm"
        pwm_response = requests.get(pwm_url)
        pwm_text = pwm_response.text
        
        handle = io.StringIO(pwm_text)
        motif = motifs.read(handle, "jaspar")
        log += f"Successfully retrieved PWM for {tf_name}\n"

        pssm = motif.pssm

        log += "\n## Step 2: Scanning sequence for binding sites\n"
        log += f"Sequence length: {len(sequence)} bp, Score threshold: {threshold}\n\n"

        binding_sites = []
        max_score = pssm.max
        min_score = pssm.min

        for position, score in pssm.search(Seq(sequence), threshold=threshold):
            relative_score = (score - min_score) / (max_score - min_score)
            if position >= 0:
                strand = "+"
                site_seq = sequence[position:position+len(pssm)]
            else:
                strand = "-"
                site_seq = sequence[len(sequence)+position-len(pssm):len(sequence)+position]
            binding_sites.append({
                "position": abs(position),
                "strand": strand,
                "score": score,
                "relative_score": relative_score,
                "sequence": site_seq
            })

        log += f"## Step 3: Results - Found {len(binding_sites)} potential binding sites\n\n"
        if binding_sites:
            binding_sites.sort(key=lambda x: x["position"])
            log += "| Position | Strand | Sequence | Score | Relative Score |\n"
            log += "|----------|--------|----------|-------|---------------|\n"
            for site in binding_sites:
                log += f"| {site['position']} | {site['strand']} | {site['sequence']} | {site['score']:.2f} | {site['relative_score']:.2f} |\n"
        else:
            log += "No binding sites found meeting the threshold criteria.\n"

        # 生成文件内容并使用同步版本上传到 MinIO
        output_content = "Position\tStrand\tSequence\tScore\tRelative Score\n"
        for site in binding_sites:
            output_content += f"{site['position']}\t{site['strand']}\t{site['sequence']}\t{site['score']:.2f}\t{site['relative_score']:.2f}\n"

        file_name = f"{tf_name}_{datetime.now().strftime('%Y%m%d%H%M%S')}.tsv"
        # 直接调用同步函数
        file_url = upload_content_to_minio_sync(
            content=output_content,
            file_name=file_name,
            file_extension=".tsv",
            content_type="text/tab-separated-values"
        )
        log += f"\nResults uploaded to: {file_url}\n"

    except Exception as e:
        log += f"\n## Error occurred during analysis: {str(e)}\n"

    log += "\n## Analysis complete\n"
    return log

tf_binding_tool = StructuredTool.from_function(
    func=identify_transcription_factor_binding_sites_sync,
    name=Tools.TF_BINDING_SITE,
    description="""
    【领域：生物】Identifies transcription factor binding sites in a genomic sequence using JASPAR PWMs""",
    args_schema=TFBindingSiteInput,
    metadata={"args_schema_json": TFBindingSiteInput.schema()}
)





#测试成功
class PCRGelInput(BaseModel):
    genomic_dna_url: str = Field(..., description="URL to FASTA file or raw genomic DNA sequence string")
    forward_primer: Optional[str] = Field(None, description="Forward primer sequence (optional)")
    reverse_primer: Optional[str] = Field(None, description="Reverse primer sequence (optional)")
    target_region: Optional[Tuple[int,int]] = Field(None, description="Target region (start, end) for primer design")
    annealing_temp: float = Field(58, description="Annealing temperature in °C")
    extension_time: int = Field(30, description="Extension time in seconds")
    cycles: int = Field(35, description="Number of PCR cycles")
    gel_percentage: float = Field(2.0, description="Agarose gel concentration (%)")

def perform_pcr_and_gel_upload(
    genomic_dna_url: str,
    forward_primer: Optional[str] = None,
    reverse_primer: Optional[str] = None,
    target_region: Optional[Tuple[int,int]] = None,
    annealing_temp: float = 58,
    extension_time: int = 30,
    cycles: int = 35,
    gel_percentage: float = 2.0,
) -> Dict[str, Any]:

    log = f"PCR & GEL ELECTROPHORESIS LOG - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    log += "="*80 + "\n\n"

    # Step 1: Load genomic DNA
    try:
        if genomic_dna_url.startswith("http"):
            response = requests.get(genomic_dna_url)
            response.raise_for_status()
            fasta_io = StringIO(response.text)
            record = SeqIO.read(fasta_io, "fasta")
            dna_sequence = str(record.seq)
            log += f"- Loaded DNA from URL: {genomic_dna_url}\n- Length: {len(dna_sequence)} bp\n"
        else:
            if os.path.isfile(genomic_dna_url):
                record = SeqIO.read(genomic_dna_url, "fasta")
                dna_sequence = str(record.seq)
                log += f"- Loaded DNA from local file: {genomic_dna_url}\n- Length: {len(dna_sequence)} bp\n"
            else:
                dna_sequence = genomic_dna_url
                log += f"- Using provided DNA sequence string\n- Length: {len(dna_sequence)} bp\n"
    except Exception as e:
        return {"error": f"Failed to load DNA: {str(e)}"}

    # Step 2: Primer design
    if forward_primer is None or reverse_primer is None:
        if target_region is None:
            return {"error": "Either primers or target_region must be provided"}
        start, end = target_region
        if forward_primer is None:
            forward_primer = dna_sequence[start:start+20]
            log += "- Forward primer designed from target region\n"
        if reverse_primer is None:
            reverse_primer = str(Seq(dna_sequence[end-20:end]).reverse_complement())
            log += "- Reverse primer designed from target region\n"
    log += f"- Forward primer: 5'-{forward_primer}-3'\n"
    log += f"- Reverse primer: 5'-{reverse_primer}-3'\n"

    # Step 3: PCR Simulation
    fwd_pos = dna_sequence.find(forward_primer)
    rev_pos = dna_sequence.find(str(Seq(reverse_primer).reverse_complement()))
    amplicon_size, amplicon_sequence = None, None
    if fwd_pos != -1 and rev_pos != -1 and fwd_pos < rev_pos:
        amplicon_size = rev_pos + len(reverse_primer) - fwd_pos
        amplicon_sequence = dna_sequence[fwd_pos:rev_pos+len(reverse_primer)]
        log += f"- Amplicon detected: {amplicon_size} bp\n"
    elif target_region:
        start, end = target_region
        amplicon_size = end - start + len(forward_primer) + len(reverse_primer)
        log += f"- Simulated amplicon based on target region: {amplicon_size} bp\n"
    else:
        return {"error": "PCR failed: cannot determine amplicon"}

    # Step 4: Gel electrophoresis simulation
    fig, ax = plt.subplots(figsize=(6,8))
    ax.add_patch(plt.Rectangle((0,0),6,10,color='lightgray',alpha=0.5))
    ladder_sizes = [100,200,300,500,700,1000,1500,2000]
    ladder_positions = [10-(np.log(size)/np.log(2000)*8) for size in ladder_sizes]
    for pos, size in zip(ladder_positions, ladder_sizes):
        ax.add_patch(plt.Rectangle((0.5,pos-0.1),1,0.2,color='black'))
        ax.text(0.2,pos,f"{size}bp",fontsize=8,ha='right',va='center')
    if amplicon_size:
        sample_pos = 10-(np.log(amplicon_size)/np.log(2000)*8)
        ax.add_patch(plt.Rectangle((3.5,sample_pos-0.15),1,0.3,color='black'))
        ax.text(4.5,sample_pos,f"{amplicon_size}bp",fontsize=8,ha='left',va='center')
    ax.set_xlim(0,6); ax.set_ylim(0,10)
    ax.set_xticks([0.5,3.5]); ax.set_xticklabels(['Ladder','Sample']); ax.set_yticks([])
    ax.set_title(f"{gel_percentage}% Agarose Gel")
    
    # 保存到 BytesIO 并上传
    gel_bytes = io.BytesIO()
    plt.savefig(gel_bytes, format='png', dpi=300, bbox_inches='tight')
    plt.close()
    gel_bytes.seek(0)
    gel_url = upload_content_to_minio_sync(gel_bytes.read(), file_extension=".png", content_type="image/png")

    # 上传 amplicon FASTA
    amplicon_url = None
    if amplicon_sequence:
        fasta_content = f">PCR_Amplicon_{amplicon_size}bp\n{amplicon_sequence}"
        amplicon_url = upload_content_to_minio_sync(fasta_content, file_extension=".fasta", content_type="text/plain")

    # 上传 log
    log_url = upload_content_to_minio_sync(log, file_extension=".txt", content_type="text/plain")

    return {"log_url": log_url, "gel_url": gel_url, "amplicon_url": amplicon_url}

pcr_gel_tool = StructuredTool.from_function(
    func=perform_pcr_and_gel_upload,
    name=Tools.PCR_GEL_TOOL,
    description="""
    【领域：生物】Simulates PCR amplification of target DNA and visualizes results via agarose gel. Returns log, gel image, and amplicon fasta file.""",
    args_schema=PCRGelInput,
    metadata={"args_schema_json": PCRGelInput.schema()}
)


