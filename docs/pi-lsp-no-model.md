# Baseline / LSP 无模型验证

依赖 Harbor 0.24.0、Docker 和 Python 3.12。安装由 Harbor 的原生 Pi
Adapter 执行，固定 Pi 1.4.0、pi-diet-lsp 0.1.9、Pyright 1.1.413。
`pi-builds` 不参与安装或运行。

在仓库根目录执行，先通过本地环境设置 `EXPERIMENT_PROXY_CONTAINER`。
不把代理地址或密钥写入受 Git 跟踪的文件。

```bash
python prebuild_harbor_cases.py \
  benchmarks/swe-bench-verified/astropy__astropy-7166 \
  --jobs 1 --no-pin --proxy "$EXPERIMENT_PROXY_CONTAINER"

PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}" \
  harbor run -c experiments/pi-lsp-no-model.json
```

自定义 Adapter 必须可被运行 Harbor 的 Python 环境导入。示例通过
`PYTHONPATH` 提供仓库路径，不要求在 Case 容器中安装 Python Adapter。

这个安装阶段验证依次执行：

1. 原生 Pi 安装；统一使用 `/tmp/harbor-pi-agent`。
2. Baseline CLI 启动审计和 SDK 加载审计：默认活跃工具仅为
   `read`、`bash`、`edit`、`write`，没有第三方扩展或 Skill。
3. 安装 Pyright 与 LSP 插件。
4. LSP CLI/SDK 审计：增加五个 `lsp_*` 工具。
5. 在 `/tmp` 临时 Python 工程检查跨文件定义、引用、hover 和符号查询，
   再检查真实 `/testbed/astropy/utils/misc.py` 的符号与 hover。

探针把 Case 的 `testbed` Python 放到 PATH 前部，同时保存实际解释器信息。
不会更改 `/testbed` 源码，不创建模型对话，并拦截意外的模型请求。
CLI 只加载一个不注册工具的审计扩展，记录结果后退出。

结果在 `jobs/<job>/<trial>/agent/probes/` 的 `*-cli.json`、`*-sdk.json`。
Harbor 的 `install_only=true` 会跳过 Agent 求解和 Verifier，故没有 Reward；
Verifier 代理仍显式配置，不能依赖 Agent 代理自动继承。

这是同一容器中先 Baseline、后安装 LSP 的安装/能力 smoke，不能当作独立
Trial 的效果消融。SDK 通过实际注册的 Tool 实现执行受控调用；没有模型
自主选择工具，也没有验证模型 Endpoint。完整模型实验后续使用独立容器。

调试时可额外加 `--ek keep_containers=true` 保留停止的探针容器。
仅设置 `environment.delete=false` 仍会执行 Compose down，不能保留容器。
默认运行会销毁自己的容器，并终止插件残留的语言服务器子进程。

## 已完成的本机验证

2026-10-24，Job `pi-lsp-local-20261024-214626` 完成，Harbor 退出码 0，
Trial 无异常。Baseline 与 LSP 的 CLI/SDK 检查均通过，六次 LSP 受控调用
通过，模型请求数为 0，Case 受跟踪文件未变。

实测 Node 22.23.4、Agent 用户 root、Case Python 3.6.13；Pi 和 LSP 包版本
与上文固定版本一致。诊断工具目前只验证注册，未断言其诊断结果。
此次使用保留容器选项，容器在试跑结束后已停止。日志和配置在 Git 忽略的
`jobs/` 目录中；这次本机验证不能替代远端最终复验或模型求解实验。
