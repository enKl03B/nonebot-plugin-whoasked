from typing import Any, Optional
from pydantic import BaseModel, Field
from pydantic import __version__ as pydantic_version
from nonebot import get_plugin_config, logger
from nonebot.compat import field_validator

# 判断 Pydantic 版本
PYDANTIC_V2 = pydantic_version.startswith("2")

class Config(BaseModel):
    """插件配置类"""
    
    if PYDANTIC_V2:
        model_config = {"extra": "ignore"}  # V2 配置方式
    else:
        class Config:
            extra = "ignore"  # V1 配置方式
    
    whoasked_max_messages: int = Field(
        default=20,
        description="最大返回消息数量",
        gt=0,
        le=100
    )
    
    whoasked_storage_days: int = Field(
        default=3,
        description="消息存储天数",
        gt=0,
        le=30
    )

    @field_validator("whoasked_max_messages")
    def validate_max_messages(cls, v):
        if v < 1:
            raise ValueError("最大消息数量必须大于0")
        return v

    @field_validator("whoasked_storage_days")
    def validate_storage_days(cls, v):
        if v < 1:
            raise ValueError("存储天数必须大于0")
        return v

# 删除 _config_cache 和 get_plugin_config 函数
# 直接使用 get_plugin_config 获取配置
plugin_config = get_plugin_config(Config)