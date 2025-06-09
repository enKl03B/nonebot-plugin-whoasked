from nonebot import get_plugin_config, logger
from nonebot.compat import BaseModel, field_validator
from pydantic import Field
from typing import Union, List, Set

class Config(BaseModel):
    """插件配置类"""
    
    whoasked_max_messages: int = Field(
        default=25,
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
    
    whoasked_keywords: Set[str] = Field(
        default={"谁问我了"},
        description="触发查询的关键词列表",
    )

    @field_validator("whoasked_keywords")
    def validate_keywords(cls, v: Union[Set[str], List[str], str]):
        if isinstance(v, str):
            v = {v.strip() for v in v.split(",") if v.strip()}
        elif isinstance(v, list):
            v = set(v)
        return v

    @field_validator("whoasked_max_messages")
    def validate_max_messages(cls, v: Union[int, str, float]):
        try:
            v = int(v) if not isinstance(v, int) else v
            if v < 1:
                raise ValueError("最大消息数量必须大于0")
            return min(v, 100)  # 确保不超过上限
        except (ValueError, TypeError):
            logger.warning(f"无效的 whoasked_max_messages 配置值: {v}, 使用默认值 25")
            return 25

    @field_validator("whoasked_storage_days")
    def validate_storage_days(cls, v: Union[int, str, float]):
        try:
            v = int(v) if not isinstance(v, int) else v
            if v < 1:
                raise ValueError("存储天数必须大于0")
            return min(v, 30)  # 确保不超过上限
        except (ValueError, TypeError):
            logger.warning(f"无效的 whoasked_storage_days 配置值: {v}, 使用默认值 3")
            return 3

plugin_config = get_plugin_config(Config)