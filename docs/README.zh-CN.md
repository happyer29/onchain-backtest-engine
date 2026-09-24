# On-Chain Backtest Engine

**语言：** [English](../README.md) · [Русский](README.ru.md) · 简体中文

这是一个在单台主机上运行的链上研究与回测项目。它以只读、有限范围的方式
获取外部数据，生成可验证的本地不可变工件，然后在事件循环中不依赖 SQL
或网络访问地重放策略。本项目处于 alpha 阶段，不是实盘交易系统，也不构成
投资建议。

## 包含的工具

| 工具 | 用途 |
| --- | --- |
| 数据准备 | 检查数据源、规划有限范围的数据集并生成 Parquet 快照。 |
| 重放与策略 | 使用参考引擎运行 Sniping、Copy Buy 和 FirstSwap。 |
| 链上研究 | 从经过验证的本地工件查看签名钱包活动和共同购买关系。 |
| ML 基础设施 | 构建时间点可用的特征、标签和样本集合，运行现有的安全精确模型流程。 |
| 运维工具 | 管理持久化任务队列、检查结果与工件来源、固定和回收工件、验证备份。 |
| 用户界面 | 通过统一的应用契约使用 CLI、本机 Control API 和 React Web UI。 |

独立的[基础 ML 示例](ml-baseline.zh-CN.md)只使用合成数据、一种逻辑回归
模型和四个简单特征。它不是可投入执行的交易策略或预测质量证明。
精确模型也可以用同一个 ReplayPack 的早期行训练，再对后续行预测：构建
PredictionSet 时选择“第一模型之前不预测”，并在 FirstSwap 运行中选择相同的
推理规则。早期行保持无预测；第一模型之后的调度缺口仍会报错。

可观看[项目概览（99 秒，俄语配音）](assets/project-overview-demo-ru.mp4)和
[ML 流程视频（67 秒，俄语配音）](assets/ml-workflow-demo-ru.mp4)。
两段视频均使用合成数据；不包含真实数据源连接或完整的 UI 端 ML 作业运行。

## 快速开始

需要 Python 3.13 和 [`uv`](https://docs.astral.sh/uv/)。Linux x86_64 与
macOS arm64 可原生运行；Windows 11 x86_64 请使用 WSL2/Ubuntu。

```bash
uv sync --all-groups --frozen
source .venv/bin/activate
backtest --help
cp configs/local-16gb.toml configs/local.toml
backtest serve --config configs/local.toml
```

连接真实索引器之前，请配置本地数据目录、数据源能力和密钥。不要把凭据提交
到 Git。Web UI 只监听配置的 `127.0.0.1` 端口。详见[快速入门](getting-started.zh-CN.md)
和[配置指南](configuration.zh-CN.md)。

无需连接外部数据源即可运行 ML 示例：

```bash
python -m backtest.examples.ml_baseline
```

输出包括训练/测试样本量、未知及因时间边界被排除的标签，以及基本留出集
指标。所有特征只根据更早的合成事件构建。

## 工作流程

```text
inspect-source → plan-dataset → prepare-dataset → compile-replay（可选）
               → resolve-run → run / sweep → 查看并验证结果
```

`backtest research` 用于有界的钱包研究，`backtest serve` 打开本地工作区。
命令语法请运行 `backtest <command> --help`，或查看[CLI 指南](cli-reference.zh-CN.md)。

不能默认认为外部数据完整或及时。对于不支持、过期、损坏或超出资源预算的
输入，系统会明确报错。研究结论不会自动获得策略执行资格；合成结算模式也
会明确标记。精确约束以[英文架构规范](architecture-deep-dive.md)为准。

## 文档与贡献

- [中文文档索引](index.zh-CN.md)
- [Web UI 图文指南](ui-guide.zh-CN.md)
- [静态演示](demo.md)（英文）
- [贡献指南](../.github/CONTRIBUTING.md)（英文）
- [安全政策](../.github/SECURITY.md)（英文）
- [支持](SUPPORT.md)（英文）

项目使用 [MIT 许可证](../LICENSE)；第三方声明见[通知](THIRD_PARTY_NOTICES.md)。
