import traceback
import time
from functools import wraps
from typing import Dict, List, Set, Any, Union, Optional, Callable, Awaitable
import asyncio
import sys # 导入 sys 模块

from nonebot import get_driver, on_command, on_message, on_keyword
import nonebot.log
from nonebot.log import default_filter as original_default_filter, logger_id, default_format # 导入并重命名原始过滤器，导入 logger_id 和 default_format
from nonebot.adapters.onebot.v11 import Bot, MessageSegment, GroupMessageEvent, MessageEvent, Message
from nonebot.rule import Rule, to_me
from nonebot.plugin import PluginMetadata
from nonebot import require, logger
from nonebot.matcher import Matcher
from nonebot.exception import FinishedException


# 先导入依赖
require("nonebot_plugin_localstore")
from .config import Config, get_plugin_config
from .data_manager import MessageRecorder

# 然后定义插件元数据
__plugin_meta__ = PluginMetadata(
    name="whoasked",
    description="查询谁@了你或引用了你的消息",
    usage="发送 谁问我了 即可查询",
    type="application",
    homepage="https://github.com/enKl03B/nonebot-plugin-whoasked",
    supported_adapters={"~onebot.v11"},
    config=Config,
    extra={
        "unique_name": "whoasked",
        "example": "谁问我了",
        "author": "enKl03B",
        "version": "0.2.2",
        "repository": "https://github.com/enKl03B/nonebot-plugin-whoasked"
    }
)

# --- 全局关闭状态标志 ---
_is_shutting_down = False

# --- 定义新的组合过滤器 ---
def custom_whoasked_filter(record):
    """日志过滤"""
    # 应用原始的 NoneBot 默认过滤器
    if not original_default_filter(record):
        return False

    log_name = record.get("name")
    log_level_name = record.get("level").name
    log_message = record.get("message", "")

    # 条件 1: 过滤 record_msg 的 SUCCESS 完成日志 
    if log_name == "nonebot" and log_level_name == "SUCCESS":
        is_record_msg_matcher = "Matcher(type='message', module='nonebot_plugin_whoasked'" in log_message and "record_msg" in log_message
        is_completion_log = "running complete" in log_message
        if is_record_msg_matcher and is_completion_log:
            return False # 过滤掉这条日志

    # 条件 2: 过滤本插件内所有 Matcher 的 INFO 完成日志 
    if log_name == "nonebot" and log_level_name == "INFO":
        # 检查是否是 "running complete" 日志
        is_whoasked_matcher_complete = "Matcher(" in log_message and "module=nonebot_plugin_whoasked" in log_message and "running complete" in log_message
        if is_whoasked_matcher_complete:
            logger.debug(f"条件2满足，INFO完成日志: {log_message}。将被过滤。")
            return False # 过滤掉这条日志
        
        # 条件 3: 过滤本插件内所有 Matcher 的 "Event will be handled" 日志
        is_whoasked_matcher_handle = log_message.startswith("Event will be handled by Matcher(") and "module=nonebot_plugin_whoasked" in log_message
        if is_whoasked_matcher_handle:
            logger.debug(f"条件3满足，INFO处理日志: {log_message}。将被过滤。")
            return False # 过滤掉这条日志

    # 如果以上条件都不满足，则保留该日志
    return True

# 全局配置
global_config = get_driver().config

# 修改消息记录器初始化
message_recorder = None

async def init_message_recorder():
    global message_recorder
    if message_recorder is None: # 避免重复初始化
        message_recorder = MessageRecorder()

# --- 定义关闭感知的 Rule ---
async def shutdown_aware_rule() -> bool:
    """如果程序正在关闭，则返回 False"""
    return not _is_shutting_down

# 在插件加载时初始化
from nonebot import get_driver
driver = get_driver()

@driver.on_startup
async def _startup():
    """插件启动时的操作"""
    global _is_shutting_down
    _is_shutting_down = False # 确保启动时标志为 False
    # 初始化消息记录器
    await init_message_recorder()

    # --- 应用新的过滤器 (通过替换 Handler) ---
    # 尝试移除默认 handler
    try:
        logger.remove(logger_id)
        logger.debug("已移除默认日志处理器。") # 改为 DEBUG
        # 添加新的 handler，使用自定义过滤器和默认格式
        logger.add(
            sys.stdout, # 输出到控制台
            level=0, # level 设置为 0，让自定义 filter 完全控制
            diagnose=False, # 根据需要设置
            filter=custom_whoasked_filter, # 使用我们的过滤器
            format=default_format # 使用 NoneBot 的默认格式
        )
    except ValueError:
        # 如果 logger_id 已经被移除，这里会触发 ValueError
        logger.warning("默认日志处理器已被移除或未找到。")



@driver.on_shutdown
async def shutdown_hook():
    """在驱动器关闭时调用"""
    global _is_shutting_down
    logger.debug("检测到关闭信号，设置关闭标志...")
    _is_shutting_down = True # 立即设置关闭标志

    # 等待一小段时间，让事件循环有机会处理完当前正在执行的任务
    # 并让 Rule 生效，阻止新的 Matcher 运行
    await asyncio.sleep(0.1) 

    if message_recorder:
        await message_recorder.shutdown() # 然后再执行数据保存等清理操作

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

# --- 修改消息记录器注册，加入 Rule ---
record_msg = on_message(rule=shutdown_aware_rule, priority=1, block=False) # 添加 rule
@record_msg.handle() # 现在日志中看到的行号可能是这里
async def _handle_record_msg(bot: Bot, event: MessageEvent):
    """记录所有消息"""
    # 无需在此处再次检查 _is_shutting_down，因为 Rule 已经阻止了它
    if message_recorder is None:
        logger.warning("尝试记录消息时，MessageRecorder 未初始化。")
        return
    try:
        # 注意：即使 Rule 阻止了新的匹配，如果 handle 在 Rule 检查前已被调用，
        # 这里的 shutdown 检查仍然是有意义的，防止并发问题。
        if message_recorder._shutting_down:
             logger.debug("MessageRecorder 正在关闭，跳过内部记录逻辑")
             return
        await message_recorder.record_message(bot, event)
    except Exception as e:
        logger.error(f"记录消息失败: {e}")
        logger.error(traceback.format_exc())

# 修改命令处理器
who_at_me = on_command("谁问我了", priority=50, block=True)
@who_at_me.handle()
@catch_exception
async def handle_who_at_me(bot: Bot, event: GroupMessageEvent):
    """处理查询@消息的指令"""
    if message_recorder is None:
        await who_at_me.finish("消息记录器未初始化，请稍后再试")
        return
        
    await process_query(bot, event, who_at_me)

# 修改查询处理函数
async def process_query(bot: Bot, event: GroupMessageEvent, matcher: Matcher):
    """处理查询@消息的请求"""
    user_id = str(event.user_id)
    current_group_id = str(event.group_id)
    
    try:
        async with asyncio.timeout(10):  # 增加10秒超时控制
            user_id = str(event.user_id)
            current_group_id = str(event.group_id)
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
        
        forward_messages = []

        # 定义格式化函数
        def format_message_content(msg_data):
            msg_time = msg_data["time"]
            time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(msg_time))
            time_passed = int(time.time()) - msg_time
            if time_passed < 60:
                elapsed = f"{time_passed}秒前"
            elif time_passed < 3600:
                elapsed = f"{time_passed//60}分钟前"
            elif time_passed < 86400:
                elapsed = f"{time_passed//3600}小时前"
            else:
                elapsed = f"{time_passed//86400}天前"

            if msg_data.get('is_reply', False):
                replied_segments_data = msg_data.get('replied_message_segments') # 获取可能存在的字段
                replied_message_content = Message() # 初始化为空 Message
                
                # 检查是否为新格式数据 (包含有效的 segments 列表)
                if replied_segments_data and isinstance(replied_segments_data, list):
                    try:
                        # 手动从字典列表构建 MessageSegment 并添加到 replied_message_content
                        for seg_data in replied_segments_data:
                            # 创建单个 MessageSegment
                            try:
                                seg = MessageSegment(type=seg_data['type'], data=seg_data['data'])
                            except Exception as seg_e:
                                logger.warning(f"创建消息段失败: {seg_e} 数据: {seg_data}")
                                continue # 跳过无法创建的段
                                
                            # 处理不同类型的消息段
                            if seg.type == "text":
                                replied_message_content.append(seg)
                            elif seg.type == "image":
                                # 将图片显示为文字标识
                                replied_message_content.append(MessageSegment.text("[图片]"))
                            # 添加对其他类型消息段的处理
                            else:
                                # 定义类型到中文名称的映射
                                type_mapping = {
                                    "face": "表情",
                                    "record": "语音",
                                    "video": "视频",
                                    "at": "@",
                                    "rps": "猜拳",
                                    "dice": "骰子",
                                    "share": "链接分享",
                                    "contact": "名片",
                                    "location": "位置",
                                    "music": "音乐",
                                    "forward": "合并消息",
                                    "json": "JSON消息",
                                    "file": "文件",
                                    "markdown": "Markdown",
                                    "lightapp": "小程序",
                                    "mface": "大表情"
                                }
                                # 查找中文名，找不到则使用原始类型或通用提示
                                display_name = type_mapping.get(seg.type, seg.type.capitalize())
                                replied_message_content.append(MessageSegment.text(f"[{display_name}]"))
                    except Exception as e:
                        logger.error(f"反序列化被引用消息失败: {e}")
                        # 清空可能已部分添加的内容，并添加错误提示
                        replied_message_content.clear()
                        replied_message_content.append(MessageSegment.text("[无法加载被引用消息]")) 
                else:
                    # 处理旧格式数据或加载失败的情况
                    replied_message_content.append(MessageSegment.text("[旧格式数据，无法加载被引用消息内容]"))

                # 构建新的引用消息格式
                content_msg = Message()
                content_msg.append(MessageSegment.text("【引用了你的消息】\n"))
                content_msg.append(MessageSegment.text(f"{msg_data['raw_message']}\n"))
                content_msg.append(MessageSegment.text("━━━━━━━━━━━\n"))
                content_msg.append(MessageSegment.text("被引用的消息：\n"))
                content_msg.extend(replied_message_content) # 添加处理后的被引用消息内容
                content_msg.append(MessageSegment.text("\n━━━━━━━━━━━\n"))
                content_msg.append(MessageSegment.text(f"📅消息发送时间： {time_str} ({elapsed})"))
                return content_msg
            else: # @消息保持原格式
                 content = f"""
【@了你】
{msg_data['raw_message']}
━━━━━━━━━━━
📅消息发送时间： {time_str} ({elapsed})
"""
                 # 返回 Message 对象，而不是单个 MessageSegment
                 return Message(MessageSegment.text(content))

        # 构建转发消息节点
        for msg_data in filtered_messages:
            node_content_message = format_message_content(msg_data) # 返回 Message 对象
            # 将 Message 对象显式序列化为 API 需要的列表格式
            node_content_serializable = [{'type': seg.type, 'data': seg.data} for seg in node_content_message]
            forward_messages.append({
                "type": "node",
                "data": {
                    "nickname": msg_data["sender_name"],
                    "user_id": msg_data["user_id"],
                    "content": node_content_serializable # 使用序列化后的列表
                }
            })
        
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