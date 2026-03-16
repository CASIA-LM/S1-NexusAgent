"""
Sandbox工作目录说明 - System Prompt模板
参考DeerFlow的设计,明确告知Agent路径规范
"""

SANDBOX_WORKING_DIRECTORY_PROMPT = """
<working_directory>
你的代码在隔离的沙箱环境中运行,可以访问以下目录:

📁 目录结构:
- 工作区: /home/gem/workspace/
  用途: 临时文件、中间结果
  权限: 可读写
  说明: 用于存放代码执行过程中的临时文件

- 上传文件: /home/gem/uploads/
  用途: 用户上传的输入文件
  权限: 只读
  说明: 包含用户提供的数据文件、配置文件等

- 输出文件: /home/gem/outputs/
  用途: 最终结果文件
  权限: 可写
  说明: **所有需要持久化的结果必须保存到这里**

🔑 重要规则:
1. 最终结果文件必须保存到 /home/gem/outputs/ 目录
2. 宿主机可以直接访问outputs目录的文件
3. 每个会话有独立的目录空间,不会相互干扰
4. 容器重启后数据不保留,请及时保存重要结果

💡 使用示例:
```python
# ✅ 正确: 保存结果到outputs目录
with open('/home/gem/outputs/result.csv', 'w') as f:
    f.write(data)

# ✅ 正确: 读取用户上传的文件
df = pd.read_csv('/home/gem/uploads/input.csv')

# ✅ 正确: 使用workspace存放临时文件
temp_file = '/home/gem/workspace/temp.txt'

# ❌ 错误: 不要保存到其他位置
with open('/tmp/result.csv', 'w') as f:  # 宿主机无法访问
    f.write(data)
```

📤 文件分享:
如果需要生成可分享的链接,可以使用save_output_file工具并设置upload_to_minio=True。
</working_directory>
"""


SANDBOX_FILE_OPERATIONS_PROMPT = """
<file_operations>
可用的文件操作工具:

1. upload_file_to_sandbox
   - 功能: 上传宿主机文件到sandbox
   - 目标目录: /home/gem/uploads/
   - 使用场景: 需要处理本地文件时

2. save_output_file
   - 功能: 保存结果文件到outputs目录
   - 目标目录: /home/gem/outputs/
   - 可选: 同时上传到MinIO获取分享链接
   - 使用场景: 保存最终结果

3. get_output_file
   - 功能: 读取outputs目录的文件
   - 使用场景: 获取之前保存的结果

4. sandbox_code_executor
   - 功能: 在sandbox中执行Python代码
   - 说明: 代码可以直接访问上述三个目录

5. sandbox_shell_command_executor
   - 功能: 在sandbox中执行Shell命令
   - 说明: 可以使用ls, cat等命令查看文件
</file_operations>
"""


def get_sandbox_prompt(session_id: str) -> str:
    """
    生成包含session信息的完整sandbox提示

    Args:
        session_id: 会话ID

    Returns:
        完整的prompt文本
    """
    return f"""
{SANDBOX_WORKING_DIRECTORY_PROMPT}

{SANDBOX_FILE_OPERATIONS_PROMPT}

<session_info>
当前会话ID: {session_id}
所有文件操作都会自动关联到此会话。
</session_info>
"""
