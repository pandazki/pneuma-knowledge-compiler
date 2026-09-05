# 在 {{PROJECT_NAME}} 中工作

这是生成的知识库应用，框架位于 `{{FRAMEWORK_REPO}}`。先读本项目 README，建立和验证
知识库时使用框架的 `scaffold/AGENT-GUIDE.zh-CN.md`；具体化契约时读
`docs/guides/compile-contract.zh-CN.md`。

- 保留原始来源及身份、时间、媒体等结构字段。未知资料保持未知；租户可以代表团队或主题，
  不一定是材料中的某个人。
- 从可运行的契约起步，按实际未来用途调整主体边界与准入。账本保留有用细节，概览忠实呈现
  当前图景。
- 分别验证来源完整性、正本忠实度和回答可用性。用 `ask --sources` 读精确证据，报告失败
  和降级，不能只列成功命令。
- 策略放入 `engine/` 并提交有意保留的状态。凭据、私人输入和运行回执不入 Git。进程环境
  可临时覆盖 engine 文件。
- 沿用用户已有授权，不要反复为可逆操作请求确认；重要决策缺少必要信息或授权时再提问。
- 不要手工改正本来改善结果。派生重建不等于重编译。测试新契约时保留原库，在新项目构建。
- 不要让 console worker 与 CLI compile/build 同时消费同一中间件队列。
- `app.py`、`start.sh`、`server.py`、`worker.py`、`docker-compose.yml` 是生成的机械层。
  应改进框架模板，再保留本项目 engine 和数据地替换机械层。

默认路径：`./start.sh` → `glance` → `ask --sources` → 检查 `data/run-reports/`。
闸门通过说明结构和出处地址通过检查，不证明主张的含义正确。
