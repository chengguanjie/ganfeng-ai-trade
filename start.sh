#!/usr/bin/env bash
# 赣丰玻纤 · 数据飞轮系统 · 启动脚本
set -e

cd "$(dirname "$0")"

PYTHON=${PYTHON:-python3}
if [ -f ".venv/bin/python" ]; then
  PYTHON=.venv/bin/python
fi

echo "🔧 初始化数据库..."
$PYTHON scripts/init_db.py

echo ""
echo "🚀 启动数据飞轮系统..."
echo "   📍 独立站:     http://127.0.0.1:5000/"
echo "   📊 管理后台:    http://127.0.0.1:5000/admin"
echo "   📦 数据源:      scripts/free_data_sources.py"
echo ""

PORT=${PORT:-5000}
exec $PYTHON app.py
