from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List, Tuple

from langchain_core.tools import StructuredTool
from workflow.const import Tools
from workflow.utils.minio_utils import upload_content_to_minio

import asyncio
import aiohttp
import io
import os
import json
import time

import numpy as np
import pandas as pd
from scipy.integrate import solve_ivp

from Bio.PDB import PDBParser, Superimposer, PDBIO, Select
from Bio.PDB.PDBExceptions import PDBConstructionWarning
import warnings



class FBAInput(BaseModel):
    model_url: str = Field(..., description="URL to the metabolic model file (SBML or JSON)")
    constraints: Optional[Dict[str, tuple]] = Field(None, description="Reaction constraints: {reaction_id: (lower_bound, upper_bound)}")
    objective_reaction: Optional[str] = Field(None, description="Reaction ID to set as objective function")
    output_file: Optional[str] = Field("fba_results.csv", description="Output file name (实际通过上传获取链接)")

async def perform_fba_coroutine(
    model_url: str,
    constraints: Optional[Dict[str, tuple]] = None,
    objective_reaction: Optional[str] = None,
    output_file: Optional[str] = "fba_results.csv"
) -> Dict[str, Any]:
    log = "# Flux Balance Analysis (FBA) Research Log\n\n"

    # Step 1: Download model file
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(model_url) as resp:
                if resp.status != 200:
                    return {"research_log": f"Error fetching model from URL: status {resp.status}", "flux_csv_url": None}
                model_bytes = await resp.read()

        # Save to temporary file for cobra loading
        tmp_path = "temp_model_file"
        with open(tmp_path, "wb") as f:
            f.write(model_bytes)
        log += f"## Step 1: Loaded metabolic model from {model_url}\n"
    except Exception as e:
        return {"research_log": f"Error downloading model: {str(e)}", "flux_csv_url": None}

    # Step 2: Load model
    try:
        if model_url.endswith('.xml') or model_url.endswith('.sbml'):
            model = cobra.io.read_sbml_model(tmp_path)
        elif model_url.endswith('.json'):
            model = cobra.io.load_json_model(tmp_path)
        else:
            model = cobra.io.load_model(tmp_path)
        log += f"- Model contains {len(model.reactions)} reactions and {len(model.metabolites)} metabolites\n\n"
    except Exception as e:
        return {"research_log": f"Error loading model: {str(e)}", "flux_csv_url": None}
    finally:
        os.remove(tmp_path)

    # Step 3: Set constraints
    log += "## Step 2: Setting constraints\n"
    if constraints:
        log += "- Applied the following constraints:\n"
        for rxn_id, (lb, ub) in constraints.items():
            try:
                rxn = model.reactions.get_by_id(rxn_id)
                rxn.bounds = (lb, ub)
                log += f"  * {rxn_id}: lower_bound={lb}, upper_bound={ub}\n"
            except Exception as e:
                log += f"  * Error setting constraint for {rxn_id}: {str(e)}\n"
    else:
        log += "- No additional constraints specified, using model defaults\n"
    log += "\n"

    # Step 4: Set objective
    log += "## Step 3: Setting objective function\n"
    try:
        if objective_reaction:
            model.objective = objective_reaction
            log += f"- Set objective function to maximize {objective_reaction}\n\n"
        else:
            log += f"- Using model's default objective function: {model.objective.expression}\n\n"
    except Exception as e:
        log += f"- Error setting objective: {str(e)}\n- Using default objective\n\n"

    # Step 5: Solve FBA
    log += "## Step 4: Solving FBA optimization problem\n"
    try:
        solution = model.optimize()
        log += f"- Optimization status: {solution.status}\n"
        log += f"- Objective value: {solution.objective_value:.6f}\n\n"
    except Exception as e:
        log += f"- Error during optimization: {str(e)}\n"
        return {"research_log": log, "flux_csv_url": None}

    # Step 6: Save flux distribution
    log += "## Step 5: Analyzing flux distribution\n"
    flux_df = pd.DataFrame({
        'reaction_id': [r.id for r in model.reactions],
        'reaction_name': [r.name for r in model.reactions],
        'flux': [solution.fluxes[r.id] for r in model.reactions],
        'lower_bound': [r.lower_bound for r in model.reactions],
        'upper_bound': [r.upper_bound for r in model.reactions]
    })

    # Upload CSV
    buf = io.StringIO()
    flux_df.to_csv(buf, index=False)
    flux_csv_url = await upload_content_to_minio(
        content=buf.getvalue().encode('utf-8'),
        file_name=output_file,
        file_extension=".csv",
        content_type="text/csv",
        no_expired=True
    )
    log += f"- Flux distribution uploaded to {flux_csv_url}\n"

    # Top reactions
    active_reactions = flux_df[abs(flux_df['flux'])>1e-6]
    log += f"- Number of active reactions (flux > 1e-6): {len(active_reactions)}\n"
    top_reactions = flux_df.iloc[abs(flux_df['flux']).argsort()[::-1]].head(10)
    log += "- Top 10 reactions by absolute flux magnitude:\n"
    for _, row in top_reactions.iterrows():
        log += f"  * {row['reaction_id']} ({row['reaction_name']}): {row['flux']:.6f}\n"

    return {"research_log": log, "flux_csv_url": flux_csv_url}

perform_fba_tool = StructuredTool.from_function(
    name=Tools.perform_fba,
    description="""
    【领域：生物】
        "对基因组规模代谢网络模型执行Flux Balance Analysis(FBA)，预测代谢通量分布。\n\n"
        "返回：\n"
        " - research_log: FBA分析日志\n"
        " - flux_csv_url: 通量分布 CSV 文件链接"
"""
,
    args_schema=FBAInput,
    coroutine=perform_fba_coroutine,
    metadata={"args_schema_json": FBAInput.schema()}
)





class RASSimulationInput(BaseModel):
    initial_concentrations: Dict[str, float] = Field(..., description="Initial concentrations of RAS components")
    rate_constants: Dict[str, float] = Field(..., description="Kinetic rate constants")
    feedback_params: Dict[str, float] = Field(..., description="Feedback parameters")
    simulation_time: Optional[float] = Field(48, description="Total simulation time in hours")
    time_points: Optional[int] = Field(100, description="Number of time points")

async def simulate_ras_coroutine(
    initial_concentrations: Dict[str, float],
    rate_constants: Dict[str, float],
    feedback_params: Dict[str, float],
    simulation_time: float = 48,
    time_points: int = 100
) -> Dict[str, Any]:

    # Initial values
    y0 = [
        initial_concentrations['renin'],
        initial_concentrations['angiotensinogen'],
        initial_concentrations['angiotensin_I'],
        initial_concentrations['angiotensin_II'],
        initial_concentrations['ACE2_angiotensin_II'],
        initial_concentrations['angiotensin_1_7']
    ]

    # Define ODE system
    def ras_ode_system(t, y):
        renin, agt, ang_I, ang_II, ace2_ang_II, ang_1_7 = y
        renin_prod = rate_constants['k_ren'] / (1 + feedback_params['fb_ang_II'] * ang_II)
        agt_prod = rate_constants['k_agt']
        ang_I_form = renin * agt
        ang_II_form = rate_constants['k_ace'] * ang_I
        ace2_bind = rate_constants['k_ace2'] * ang_II
        ang_1_7_form = ace2_ang_II
        renin_cl = 0.1 * renin
        agt_cl = 0.05 * agt
        ang_I_cl = 0.2 * ang_I
        ang_II_cl = 0.3 * ang_II + rate_constants['k_at1r'] * ang_II
        ace2_ang_II_cl = 0.15 * ace2_ang_II
        ang_1_7_cl = 0.25 * ang_1_7 + rate_constants['k_mas'] * ang_1_7
        return [
            renin_prod - renin_cl,
            agt_prod - agt_cl - ang_I_form,
            ang_I_form - ang_I_cl - ang_II_form,
            ang_II_form - ang_II_cl - ace2_bind,
            ace2_bind - ace2_ang_II_cl - ang_1_7_form,
            ang_1_7_form - ang_1_7_cl
        ]

    t_span = (0, simulation_time)
    t_eval = np.linspace(0, simulation_time, time_points)
    sol = solve_ivp(ras_ode_system, t_span, y0, method='RK45', t_eval=t_eval, rtol=1e-6)

    # Prepare results CSV
    component_names = ['Renin', 'Angiotensinogen', 'Angiotensin I', 
                       'Angiotensin II', 'ACE2-Angiotensin II', 'Angiotensin 1-7']
    df = pd.DataFrame(sol.y.T, columns=component_names)
    df.insert(0, 'Time (hours)', sol.t)

    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)

    # Upload CSV
    results_url = await upload_content_to_minio(
        csv_buffer.getvalue().encode('utf-8'),
        "ras_simulation_results",
        ".csv",
        "text/csv",
        no_expired=True
    )

    # Build research log
    log = f"RAS Simulation completed.\nSimulation time: {simulation_time} hours, {time_points} points.\nResults saved to {results_url}"

    return {
        "research_log": log,
        "results_csv_url": results_url
    }

ras_tool = StructuredTool.from_function(
    name=Tools.simulate_ras,
    description="""
    【领域：生物】
    Simulate RAS system dynamics and provide time-course of all components""",
    args_schema=RASSimulationInput,
    coroutine=simulate_ras_coroutine,
    metadata={"args_schema_json": RASSimulationInput.schema()}
)
