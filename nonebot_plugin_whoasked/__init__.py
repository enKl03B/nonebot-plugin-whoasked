import traceback
import time
import logging
from functools import wraps
from typing import Dict, List, Set, Any, Union, Optional, Callable, Awaitable

from nonebot import get_driver, on_command, on_message, on_keyword
from nonebot.adapters.onebot.v11 import Bot, MessageSegment, GroupMessageEvent, MessageEvent, Message
from nonebot.rule import Rule, to_me
from nonebot.plugin import PluginMetadata
from nonebot import require
from nonebot.matcher import Matcher
from nonebot.exception import FinishedException

# 初始化日志记录器
logger = logging.getLogger("nonebot.plugin.whoasked")

# 先导入依赖
require("nonebot_plugin_localstore")
from .config import Config, get_plugin_config
from .data_manager import MessageRecorder

# 然后定义插件元数据
__plugin_meta__ = PluginMetadata(
    name="whoasked",
    description="查询谁@了你或引用了你的消息",
    usage="发送 谁问我了/谁at了我/谁@了我 即可查询",
    type="application",
    homepage="https://github.com/enKl03B/nonebot-plugin-whoasked",
    supported_adapters={"~onebot.v11"},
    config=Config,
    extra={
        "unique_name": "whoasked",
        "example": "谁问我了",
        "author": "enKl03B",
        "version": "0.1.0",
        "repository": "https://github.com/enKl03B/nonebot-plugin-whoasked"
    }
)

# 全局配置
global_config = get_driver().config
plugin_config = get_plugin_config(global_config)

# 修改消息记录器初始化
message_recorder = None

async def init_message_recorder():
    global message_recorder
    message_recorder = MessageRecorder()
    logger.info("消息记录器初始化完成")

# 在插件加载时初始化
from nonebot import get_driver
driver = get_driver()

@driver.on_startup
async def _():
    await init_message_recorder()

# 关键词集合
QUERY_KEYWORDS = {"谁问我了"}

# 修改错误处理装饰器
def catch_exception(func: Callable) -> Callable:
    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except FinishedException:
            raise
        except Exception as e:
            logger.error(f"函数 {func.__name__} 执行出错: {str(e)}")
            logger.error(traceback.format_exc())
            if len(args) > 0 and hasattr(args[0], "finish"):
                try:
                    await args[0].finish(f"处理命令时出错: {str(e)[:100]}")
                except FinishedException:
                    raise
    return wrapper

# 修改消息记录器注册
record_msg = on_message(priority=1, block=False)
@record_msg.handle()
async def _(bot: Bot, event: MessageEvent):
    """记录所有消息"""
    try:
        await message_recorder.record_message(bot, event)
    except Exception as e:
        logger.error(f"记录消息失败: {e}")

# 修改命令处理器
who_at_me = on_command("谁问我了", priority=50, block=True)
@who_at_me.handle()
@catch_exception
async def handle_who_at_me(bot: Bot, event: GroupMessageEvent):
    """处理查询@消息的指令"""
    if message_recorder is None:
        await who_at_me.finish("消息记录器未初始化，请稍后再试")
        return
        
    logger.info(f"收到谁@我命令，来自用户 {event.user_id}，群 {event.group_id}")
    await process_query(bot, event, who_at_me)

# 修改查询处理函数
async def process_query(bot: Bot, event: GroupMessageEvent, matcher: Matcher):
    """处理查询@消息的请求"""
    user_id = str(event.user_id)
    current_group_id = str(event.group_id)
    
    try:
        # 添加性能监控
        start_time = time.time()
        
        messages = await message_recorder.get_at_messages(user_id)
        
        if not messages:
            await matcher.finish("最近没人问你")
            return
        
        # 使用生成器表达式优化内存使用
        filtered_messages = (
            msg for msg in messages
            if msg.get("group_id") == current_group_id and
               (user_id in msg.get("at_list", []) or
               (msg.get("is_reply", False) and msg.get("reply_user_id") == user_id))
        )
        
        # 转换为列表并检查是否为空
        filtered_messages = list(filtered_messages)
        if not filtered_messages:
            await matcher.finish("最近在本群没有人问你")
            return
        
        # 构建转发消息
        forward_messages = [{
            "type": "node",
            "data": {
                "name": event.sender.card or event.sender.nickname,
                "uin": user_id,
                "content": str(event.get_message())
            }
        }]
        
        # 使用列表推导式优化
        forward_messages.extend({
            "type": "node",
            "data": {
                "name": msg_data["sender_name"],
                "uin": msg_data["user_id"],
                "content": f"【{'引用了你的消息' if msg_data.get('is_reply', False) else '@了你'}】\n{msg_data['raw_message']}"
            }
        } for msg_data in filtered_messages)
        
        # 添加性能日志
        logger.info(f"处理查询请求耗时: {time.time() - start_time:.2f}秒")
        
        await bot.call_api(
            "send_group_forward_msg",
            group_id=event.group_id,
            messages=forward_messages
        )
    except FinishedException:
        raise
    except Exception as e:
        logger.error(f"处理查询请求失败: {e}")
        logger.error(traceback.format_exc())
        try:
            await matcher.finish("查询失败，请稍后再试")
        except FinishedException:
            raise