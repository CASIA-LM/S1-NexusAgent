---
name: literature-review
description: Conduct systematic literature review on scientific topics using PubMed and other databases
category: public
enabled: true
version: 1.0.0
author: S1-NexusAgent Team
tags: [literature, research, pubmed, review]
---

# Literature Review Skill

## Overview
This skill helps conduct systematic literature reviews on scientific topics by searching and analyzing research papers.

## When to Use
Use this skill when the user asks to:
- Review literature on a topic
- Find recent papers about a subject
- Summarize research trends
- Identify key papers in a field
- Compare different research approaches

## Workflow Instructions

### Step 1: Define Search Query
- Extract key terms from user request
- Identify relevant keywords and synonyms
- Determine time range (if specified)
- Select appropriate databases (PubMed, arXiv, etc.)

### Step 2: Search Literature
- Use `bio_literature` tools to search databases
- Apply filters (date, journal, citation count)
- Retrieve paper metadata (title, abstract, authors, year)
- Collect 10-50 most relevant papers

### Step 3: Analyze Papers
- Read abstracts and identify main themes
- Group papers by methodology or topic
- Identify highly cited papers
- Note research gaps or controversies

### Step 4: Synthesize Findings
- Summarize key findings across papers
- Identify research trends over time
- Highlight seminal works
- Note emerging directions

### Step 5: Generate Report
- Create structured summary
- Include paper citations
- Organize by themes or chronology
- Provide recommendations for further reading

## Example Usage

**User Query**: "Review recent literature on CRISPR gene editing in plants"

**Execution**:
1. Define: Keywords = ["CRISPR", "gene editing", "plants", "crop improvement"]
2. Search: PubMed for papers from 2020-2025
3. Analyze: Group by crop type and application
4. Synthesize: Identify trends in efficiency and off-target effects
5. Report: Structured summary with key papers and findings

## Tools to Use
- `bio_literature` tools for paper search
- Text processing tools for abstract analysis
- Data analysis tools for trend identification

## Output Format
```
# Literature Review: [Topic]

## Overview
- Total papers found: X
- Date range: YYYY-YYYY
- Key themes: [theme1, theme2, ...]

## Key Findings
1. [Finding 1]
   - Papers: [Author et al., Year]

2. [Finding 2]
   - Papers: [Author et al., Year]

## Research Trends
- [Trend 1]
- [Trend 2]

## Seminal Papers
1. [Author et al., Year] - [Title]
2. [Author et al., Year] - [Title]

## Future Directions
- [Direction 1]
- [Direction 2]
```

## Notes
- Focus on peer-reviewed papers
- Include preprints only if specifically requested
- Cite papers properly with DOI when available
- Limit to most relevant papers to avoid information overload
