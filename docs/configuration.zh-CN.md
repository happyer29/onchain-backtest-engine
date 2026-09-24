# 配置

**语言：** [English](configuration.md) · [Русский](configuration.ru.md) · 简体中文

项目采用本地 TOML 配置。先复制示例文件，再在未跟踪的本地文件中修改：

```bash
cp configs/local-16gb.toml configs/local.toml
```

`configs/local.toml` 应设置本机数据根目录、资源预算以及 Control API 的
回环地址和端口。不要将数据根目录指向仓库、网络挂载或 Windows 的
`/mnt/c`/`/mnt/d`。已生成的工件、临时文件和日志不应提交到 Git。

外部 ClickHouse 仅可用于有界、只读的数据准备与检查。连接信息、能力声明、
网络身份和请求区间必须与计划严格匹配；静态声明不能自行证明来源完整性。
凭据应来自环境变量、钥匙串或本地密钥提供者，绝不能写入受版本控制的
TOML、网页或命令输出。Web UI 和 API 仅限本机/同源访问。

具体 TOML 字段、来源映射和故障代码以[英文完整配置手册](configuration.md)
为准。更改来源语义或数据范围之后，请重新生成并验证相应工件，不要复用
不匹配的旧结果。
