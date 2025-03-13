import json
import time
import os
import logging
from typing import List, Dict, Any
from nonebot import get_driver
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, GroupMessageEvent
import nonebot_plugin_localstore as store
from .config import get_plugin_config
import traceback
import asyncio

# 初始化日志记录器
logger = logging.getLogger("nonebot.plugin.whoasked")

class MessageRecorder:
    def __init__(self):
        # 使用异步锁保证线程安全
        self._lock = asyncio.Lock()
        try:
            # 获取全局配置
            self.config = get_driver().config
            # 使用 localstore 插件获取数据存储目录
            self.data_dir = store.get_data_dir("whoasked")
            # 创建数据目录（如果不存在）
            os.makedirs(self.data_dir, exist_ok=True)
            # 消息记录文件路径
            self.message_file = os.path.join(self.data_dir, "message_records.json")
            # 加载已有消息记录
            self.messages = self._load_messages()
            logger.info(f"消息记录器初始化成功，数据目录：{self.data_dir}")
        except Exception as e:
            logger.error(f"消息记录器初始化失败: {e}")
            raise
    
    def _load_messages(self) -> Dict[str, List[Dict[str, Any]]]:
        """从文件加载消息记录"""
        # 如果文件不存在，返回空字典
        if not os.path.exists(self.message_file):
            logger.info("未找到历史消息记录，创建新文件")
            return {}
            
        try:
            # 读取并解析 JSON 文件
            with open(self.message_file, "r", encoding="utf-8") as f:
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
            with open(self.message_file, "w", encoding="utf-8") as f:
                json.dump(self.messages, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存消息记录文件失败: {e}")
    
    async def record_message(self, bot: Bot, event: MessageEvent):
        """记录新消息"""
        async with self._lock:  # 使用锁保证线程安全
            try:
                at_list = []  # 被@的用户列表
                is_reply = False  # 是否是回复消息
                reply_user_id = None  # 被回复的用户ID
                
                # 获取消息内容
                message = event.get_message()
                if not message:
                    return
                
                # 如果是群消息，获取群ID
                group_id = str(event.group_id) if isinstance(event, GroupMessageEvent) else None
                
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
                    
                    # 将被引用消息也记录下来
                    reply_message_info = {
                        "time": int(time.time()),
                        "user_id": str(reply_msg.sender.user_id),
                        "raw_message": str(reply_msg.message),
                        "at_list": [],
                        "is_reply": False,
                        "reply_user_id": None,
                        "sender_name": reply_msg.sender.card or reply_msg.sender.nickname,
                        "group_id": group_id
                    }
                    self._record_for_users([], None, reply_message_info)
                
                # 记录当前消息
                message_info = {
                    "time": int(time.time()),
                    "user_id": str(event.get_user_id()),
                    "raw_message": str(message),
                    "at_list": at_list,
                    "is_reply": is_reply,
                    "reply_user_id": reply_user_id,
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
        # 计算过期时间
        expire_time = int(time.time()) - get_plugin_config(get_driver().config).whoasked_storage_days * 86400
        # 遍历所有用户的消息记录
        for user_id in list(self.messages.keys()):
            # 过滤掉过期消息
            self.messages[user_id] = [msg for msg in self.messages[user_id] if msg["time"] > expire_time]
            # 如果用户没有消息记录，删除该用户
            if not self.messages[user_id]:
                del self.messages[user_id]
    
    async def get_at_messages(self, user_id: str) -> List[Dict[str, Any]]:
        """获取指定用户的@消息"""
        if user_id not in self.messages:
            return []
        
        # 获取配置的最大消息数量
        max_messages = get_plugin_config(get_driver().config).whoasked_max_messages
        # 返回按时间排序的最新消息
        return sorted(self.messages[user_id], key=lambda x: x["time"], reverse=True)[:max_messages]

    async def _save_messages_async(self):
        """异步保存消息"""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._save_messages)