import sys
from nonebot.log import default_filter as original_default_filter, logger_id, default_format
from nonebot import logger

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

def setup_log_filter():
    """设置日志过滤器"""
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