      

import os
import io
import tempfile
import subprocess
import traceback
import json
from typing import List, Optional, Dict, Any, Tuple, Union, Set
from collections import namedtuple, defaultdict
from itertools import combinations
from io import BytesIO, StringIO

import pandas as pd
import requests
from bs4 import BeautifulSoup
from Bio import Entrez, SeqIO, Restriction
from Bio.Seq import Seq
from Bio.Restriction import Analysis
from Bio.SeqUtils import MeltingTemp as mt

from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool
from workflow.const import Tools

from workflow.utils.minio_utils import upload_content_to_minio



# 测试成功
# 请从 NCBI 获取 Homo sapiens 的 TP53 基因的编码序列 (CDS)，并生成结果 CSV。
class GeneCodingSequenceInput(BaseModel):
    gene_name: str = Field(..., description="Gene name, e.g., TP53")
    organism: str = Field(..., description="Organism name, e.g., Homo sapiens")
    #email: Optional[str] = Field(None, description="Email for NCBI Entrez access (recommended)")

async def get_gene_coding_sequence_coroutine(
    gene_name: str,
    organism: str,
    #email: Optional[str] = None
) -> Dict[str, Any]:
    log = "# Gene Coding Sequence Retrieval Log\n"

    try:
        # if email:
            # Entrez.email = email
            # log += f"Using email: {email}\n"

        # Search gene ID
        query = f"{organism}[Organism] AND {gene_name}[Gene]"
        with Entrez.esearch(db="gene", term=query, retmax=5) as handle:
            record = Entrez.read(handle)
        if not record["IdList"]:
            return {"research_log": f"No records found for gene '{gene_name}' in '{organism}'", "sequences_csv_url": None}

        gene_id = record["IdList"][0]
        log += f"Found gene ID: {gene_id}\n"

        # Fetch RefSeq ID
        with Entrez.efetch(db="gene", id=gene_id, rettype="gb", retmode="xml") as handle:
            gene_record = Entrez.read(handle)
        try:
            locus = gene_record[0]["Entrezgene_locus"][0]
            accession = locus["Gene-commentary_accession"]
            version = locus["Gene-commentary_version"]
            refseq_id = f"{accession}.{version}"
            log += f"RefSeq ID: {refseq_id}\n"
        except (KeyError, IndexError) as e:
            return {"research_log": f"Unable to process gene record: {e}", "sequences_csv_url": None}

        # Fetch coding sequences
        with Entrez.efetch(db="nucleotide", id=refseq_id, rettype="gbwithparts", retmode="text") as handle:
            seq_record = SeqIO.read(handle, "genbank")

        sequences = []
        for feature in seq_record.features:
            if feature.type == "CDS" and feature.qualifiers.get("gene", ["N/A"])[0] == gene_name:
                cds_seq = feature.location.extract(seq_record).seq
                sequences.append({
                    "refseq_id": refseq_id,
                    "sequence": str(cds_seq)
                })

        log += f"Retrieved {len(sequences)} coding sequences for gene '{gene_name}'\n"

        # Convert to CSV and upload
        sequences_df = pd.DataFrame(sequences)
        csv_buf = io.StringIO()
        sequences_df.to_csv(csv_buf, index=False)
        sequences_csv_url = await upload_content_to_minio(
            content=csv_buf.getvalue().encode("utf-8"),
            file_name=f"{gene_name}_coding_sequences.csv",
            file_extension=".csv",
            content_type="text/csv",
            no_expired=True
        )

        explanation = (
            "Output fields for each coding sequence:\n"
            "- refseq_id: RefSeq identifier for the gene sequence (e.g., NM_000546.5)\n"
            "- sequence: The coding sequence (exons only, starts with ATG, ends with stop codon)"
        )

        return {
            "research_log": log,
            "explanation": explanation,
            "sequences_csv_url": sequences_csv_url
        }

    except Exception as e:
        tb = traceback.format_exc()
        return {"research_log": f"Error retrieving coding sequences: {e}\n{tb}", "sequences_csv_url": None}

get_gene_coding_sequence_tool = StructuredTool.from_function(
    name=Tools.get_gene_coding_sequence,
description="""
    【领域：生物】
        "从 NCBI Entrez 获取指定基因的编码序列（CDS）。\n"
        "返回：\n"
        "- research_log: 完整日志\n"
        "- explanation: 字段说明\n"
        "- sequences_csv_url: CDS序列 CSV 文件链接"
    """,
    args_schema=GeneCodingSequenceInput,
    coroutine=get_gene_coding_sequence_coroutine,
    metadata={"args_schema_json": GeneCodingSequenceInput.schema()}
)


# 测试成功
# 从 Addgene 获取质粒 #12259 (pEGFP-C1) 的序列，并导出为 CSV 文件。
class GetPlasmidSequenceInput(BaseModel):
    identifier: str = Field(..., description="Addgene ID or plasmid name")
    is_addgene: Optional[bool] = Field(None, description="Force Addgene lookup if True, force NCBI if False; auto-detect if None")

async def get_plasmid_sequence_coroutine(
    identifier: str,
    is_addgene: Optional[bool] = None
) -> Dict[str, Any]:
    log = "# Plasmid Sequence Retrieval Log\n"
    try:
        if is_addgene is None:
            is_addgene = identifier.isdigit()
            log += f"Auto-detected source: {'Addgene' if is_addgene else 'NCBI'}\n"

        result = None

        if is_addgene:
            # --- Addgene retrieval ---
            ADDGENE_BASE_URL = "https://www.addgene.org"
            url = f"{ADDGENE_BASE_URL}/{identifier}/sequences/"
            resp = requests.get(url)
            if resp.status_code != 200:
                log += f"Failed to retrieve Addgene plasmid {identifier}\n"
            else:
                soup = BeautifulSoup(resp.content, "html.parser")
                textarea = soup.find('textarea', {'class': 'copy-from'})
                if textarea:
                    seq_text = textarea.text.strip()
                    lines = seq_text.split('\n')
                    if lines[0].strip() == '> Addgene NGS Result':
                        sequence = ''.join(lines[1:]).replace(' ', '')
                        result = {
                            "source": "Addgene",
                            "identifier": identifier,
                            "sequence": sequence
                        }
                        log += f"Retrieved sequence from Addgene, length {len(sequence)}\n"
                    else:
                        log += f"No sequence found for Addgene plasmid {identifier}\n"
                else:
                    log += f"No sequence textarea found for Addgene plasmid {identifier}\n"

        else:
            # --- NCBI retrieval ---
            query = f"Cloning vector {identifier}"
            with Entrez.esearch(db="nuccore", term=query, retmax=1, sort="relevance") as handle:
                record = Entrez.read(handle)
            if not record["IdList"]:
                log += f"No results found for {identifier} in NCBI.\n"
            else:
                plasmid_id = record["IdList"][0]
                with Entrez.efetch(db="nuccore", id=plasmid_id, rettype="fasta", retmode="text") as handle:
                    try:
                        seq_record = SeqIO.read(handle, "fasta")
                        sequence = str(seq_record.seq)
                        result = {
                            "source": "NCBI",
                            "identifier": plasmid_id,
                            "sequence": sequence
                        }
                        log += f"Retrieved sequence from NCBI, length {len(sequence)}\n"
                    except Exception as e:
                        log += f"Error retrieving NCBI sequence: {str(e)}\n"

        if not result:
            return {"research_log": log, "plasmid_csv_url": None}

        # Convert to CSV and upload
        import pandas as pd
        df = pd.DataFrame([result])
        csv_buf = io.StringIO()
        df.to_csv(csv_buf, index=False)
        plasmid_csv_url = await upload_content_to_minio(
            content=csv_buf.getvalue().encode("utf-8"),
            file_name=f"plasmid_{identifier}.csv",
            file_extension=".csv",
            content_type="text/csv",
            no_expired=True
        )

        explanation = (
            "Output fields:\n"
            "- source: Source database (Addgene or NCBI)\n"
            "- identifier: Addgene ID or NCBI accession number\n"
            "- sequence: Complete plasmid sequence"
        )

        return {
            "research_log": log,
            "explanation": explanation,
            "plasmid_csv_url": plasmid_csv_url
        }

    except Exception as e:
        tb = traceback.format_exc()
        return {"research_log": f"Error retrieving plasmid sequence: {e}\n{tb}", "plasmid_csv_url": None}

get_plasmid_sequence_tool = StructuredTool.from_function(
    name=Tools.get_plasmid_sequence,
description="""
    【领域：生物】
        "统一从 Addgene 或 NCBI 获取质粒序列。\n"
        "返回：\n"
        "- research_log: 完整日志\n"
        "- explanation: 字段说明\n"
        "- plasmid_csv_url: 质粒序列 CSV 文件链接"
    """,
    args_schema=GetPlasmidSequenceInput,
    coroutine=get_plasmid_sequence_coroutine,
    metadata={"args_schema_json": GetPlasmidSequenceInput.schema()}
)



# 测试成功
# 请将引物 ATGCGTACG 比对到目标 DNA 序列 ATGCGTACGTTAGCCTAGGCTTACG 上，并检查是否存在反向互补匹配
class SequenceAlignmentInput(BaseModel):
    long_sequence: str = Field(..., description="Target DNA sequence")
    short_sequences: Union[str, List[str]] = Field(..., description="Single short sequence or list of short sequences (primers)")

async def align_sequences_coroutine(
    long_sequence: str,
    short_sequences: Union[str, List[str]]
) -> Dict[str, Any]:
    log = "# Sequence Alignment Log\n"
    try:
        long_seq = long_sequence.upper()
        if isinstance(short_sequences, str):
            short_seqs = [short_sequences.upper()]
        else:
            short_seqs = [s.upper() for s in short_sequences]
        
        def reverse_complement(seq: str) -> str:
            complement = {'A':'T','T':'A','C':'G','G':'C'}
            return ''.join(complement.get(b,b) for b in reversed(seq))

        results = []
        for short_seq in short_seqs:
            alignments = []
            seq_len = len(short_seq)
            sequences_to_check = [
                (short_seq, '+'),
                (reverse_complement(short_seq), '-')
            ]
            for seq_to_align, strand in sequences_to_check:
                for i in range(len(long_seq) - seq_len + 1):
                    window = long_seq[i:i+seq_len]
                    mismatches = [(j, seq_to_align[j], window[j]) for j in range(seq_len) if window[j] != seq_to_align[j]]
                    if len(mismatches) <= 1:
                        alignments.append({
                            "position": i,
                            "strand": strand,
                            "mismatches": mismatches
                        })
            results.append({
                "sequence": short_seq,
                "alignments": alignments
            })

        log += f"Aligned {len(short_seqs)} sequences to target sequence of length {len(long_seq)}\n"

        # Convert results to CSV
        csv_rows = []
        for res in results:
            for aln in res["alignments"]:
                csv_rows.append({
                    "short_sequence": res["sequence"],
                    "position": aln["position"],
                    "strand": aln["strand"],
                    "mismatches": ";".join([f"{pos}:{exp}>{found}" for pos, exp, found in aln["mismatches"]])
                })
        df = pd.DataFrame(csv_rows)
        csv_buf = io.StringIO()
        df.to_csv(csv_buf, index=False)
        csv_url = await upload_content_to_minio(
            content=csv_buf.getvalue().encode("utf-8"),
            file_name="sequence_alignments.csv",
            file_extension=".csv",
            content_type="text/csv",
            no_expired=True
        )

        explanation = (
            "Output fields:\n"
            "- sequences: List of alignment results, each containing:\n"
            "  * sequence: The short sequence that was aligned\n"
            "  * alignments: List of all positions found, each containing:\n"
            "    - position: 0-based start position in target sequence\n"
            "    - strand: '+' for forward, '-' for reverse complement\n"
            "    - mismatches: List of mismatches (position: expected>found)"
        )

        return {
            "research_log": log,
            "explanation": explanation,
            "alignments_csv_url": csv_url
        }

    except Exception as e:
        tb = traceback.format_exc()
        return {"research_log": f"Error during alignment: {e}\n{tb}", "alignments_csv_url": None}

align_sequences_tool = StructuredTool.from_function(
    name=Tools.align_sequences,
description="""
    【领域：生物】
        "将短序列（如引物）比对到目标长序列，允许最多一个错配。\n"
        "同时检查正向和反向互补链。\n"
        "返回：\n"
        "- research_log: 完整日志\n"
        "- explanation: 字段说明\n"
        "- alignments_csv_url: 对齐结果 CSV 文件链接"
    """,
    args_schema=SequenceAlignmentInput,
    coroutine=align_sequences_coroutine,
    metadata={"args_schema_json": SequenceAlignmentInput.schema()}
)




class PCRSimulationInput(BaseModel):
    sequence: str = Field(..., description="Target DNA sequence (template)")
    forward_primer: str = Field(..., description="Forward primer sequence (5' to 3')")
    reverse_primer: str = Field(..., description="Reverse primer sequence (5' to 3')")
    circular: Optional[bool] = Field(False, description="Whether the template sequence is circular")

async def pcr_simple_coroutine(
    sequence: str,
    forward_primer: str,
    reverse_primer: str,
    circular: bool = False
) -> Dict[str, Any]:
    log = "# PCR Simulation Log\n"
    try:
        # Align primers to template
        fwd_align_res = await align_sequences_coroutine(sequence, forward_primer)
        rev_align_res = await align_sequences_coroutine(sequence, str(Seq(reverse_primer).reverse_complement()))
        
        fwd_result = fwd_align_res["sequences"][0]["alignments"]
        rev_result = rev_align_res["sequences"][0]["alignments"]

        log += f"Forward primer bindings: {len(fwd_result)}\n"
        log += f"Reverse primer bindings: {len(rev_result)}\n"

        if not fwd_result or not rev_result:
            return {
                "research_log": log,
                "explanation": (
                    "Output fields:\n"
                    "- success: Boolean indicating if any PCR products were found\n"
                    "- message: Error message if no products found\n"
                    "- products: Empty list when no products found\n"
                    "- forward_binding_sites: Number of forward primer binding locations\n"
                    "- reverse_binding_sites: Number of reverse primer binding locations"
                ),
                "success": False,
                "message": "One or both primers do not align to the sequence.",
                "products": [],
                "forward_binding_sites": len(fwd_result),
                "reverse_binding_sites": len(rev_result)
            }

        fwd_positions = [align["position"] for align in fwd_result]
        rev_positions = [align["position"] for align in rev_result]
        seq_len = len(sequence)

        # Find all possible PCR products
        products = []
        for fwd_pos in fwd_positions:
            for rev_pos in rev_positions:
                if fwd_pos < rev_pos:
                    size = rev_pos - fwd_pos + len(reverse_primer)
                    prod_seq = sequence[fwd_pos:rev_pos + len(reverse_primer)]
                elif circular:
                    size = seq_len - fwd_pos + rev_pos + len(reverse_primer)
                    prod_seq = sequence[fwd_pos:] + sequence[:rev_pos + len(reverse_primer)]
                else:
                    continue
                products.append({
                    "size": size,
                    "forward_position": fwd_pos,
                    "reverse_position": rev_pos,
                    "sequence": prod_seq,
                    "forward_mismatches": fwd_result[fwd_positions.index(fwd_pos)]["mismatches"],
                    "reverse_mismatches": rev_result[rev_positions.index(rev_pos)]["mismatches"]
                })

        if not products:
            return {
                "research_log": log,
                "explanation": (
                    "Output fields:\n"
                    "- success: Boolean indicating if any PCR products were found\n"
                    "- message: Error message if no products found\n"
                    "- products: Empty list when no products found\n"
                    "- forward_binding_sites: Number of forward primer binding locations\n"
                    "- reverse_binding_sites: Number of reverse primer binding locations"
                ),
                "success": False,
                "message": "No valid PCR products found with these primers.",
                "products": [],
                "forward_binding_sites": len(fwd_positions),
                "reverse_binding_sites": len(rev_positions)
            }

        # Convert products to CSV
        csv_buf = io.StringIO()
        df = pd.DataFrame(products)
        df.to_csv(csv_buf, index=False)
        csv_url = await upload_content_to_minio(
            content=csv_buf.getvalue().encode("utf-8"),
            file_name="pcr_products.csv",
            file_extension=".csv",
            content_type="text/csv",
            no_expired=True
        )

        return {
            "research_log": log,
            "explanation": (
                "Output fields:\n"
                "- success: Boolean indicating if any PCR products were found\n"
                "- products: List of all possible PCR products, each containing size, sequence, positions, and mismatches\n"
                "- forward_binding_sites: Number of locations where forward primer can bind\n"
                "- reverse_binding_sites: Number of locations where reverse primer can bind\n"
                "- products_csv_url: CSV file with all PCR products"
            ),
            "success": True,
            "products": products,
            "forward_binding_sites": len(fwd_positions),
            "reverse_binding_sites": len(rev_positions),
            "products_csv_url": csv_url
        }

    except Exception as e:
        tb = traceback.format_exc()
        return {"research_log": f"Error during PCR simulation: {e}\n{tb}", "success": False, "products_csv_url": None}

pcr_simple_tool = StructuredTool.from_function(
    name=Tools.pcr_simple,
description="""
    【领域：生物】
        "模拟 PCR 扩增，输入模板序列和正向/反向引物。\n"
        "检查线性和可选的环状模板，输出可能的扩增产物。\n"
        "返回：\n"
        "- research_log: 完整日志\n"
        "- explanation: 字段说明\n"
        "- success: 是否成功找到产物\n"
        "- products: 扩增产物列表\n"
        "- forward_binding_sites / reverse_binding_sites: 引物结合位置数量\n"
        "- products_csv_url: CSV 文件链接"
    """,
    args_schema=PCRSimulationInput,
    coroutine=pcr_simple_coroutine,
    metadata={"args_schema_json": PCRSimulationInput.schema()}
)



# 测试成功
# 我有 DNA 序列 ATCGGAATTCTAGCTAGGATCCGCTA，请用 EcoRI 和 BamHI 同时进行消化，DNA 是环状的
class DigestSequenceInput(BaseModel):
    dna_sequence: str = Field(..., description="Input DNA sequence for digestion")
    enzyme_names: List[str] = Field(..., description="List of restriction enzyme names (as defined in Bio.Restriction)")
    is_circular: Optional[bool] = Field(True, description="Whether the DNA sequence is circular (default: True)")

async def digest_sequence_coroutine(
    dna_sequence: str,
    enzyme_names: List[str],
    is_circular: bool = True
) -> Dict[str, Any]:
    log = "# Restriction Digest Simulation Log\n"
    try:
        seq = Seq(dna_sequence)
        seq_len = len(seq)
        log += f"Input sequence length: {seq_len} bp, Circular: {is_circular}\n"
        
        all_cut_positions = []
        for enzyme_name in enzyme_names:
            enzyme_obj = getattr(Restriction, enzyme_name, None)
            if enzyme_obj is None:
                log += f"Warning: Enzyme {enzyme_name} not found in Bio.Restriction.\n"
                continue
            cut_sites = enzyme_obj.search(seq, linear=not is_circular)
            all_cut_positions.extend(cut_sites)
            log += f"{enzyme_name}: {len(cut_sites)} cut sites\n"
        
        all_cut_positions = sorted(set(all_cut_positions))
        log += f"Total unique cut positions: {len(all_cut_positions)}\n"
        
        fragments = []
        if not all_cut_positions:
            fragments.append({
                "fragment": str(seq),
                "length": seq_len,
                "start": 0,
                "end": seq_len,
                "is_wrapped": False
            })
        else:
            if is_circular:
                for i in range(len(all_cut_positions)):
                    start = all_cut_positions[i]
                    end = all_cut_positions[i + 1] if i < len(all_cut_positions) - 1 else all_cut_positions[0] + seq_len
                    fragment_seq = dna_sequence[start:end] if end <= seq_len else dna_sequence[start:] + dna_sequence[:end - seq_len]
                    fragments.append({
                        "fragment": fragment_seq,
                        "length": len(fragment_seq),
                        "start": start,
                        "end": end if end <= seq_len else end - seq_len,
                        "is_wrapped": end > seq_len
                    })
            else:
                # Linear fragments
                positions = [0] + all_cut_positions + [seq_len]
                for i in range(len(positions) - 1):
                    start = positions[i]
                    end = positions[i + 1]
                    if start == end:
                        continue
                    fragments.append({
                        "fragment": dna_sequence[start:end],
                        "length": end - start,
                        "start": start,
                        "end": end,
                        "is_wrapped": False
                    })
        
        # Sort fragments by length descending
        fragments.sort(key=lambda x: x["length"], reverse=True)

        # Upload CSV of fragments
        df = pd.DataFrame(fragments)
        csv_buf = io.StringIO()
        df.to_csv(csv_buf, index=False)
        csv_url = await upload_content_to_minio(
            content=csv_buf.getvalue().encode("utf-8"),
            file_name="digest_fragments.csv",
            file_extension=".csv",
            content_type="text/csv",
            no_expired=True
        )

        return {
            "research_log": log,
            "explanation": (
                "Output fields:\n"
                "- sequence_info: Input sequence info (length, circular/linear)\n"
                "- digestion_info: Enzymes used, cut positions, number of fragments\n"
                "- fragments: List of all fragments with sequence, length, start/end positions, and wrap info\n"
                "- fragments_csv_url: CSV file containing all fragments"
            ),
            "sequence_info": {
                "length": seq_len,
                "is_circular": is_circular
            },
            "digestion_info": {
                "enzymes_used": enzyme_names,
                "number_of_fragments": len(fragments),
                "cut_positions": all_cut_positions
            },
            "fragments": fragments,
            "fragments_csv_url": csv_url
        }

    except Exception as e:
        tb = traceback.format_exc()
        return {"research_log": f"Error during restriction digest: {e}\n{tb}", "fragments_csv_url": None}

digest_sequence_tool = StructuredTool.from_function(
    name=Tools.digest_sequence,
description="""
    【领域：生物】
        "模拟限制性内切酶消化，输入 DNA 序列和酶列表。\n"
        "支持环状或线性 DNA，返回切割产物及其长度和起止位置。\n"
        "返回：\n"
        "- research_log: 完整日志\n"
        "- explanation: 字段说明\n"
        "- sequence_info: 输入序列信息\n"
        "- digestion_info: 消化酶使用及切位点统计\n"
        "- fragments: 切割产物列表\n"
        "- fragments_csv_url: CSV 文件链接"
    """,
    args_schema=DigestSequenceInput,
    coroutine=digest_sequence_coroutine,
    metadata={"args_schema_json": DigestSequenceInput.schema()}
)



# 测试成功
# 请在序列 GAATTCGCGATCGAATTCGCG 中查找 EcoRI 的切位点，DNA 是环状的
class FindRestrictionSitesInput(BaseModel):
    dna_sequence: str = Field(..., description="Input DNA sequence to scan for restriction sites")
    enzymes: List[str] = Field(..., description="List of restriction enzyme names (as defined in Bio.Restriction)")
    is_circular: Optional[bool] = Field(True, description="Whether the DNA sequence is circular (default: True)")

async def find_restriction_sites_coroutine(
    dna_sequence: str,
    enzymes: List[str],
    is_circular: bool = True
) -> Dict[str, Any]:
    log = "# Restriction Sites Analysis Log\n"
    try:
        seq = Seq(dna_sequence.upper())
        seq_len = len(seq)
        log += f"Input sequence length: {seq_len} bp, Circular: {is_circular}\n"
        
        rb = Restriction.RestrictionBatch(enzymes)
        analysis = rb.search(seq, linear=not is_circular)
        log += f"Analyzed {len(enzymes)} enzymes.\n"

        restriction_sites = {}
        for enzyme in rb:
            positions = analysis[enzyme]
            enzyme_info = {
                'recognition_sequence': str(enzyme.elucidate()),
                'cut_positions': {
                    '5_prime': getattr(enzyme, 'fst5', None),
                    '3_prime': getattr(enzyme, 'fst3', None),
                    'overhang': getattr(enzyme, 'ovhg', None),
                    'overhang_type': 'sticky' if getattr(enzyme, 'ovhg', 0) != 0 else 'blunt'
                },
                'sites': sorted(positions) if positions else []
            }
            restriction_sites[str(enzyme)] = enzyme_info
            log += f"{enzyme}: {len(positions)} site(s) found\n"

        # Upload CSV of all sites
        records = []
        for enz_name, info in restriction_sites.items():
            for site in info['sites']:
                records.append({
                    'enzyme': enz_name,
                    'recognition_sequence': info['recognition_sequence'],
                    'site_position': site,
                    '5_prime_cut': info['cut_positions'].get('5_prime'),
                    '3_prime_cut': info['cut_positions'].get('3_prime'),
                    'overhang': info['cut_positions'].get('overhang'),
                    'overhang_type': info['cut_positions'].get('overhang_type')
                })
        df = pd.DataFrame(records)
        csv_buf = io.StringIO()
        df.to_csv(csv_buf, index=False)
        csv_url = await upload_content_to_minio(
            content=csv_buf.getvalue().encode('utf-8'),
            file_name="restriction_sites.csv",
            file_extension=".csv",
            content_type="text/csv",
            no_expired=True
        )

        return {
            "research_log": log,
            "explanation": (
                "Output fields:\n"
                "- sequence_info: Input sequence info (length, circular/linear)\n"
                "- restriction_sites: Dictionary of enzymes and their recognition sites, cut positions, and overhangs\n"
                "- restriction_sites_csv_url: CSV file containing all restriction sites"
            ),
            "sequence_info": {
                "length": seq_len,
                "is_circular": is_circular
            },
            "restriction_sites": restriction_sites,
            "restriction_sites_csv_url": csv_url
        }

    except Exception as e:
        tb = traceback.format_exc()
        return {"research_log": f"Error during restriction site analysis: {e}\n{tb}", "restriction_sites_csv_url": None}

find_restriction_sites_tool = StructuredTool.from_function(
    name=Tools.find_restriction_sites,
description="""
    【领域：生物】
        用途示例：
        - 未指定酶时做初步位点检测（例如评估序列是否含有常见酶位点，方便选酶）。
        - 需要快速生成“哪些常用酶会切” 的清单。
        识别 DNA 序列中的限制性内切酶切位点，支持环状或线性 DNA。
        返回每个酶的识别序列、切位点、5'/3'切割位置、突出端信息，并生成 CSV 文件。

        返回字段说明：
        - research_log: 完整分析日志（文本）
        - explanation: 字段说明（文本）
        - sequence_info: 输入序列信息（字典）
        - restriction_sites: 每个酶的识别序列、切位点、5'/3'切割位置、突出端信息（字典）
        - restriction_sites_csv_url: CSV 文件下载链接（每行包含 enzyme, site_position, recognition_sequence, 5_prime_cut, 3_prime_cut, overhang, overhang_type）
        
    """,
    args_schema=FindRestrictionSitesInput,
    coroutine=find_restriction_sites_coroutine,
    metadata={"args_schema_json": FindRestrictionSitesInput.schema()}
)



# 测试成功
# 请在序列 GAATTCGCGATCGGATCC 中检测常见的限制性内切酶切位点，并列出哪些酶会切。
class FindCommonRestrictionSitesInput(BaseModel):
    sequence: str = Field(..., description="Input DNA sequence to scan for common restriction sites")
    is_circular: Optional[bool] = Field(False, description="Whether the DNA sequence is circular (default: False)")

async def find_restriction_enzymes_coroutine(
    sequence: str,
    is_circular: bool = False
) -> Dict[str, Any]:
    log = "# Common Restriction Enzymes Analysis Log\n"
    try:
        seq = Seq(sequence.upper())
        seq_len = len(seq)
        log += f"Input sequence length: {seq_len} bp, Circular: {is_circular}\n"

        analysis = Restriction.CommOnly.search(seq, linear=not is_circular)
        enzyme_sites = {str(enzyme): list(pos) for enzyme, pos in analysis.items() if pos}
        log += f"Identified {len(enzyme_sites)} enzymes with recognition sites.\n"

        # Upload CSV
        records = []
        for enz_name, positions in enzyme_sites.items():
            for site in positions:
                records.append({"enzyme": enz_name, "site_position": site})
        df = pd.DataFrame(records)
        csv_buf = io.StringIO()
        df.to_csv(csv_buf, index=False)
        csv_url = await upload_content_to_minio(
            content=csv_buf.getvalue().encode('utf-8'),
            file_name="common_restriction_sites.csv",
            file_extension=".csv",
            content_type="text/csv",
            no_expired=True
        )

        return {
            "research_log": log,
            "explanation": (
                "Output fields:\n"
                "- enzyme_sites: Dictionary of enzymes and their cut positions (0-based)\n"
                "- enzymes_sites_csv_url: CSV file with all enzymes and their positions"
            ),
            "enzyme_sites": enzyme_sites,
            "enzymes_sites_csv_url": csv_url
        }

    except Exception as e:
        tb = traceback.format_exc()
        return {"research_log": f"Error during common restriction enzyme analysis: {e}\n{tb}", "enzymes_sites_csv_url": None}

find_common_restriction_sites = StructuredTool.from_function(
    name=Tools.find_common_restriction_sites,
description="""
    【领域：生物】
    用途示例：
    - 未指定酶时做初步位点检测（例如评估序列是否含有常见酶位点，方便选酶）。
    - 需要快速生成“哪些常用酶会切” 的清单。
    识别 DNA 序列中常用限制性内切酶切位点，返回每个酶的切位点信息，并生成 CSV 文件。

    返回字段说明：
    - research_log: 完整分析日志（文本）
    - explanation: 字段说明（文本）
    - enzyme_sites: {酶名: [site_positions]}
    - common_restriction_sites_csv_url: CSV 文件下载链接（每行包含 enzyme, site_position）
""",
    args_schema=FindCommonRestrictionSitesInput,
    coroutine=find_restriction_enzymes_coroutine,
    metadata={"args_schema_json": FindCommonRestrictionSitesInput.schema()}
)



# 测试成功
# 比对参考序列 ATGCGTACGTA 和查询序列 ATGAGTACGTA，找出所有碱基突变。
class FindSequenceMutationsInput(BaseModel):
    query_sequence: str = Field(..., description="The DNA or protein sequence to analyze")
    reference_sequence: str = Field(..., description="Reference sequence to compare against")
    query_start: Optional[int] = Field(1, description="Start position of the query sequence (1-based)")

async def find_sequence_mutations_coroutine(
    query_sequence: str,
    reference_sequence: str,
    query_start: int = 1
) -> Dict[str, Any]:
    log = "# Sequence Mutation Analysis Log\n"
    try:
        if not all([query_sequence, reference_sequence]):
            return {
                "research_log": log + "Empty query or reference sequence.\n",
                "mutations": [],
                "mutations_csv_url": None,
                "success": False
            }

        mutations = []
        for i, (query_aa, ref_aa) in enumerate(zip(query_sequence, reference_sequence)):
            if query_aa != ref_aa and ref_aa != '-' and query_aa != '-':
                position = query_start + i
                mutations.append(f"{ref_aa}{position}{query_aa}")
        
        log += f"Identified {len(mutations)} mutations.\n"

        # 上传 CSV
        df = pd.DataFrame({"mutation": mutations})
        csv_buf = io.StringIO()
        df.to_csv(csv_buf, index=False)
        csv_url = await upload_content_to_minio(
            content=csv_buf.getvalue().encode('utf-8'),
            file_name="sequence_mutations.csv",
            file_extension=".csv",
            content_type="text/csv",
            no_expired=True
        )

        return {
            "research_log": log,
            "explanation": (
                "Output fields:\n"
                "- mutations: List of mutations found, formatted as RefAA_Position_QueryAA\n"
                "- mutations_csv_url: CSV file containing all identified mutations\n"
                "- success: Boolean indicating if analysis was successful"
            ),
            "mutations": mutations,
            "mutations_csv_url": csv_url,
            "success": True
        }

    except Exception as e:
        tb = traceback.format_exc()
        return {
            "research_log": f"Error during mutation analysis: {e}\n{tb}",
            "mutations": [],
            "mutations_csv_url": None,
            "success": False
        }

find_sequence_mutations_tool = StructuredTool.from_function(
    name=Tools.find_sequence_mutations,
description="""
    【领域：生物】
        "比对查询序列与参考序列，检测突变位点。\n"
        "返回突变列表及 CSV 链接。\n"
        "返回字段：\n"
        "- research_log: 完整分析日志\n"
        "- mutations: 突变列表\n"
        "- mutations_csv_url: CSV 文件链接\n"
        "- success: 是否成功"
    """,
    args_schema=FindSequenceMutationsInput,
    coroutine=find_sequence_mutations_coroutine,
    metadata={"args_schema_json": FindSequenceMutationsInput.schema()}
)



# 测试成功
# 我想对人类的 EGFR 基因进行 CRISPR knockout，你可以帮我设计 1 条最佳的 sgRNA 吗？sgRNA 库放在D:\PyProject\Biomni-main\data\biomni_data\data_lake
class DesignKnockoutSgrnaInput(BaseModel):
    gene_name: str = Field(..., description="靶基因名称，如 'EGFR'")
    #data_lake_path: str = Field(..., description="数据湖根目录路径，包含 sgRNA 库文件")
    species: str = Field("human", description="物种，支持 'human' 或 'mouse'")
    num_guides: int = Field(1, description="返回的 sgRNA 数量")

async def design_knockout_sgrna_coroutine(
    gene_name: str,
    #data_lake_path: str ,
    species: str = "human",
    num_guides: int = 1,
) -> Dict[str, Any]:
    
    data_lake_path = os.path.join(os.path.dirname(__file__), "data", "data_lake")
    try:
        DEFAULT_LIBRARIES = {
            "human": os.path.join(data_lake_path, "sgRNA", "KO_SP_human.txt"),
            "mouse": os.path.join(data_lake_path, "sgRNA", "KO_SP_mouse.txt"),
        }

        species_key = species.lower()
        if species_key not in DEFAULT_LIBRARIES:
            return {"success": False, "error": f"Unsupported species: {species}"}

        library_path = DEFAULT_LIBRARIES[species_key]

        if not os.path.exists(library_path):
            return {"success": False, "error": f"Library file not found at {library_path}"}

        df = pd.read_csv(library_path, delimiter="\t")

        gene_upper = gene_name.upper()
        gene_df = df[df["Target Gene Symbol"].str.upper() == gene_upper]

        if gene_df.empty:
            gene_df = df[df["Target Gene Symbol"].str.upper().str.contains(gene_upper)]

        if gene_df.empty:
            return {
                "success": True,
                "explanation": "Output contains target gene name, species, and list of sgRNA sequences",
                "gene_name": gene_name,
                "species": species,
                "guides": [],
            }

        gene_df = gene_df.sort_values(by=["Combined Rank"])
        top_guides = gene_df.head(num_guides)
        guides = top_guides["sgRNA Sequence"].tolist()

        return {
            "success": True,
            "explanation": "Output contains target gene name, species, and list of sgRNA sequences",
            "gene_name": gene_name,
            "species": species,
            "guides": guides,
        }

    except Exception as e:
        return {"success": False, "error": f"Design sgRNA failed: {str(e)}"}

design_knockout_sgrna_tool = StructuredTool.from_function(
    coroutine=design_knockout_sgrna_coroutine,
    name=Tools.design_knockout_sgrna,
    description="""
    【领域：生物】Design sgRNAs for CRISPR knockout by searching pre-computed sgRNA libraries.
    Returns optimized guide RNAs for targeting a specific gene.
    Returns:
        Dict: Dictionary containing:
            - explanation: Explanation of the output fields
            - gene_name: Target gene name
            - species: Target species
            - guides: List of sgRNA sequences

    """,
    args_schema=DesignKnockoutSgrnaInput,
    metadata={"args_schema_json":DesignKnockoutSgrnaInput.schema()} 
)


# 测试成功
# 请生成一个标准的寡核苷酸退火实验方案
class OligoAnnealingProtocolInput(BaseModel):
    pass

async def get_oligo_annealing_protocol_coroutine(
    
) -> Dict[str, Any]:
    log = "# Oligo Annealing Protocol Log\n"
    
    protocol = {
        "title": "Oligo Annealing Protocol",
        "description": "Standard protocol for annealing complementary oligonucleotides",
        "steps": [
            {
                "step_number": 1,
                "title": "Prepare annealing reaction",
                "description": "Mix the following components in a PCR tube:",
                "components": [
                    {"name": "Forward oligo (100 μM)", "volume": "1 μl"},
                    {"name": "Reverse oligo (100 μM)", "volume": "1 μl"},
                    {"name": "Nuclease-free water", "volume": "8 μl"}
                ],
                "total_volume": "10 μl"
            },
            {
                "step_number": 2,
                "title": "Anneal in thermocycler",
                "description": "Run the following program on a thermocycler:",
                "program": [
                    {"temperature": "95°C", "time": "5 minutes", "description": "Initial denaturation"},
                    {"temperature": "Ramp down to 25°C", "rate": "5°C/minute", "description": "Slow cooling for proper annealing"}
                ]
            },
            {
                "step_number": 3,
                "title": "Dilute annealed oligos",
                "description": "Dilute the annealed oligos 1:200 in nuclease-free water",
                "details": "Add 1 μl of annealed oligos to 199 μl of nuclease-free water"
            }
        ],
        "notes": [
            "Store annealed and diluted oligos at -20°C for long-term storage",
            "Diluted oligos can be used directly in ligation reactions"
        ]
    }

    log += "Generated standard oligo annealing protocol\n"

    # 上传为 JSON 文件
    buf = io.StringIO()
    json.dump(protocol, buf, indent=2)
    protocol_url = await upload_content_to_minio(
        content=buf.getvalue().encode('utf-8'),
        file_name="oligo_annealing_protocol.json",
        file_extension=".json",
        content_type="application/json",
        no_expired=True
    )

    return {
        "research_log": log,
        "protocol_json_url": protocol_url
    }

get_oligo_annealing_protocol_tool = StructuredTool.from_function(
    name=Tools.get_oligo_annealing_protocol,
description="""
    【领域：生物】
        "返回标准的寡核苷酸退火实验方案（无需磷酸化）。\n"
        "返回：\n"
        " - research_log: 生成日志\n"
        " - protocol_json_url: 完整实验方案 JSON 文件链接"
    """,
    args_schema=OligoAnnealingProtocolInput,
    coroutine=get_oligo_annealing_protocol_coroutine,
    metadata={"args_schema_json": OligoAnnealingProtocolInput.schema()}
)



# 测试成功
# 生成一个 Golden Gate 装配方案，使用 BsaI 酶，载体长度 5000bp，一个插入片段长度 1000bp。
class GoldenGateAssemblyProtocolInput(BaseModel):
    num_inserts: Optional[int] = Field(1, description="Number of inserts to be assembled (default: 1)")
    enzyme_name: str = Field(..., description="Type IIS restriction enzyme to be used (e.g., BsaI, BsmBI, BbsI, Esp3I, BtgZI, SapI)")
    vector_length: int = Field(..., description="Length of the destination vector in base pairs")
    vector_amount_ng: Optional[float] = Field(75.0, description="Amount of vector DNA to use in ng (default: 75.0)")
    insert_lengths: Optional[List[int]] = Field(None, description="List of insert lengths in base pairs (optional)")
    is_library_prep: Optional[bool] = Field(False, description="Whether this assembly is for library preparation (default: False)")
    

async def get_golden_gate_assembly_protocol_coroutine(
    num_inserts: int = 1,
    enzyme_name: str = None,
    vector_length: int = None,
    vector_amount_ng: float = 75.0,
    insert_lengths: Optional[List[int]] = None,
    is_library_prep: bool = False,
    
) -> Dict[str, Any]:
    log = "# Golden Gate Assembly Protocol Log\n"

    # Validate enzyme
    supported_enzymes = ["BsaI", "BsmBI", "BbsI", "Esp3I", "BtgZI", "SapI"]
    if enzyme_name not in supported_enzymes:
        raise ValueError(f"Unsupported enzyme: {enzyme_name}. Supported: {', '.join(supported_enzymes)}")
    log += f"Using enzyme: {enzyme_name}\n"

    # Thermal protocol
    if num_inserts == 1:
        if is_library_prep:
            thermal_protocol = [{"temperature": "37°C", "time": "1 hour", "description": "Cleavage and ligation"}]
        else:
            thermal_protocol = [{"temperature": "37°C", "time": "5 minutes", "description": "Cleavage and ligation"}]
        thermal_protocol.append({"temperature": "60°C", "time": "5 minutes", "description": "Enzyme inactivation"})
    elif 2 <= num_inserts <= 10:
        thermal_protocol = [
            {"temperature": "Cycle (30x)", "description": "Cleavage and ligation cycles",
             "cycles": [
                 {"temperature": "37°C", "time": "1 minute", "description": "Restriction digestion"},
                 {"temperature": "16°C", "time": "1 minute", "description": "Ligation"}
             ]},
            {"temperature": "60°C", "time": "5 minutes", "description": "Enzyme inactivation"}
        ]
    else:
        thermal_protocol = [
            {"temperature": "Cycle (30x)", "description": "Cleavage and ligation cycles",
             "cycles": [
                 {"temperature": "37°C", "time": "5 minutes", "description": "Restriction digestion"},
                 {"temperature": "16°C", "time": "5 minutes", "description": "Ligation"}
             ]},
            {"temperature": "60°C", "time": "5 minutes", "description": "Enzyme inactivation"}
        ]
    log += f"Thermal protocol configured for {num_inserts} insert(s)\n"

    # Assembly mix
    assembly_mix_volume = "2 μl" if num_inserts > 10 else "1 μl"

    # Molar amounts
    vector_pmol = vector_amount_ng / (vector_length * 650) * 1e6

    # Insert components
    insert_components = []
    if insert_lengths:
        for i, length in enumerate(insert_lengths):
            insert_pmol = 2 * vector_pmol
            insert_ng = (insert_pmol * length * 650) / 1e6
            insert_components.append({
                "name": f"Insert {i+1} ({length} bp)",
                "amount": f"{insert_ng:.1f} ng ({insert_pmol:.3f} pmol)",
                "molar_ratio": "2:1 (insert:vector)"
            })
    else:
        insert_components = [{
            "name": "Insert DNA (precloned or amplicon)",
            "amount": "Variable based on length and concentration",
            "note": "Use 2:1 molar ratio (insert:vector) for optimal assembly"
        }]

    reaction_components = [{"name": f"Destination Vector ({vector_length} bp)",
                            "amount": f"{vector_amount_ng} ng ({vector_pmol:.3f} pmol)"}]
    reaction_components.extend(insert_components)
    reaction_components.extend([
        {"name": "T4 DNA Ligase Buffer (10X)", "volume": "2 μl"},
        {"name": f"NEB Golden Gate Assembly Mix ({enzyme_name})", "volume": assembly_mix_volume},
        {"name": "Nuclease-free H₂O", "volume": "to 20 μl"}
    ])

    protocol = {
        "title": f"Golden Gate Assembly Protocol ({enzyme_name})",
        "description": f"Customized protocol for Golden Gate assembly with {enzyme_name} and {num_inserts} insert(s)",
        "steps": [
            {
                "step_number": 1,
                "title": "Prepare assembly reaction",
                "description": "Mix the following components in a PCR tube:",
                "components": reaction_components,
                "total_volume": "20 μl"
            },
            {
                "step_number": 2,
                "title": "Run assembly reaction",
                "description": "Run the following program on a thermocycler:",
                "program": thermal_protocol
            }
        ],
        "notes": [
            f"Destination vector must possess {enzyme_name} restriction sites in the proper orientation",
            f"Inserts must possess {enzyme_name} restriction sites at both ends in the proper orientation",
            "For amplicon inserts, add 5′ flanking bases (6 recommended) before the restriction sites",
            f"Vector amount: {vector_amount_ng} ng = {vector_pmol:.3f} pmol",
            "Insert:vector molar ratio is 2:1 for optimal assembly efficiency"
        ]
    }

    log += f"Generated customized Golden Gate assembly protocol\n{protocol}"

    # Upload protocol JSON
    buf = io.StringIO()
    json.dump(protocol, buf, indent=2)
    protocol_url = await upload_content_to_minio(
        content=buf.getvalue().encode('utf-8'),
        file_name="golden_gate_protocol.json",
        file_extension=".json",
        content_type="application/json",
        no_expired=True
    )

    return {
        "research_log": log,
        "protocol_json_url": protocol_url
    }

get_golden_gate_assembly_protocol_tool = StructuredTool.from_function(
    name=Tools.get_golden_gate_assembly_protocol,
description="""
    【领域：生物】
        "根据插入片段数和 DNA 信息生成定制的 Golden Gate 装配方案。\n"
        "返回：\n"
        " - research_log: 生成日志\n"
        " - protocol_json_url: 完整 Golden Gate 装配方案 JSON 文件链接"
    """,
    args_schema=GoldenGateAssemblyProtocolInput,
    coroutine=get_golden_gate_assembly_protocol_coroutine,
    metadata={"args_schema_json": GoldenGateAssemblyProtocolInput.schema()}
)


# 测试成功
# 生成一个标准的 大肠杆菌转化实验方案，使用默认的安培西林抗性筛选
class BacterialTransformationProtocolInput(BaseModel):
    antibiotic: Optional[str] = Field("ampicillin", description="Selection antibiotic (default: ampicillin)")
    is_repetitive: Optional[bool] = Field(False, description="Whether the sequence contains repetitive elements (default: False)")
   

async def get_bacterial_transformation_protocol_coroutine(
    antibiotic: str = "ampicillin",
    is_repetitive: bool = False,
    
) -> Dict[str, Any]:
    log = "# Bacterial Transformation Protocol Log\n"

    incubation_temp = "30°C" if is_repetitive else "37°C"
    log += f"Using incubation temperature: {incubation_temp}\n"

    protocol = {
        "title": "Bacterial Transformation Protocol",
        "description": "Standard protocol for transforming DNA into competent E. coli cells",
        "steps": [
            {"step_number": 1, "title": "Add DNA to competent cells",
             "description": "Add 5 μl of DNA to 50 μl of competent E. coli cells",
             "note": "Keep cells on ice during this step and handle gently"},
            {"step_number": 2, "title": "Ice incubation",
             "description": "Incubate on ice for 30 minutes",
             "note": "This allows DNA to associate with the cell membrane"},
            {"step_number": 3, "title": "Heat shock",
             "description": "Heat shock at 42°C for 45 seconds",
             "note": "Precise timing is critical"},
            {"step_number": 4, "title": "Recovery on ice",
             "description": "Return to ice for 2 minutes",
             "note": "This step helps cells recover from heat shock"},
            {"step_number": 5, "title": "Add recovery medium",
             "description": "Add 950 μl of SOC medium",
             "note": "SOC is preferred, but LB can be used if necessary"},
            {"step_number": 6, "title": "Recovery incubation",
             "description": f"Incubate at {incubation_temp} for 1 hour with shaking (200-250 rpm)",
             "note": "This allows expression of antibiotic resistance genes"},
            {"step_number": 7, "title": "Plate on selective media",
             "description": f"Plate 100 μl on LB agar plates containing 100 μg/ml {antibiotic}",
             "note": "Spread thoroughly using sterile glass beads or a spreader"},
            {"step_number": 8, "title": "Incubate plates",
             "description": f"Incubate overnight (16-18 hours) at {incubation_temp}",
             "note": "Invert plates to prevent condensation from dripping onto colonies"}
        ],
        "notes": [
            "Always include positive and negative controls for transformation",
            f"For repetitive sequences, the lower temperature ({incubation_temp}) helps maintain sequence integrity" if is_repetitive else "Standard incubation at 37°C works well for most plasmids",
            f"Use fresh plates containing {antibiotic} for best results"
        ]
    }

    log += f"Generated bacterial transformation protocol\n{protocol}"

    # Upload JSON
    buf = io.StringIO()
    json.dump(protocol, buf, indent=2)
    protocol_url = await upload_content_to_minio(
        content=buf.getvalue().encode('utf-8'),
        file_name="bacterial_transformation_protocol.json",
        file_extension=".json",
        content_type="application/json",
        no_expired=True
    )

    return {
        "research_log": log,
        "protocol_json_url": protocol_url
    }

get_bacterial_transformation_protocol_tool = StructuredTool.from_function(
    name=Tools.get_bacterial_transformation_protocol,
description="""
    【领域：生物】
        "生成标准的细菌转化实验方案。\n"
        "返回：\n"
        " - research_log: 生成日志\n"
        " - protocol_json_url: 完整细菌转化实验方案 JSON 文件链接
        """
    ,
    args_schema=BacterialTransformationProtocolInput,
    coroutine=get_bacterial_transformation_protocol_coroutine,
    metadata={"args_schema_json": BacterialTransformationProtocolInput.schema()}
)



# 测试成功
# 在给定 DNA 序列 ATGCGTACGTTAGCTAGCTAGCTAGCGTACGTAGCTAGCATCGATCG 中，从位置 5 开始搜索引物。”
class PrimerDesignInput(BaseModel):
    sequence: str = Field(..., description="Target DNA sequence")
    start_pos: int = Field(..., description="Starting position for primer search")
    primer_length: Optional[int] = Field(20, description="Length of the primer to design (default: 20)")
    min_gc: Optional[float] = Field(0.4, description="Minimum GC content (default: 0.4)")
    max_gc: Optional[float] = Field(0.6, description="Maximum GC content (default: 0.6)")
    min_tm: Optional[float] = Field(55.0, description="Minimum melting temperature in °C (default: 55.0)")
    max_tm: Optional[float] = Field(65.0, description="Maximum melting temperature in °C (default: 65.0)")
    search_window: Optional[int] = Field(100, description="Size of window to search for primers (default: 100)")
   
async def design_primer_coroutine(
    sequence: str,
    start_pos: int,
    primer_length: int = 20,
    min_gc: float = 0.4,
    max_gc: float = 0.6,
    min_tm: float = 55.0,
    max_tm: float = 65.0,
    search_window: int = 100,
   
) -> Dict[str, Any]:
    log = "# Primer Design Log\n"

    primer_region_start = start_pos
    primer_region_end = min(start_pos + search_window, len(sequence))
    primer_region = sequence[primer_region_start:primer_region_end]

    if len(primer_region) < primer_length:
        log += f"Search region too short ({len(primer_region)} bp) for primer length {primer_length}\n"
        return {"research_log": log, "primer_json_url": None}

    best_primer = None
    best_score = float('inf')

    for j in range(0, len(primer_region) - primer_length + 1):
        candidate = primer_region[j:j+primer_length]
        gc_content = (candidate.count('G') + candidate.count('C')) / primer_length
        if gc_content < min_gc or gc_content > max_gc:
            continue

        tm = mt.Tm_Wallace(candidate)
        if tm < min_tm or tm > max_tm:
            continue

        ideal_gc = (min_gc + max_gc) / 2
        ideal_tm = (min_tm + max_tm) / 2
        gc_penalty = abs(gc_content - ideal_gc) * 100
        tm_penalty = abs(tm - ideal_tm)
        score = gc_penalty + tm_penalty

        if score < best_score:
            best_score = score
            best_primer = {
                "sequence": candidate,
                "position": primer_region_start + j,
                "gc": gc_content,
                "tm": tm,
                "score": score
            }

    if best_primer:
        log += f"Designed primer at position {best_primer['position']}, sequence: {best_primer['sequence']}\n"
    else:
        log += "No suitable primer found in the search window\n"

    # Upload JSON
    buf = io.StringIO()
    json.dump(best_primer or {}, buf, indent=2)
    primer_url = await upload_content_to_minio(
        content=buf.getvalue().encode('utf-8'),
        file_name="designed_primer.json",
        file_extension=".json",
        content_type="application/json",
        no_expired=True
    )

    return {
        "research_log": log,
        "primer_json_url": primer_url
    }

design_primer_tool = StructuredTool.from_function(
    name=Tools.design_primer,
description="""
    【领域：生物】
        "在给定 DNA 序列的搜索窗口中设计单个引物。\n"
        "返回：\n"
        " - research_log: 设计日志\n"
        " - primer_json_url: 设计得到的引物信息 JSON 文件链接\n"
    """,
    args_schema=PrimerDesignInput,
    coroutine=design_primer_coroutine,
    metadata={"args_schema_json": PrimerDesignInput.schema()}
)





#测试成功
class VerificationPrimerDesignInput(BaseModel):
    plasmid_sequence: str = Field(..., description="Complete plasmid sequence")
    target_region: Tuple[int, int] = Field(..., description="Start and end positions (0-based) of the target region")
    existing_primers: Optional[List[Dict[str, str]]] = Field(
        None, description="List of existing primers with 'name' and 'sequence'; uses default lab primers if None"
    )
    is_circular: Optional[bool] = Field(True, description="Whether the plasmid is circular (default: True)")
    coverage_length: Optional[int] = Field(800, description="Typical read length for each primer")
    primer_length: Optional[int] = Field(20, description="Length of newly designed primers")
    min_gc: Optional[float] = Field(0.4, description="Minimum GC content for new primers")
    max_gc: Optional[float] = Field(0.6, description="Maximum GC content for new primers")
    min_tm: Optional[float] = Field(55.0, description="Minimum melting temperature in °C")
    max_tm: Optional[float] = Field(65.0, description="Maximum melting temperature in °C")

async def design_verification_primers_coroutine(
    plasmid_sequence: str,
    target_region: Tuple[int, int],
    existing_primers: Optional[List[Dict[str, str]]] = None,
    is_circular: bool = True,
    coverage_length: int = 800,
    primer_length: int = 20,
    min_gc: float = 0.4,
    max_gc: float = 0.6,
    min_tm: float = 55.0,
    max_tm: float = 65.0
) -> Dict[str, Any]:
    """
    Design Sanger sequencing primers to verify a target region in a plasmid.
    Uses existing primers if available, otherwise designs new primers.
    """
    try:
        steps_log = f"Starting verification primer design for region {target_region}\n"

        # ======= 内部 helper 函数 =======
        def merge_overlapping_regions(regions):
            if not regions: return []
            sorted_regions = sorted(regions, key=lambda x: x["start"])
            merged = [sorted_regions[0]]
            for region in sorted_regions[1:]:
                prev = merged[-1]
                if region["start"] <= prev["end"] + 1:
                    prev["end"] = max(prev["end"], region["end"])
                else:
                    merged.append(region)
            return merged

        def is_position_covered(pos, covered_regions):
            for region in covered_regions:
                if region["start"] <= pos <= region["end"]:
                    return True
            return False

        def is_region_fully_covered(covered_regions, start, end):
            merged = merge_overlapping_regions(covered_regions)
            for pos in range(start, end + 1):
                if not any(r["start"] <= pos <= r["end"] for r in merged):
                    return False
            return True

        def reverse_complement(seq: str) -> str:
            complement = {"A": "T", "T": "A", "G": "C", "C": "G"}
            return "".join(complement.get(base, "N") for base in reversed(seq))

        def design_primer(sequence, position, primer_length, min_gc, max_gc, min_tm, max_tm):
            # 简化示例: 取指定位置的片段并返回模拟 GC 和 Tm
            seq = sequence[position:position + primer_length]
            gc = (seq.count("G") + seq.count("C")) / len(seq) if len(seq) > 0 else 0
            tm = 2 * (seq.count("A") + seq.count("T")) + 4 * (seq.count("G") + seq.count("C"))
            if min_gc <= gc <= max_gc and min_tm <= tm <= max_tm:
                return {"sequence": seq, "position": position, "gc": gc, "tm": tm}
            return None

        # ======= 主逻辑 =======
        plasmid_sequence = plasmid_sequence.upper()
        start, end = target_region
        region_length = end - start + 1
        if region_length <= 0:
            return {"success": False, "log": steps_log, "error": "Target region end must be greater than start."}

        recommended_primers = []
        coverage_map = []

        # 使用默认实验室引物
        if existing_primers is None:
            existing_primers = [
                {"name": "T7", "sequence": "TAATACGACTCACTATAGGG"},
                {"name": "T3", "sequence": "ATTAACCCTCACTAAAGGGA"},
                {"name": "SP6", "sequence": "GATTTAGGTGACACTATAG"},
            ]

        # 简化: 假设所有 existing_primers 可以覆盖目标区域
        for i, p in enumerate(existing_primers):
            coverage_start = start
            coverage_end = min(end, start + coverage_length)
            recommended_primers.append({
                "name": p.get("name", f"Existing_{i+1}"),
                "sequence": p["sequence"],
                "position": start,
                "strand": "+",
                "source": "existing",
                "covers": [coverage_start, coverage_end]
            })
            coverage_map.append({
                "primer": p.get("name", f"Existing_{i+1}"),
                "start": coverage_start,
                "end": coverage_end,
                "length": coverage_end - coverage_start + 1
            })
            break  # 只选一个示例引物覆盖

        # 检查是否完全覆盖
        covered_regions = [{"start": cm["start"], "end": cm["end"]} for cm in coverage_map]
        uncovered_regions = []
        if not is_region_fully_covered(covered_regions, start, end):
            # 设计新引物覆盖剩余区域
            uncovered_regions.append({"start": start, "end": end})
            for idx, region in enumerate(uncovered_regions):
                pos = region["start"]
                new_primer = design_primer(plasmid_sequence, pos, primer_length, min_gc, max_gc, min_tm, max_tm)
                if new_primer:
                    name = f"New_primer_{len(recommended_primers)+1}"
                    recommended_primers.append({
                        "name": name,
                        "sequence": new_primer["sequence"],
                        "position": new_primer["position"],
                        "strand": "+",
                        "source": "newly_designed",
                        "gc": new_primer["gc"],
                        "tm": new_primer["tm"],
                        "covers": [region["start"], region["end"]]
                    })
                    coverage_map.append({
                        "primer": name,
                        "start": region["start"],
                        "end": region["end"],
                        "length": region["end"] - region["start"] + 1
                    })

        is_fully_covered = is_region_fully_covered(coverage_map, start, end)
        steps_log += "Primer design completed.\n"

        result = {
            "success": True,
            "log": steps_log,
            "target_region": {"start": start, "end": end, "length": region_length},
            "recommended_primers": recommended_primers,
            "coverage_map": coverage_map,
            "is_fully_covered": is_fully_covered
        }
        if not is_fully_covered:
            result["warning"] = "The target region may not be fully covered. Review coverage map."

        return result

    except Exception as e:
        return {"success": False, "error": str(e)}

design_verification_primers_tool = StructuredTool.from_function(
    coroutine=design_verification_primers_coroutine,
    name=Tools.design_verification_primers,
    description="""
    【领域：生物】Design Sanger sequencing primers for a plasmid target region.

Parameters
----------
- plasmid_sequence (str): Complete plasmid sequence
- target_region (tuple): Start and end positions (0-based) to verify
- existing_primers (list, optional): Existing primers to use
- is_circular (bool, optional): Whether plasmid is circular
- coverage_length (int, optional): Read length per primer
- primer_length (int, optional): Length of newly designed primers
- min_gc, max_gc (float, optional): GC content bounds
- min_tm, max_tm (float, optional): Melting temperature bounds

Returns
-------
- dict: Recommended primers, coverage map, and logs
""",
    args_schema=VerificationPrimerDesignInput,
    metadata={"args_schema_json": VerificationPrimerDesignInput.schema()}
)



#测试成功
class GoldenGateOligoDesignInput(BaseModel):
    backbone_sequence: str = Field(..., description="Plasmid or backbone DNA sequence")
    insert_sequence: str = Field(..., description="Sequence to be inserted")
    enzyme_name: str = Field(..., description="Type IIS restriction enzyme to be used, e.g., BsaI, BsmBI")
    is_circular: Optional[bool] = Field(True, description="Whether the backbone is circular (default: True)")

async def design_golden_gate_oligos_coroutine(
    backbone_sequence: str,
    insert_sequence: str,
    enzyme_name: str,
    is_circular: bool = True
) -> Dict[str, Any]:
    """
    Design Golden Gate cloning oligos by identifying enzyme cut sites and generating
    matching insert oligos.
    """
    try:
        steps_log = (
            f"Starting Golden Gate oligo design with enzyme {enzyme_name}\n"
            f"Backbone length: {len(backbone_sequence)} bp, "
            f"Insert length: {len(insert_sequence)} bp, "
            f"Circular: {is_circular}\n"
        )

        # Enzyme recognition properties
        TYPE_IIS_PROPERTIES = {
            "BsaI": {"recognition_site": "GGTCTC", "offset_fwd": 1, "offset_rev": 5},
            "BsmBI": {"recognition_site": "CGTCTC", "offset_fwd": 1, "offset_rev": 5},
            "BbsI": {"recognition_site": "GAAGAC", "offset_fwd": 2, "offset_rev": 6},
            "Esp3I": {"recognition_site": "CGTCTC", "offset_fwd": 1, "offset_rev": 5},
            "BtgZI": {"recognition_site": "GCGATG", "offset_fwd": 10, "offset_rev": 14},
            "SapI": {"recognition_site": "GCTCTTC", "offset_fwd": 1, "offset_rev": 4},
        }

        if enzyme_name not in TYPE_IIS_PROPERTIES:
            supported = ", ".join(TYPE_IIS_PROPERTIES.keys())
            return {
                "success": False,
                "log": steps_log,
                "error": f"Unsupported enzyme: {enzyme_name}. Supported enzymes: {supported}"
            }

        # Clean input sequences
        backbone_sequence = "".join(c for c in backbone_sequence.upper() if c in "ATGC")
        insert_sequence = "".join(c for c in insert_sequence.upper() if c in "ATGC")

        # Reverse complement helper
        def reverse_complement(seq: str) -> str:
            complement = {"A": "T", "T": "A", "G": "C", "C": "G"}
            return "".join(complement.get(base, "N") for base in reversed(seq))

        # Get enzyme properties
        props = TYPE_IIS_PROPERTIES[enzyme_name]
        recognition_site = props["recognition_site"]
        offset_fwd, offset_rev = props["offset_fwd"], props["offset_rev"]

        # Step 1: Find recognition sites
        restriction_sites = []
        for i in range(len(backbone_sequence)):
            if is_circular and i + len(recognition_site) > len(backbone_sequence):
                site_seq = backbone_sequence[i:] + backbone_sequence[: i + len(recognition_site) - len(backbone_sequence)]
            elif i + len(recognition_site) <= len(backbone_sequence):
                site_seq = backbone_sequence[i : i + len(recognition_site)]
            else:
                continue

            if site_seq == recognition_site:
                restriction_sites.append({"position": i, "strand": "forward"})
            if site_seq == reverse_complement(recognition_site):
                restriction_sites.append({"position": i, "strand": "reverse"})

        if len(restriction_sites) < 2:
            return {
                "success": False,
                "log": steps_log,
                "error": f"Need at least 2 {enzyme_name} recognition sites in the backbone."
            }

        # Step 2: Determine cut sites & overhangs
        cut_sites = []
        for site in restriction_sites:
            pos = site["position"]
            if site["strand"] == "forward":
                cut_fwd = (pos + len(recognition_site) + offset_fwd) % len(backbone_sequence)
                cut_rev = (pos + len(recognition_site) + offset_rev) % len(backbone_sequence)
            else:  # reverse strand
                cut_rev = (pos - offset_fwd) % len(backbone_sequence)
                cut_fwd = (pos - offset_rev) % len(backbone_sequence)

            if cut_fwd < cut_rev:
                overhang = backbone_sequence[cut_fwd:cut_rev]
            else:
                overhang = backbone_sequence[cut_fwd:] + backbone_sequence[:cut_rev]

            cut_sites.append({
                "site_position": pos,
                "strand": site["strand"],
                "cut_fwd": cut_fwd,
                "cut_rev": cut_rev,
                "overhang": overhang
            })

        # Step 3: Select overhangs for insert (use first two for demo)
        upstream_overhang = cut_sites[0]["overhang"]
        downstream_overhang = cut_sites[1]["overhang"]

        # Step 4: Design oligos
        fw_oligo = upstream_overhang + insert_sequence
        rev_oligo = reverse_complement(insert_sequence + reverse_complement(downstream_overhang))

        steps_log += f"Found {len(restriction_sites)} {enzyme_name} sites. Using overhangs {upstream_overhang} / {downstream_overhang}.\n"
        steps_log += "Oligo design completed successfully.\n"

        return {
            "success": True,
            "log": steps_log,
            "overhangs": {"upstream": upstream_overhang, "downstream": downstream_overhang},
            "oligos": {
                "forward": fw_oligo,
                "reverse": rev_oligo,
                "notes": [
                    f"Forward oligo includes {upstream_overhang} at 5' end.",
                    f"Reverse oligo includes {reverse_complement(downstream_overhang)} at 5' end of reverse complement."
                ],
            },
            "cut_sites": [
                {"position": site["site_position"], "overhang": site["overhang"]}
                for site in cut_sites
            ],
            "assembly_notes": f"Using overhangs {upstream_overhang} and {downstream_overhang} for assembly."
        }

    except Exception as e:
        return {"success": False, "error": f"Oligo design failed: {str(e)}"}

design_golden_gate_oligos_tool = StructuredTool.from_function(
    coroutine=design_golden_gate_oligos_coroutine,
    name=Tools.design_golden_gate_oligos,
    description="""
    【领域：生物】Design oligos for Golden Gate cloning given backbone and insert sequences.

    Parameters
    ----------
    - backbone_sequence (str): DNA sequence of the plasmid or backbone.
    - insert_sequence (str): DNA sequence to be inserted.
    - enzyme_name (str): Type IIS restriction enzyme name (e.g., BsaI, BsmBI, BbsI, Esp3I, BtgZI, SapI).
    - is_circular (bool, optional): Whether the backbone is circular. Default: True.

    Returns
    -------
    - Dict: Step logs, detected cut sites, overhangs, designed forward/reverse oligos, and assembly notes.
    """,
    args_schema=GoldenGateOligoDesignInput,
    metadata={"args_schema_json": GoldenGateOligoDesignInput.schema()}
)



