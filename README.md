# nonebot-plugin-whoasked

一个用于查询谁@了你或引用了你的消息的NoneBot2插件

## 功能

- 记录群聊中的@消息和引用消息
- 通过命令查询谁@了你或引用了你的消息
- 支持配置最大返回消息数量和消息存储天数

## 安装

使用nb-cli安装：

```bash
nb plugin install nonebot-plugin-whoasked
```

## 配置

在.env文件中添加以下配置（可选）：

```bash
# 最大返回消息数量，默认20
WHOASKED_MAX_MESSAGES=20

# 消息存储天数，默认3
WHOASKED_STORAGE_DAYS=3
```

## 使用

在群聊中发送以下命令：
> [!WARNING]
> 此处示例中的"/"为 nb 默认的命令开始标志，若您设置了另外的标志，则请使用您设置的标志作为命令的开头

- /谁问我了

## 注意事项
- 该插件代码基本由AI完成，如有更好的改进建议欢迎提交pr
- 目前仅使用了`OnebotV11适配器+Napcat`，在Linux系统下测试通过，如有兼容性问题/其他适配器的运行情况欢迎提交issue


## 许可证

MIT