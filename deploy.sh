#!/bin/bash
# 默认变量
process_aip=false

# 处理命令行参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --aip)
            process_aip=true
            shift
            ;;
        *)
            echo "未知参数: $1"
            exit 1
            ;;
    esac
done

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "脚本所在目录: $BASE_DIR"
DEST_FILE="$BASE_DIR/docker/.env"
COMPOSE_FILE="$BASE_DIR/docker/docker-compose.yml"
SOURCE_DIR="$BASE_DIR/backend/config"
envs=`ls ${SOURCE_DIR} | grep 'env_' | awk -F '_' '{printf "%s ", $2}'`
echo $envs
# 检查是否传入环境参数
if [ -z $AGENT_ENV ]; then
    echo -e "********************\n* 1. 请vim ~/.bashrc在最下面添加export AGENT_ENV=xxx, xxx取值范围为${envs}\n* 2. source ~/.bashrc. \n* 3.然后执行bash deploy.sh\n********************"
    exit 1
fi

SOURCE_FILE="$BASE_DIR/backend/config/env_$AGENT_ENV"

# 进入目标目录
echo "进入目录: $BASE_DIR"
cd "$BASE_DIR" || {
    echo "错误: 无法进入目录 $BASE_DIR，请检查路径是否存在"
    exit 1
}

# 检查源配置文件是否存在
if [ ! -f "$SOURCE_FILE" ]; then
    echo "错误: 环境配置文件 $SOURCE_FILE 不存在，请检查参数是否正确"
    exit 1
fi

# 复制配置文件到目标位置
echo "复制配置文件: $SOURCE_FILE -> $DEST_FILE"
cp "$SOURCE_FILE" "$DEST_FILE" || {
    echo "错误: 复制文件失败"
    exit 1
}

# 检查 docker-compose 文件是否存在
if [ ! -f "$COMPOSE_FILE" ]; then
    echo "错误: docker-compose 文件 $COMPOSE_FILE 不存在"
    exit 1
fi


# 构建前端服务
echo "开始构建 前端 服务..."
docker compose -f "$COMPOSE_FILE" build flock_frontend || {
    echo "错误: 构建 前端 服务失败"
    exit 1
}

# 启动前端服务
echo "启动 前端 服务..."
docker compose -f "$COMPOSE_FILE" up -d flock_frontend || {
    echo "错误: 启动 前端 服务失败"
    exit 1
}

# 构建 api 服务
echo "开始构建 api 服务..."
docker compose -f "$COMPOSE_FILE" build flock_api || {
    echo "错误: 构建 api 服务失败"
    exit 1
}

# 启动 api 服务
echo "启动 api 服务..."
docker compose -f "$COMPOSE_FILE" up -d flock_api || {
    echo "错误: 启动 api 服务失败"
    exit 1
}

if [ "$process_aip" = true ]; then
    echo "启动 aip-gateway 服务..."
    docker compose -f "$COMPOSE_FILE" up -d flock_aip_gateway || {
        echo "错误: 启动 aip-gateway 服务"
        exit 1
    }
fi

# 启动 aip-gateway 服务

echo "开始构建 code 服务..."
docker compose -f "$COMPOSE_FILE" build code-interpreter || {
    echo "错误: 构建 api 服务失败"
    exit 1
}

echo "启动 code 服务..."
docker compose -f "$COMPOSE_FILE" up -d code-interpreter || {
    echo "错误: 启动 api 服务失败"
    exit 1
}

echo "操作完成: api 服务已启动 (环境: $ENV_NAME)"