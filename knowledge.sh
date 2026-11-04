#!/bin/sh
# 安装控制器后使用；所有动作提交到与 Web 相同的持久任务队列。
set -eu
case "${1:-}" in
  build|up|stop|status|logs|backfill|sync|retry) ;;
  *) echo '用法：./knowledge.sh build|up|stop|status|logs|sync|backfill 起始日期 结束日期 [--binding-code 计划编码]|retry --operation-id 任务ID' >&2; exit 2 ;;
esac
project=${KNOWLEDGE_MAIN_PROJECT:-enterprise_agent}
controller=$(docker ps --filter "label=com.docker.compose.project=$project" --filter 'label=com.docker.compose.service=knowledge-ops-controller' --format '{{.ID}}')
case "$controller" in
  ''|*'
'*) echo '未找到唯一运行的知识运维执行器，请先按 knowledge/README.md 安装；可用 KNOWLEDGE_MAIN_PROJECT 指定主项目。' >&2; exit 1 ;;
esac
exec docker exec "$controller" python -m app.cli.knowledge_ops "$@"
