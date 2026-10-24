# Pi 组件安装与无模型验证

组件定义由 `scripts/pi_components.py` 维护，安装资源随本仓库分发，运行时
不读取 pi-builds。保留原来的 baseline/LSP 示例；扩展示例为
`experiments/pi-components-no-model.json`。

| components 名称 | 安装内容 | 当前验证范围 |
|---|---|---|
| 空数组 | Pi 1.4.0 | 默认工具、扩展/Skill 隔离 |
| lsp | pi-diet-lsp 0.1.9、Pyright 1.1.413 | 定义、引用、hover、符号 |
| ast-search | pi-ast-grep 0.4.2、ast-grep CLI 0.45.3 | 结构化搜索和源码 outline；禁用附带 Skill |
| todo | 本地维护的 Pi 官方 Todo 示例 | 无模型 list/add/toggle/clear |
| skills | diagnosing-bugs、tdd 及附属文件 | 发现、加载、引用文件完整性 |
| web-search | pi-web-access 0.44.0、search-only 配置 | 不进行测试 |
| subagent | 官方扩展和四个 Agent 定义 | 不进行测试 |
| plan | 暂不安装 | 无人值守策略确定前禁用 |

可组合组件，例如 `"components": ["lsp", "skills"]`。组件去重校验和未知组件
校验在创建容器前执行。组件安装顺序由本地注册表决定，与用户填写顺序无关。

## 测试入口

使用安装了 Harbor 0.24.0 的 Python 环境，在仓库根目录设置本地
`EXPERIMENT_PROXY_CONTAINER` 后执行。代理值不写入受跟踪文件。

```bash
python -m unittest discover -s tests -v
PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}" \
  harbor run -c experiments/pi-components-no-model.json
```

该配置创建 baseline、LSP、AST、Todo、Skills、LSP+Skills 六个独立 Trial，
默认串行运行。安装和探针统一使用 `/tmp/harbor-pi-agent`，每个容器独立；
同一 Case 为 `astropy__astropy-7166`。尚未预构建时先使用现有 prebuild 脚本。

`PiNoModelProbe` 的 Preflight 只接受允许测试的组件；即使误把 Web Search
或 Subagent 写入该配置，也会拒绝执行。测试期间不调用模型，不运行 Verifier。
保留 Verifier 的代理环境配置，供后续实际求解入口使用。

## 仅安装入口

`scripts.pi_no_model_agent:PiComponentInstaller` 复用相同注册表，供显式选择
组件的安装阶段使用。例如 Agent 的配置片段：

```json
{
  "import_path": "scripts.pi_no_model_agent:PiComponentInstaller",
  "kwargs": { "version": "1.4.0", "components": ["web-search"] }
}
```

此片段不是独立 Job；仍需上面的 `install_only=true`、Case、代理变量和
`PI_CODING_AGENT_DIR`。该入口只安装，不执行加载/能力探针，也不运行模型。
Web Search/Subagent 没有加入默认运行配置，本轮不执行它们的安装或测试。
`selection.json` 对安装完成和验证状态分别记录，未测试时保持
`verification=not_tested`，不能将安装完成解释为测试通过。

## 模型执行入口

`scripts.pi_no_model_agent:PiComponentAgent` 复用相同的组件安装逻辑，随后
交给 Harbor Pi Agent 正常执行模型请求。自定义 OpenAI 兼容端点通过
`kwargs.model_api` 选择 API 方言，并由 Harbor 的模型连接配置提供 Base URL
与 API Key 环境变量；端点和密钥应从运行时环境注入，不写入跟踪配置。无模型
探针与安装入口仍分别使用 `PiNoModelProbe` 和 `PiComponentInstaller`。

模型 Agent 默认把自定义模型上下文窗口显式设为 262,144 token，并在估算上下文
超过 90% 时自动压缩（`reserveTokens=26,214`）；压缩后保留最近 20,000 token。
可通过 `kwargs.context_window` 和 `kwargs.compaction_trigger_ratio` 覆盖窗口与
触发比例。该上下文元数据由 Pi 使用；Harbor 本身不从 vLLM 自动同步它。

## 结果与限制

结果位于每个 Trial 的 `agent/probes/`：

- `selection.json`：组件、预期资源、安装状态、验证状态和限制。
- `<variant>-cli.json`：真实 CLI 加载的活跃/注册工具。
- `<variant>-sdk.json`：实际包版本、Skill 发现结果、能力调用、模型请求数、
  源码未改动检查及运行环境。

Skill 保留上游原文和许可，未将人工确认规则改成自动执行；发现/加载成功
不证明在模型求解中能自主完成其工作流。Subagent 的模型继承、凭据、代理和
Token 统计均未验证。Web Search 的 Provider/认证/网络均未验证。来源与适配
说明见 `scripts/resources/UPSTREAM.md`。

现有 LSP diagnostics、AST scan/rewrite/debug/languages 只检查注册，不声称
全部能力都已测试。无模型 smoke 不能用于比较成功率或推理成本。

## 本机验证记录

2026-10-24，Job `pi-expanded-local-20261024-221836` 的六个独立 Trial 全部
通过，Harbor 退出码 0，Trial 无异常。开发验证使用两个 Trial 并发；公开
示例仍默认串行。测试容器已在保留日志后清理。

| 组 | 已验证内容 |
|---|---|
| baseline | CLI/SDK 默认工具与组件隔离 |
| lsp | 6 次定义、引用、hover、符号调用 |
| ast-search | 3 次结构化查询和真实源码 outline；无附带 Skill |
| todo | 7 次 list/add/toggle/clear 操作 |
| skills | 两个 Skill 被发现，5 个正文/引用文件完整，无额外工具 |
| lsp+skills | LSP 能力与两个 Skill 同时加载，6 次 LSP 调用 |

六组的模型请求数均为 0，Case 受跟踪文件未变。5 项配置/注册表回归测试
通过。Web Search/Subagent 没有出现在本次 Job 中，也未运行其安装或测试。
