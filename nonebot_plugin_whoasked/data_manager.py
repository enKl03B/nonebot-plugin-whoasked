import json
import time
import os
from typing import List, Dict, Any
from nonebot import get_driver, logger
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, GroupMessageEvent
from nonebot import require
from .config import plugin_config
import traceback
import asyncio
from pathlib import Path

# 加载 localstore 插件
require("nonebot_plugin_localstore")
import nonebot_plugin_localstore as store

class MessageRecorder:
    def __init__(self):
        # 使用异步锁保证线程安全
        self._lock = asyncio.Lock()
        self._shutting_down = False  # 新增关闭标志
        try:
            # 使用 get_plugin_data_dir 获取插件数据目录
            self.data_dir: Path = store.get_plugin_data_dir()
            # 创建数据目录（如果不存在）
            self.data_dir.mkdir(parents=True, exist_ok=True)
            # 消息记录文件路径
            self.message_file = self.data_dir / "message_records.json"
            # 加载已有消息记录
            self.messages = self._load_messages()
            logger.info(f"消息记录器初始化成功，数据目录：{self.data_dir}")
        except Exception as e:
            logger.error(f"消息记录器初始化失败: {e}")
            raise
    
    def _load_messages(self) -> Dict[str, List[Dict[str, Any]]]:
        """从文件加载消息记录"""
        # 如果文件不存在，返回空字典
        if not self.message_file.exists():
            logger.info("未找到历史消息记录，创建新文件")
            return {}
            
        try:
            # 读取并解析 JSON 文件
            with self.message_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
                logger.info(f"成功加载历史消息记录，共 {sum(len(v) for v in data.values())} 条消息")
                return data
        except Exception as e:
            logger.error(f"加载消息记录文件失败: {e}")
            return {}
    
    def _save_messages(self):
        """将消息记录保存到文件"""
        # 确保目录存在
        os.makedirs(self.data_dir, exist_ok=True)
        try:
            # 将消息记录写入文件
            with self.message_file.open("w", encoding="utf-8") as f:
                json.dump(self.messages, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存消息记录文件失败: {e}")
    
    async def record_message(self, bot: Bot, event: MessageEvent):
        """记录新消息"""
        if self._shutting_down:  # 如果正在关闭，则不再记录
             logger.debug("正在关闭，跳过消息记录")
             return

        async with self._lock:  # 使用锁保证线程安全
            try:
                at_list = []  # 被@的用户列表
                is_reply = False  # 是否是回复消息
                reply_user_id = None  # 被回复的用户ID
                replied_message_segments = None # 初始化被引用消息段列表
                
                # 获取消息内容
                message = event.get_message()
                if not message:
                    return
                
                # 处理@消息
                for seg in message:
                    if seg.type == "at":
                        at_user_id = str(seg.data.get("qq", ""))
                        if at_user_id:  # 确保@的用户ID有效
                            at_list.append(at_user_id)
                
                # 处理引用消息
                if hasattr(event, "reply") and event.reply:  # 检查是否有引用消息
                    reply_msg = event.reply
                    is_reply = True
                    reply_user_id = str(reply_msg.sender.user_id)
                    # 将 Message 对象转换为可序列化的字典列表
                    replied_message_segments = [{'type': seg.type, 'data': seg.data} for seg in reply_msg.message]
                
                # 优化：检查消息是否包含@或引用
                if not at_list and not is_reply:
                    # logger.trace("消息既不包含@也不是回复，跳过记录") # 可以取消注释以进行调试
                    return # 如果消息无关，则直接返回，不记录

                # --- 如果消息相关，则继续记录 --- 
                group_id = str(event.group_id) if isinstance(event, GroupMessageEvent) else None
                
                # 记录当前消息
                message_info = {
                    "time": int(time.time()),
                    "user_id": str(event.get_user_id()),
                    "raw_message": str(message),
                    "at_list": at_list,
                    "is_reply": is_reply,
                    "reply_user_id": reply_user_id,
                    "replied_message_segments": replied_message_segments, # 新增字段
                    "group_id": group_id,
                    "sender_name": event.sender.card or event.sender.nickname if isinstance(event, GroupMessageEvent) else event.sender.nickname
                }
                
                # 记录消息给相关用户
                self._record_for_users(at_list, reply_user_id, message_info)
                # 异步保存消息
                await self._save_messages_async()
            except Exception as e:
                logger.error(f"记录消息时出错: {e}")
                logger.error(traceback.format_exc())
    
    def _record_for_users(self, at_list: List[str], reply_user_id: str, message_info: Dict[str, Any]):
        """将消息记录给相关用户"""
        # 记录给被@的用户
        for at_user_id in at_list:
            self.messages.setdefault(at_user_id, []).append(message_info)
        
        # 记录给被回复的用户
        if reply_user_id:
            self.messages.setdefault(reply_user_id, []).append(message_info)
        
        # 清理过期消息
        self._clean_old_messages()
    
    def _clean_old_messages(self):
        """清理过期消息"""
        if not hasattr(plugin_config, 'whoasked_storage_days'):  # 配置检查
            logger.warning("未找到有效存储天数配置，使用默认值3天")
            storage_days = 3
        else:
            storage_days = plugin_config.whoasked_storage_days
            
        expire_time = int(time.time()) - storage_days * 86400
        
        # 使用字典推导式优化清理逻辑
        self.messages = {
            user_id: [msg for msg in msgs if msg["time"] > expire_time]
            for user_id, msgs in self.messages.items()
            if msgs and any(msg["time"] > expire_time for msg in msgs)
        }
    
    async def get_at_messages(self, user_id: str) -> List[Dict[str, Any]]:
        """获取指定用户的@消息"""
        if user_id not in self.messages:
            return []
        
        # 获取配置的最大消息数量
        max_messages = plugin_config.whoasked_max_messages
        # 返回按时间排序的最新消息
        return sorted(self.messages[user_id], key=lambda x: x["time"], reverse=True)[:max_messages]

    async def _save_messages_async(self):
        """异步保存消息"""
        await asyncio.to_thread(self._save_messages)

    async def shutdown(self):
        """执行关闭前的清理操作"""
        if self._shutting_down:
            return
        logger.debug("开始关闭 MessageRecorder，执行最后一次保存...")
        self._shutting_down = True
        async with self._lock:  # 获取锁，确保没有其他记录操作在进行
            try:
                self._save_messages()  # 直接调用同步保存方法
                logger.info("MessageRecorder 最后一次保存完成。")
            except Exception as e:
                logger.error(f"关闭 MessageRecorder 时保存消息失败: {e}")
                logger.error(traceback.format_exc())