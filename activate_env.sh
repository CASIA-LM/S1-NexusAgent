#!/bin/bash
# S1-NexusAgent 环境激活脚本

echo "正在激活 nexusagent conda 环境..."
source ~/anaconda3/etc/profile.d/conda.sh
conda activate nexusagent

echo "✓ nexusagent 环境已激活"
echo ""
echo "环境信息:"
python --version
echo "LangChain Core: $(python -c 'import langchain_core; print(langchain_core.__version__)')"
echo "Pydantic: $(python -c 'import pydantic; print(pydantic.__version__)')"
echo ""
echo "使用 'conda deactivate' 退出环境"
