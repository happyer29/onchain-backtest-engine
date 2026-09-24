# CLI 命令概览

**语言：** [English](cli-reference.md) · [Русский](cli-reference.ru.md) · 简体中文

运行 `backtest --help` 查看当前所有命令，运行
`backtest <command> --help` 查看精确参数。CLI 与本机 API/Web UI 通过相同的
应用契约操作，耗时任务进入隔离的任务进程。

| 用途 | 主要命令 |
| --- | --- |
| 来源与数据 | `inspect-source`、`plan-dataset`、`prepare-dataset` |
| 钱包研究 | `research prepare`、`research analyze`、`research show`、`research rows` |
| 重放 | `compile-replay`、`compile-delivery-schedule` |
| 策略执行 | `resolve-run`、`run`、`sweep` |
| 结果 | `list-runs`、`show-run-summary`、`list-roundtrips` |
| 工件与运维 | `verify-artifact`、`show-lineage`、固定/回收、备份与恢复验证 |
| 本机界面 | `serve` |

常见顺序如下：

```text
inspect-source → plan-dataset → prepare-dataset → resolve-run → run
               → show-run-summary → verify-artifact
```

钱包研究是观察性流程，与策略执行和模型训练分离。不要把研究结果直接当作
可执行输入。单独的[合成 ML 示例](ml-baseline.zh-CN.md)使用
`python -m backtest.examples.ml_baseline`，不需要数据源或任务队列。

完整的命令参数、JSON 示例和错误语义以[英文 CLI 手册](cli-reference.md)为准。
