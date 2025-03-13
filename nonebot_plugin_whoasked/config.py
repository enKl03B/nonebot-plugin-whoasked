import os
import logging
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field
from dotenv import load_dotenv

logger = logging.getLogger("nonebot.plugin.whoasked")

try:
    load_dotenv()
except Exception as e:
    logger.warning(f"加载.env文件失败: {e}")

def get_env_value(key: str, default: Any, converter: callable = str) -> Any:
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return converter(value)
    except (ValueError, TypeError) as e:
        logger.warning(f"环境变量 {key} 值转换失败: {e}")
        return default

class Config(BaseModel):
    model_config = ConfigDict(extra="ignore")
    
    whoasked_max_messages: int = Field(
        default=get_env_value("WHOASKED_MAX_MESSAGES", 20, int),
        description="最大返回消息数量",
        gt=0,
        le=100
    )
    
    whoasked_storage_days: int = Field(
        default=get_env_value("WHOASKED_STORAGE_DAYS", 3, int),
        description="消息存储天数",
        gt=0,
        le=30
    )

_config_cache: Optional[Config] = None

def get_plugin_config(driver_config: Any) -> Config:
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    
    try:
        config_dict = driver_config.model_dump() if hasattr(driver_config, "model_dump") else dict(driver_config)
        _config_cache = Config.model_validate(config_dict) if hasattr(Config, "model_validate") else Config.parse_obj(config_dict)
    except Exception as e:
        logger.error(f"获取配置时出错: {e}")
        _config_cache = Config()
    
    return _config_cache