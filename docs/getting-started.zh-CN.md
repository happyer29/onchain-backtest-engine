# 快速入门

**语言：** [English](getting-started.md) · [Русский](getting-started.ru.md) · 简体中文

## 安装

使用 Python 3.13 和 `uv`。Linux x86_64、macOS arm64 可原生运行；Windows
11 x86_64 应先安装 WSL2/Ubuntu，并将仓库与数据目录放在 WSL 的 Linux 文件
系统中，而不是 `/mnt/c` 或 `/mnt/d`。

```bash
uv sync --all-groups --frozen
source .venv/bin/activate
backtest --help
```

启动本机 Web UI：

```bash
cp configs/local-16gb.toml configs/local.toml
backtest serve --config configs/local.toml
```

数据准备、策略、任务队列、结果、ML 和研究页面的详细说明见
[Web UI 图文指南](ui-guide.zh-CN.md)。

启动前请检查 `configs/local.toml` 中的数据目录、控制端口和资源预算。
不要提交本地配置或凭据。Web UI 通过本机 `127.0.0.1` 访问；没有配置真实
数据源时仍可查看界面，但不能执行真实数据准备。

## 第一次回测

使用真实索引器之前，必须提供[配置指南](configuration.zh-CN.md)所述的
只读能力声明和密钥。按以下顺序操作，每个命令的精确参数以
`backtest <command> --help` 为准：

```text
inspect-source → plan-dataset → prepare-dataset → compile-replay（可选）
               → resolve-run → run → show-run-summary → verify-artifact
```

数据准备从指定的半开区间读取。回测只能读取已验证的本地快照；缺口、不匹配、
不可证明的来源性质或超出资源预算都应明确失败。研究快照不能直接替代可执行
数据集。浏览器不接收 SQL、可执行代码、文件系统路径或凭据。

如需先体验 ML，请运行完全离线的[基础示例](ml-baseline.zh-CN.md)：

```bash
python -m backtest.examples.ml_baseline
```

如需在 Web UI 中对同一个 ReplayPack 训练并预测，请在 **Models and features**
中依次生成 FeatureSet、Universe、LabelSet、模型和 ModelSchedule。第一个
`eligible_from` 不得早于模型可用时间，之后的决策区间必须全部覆盖。在
**Predictions** 中选择“第一模型之前不预测”以生成 PredictionSet v2。
用该工件运行 FirstSwap 时，选择 `FROZEN`、相同的前缀规则；如需跳过早期
无预测行，将“缺失预测”设为 `NULL`。模型仍绑定训练时的原始 FeatureSet；
中间或末尾的调度缺口会报错。

这段[俄语配音视频](assets/ml-workflow-demo-ru.mp4)用合成数据展示界面和该规则；
视频不包含真实数据源连接，也不展示完整的 UI 端 ML 作业运行。

更完整的策略输入、结果检查和故障排查步骤见[英文详细指南](getting-started.md)。
