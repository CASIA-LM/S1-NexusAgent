#!/bin/bash
# 重启AIO Sandbox容器并添加volume挂载
# 这是可选的升级脚本,用于从API同步模式迁移到volume挂载模式

set -e

echo "=== AIO Sandbox容器重启脚本(带volume挂载) ==="
echo ""

# 配置
CONTAINER_NAME="aio_sandbox_test6"
IMAGE="eval-aio-sandbox:v2"
HOST_PORT=9001
CONTAINER_PORT=8080
DATA_DIR="/home/pangziliang/nexus_data"

# 检查是否提供session_id
if [ -z "$1" ]; then
    echo "用法: $0 <session_id>"
    echo "示例: $0 user123_20260313"
    exit 1
fi

SESSION_ID="$1"
SESSION_DIR="$DATA_DIR/sessions/$SESSION_ID"

echo "Session ID: $SESSION_ID"
echo "Session目录: $SESSION_DIR"
echo ""

# 创建session目录
echo "1. 创建session目录..."
mkdir -p "$SESSION_DIR/workspace"
mkdir -p "$SESSION_DIR/uploads"
mkdir -p "$SESSION_DIR/outputs"
echo "   ✓ 目录已创建"
echo ""

# 停止现有容器
echo "2. 停止现有容器..."
if docker ps -a | grep -q "$CONTAINER_NAME"; then
    docker stop "$CONTAINER_NAME" 2>/dev/null || true
    docker rm "$CONTAINER_NAME" 2>/dev/null || true
    echo "   ✓ 容器已停止并删除"
else
    echo "   ℹ 容器不存在,跳过"
fi
echo ""

# 启动新容器(带volume挂载)
echo "3. 启动新容器(带volume挂载)..."
docker run -d \
    --name "$CONTAINER_NAME" \
    --security-opt seccomp=unconfined \
    -p "$HOST_PORT:$CONTAINER_PORT" \
    --shm-size 2gb \
    -v "$SESSION_DIR/workspace:/home/gem/workspace" \
    -v "$SESSION_DIR/uploads:/home/gem/uploads" \
    -v "$SESSION_DIR/outputs:/home/gem/outputs" \
    -e WORKSPACE=/home/gem \
    -e TZ=Asia/Shanghai \
    "$IMAGE"

echo "   ✓ 容器已启动"
echo ""

# 等待容器启动
echo "4. 等待容器启动..."
sleep 5

# 检查容器状态
if docker ps | grep -q "$CONTAINER_NAME"; then
    echo "   ✓ 容器运行正常"
else
    echo "   ✗ 容器启动失败"
    docker logs "$CONTAINER_NAME"
    exit 1
fi
echo ""

# 验证volume挂载
echo "5. 验证volume挂载..."
docker inspect "$CONTAINER_NAME" | grep -A 10 "Mounts"
echo ""

echo "=== 完成 ==="
echo ""
echo "容器信息:"
echo "  名称: $CONTAINER_NAME"
echo "  端口: http://localhost:$HOST_PORT"
echo "  Session: $SESSION_ID"
echo ""
echo "Volume挂载:"
echo "  $SESSION_DIR/workspace → /home/gem/workspace"
echo "  $SESSION_DIR/uploads → /home/gem/uploads"
echo "  $SESSION_DIR/outputs → /home/gem/outputs"
echo ""
echo "测试命令:"
echo "  docker exec $CONTAINER_NAME ls -la /home/gem/"
echo "  curl http://localhost:$HOST_PORT/v1/sandbox"
