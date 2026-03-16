---
name: protein-analysis
description: Analyze protein structure and function using PDB database and bioinformatics tools
category: public
enabled: true
version: 1.0.0
author: S1-NexusAgent Team
tags: [biology, protein, structure, bioinformatics]
---

# Protein Analysis Skill

## Overview
This skill helps analyze protein structures and functions using various bioinformatics tools and databases.

## When to Use
Use this skill when the user asks to:
- Analyze protein structure
- Get protein information from PDB
- Predict protein function
- Compare protein sequences
- Visualize protein structures

## Workflow Instructions

### Step 1: Identify the Protein
- Extract protein name or PDB ID from user query
- If only protein name is given, search for corresponding PDB ID

### Step 2: Retrieve Protein Data
- Use PDB database tools to fetch protein structure data
- Get sequence information
- Retrieve metadata (organism, resolution, method)

### Step 3: Perform Analysis
Depending on user request:
- **Structure Analysis**: Analyze secondary structure, domains, binding sites
- **Function Prediction**: Use sequence-based tools to predict function
- **Sequence Comparison**: Compare with similar proteins
- **Visualization**: Generate structure visualization if needed

### Step 4: Report Results
- Summarize key findings
- Include relevant metrics (resolution, sequence length, etc.)
- Provide visualization or data files if generated
- Suggest follow-up analyses if appropriate

## Example Usage

**User Query**: "Analyze the structure of TP53 protein"

**Execution**:
1. Identify: TP53 (tumor protein p53)
2. Retrieve: Search PDB for TP53 structures
3. Analyze: Get structure with best resolution, analyze domains
4. Report: Summarize structure features, DNA-binding domain, mutations

## Tools to Use
- `bio_database` tools for PDB access
- `bio_molecular` tools for structure analysis
- `bio_genetics` tools for sequence analysis
- Python tools for data processing and visualization

## Notes
- Always check if PDB ID is valid before analysis
- For large proteins, focus on specific domains if requested
- Mention data source and resolution in results
