#!/usr/bin/env bash
# Interactive tour of the OPC example. Stage-aware: browsing the prebuilt library needs
# no API key; asking questions and recompiling do.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "已从 .env.example 生成 .env。无 key 也能先浏览；要问答/重编译时再填 OPENROUTER_API_KEY。"
fi

echo ""
echo "OPC 示例——一个用 scaffold 建出来的完整知识库项目"
echo "  [1] 开箱浏览：起栈 + 恢复预编译库 + 打开 Web（不需要 API key）"
echo "  [2] 问一问：对预编译库提问（需要 .env 里有 key）"
echo "  [3] 自己重编译：改 contract.md / 模型参数后，从材料重新编译（需要 key，花真金白银）"
echo "  [q] 退出"
read -r -p "选择: " choice

case "$choice" in
  1)
    ./app.py up
    docker compose -f docker-compose.yml --profile web up -d --build --wait api web
    ./bootstrap.py
    echo ""
    echo "打开 http://127.0.0.1:${PNEUMA_APP_WEB_PORT:-24173} ——"
    echo "文库/原料/历史随便翻；问答要 key（菜单 2）。"
    ;;
  2)
    read -r -p "问题: " q
    ./app.py ask "$q" --sources
    ;;
  3)
    echo "将清空本地库并用你的参数重新编译全部材料（预编译库可随时用菜单 1 恢复）。"
    read -r -p "确认? [y/N] " ok
    [ "$ok" = "y" ] || exit 0
    ./app.py down --volumes && rm -rf data/
    ./app.py up
    ./app.py init
    ./app.py ingest my-data
    ./app.py compile
    ./app.py glance
    ;;
  *) exit 0 ;;
esac
