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

示例配置包含两个 Agent 配置。Harbor 为它们分别创建 Trial 和 Case 容器，
`n_concurrent_trials=1` 使两组串行执行；每个容器只安装自己选定的组件。

| `agents[].kwargs.components` | 安装内容 | 验证内容 |
|---|---|---|
| `[]` | Pi | Baseline CLI/SDK 审计，无 LSP 包、工具或 Skill |
| `["lsp"]` | Pi、Pyright、pi-diet-lsp | LSP CLI/SDK 审计和能力探针 |

本示例选择这两组，默认 `components=[]`；其它组件见 [扩展说明](pi-components-no-model.md)。未知组件、重复组件及非法类型
会在 Harbor Preflight 阶段报错，不创建容器。若只验证一组，保留 JSON 的
`agents` 数组中对应的一项即可。

每个 Trial 的安装验证依次执行：

1. 原生 Pi 安装；统一使用 `/tmp/harbor-pi-agent`。
2. 仅当选定 `lsp` 时，安装 Pyright 与 LSP 插件。
3. 执行所选组的 CLI/SDK 审计：Baseline 活跃工具仅为
   `read`、`bash`、`edit`、`write`；LSP 组增加五个 `lsp_*` 工具。
4. LSP 组在 `/tmp` 临时 Python 工程检查跨文件定义、引用、hover 和符号查询，
   再检查真实 `/testbed/astropy/utils/misc.py` 的符号与 hover。

探针把 Case 的 `testbed` Python 放到 PATH 前部，同时保存实际解释器信息。
不会更改 `/testbed` 源码，不创建模型对话，并拦截意外的模型请求。
CLI 只加载一个不注册工具的审计扩展，记录结果后退出。

结果在 `jobs/<job>/<trial>/agent/probes/` 的 `*-cli.json`、`*-sdk.json`。
`selection.json` 记录该 Trial 的 `components` 和组名；SDK 报告另包含实际
全局包清单。Baseline 报告检查全局未安装 Pyright 或 pi-diet-lsp。
Harbor 原生汇总可能将两个配置都显示为 `pi`，应通过 Trial 的配置及这些
报告区分两组，不将 Job 总均值作为消融结果。
Harbor 的 `install_only=true` 会跳过 Agent 求解和 Verifier，故没有 Reward；
Verifier 代理仍显式配置，不能依赖 Agent 代理自动继承。

两组使用独立容器，但目前仍是安装/能力 smoke。SDK 通过实际注册的 Tool
实现执行受控调用；没有模型自主选择工具，也没有验证模型 Endpoint，
不能据此比较任务成功率。

调试时可额外加 `--ek keep_containers=true` 保留停止的探针容器。
仅设置 `environment.delete=false` 仍会执行 Compose down，不能保留容器。
默认运行会销毁自己的容器，并终止插件残留的语言服务器子进程。

不启动容器的配置回归测试：

```bash
# 使用安装了 Harbor 的同一 Python 环境
python -m unittest discover -s tests -v
```

诊断工具目前只验证注册，未断言其诊断结果。日志和配置保存在 Git 忽略的
`jobs/` 目录中。本机验证不能替代远端最终复验或模型求解实验。

## 独立容器验证记录

2026-10-24，本机 Job `pi-components-local-20261024-220341` 完成：两个
Trial 均无异常，Harbor 退出码 0。Baseline 的 CLI/SDK 检查通过，全局未安装
Pyright；LSP 组的 CLI/SDK 和六次能力查询通过。两组均没有模型请求，Case
受跟踪文件未变。该 Job 使用默认清理策略，两个测试容器均已销毁。
