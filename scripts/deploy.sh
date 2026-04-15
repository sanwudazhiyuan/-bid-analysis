#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# 标书智能解析系统 - Docker 一键部署脚本
# 所有依赖均使用国内镜像源
# ============================================================

echo "=========================================="
echo "  标书智能解析系统 - 部署脚本"
echo "=========================================="

# 颜色定义
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 检查 Docker 是否已安装
if ! command -v docker &>/dev/null; then
    log_error "Docker 未安装，请先安装 Docker"
    log_info "国内安装参考: https://mirror.azure.cn/docker-ce/"
    exit 1
fi

# 检查 docker-compose 是否可用
if ! docker compose version &>/dev/null; then
    log_error "Docker Compose 不可用，请使用 Docker Compose V2"
    exit 1
fi

# 检查 .env 文件
if [ ! -f .env ]; then
    log_warn ".env 文件不存在，从 .env.example 复制"
    cp .env.example .env
    log_warn "请编辑 .env 文件，配置 DASHSCOPE_API_KEY"
fi

# ============================================================
# Docker 镜像源配置（仅首次运行需要）
# ============================================================

DOCKER_REGISTRY_MIRRORS=(
    "https://docker.1ms.run"
    "https://docker.xuanyuan.me"
    "https://hub.rat.dev"
    "https://registry.dockermirror.com"
)

configure_docker_mirror() {
    log_info "配置 Docker 镜像源（国内加速）..."

    # 检测 Docker 操作系统
    if [[ "$(uname)" == *"MINGW"* || "$(uname)" == *"MSYS"* ]]; then
        # Windows Docker Desktop
        log_info "检测到 Windows 系统 (Docker Desktop)"
        log_info "请手动配置 Docker Desktop 镜像源:"
        log_info "  1. 打开 Docker Desktop -> Settings -> Docker Engine"
        log_info "  2. 在 JSON 配置中添加:"
        echo '     "registry-mirrors": ['
        for mirror in "${DOCKER_REGISTRY_MIRRORS[@]}"; do
            echo "       \"$mirror\","
        done | sed '$ s/,$//'
        echo '     ]'
        log_warn "配置完成后请重启 Docker Desktop"
        return
    elif [[ "$(uname)" == "Darwin" ]]; then
        # macOS Docker Desktop
        log_info "检测到 macOS 系统 (Docker Desktop)"
        log_info "请手动配置 Docker Desktop 镜像源:"
        log_info "  Docker Desktop -> Settings -> Docker Engine -> 添加 registry-mirrors"
        return
    else
        # Linux
        DOCKER_CONFIG="/etc/docker/daemon.json"

        if [ -f "$DOCKER_CONFIG" ] && grep -q "registry-mirrors" "$DOCKER_CONFIG" 2>/dev/null; then
            log_info "Docker 镜像源已配置"
            return
        fi

        log_info "配置 Linux Docker 镜像源到 $DOCKER_CONFIG"

        # 创建或更新 daemon.json
        if [ -f "$DOCKER_CONFIG" ]; then
            # 已有配置文件，添加镜像源
            python3 -c "
import json, sys
with open('$DOCKER_CONFIG') as f:
    config = json.load(f)
config['registry-mirrors'] = ${DOCKER_REGISTRY_MIRRORS[@]}
with open('$DOCKER_CONFIG', 'w') as f:
    json.dump(config, f, indent=2)
" 2>/dev/null || {
                log_warn "无法自动更新 $DOCKER_CONFIG，请手动添加:"
                echo "  $DOCKER_CONFIG:"
                echo "  {"
                echo "    \"registry-mirrors\": ["
                for mirror in "${DOCKER_REGISTRY_MIRRORS[@]}"; do
                    echo "      \"$mirror\","
                done | sed '$ s/,$//'
                echo "    ]"
                echo "  }"
                return
            }
        else
            # 创建新配置文件
            sudo mkdir -p /etc/docker
            sudo tee "$DOCKER_CONFIG" > /dev/null << EOF
{
  "registry-mirrors": [$(printf '"%s",' "${DOCKER_REGISTRY_MIRRORS[@]}" | sed 's/,$//')
  ]
}
EOF
        fi

        # 重启 Docker 服务
        log_info "重启 Docker 服务..."
        sudo systemctl daemon-reload
        sudo systemctl restart docker
        log_info "Docker 镜像源配置完成"
    fi
}

# 检查是否需要配置镜像源
if [ "${SKIP_MIRROR_CONFIG:-0}" != "1" ]; then
    configure_docker_mirror
fi

# ============================================================
# 构建并启动服务
# ============================================================

log_info "开始拉取基础镜像和构建服务..."
log_info "所有包管理器已配置国内镜像源:"
log_info "  - pip: mirrors.aliyun.com/pypi"
log_info "  - npm/registry.npmmirror.com"
log_info "  - bun: registry.npmmirror.com"
log_info "  - apt: mirrors.aliyun.com"

# 拉取基础镜像（使用已配置的 Docker 镜像源）
log_info "拉取基础镜像..."
docker compose pull postgres redis

# 构建并启动所有服务
log_info "构建并启动服务..."
docker compose up -d --build

# 等待服务启动
log_info "等待服务启动..."
sleep 10

# 检查服务状态
log_info "服务状态:"
docker compose ps

echo ""
log_info "=========================================="
log_info "  部署完成！"
log_info "=========================================="
log_info "  前端访问地址: http://localhost"
log_info "  API 文档:     http://localhost:8000/docs"
log_info "  健康检查:     http://localhost:8000/api/health"
log_info "=========================================="
log_info "  常用命令:"
log_info "    查看日志:     docker compose logs -f"
log_info "    停止服务:     docker compose down"
log_info "    重启服务:     docker compose restart"
log_info "    查看状态:     docker compose ps"
log_info "=========================================="
