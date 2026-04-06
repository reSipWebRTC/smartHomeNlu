# nlu_rule_engine.py
"""
智能家居指令规则匹配引擎（从 wordfiller 迁移）
基于热词表和模式匹配快速解析指令

版本：v2.1 - 智能处理"把...调为/到/设置"模式
"""

from __future__ import annotations

import re
import json
import hashlib
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, List, Set, Tuple, Optional, Any
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .template_matcher import TemplateMatcher

try:
    import pypinyin  # type: ignore
except ImportError:
    pypinyin = None

logger = logging.getLogger(__name__)

_ARABIC_FLOOR_PATTERN = re.compile(r"\d+楼")
_CN_FLOOR_PATTERN = re.compile(r"[零一二三四五六七八九十百两千万亿]+楼")


# ── 内联 LRU 缓存 ─────────────────────────────────────────────────


def _text_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:16]


class _SimpleLRUCache:
    def __init__(self, maxsize: int = 1000, ttl: int = 3600):
        self.maxsize = maxsize
        self.ttl = ttl
        self._cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any | None:
        if key not in self._cache:
            self.misses += 1
            return None
        item = self._cache[key]
        if time.time() > item["expire_time"]:
            self._cache.pop(key)
            self.misses += 1
            return None
        self._cache.move_to_end(key)
        self.hits += 1
        return item["value"]

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        if len(self._cache) >= self.maxsize:
            self._cache.popitem(last=False)
        self._cache[key] = {"value": value, "expire_time": time.time() + (ttl or self.ttl)}
        self._cache.move_to_end(key)

    def clear(self) -> None:
        self._cache.clear()
        self.hits = 0
        self.misses = 0

    def stats(self) -> Dict[str, Any]:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total * 100, 2) if total else 0,
            "current_size": len(self._cache),
        }


_rule_cache = _SimpleLRUCache(maxsize=2000, ttl=3600)


def cached_rule_engine_parse(text: str, parse_func):
    key = f"parse:{_text_hash(text)}"
    result = _rule_cache.get(key)
    if result is not None:
        return result
    result = parse_func(text)
    _rule_cache.set(key, result)
    return result


def get_cache_stats() -> Dict[str, Any]:
    return _rule_cache.stats()


def clear_cache() -> None:
    _rule_cache.clear()


# ── Pydantic 语义模型 ───────────────────────────────────────────────

IntentType = str  # "device_control" | "state_query" | "scene_activate" | ...
RelationType = str  # "single" | "parallel" | "sequence" | "condition"
SourceType = str  # "rule" | "llm" | "context" | "hybrid"


class SlotValue(BaseModel):
    raw: str = Field(default="")
    normalized: str = Field(default="")
    canonical_id: Optional[str] = Field(default=None)
    confidence: float = Field(default=1.0)


class TriggerSpec(BaseModel):
    type: str = ""
    condition_text: Optional[str] = None
    time_expression: Optional[str] = None
    schedule_type: Optional[str] = None
    recurrence: Optional[str] = None
    delay_expression: Optional[str] = None
    weekdays: List[str] = Field(default_factory=list)
    raw_text: Optional[str] = None


class ExecutionStep(BaseModel):
    step_id: str = ""
    command_index: int = 0
    relation: RelationType = "single"
    depends_on: List[int] = Field(default_factory=list)
    group_id: Optional[str] = None
    condition: Optional[str] = None
    trigger_type: Optional[str] = None
    summary: Optional[str] = None


class SemanticCommand(BaseModel):
    intent: str = "unknown"
    query_type: Optional[str] = None
    trigger_type: Optional[str] = None
    trigger: Optional[TriggerSpec] = None
    action: Optional[SlotValue] = None
    device: Optional[SlotValue] = None
    location: Optional[SlotValue] = None
    parameter: Optional[SlotValue] = None
    delta: Optional[float] = None
    delta_unit: Optional[str] = None
    scope: Optional[str] = None
    value: Optional[SlotValue] = None
    unit: Optional[SlotValue] = None
    time: Optional[SlotValue] = None
    condition: Optional[str] = None
    sequence_index: int = 0
    relation: RelationType = "single"
    execution_relation: RelationType = "single"
    depends_on: List[int] = Field(default_factory=list)
    group_id: Optional[str] = None
    raw_text: str = ""
    rendered_text: Optional[str] = None
    source: SourceType = "rule"
    confidence: float = 0.0
    missing_slots: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class SemanticDecision(BaseModel):
    commands: List[SemanticCommand] = Field(default_factory=list)
    normalized_text: str = ""
    rendered_text: str = ""
    implicit_signals: List[str] = Field(default_factory=list)
    suggestions: List[Any] = Field(default_factory=list)
    unresolved_slots: List[str] = Field(default_factory=list)
    execution_plan: List[ExecutionStep] = Field(default_factory=list)
    requires_confirmation: bool = False
    confirmation_message: Optional[str] = None
    source: SourceType = "rule"
    overall_confidence: float = 0.0
    debug: Dict[str, Any] = Field(default_factory=dict)


# ── 热词表配置 ──────────────────────────────────────────────────

@dataclass
class HotWordsConfig:
    """热词配置"""
    actions: Dict[str, List[str]] = field(default_factory=dict)      # 动作词
    devices: Dict[str, List[str]] = field(default_factory=dict)      # 设备词
    locations: Dict[str, List[str]] = field(default_factory=dict)    # 位置词
    parameters: Dict[str, List[str]] = field(default_factory=dict)    # 参数词
    connectors: List[str] = field(default_factory=list)              # 连接词
    semantics: Dict[str, List[str]] = field(default_factory=dict)    # 语义词（独立于四槽）
    device_aliases: Dict[str, str] = field(default_factory=dict)     # 设备别名 -> 规范设备
    filler_chars: List[str] = field(default_factory=list)            # 语气词字符（可配置）
    filler_phrases: List[str] = field(default_factory=list)          # 语气词短语（可配置）

    # 扁平化的词集合，用于快速查找
    action_set: Set[str] = field(default_factory=set)
    device_set: Set[str] = field(default_factory=set)
    location_set: Set[str] = field(default_factory=set)
    parameter_set: Set[str] = field(default_factory=set)
    connector_set: Set[str] = field(default_factory=set)
    semantic_set: Set[str] = field(default_factory=set)

    def __post_init__(self):
        """初始化词集合"""
        self._build_sets()

    def _build_sets(self):
        """构建扁平化词集合"""
        self.action_set = {word for words in self.actions.values() for word in words}
        self.device_set = {word for words in self.devices.values() for word in words}
        self.location_set = {word for words in self.locations.values() for word in words}
        self.parameter_set = {word for words in self.parameters.values() for word in words}
        self.connector_set = set(self.connectors)
        self.semantic_set = {word for words in self.semantics.values() for word in words}

    def total_words(self) -> int:
        """总词数"""
        return (
            len(self.action_set) +
            len(self.device_set) +
            len(self.location_set) +
            len(self.parameter_set) +
            len(self.connector_set) +
            len(self.semantic_set)
        )


# ── 默认热词表 ────────────────────────────────────────────────────

DEFAULT_HOT_WORDS = {
    "actions": {
        "open": ["打开", "开启", "启动", "点亮", "开"],
        "close": ["关闭", "关掉", "停止", "熄灭", "关"],
        "adjust_up": ["调高", "调亮", "调大", "升高", "加强", "变亮"],
        "adjust_down": ["调低", "调暗", "调小", "降低", "减弱", "变暗"],
        "set": ["设置", "设置成", "设置为", "调成", "变成", "保持"],
        "move": ["移动到", "移到", "放到"],
        # "把...调为/到/设置" 动作模式
        "ba_set": ["把小孩房间温度调为", "把空调调为", "把灯光调为", "把窗帘拉开", "把窗帘关闭"],
    },
    "devices": {
        "light": ["射灯", "吊灯", "台灯", "落地灯", "吸顶灯", "筒灯", "灯带", "射灯组", "灯", "灯光", "照明灯", "装饰灯", "背景灯", "氛围灯", "感应灯", "智能灯", "调光灯", "变色灯", "彩灯", "RGB灯", "LED灯", "节能灯", "阅读灯", "床头灯", "壁灯", "廊灯", "花园灯", "景观灯", "路灯", "聚光灯", "射灯", "投影灯", "舞台灯", "工矿灯", "防爆灯"],
        "curtain": ["窗帘", "百叶窗", "卷帘", "纱帘", "电动窗帘", "智能窗帘", "布帘", "纱窗", "竹帘", "木帘", "罗马帘", "风帘", "百叶帘", "遮光帘", "隔热帘", "隔音帘", "防风帘", "防蚊帘"],
        "ac": ["空调", "新风", "地暖", "暖气片", "空调柜机", "温控", "中央空调", "空调机", "冷气机", "冰柜", "冷库", "冰箱", "冷藏柜", "暖气", "暖风机", "电暖器", "油汀", "踢脚线取暖器", "空调扇", "排气扇", "抽湿机", "除湿机", "空气净化器", "新风系统", "排气扇"],
        "tv": ["电视", "电视机", "投屏", "屏幕", "显示器", "智能电视", "网络电视", "互联网电视", "4K电视", "8K电视", "投影仪", "投影机", "智能投影", "激光投影", "短焦投影", "电子屏", "LED屏", "液晶屏", "触摸屏"],
        "audio": ["音响", "音箱", "喇叭", "扬声器", "音响系统", "智能音响", "蓝牙音响", "无线音响", "WiFi音响", "功放", "功放机", "调音台", "效果器", "均衡器", "耳机", "蓝牙耳机", "无线耳机", "头戴式", "入耳式"],
        "appliance": ["电饭煲", "微波炉", "烤箱", "洗碗机", "冰箱", "洗衣机", "油烟机", "燃气灶", "消毒柜", "榨汁机", "破壁机", "空气炸锅", "扫地机", "吸尘器", "拖地机", "烘干机", "洗衣机", "熨烫机", "加湿器", "除湿机", "空气净化器", "新风系统", "排气扇"],
        "sensor": ["温湿度计", "温度计", "湿度计", "空气质量监测", "门磁", "人体感应", "红外感应", "烟雾报警器", "燃气报警器", "智能传感器", "无线传感器", "物联网传感器", "网关"],
        "system": ["森环系统", "新风系统", "空调系统", "地暖系统", "安防系统", "监控系统", "门禁系统", "可视对讲", "智能家居", "智能控制系统", "中央控制系统", "场景系统"],
        "other": ["门锁", "智能门锁", "指纹锁", "密码锁", "车库门", "电动门", "卷闸门", "伸缩门", "道闸", "开关", "智能开关", "调光器", "场景开关", "监控", "摄像头", "门禁", "车库", "水池", "喷泉", "窗帘轨道"],
        "fan": ["风扇", "吊扇", "落地扇", "台扇", "排气扇", "循环扇", "智能风扇", "变频风扇", "无叶风扇", "塔扇"],
        "heater": ["取暖器", "电暖器", "油汀", "暖风机", "空调扇", "电热毯", "热水袋", "保温器", "壁挂炉"],
        "humidifier": ["加湿器", "超声波加湿器", "蒸发式加湿器", "喷雾器", "智能加湿器", "恒湿器", "香薰机"],
        "cleaner": ["扫地机", "吸尘器", "拖地机", "洗地机", "机器人", "手持吸尘器", "无线吸尘器", "中央吸尘"]
    },
    "locations": {
        "room": ["客厅", "卧室", "主卧", "次卧", "儿童房", "书房", "餐厅", "厨房", "卫生间", "浴室", "阳台"],
        "floor": ["一楼", "二楼", "三楼", "一楼大厅", "二楼卧室"],
        "direction": ["东", "西", "南", "北", "左", "右"],
        "area": ["门厅", "玄关", "走廊", "过道", "楼梯间", "庭院", "花园"],
    },
    "parameters": {
        "brightness": ["调亮", "调暗", "变亮", "变暗", "最亮", "最暗"],
        "temperature": ["调高", "调低", "升高", "降低", "设置", "设置为", "调成", "度", "摄氏度"],
        "color": ["变红", "变蓝", "变绿", "变黄", "彩虹"],
        "speed": ["开大", "开小", "高档", "低档"],
        "ratio": ["一半", "50%", "70%", "百分之三十", "百分之五十", "百分之七十"],
        "level": ["一", "二", "三", "四", "五", "十", "二十", "三十", "五十", "七十", "一百"],
    },
    "connectors": ["并且", "并", "然后", "接着", "再", "随后", "和", "以及", "还有"],
    "semantics": {
        "query": ["查询", "查看", "检查", "看看", "多少", "几度", "状态", "是否", "有没有"],
        "scene": ["回家场景", "离家场景", "阅读场景", "影院场景", "会客场景", "睡眠场景"],
        "mode": ["回家模式", "离家模式", "阅读模式", "影院模式", "会客模式", "睡眠模式"],
        "platform": ["语音", "语音唤醒", "语音引擎", "普通话", "中文", "英文"],
        "scope": ["全屋", "区域分控"],
        "metric": ["PM2.5", "PM10", "CO2", "VOC", "O3", "温度", "湿度"],
        "other": ["设备管理", "安防监控", "环境监测", "能源管理"]
    },
    "device_aliases": {
        "风扇": "电风扇"
    },
    "filler": {
        "chars": ["阿", "啊", "嗯", "哦", "呃", "哎", "唉", "诶", "额", "哼", "嘿", "呀", "哇", "哟", "喂", "恩", "哈"],
        "phrases": ["那个", "这个", "就是", "那个那个", "这个这个", "哈哈", "哈哈哈"]
    },
}


def create_default_hot_words() -> HotWordsConfig:
    """创建默认热词配置"""
    filler = DEFAULT_HOT_WORDS.get("filler", {})
    return HotWordsConfig(
        actions=DEFAULT_HOT_WORDS["actions"],
        devices=DEFAULT_HOT_WORDS["devices"],
        locations=DEFAULT_HOT_WORDS["locations"],
        parameters=DEFAULT_HOT_WORDS["parameters"],
        connectors=DEFAULT_HOT_WORDS["connectors"],
        semantics=DEFAULT_HOT_WORDS.get("semantics", {}),
        device_aliases=DEFAULT_HOT_WORDS.get("device_aliases", {}),
        filler_chars=filler.get("chars", []),
        filler_phrases=filler.get("phrases", []),
    )


def load_hot_words_from_stt_file(filepath: str = "hot_words.txt") -> HotWordsConfig:
    """
    从 STT 热词文件（GBK 编码）加载并转换为 HotWordsConfig

    Args:
        filepath: STT 热词文件路径（GBK 编码）

    Returns:
        HotWordsConfig
    """
    from hot_words import load_categorized_hot_words

    try:
        categorized = load_categorized_hot_words(filepath)
        hot_words_dict = categorized.to_smart_home_dict()

        logger.info(
            f"Loaded STT hot words from {filepath}: "
            f"{len(categorized.all_words)} total, "
            f"{len(categorized.actions_all)} actions, "
            f"{len(categorized.devices_all)} devices, "
            f"{len(categorized.locations_all)} locations"
        )

        return HotWordsConfig(
            actions=hot_words_dict.get("actions", {}),
            devices=hot_words_dict.get("devices", {}),
            locations=hot_words_dict.get("locations", {}),
            parameters=hot_words_dict.get("parameters", {}),
            connectors=hot_words_dict.get("connectors", []),
            semantics=hot_words_dict.get("semantics", {}),
            device_aliases=DEFAULT_HOT_WORDS.get("device_aliases", {}),
            filler_chars=DEFAULT_HOT_WORDS.get("filler", {}).get("chars", []),
            filler_phrases=DEFAULT_HOT_WORDS.get("filler", {}).get("phrases", []),
        )
    except Exception as e:
        logger.warning(f"Failed to load STT hot words: {e}, using default config")
        return create_default_hot_words()


def load_hot_words_from_file(filepath: str) -> HotWordsConfig:
    """
    从文件加载热词配置

    Args:
        filepath: 配置文件路径（JSON 格式）

    Returns:
        HotWordsConfig
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        filler_cfg = data.get("filler", {}) if isinstance(data.get("filler", {}), dict) else {}

        return HotWordsConfig(
            actions=data.get("actions", {}),
            devices=data.get("devices", {}),
            locations=data.get("locations", {}),
            parameters=data.get("parameters", {}),
            connectors=data.get("connectors", []),
            semantics=data.get("semantics", {}),
            device_aliases=data.get("device_aliases", {}) if isinstance(data.get("device_aliases", {}), dict) else DEFAULT_HOT_WORDS.get("device_aliases", {}),
            filler_chars=filler_cfg.get("chars", DEFAULT_HOT_WORDS.get("filler", {}).get("chars", [])),
            filler_phrases=filler_cfg.get("phrases", DEFAULT_HOT_WORDS.get("filler", {}).get("phrases", [])),
        )
    except FileNotFoundError:
        logger.warning(f"热词文件不存在: {filepath}，使用默认配置")
        return create_default_hot_words()
    except Exception as e:
        logger.error(f"加载热词文件失败: {e}，使用默认配置")
        return create_default_hot_words()


# ── 指令解析结果 ──────────────────────────────────────────────

@dataclass
class Command:
    """智能家居指令"""
    action: str          # 动作
    device: str          # 设备
    location: str = ""    # 位置（可选）
    parameter: str = ""   # 参数名（可选）
    value: str = ""       # 参数值（可选）
    unit: str = ""        # 参数单位（可选）
    confidence: float = 1.0  # 置信度

    def __str__(self) -> str:
        """格式化输出"""
        parameter_display_map = {
            "temperature": "温度",
            "brightness": "亮度",
            "color": "颜色",
            "speed": "风速",
            "ratio": "",
            "level": "档位",
            "power_state": "状态",
            "device_state": "状态",
        }
        device_text = self.device
        if self.location and self.device and self.location not in self.device:
            device_text = f"{self.location}{self.device}"
        elif self.location and not self.device:
            device_text = self.location

        value_part = self.value or ""
        if self.unit:
            value_part += self.unit
        parameter_display = parameter_display_map.get(self.parameter, self.parameter)

        if self.action == "设置为":
            if value_part:
                if parameter_display and parameter_display not in ("", "状态"):
                    if device_text:
                        return f"设置{device_text}{parameter_display}为{value_part}"
                    return f"设置{parameter_display}为{value_part}"
                if device_text:
                    return f"设置{device_text}为{value_part}"
                return f"设置为{value_part}"
            if parameter_display and parameter_display not in ("", "状态"):
                if device_text:
                    return f"设置{device_text}{parameter_display}"
                return f"设置{parameter_display}"
            if device_text:
                return f"设置{device_text}"
            return "设置"

        if value_part and parameter_display and parameter_display not in ("状态",):
            parameter_part = value_part
        else:
            parameter_part = parameter_display or value_part
        if parameter_part:
            return f"{self.action}{device_text}{parameter_part}"
        return f"{self.action}{device_text}"

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "action": self.action,
            "device": self.device,
            "location": self.location,
            "parameter": self.parameter,
            "value": self.value,
            "unit": self.unit,
            "confidence": self.confidence,
        }


@dataclass
class ParseResult:
    """解析结果"""
    commands: List[Command] = field(default_factory=list)
    confidence: float = 0.0      # 整体置信度
    raw_input: str = ""           # 原始输入
    matched_rule: str = ""        # 匹配的规则
    needs_glm: bool = False       # 是否需要 GLM 精修

    @property
    def is_empty(self) -> bool:
        return not self.commands

    def __str__(self) -> str:
        """格式化输出（用分号分隔多个指令）"""
        return "；".join(str(cmd) for cmd in self.commands)


@dataclass
class ClauseSegment:
    """复合句拆解后的候选子句。"""
    text: str
    clause_type: str = "unknown"   # complete_command / dependent_clause / modifier_clause / unknown
    action: str = ""
    location: str = ""
    device: str = ""
    parameter: str = ""
    value: str = ""
    unit: str = ""


# ── 规则引擎 ──────────────────────────────────────────────────────

class SmartHomeRuleEngine:
    """
    智能家居规则匹配引擎

    基于热词表和模式匹配快速解析指令
    智能处理"把...调为/到/设置"模式
    """

    # 填充词（需要去除）
    FILLER_CHARS = "啊嗯哦呃哎唉诶额哼嘿呀哇哟喂恩"

    # 基础脏词列表（包含所有变体的根词）
    BASE_DIRTY_WORDS = ["tmd", "TMD", "尼玛", "他妈", "他妈的", "tm", "nm", "wc", "sb"]

    # 中文脏词及其变体
    CHINESE_DIRTY_WORDS = {
        # "他妈的" 变体组
        "tmd": [
            "他妈的", "他妈地", "他吗的", "他马的", "他骂的", "塌马的", "踏马的",
            "特么的", "特马的", "忒么的", "特妈的", "他妈", "他吗", "特么",
            "他妈的呀", "他妈的了",
        ],
        # "尼玛" 变体组
        "nm": [
            "尼玛", "泥玛", "妮玛", "你妈", "你吗", "尼马", "泥马", "妮马",
            "尼玛的", "泥玛的", "你妈的", "你吗的", "尼玛呀",
        ],
        # "卧槽" 变体组
        "wc": [
            "卧槽", "我操", "我草", "我擦", "我靠", "我去", "沃槽", "沃草",
            "卧草", "沃擦", "窝槽", "窝草", "我艹", "我日", "卧艹", "沃日",
            "卧槽啊", "我操啊", "卧槽呀",
        ],
        # "傻逼" 变体组
        "sb": [
            "傻逼", "煞笔", "傻B", "煞逼", "沙比", "煞比", "沙笔", "煞币",
            "傻币", "傻毕", "煞璧", "沙壁", "沙璧", "沙碧", "煞碧",
            "大傻逼", "真傻逼", "傻逼呀", "二逼", "二比", "二币",
        ],
        # 其他常见脏词
        "other": [
            "操你妈", "草你妈", "操尼玛", "草尼玛", "操你大爷", "草你大爷",
            "妈的", "妈滴", "妈逼", "妈比", "妈币", "妈壁",
            "狗日", "狗日的", "狗屎", "狗屁", "屁话",
            "贱人", "贱货", "骚货", "婊子", "婊砸",
            "王八蛋", "王八羔子", "混蛋", "混账", "混球",
            "滚蛋", "滚犊子", "滚开", "闭嘴", "去死",
            "傻缺", "脑残", "弱智", "白痴", "智障", "脑瘫",
            "神经病", "有病", "变态", "人渣", "败类",
            "草泥马", "草你吗", "草泥吗", "曹尼玛", "曹你妈",
        ],
    }

    # 脏词变体映射表（扩展版 - 拼音形式）
    # key: 基础脏词（小写）, value: 所有变体列表
    DIRTY_WORD_VARIANTS = {
        # tmd 变体组
        "tmd": [
            "tmdd", "nnm", "nmm", "wcc", "tamd", "tmmm", "tmmmd", "tmddd",
            "tmddd", "tmdtt", "ttmdd", "tmmmdd", "tmddd", "tmdddd", "tmd2d",
            "t3md", "tmdd3", "t1md", "tmm1", "tmd2", "tm3d", "tmd4", "tmdd2",
            # 语音识别常见错误
            "teni", "teniade", "tenimade", "temade", "temade", "teenn", "teeenn",
        ],
        # nm 变体组（尼玛）
        "nm": [
            "nmm", "tmmd", "tnmd", "nmmm", "tamd", "nmmm", "nnmm", "nmmmm",
            "nmm2", "nm2", "n3m", "nm3", "nnm", "nmnn", "nmmnn",
            # 语音识别常见错误
            "neem", "niema", "neema", "niim", "neema",
        ],
        # wc 变体组
        "wc": [
            "wcc", "tmdd", "tmm", "twcc", "wccc", "wccc", "wcccc", "wcc2",
            "wc2", "w2c", "wcc22", "wccc2", "wcc3", "w2cc", "wc22", "wc22c",
            # 语音识别常见错误
            "woc", "woac", "uoc", "uocc",
        ],
        # sb 变体组
        "sb": [
            "sbb", "sss", "sssb", "sssss", "shabi", "sbbb", "ssbb", "sbb2",
            "sb2", "s2b", "sbb3", "sb3b", "sb22", "sbb22",
            # 语音识别常见错误
            "shebi", "shabi", "shabbi", "shabbii", "saibi",
        ],
        # tm 变体组
        "tm": [
            "tmm", "tmmm", "tmmmm", "ttm", "tttm", "tmmm", "tmm2", "tm2",
            "t2m", "tmmm2", "tm22", "tm2m", "tmmmm2", "tmmmm3",
            # 语音识别常见错误
            "tem", "tiem", "tiim", "teem",
        ],
    }

    # 构建完整的脏词列表（用于快速匹配）- 包含拼音和中文
    _ALL_DIRTY_WORDS = set(BASE_DIRTY_WORDS)
    for variants in DIRTY_WORD_VARIANTS.values():
        _ALL_DIRTY_WORDS.update(variants)
    # 添加中文脏词
    for variants in CHINESE_DIRTY_WORDS.values():
        _ALL_DIRTY_WORDS.update(variants)

    # 填充词列表（包含脏词）
    FILLER_PHRASES = ["那个", "这个", "就是", "那个那个", "这个这个"] + list(_ALL_DIRTY_WORDS)
    # 噪声恢复时允许的单字动作锚点（需额外上下文信号校验）
    RECOVERY_SINGLE_CHAR_ACTIONS = {"开", "关"}

    # 动作别名归一化（文件缺失时的兜底）
    DEFAULT_ACTION_ALIASES = {
        "关上": "关闭",
        "拉上": "关闭",
        "开下": "打开",
        "开一下": "打开",
        "关下": "关闭",
        "关一下": "关闭",
        "设为": "设置为",
        "调到": "设置为",
        "调为": "设置为",
        "升到": "调高",
        "降到": "调低",
    }

    CATEGORY_CANONICAL_ACTION = {
        "open": "打开",
        "close": "关闭",
        "adjust_up": "调高",
        "adjust_down": "调低",
        "set": "设置为",
        "move": "移动到",
    }

    ACTION_CANONICAL_IDS = {
        "open": "power_on",
        "close": "power_off",
        "adjust_up": "adjust_up",
        "adjust_down": "adjust_down",
        "set": "set_value",
        "move": "move",
        "ba_set": "set_value",
    }

    PARAMETER_CANONICAL_IDS = {
        "brightness": "brightness",
        "temperature": "temperature",
        "color": "color",
        "speed": "fan_speed",
        "ratio": "ratio",
        "level": "level",
        "power_state": "power_state",
        "device_state": "device_state",
    }

    QUERY_KEYWORDS = ("查询", "查看", "检查", "看看", "多少", "几度", "状态", "是否", "有没有")
    SCENE_KEYWORDS = ("模式", "场景", "回家", "离家", "睡眠", "影院", "阅读", "会客")
    CONDITION_KEYWORDS = ("如果", "就")
    AUTOMATION_KEYWORDS = ("自动", "定时", "每", "当", "如果", "就")
    SCENE_ACTION_KEYWORDS = ("打开", "开启", "启动", "切换到", "切到", "进入", "执行", "关闭")
    IMPLICIT_SIGNAL_PATTERNS = (
        ("going_to_sleep", (r"我要睡了", r"去睡觉", r"准备睡觉", r"睡觉了", r"睡了")),
        ("leaving_home", (r"我出门了", r"出门了", r"我要出门", r"走了", r"离家了")),
        ("arriving_home", (r"我回来了", r"到家了", r"回家了", r"刚回家")),
        ("feeling_hot", (r"好热", r"热死了", r"太热了", r"有点热")),
        ("feeling_cold", (r"好冷", r"冷死了", r"太冷了", r"有点冷")),
        ("too_bright", (r"太亮了", r"太亮", r"刺眼", r"太晃眼")),
        ("too_dark", (r"太暗了", r"太暗", r"有点暗", r"看不见")),
    )
    QUERY_ACTION_CANONICAL_ID = "query"
    SCENE_ACTION_CANONICAL_ID = "activate_scene"
    AUTOMATION_ACTION_CANONICAL_ID = "create_automation"
    DEFAULT_QUERY_DEVICE = {
        "temperature": "温湿度计",
        "brightness": "灯",
        "color": "灯",
        "speed": "风扇",
        "ratio": "窗帘",
        "power_state": "",
        "device_state": "",
    }
    DEVICE_CAPABILITY_MAP = {
        "light": {"brightness", "color", "power_state", "device_state", "level"},
        "curtain": {"ratio", "power_state", "device_state", "level"},
        "ac": {"temperature", "speed", "power_state", "device_state", "level"},
        "fan": {"speed", "power_state", "device_state", "level"},
        "heater": {"temperature", "power_state", "device_state", "level"},
        "humidifier": {"power_state", "device_state", "level"},
        "sensor": {"temperature", "brightness", "device_state"},
        "system": {"temperature", "speed", "power_state", "device_state"},
        "audio": {"speed", "power_state", "device_state", "level"},
        "other": {"power_state", "device_state", "level"},
        "appliance": {"power_state", "device_state", "level"},
        "cleaner": {"power_state", "device_state", "level"},
        "tv": {"power_state", "device_state", "level"},
    }
    PARAMETER_TO_DEVICE_HINTS = {
        "temperature": ["ac", "heater", "system", "sensor"],
        "brightness": ["light", "sensor"],
        "color": ["light"],
        "speed": ["fan", "ac", "system", "audio"],
        "ratio": ["curtain", "light"],
        "level": ["light", "fan", "ac", "audio", "curtain"],
        "power_state": ["light", "curtain", "ac", "fan", "system", "other"],
        "device_state": ["ac", "light", "curtain", "fan", "system", "sensor", "other"],
    }
    ACTION_TO_DEVICE_HINTS = {
        "open": ["light", "curtain", "ac", "fan", "system", "other"],
        "close": ["light", "curtain", "ac", "fan", "system", "other"],
        "adjust_up": ["light", "fan", "ac", "heater", "audio"],
        "adjust_down": ["light", "fan", "ac", "heater", "audio"],
        "set": ["ac", "light", "curtain", "fan", "audio", "system"],
        "ba_set": ["ac", "light", "curtain", "fan", "audio", "system"],
        "move": ["curtain", "other"],
    }
    CATEGORY_DEFAULT_DEVICE = {
        "light": "灯",
        "curtain": "窗帘",
        "ac": "空调",
        "fan": "风扇",
        "heater": "取暖器",
        "humidifier": "加湿器",
        "sensor": "温湿度计",
        "system": "森环系统",
        "audio": "音响",
        "other": "设备",
    }
    PARAMETER_DEFAULT_UNIT = {
        "temperature": "度",
        "brightness": "%",
        "ratio": "%",
        "speed": "级",
        "level": "级",
    }
    PARAMETER_VALUE_RANGE = {
        "temperature": (16, 30),
        "brightness": (0, 100),
        "ratio": (0, 100),
        "speed": (1, 5),
        "level": (1, 5),
    }
    _DOMAIN_HOMOPHONE_GROUPS = (
        {"森", "生"},
        {"环", "还"},
        {"射", "社"},
        {"灯", "等", "登"},
        {"窗", "床"},
        {"帘", "连"},
        {"调", "条", "掉"},
        {"风", "峰", "封"},
        {"扇", "善"},
        {"空", "控"},
        {"锁", "索"},
        {"屏", "瓶"},
        {"机", "基"},
        {"门", "们"},
        {"度", "渡"},
        {"厅", "庭", "听"},
        {"室", "是"},
        {"房", "方"},
        {"关", "官"},
        {"梯", "提"},
    )
    CN_DIGIT_MAP = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    CN_UNIT_MAP = {
        "十": 10,
        "百": 100,
        "千": 1000,
        "万": 10000,
    }

    def __init__(self, hot_words: Optional[HotWordsConfig] = None):
        """
        初始化规则引擎

        Args:
            hot_words: 热词配置，为 None 时使用默认配置
        """
        self.hot_words = hot_words or create_default_hot_words()
        if "并" not in self.hot_words.connector_set:
            self.hot_words.connectors.append("并")
            self.hot_words._build_sets()
        self._action_aliases = self._load_action_aliases()
        self._canonical_action_map = self._build_canonical_action_map()
        self._action_category_map = self._build_category_lookup(self.hot_words.actions)
        self._device_category_map = self._build_category_lookup(self.hot_words.devices)
        self._device_aliases = self._build_device_aliases()
        self._char_homophone_index = self._build_char_homophone_index()
        self._pinyin_cache: Dict[str, Tuple[str, ...]] = {}
        self._location_category_map = self._build_category_lookup(self.hot_words.locations)
        self._parameter_category_map = self._build_category_lookup(self.hot_words.parameters)
        self._semantic_category_map = self._build_category_lookup(self.hot_words.semantics)
        self._recovery_single_char_actions = tuple(
            sorted(
                action
                for action in self.RECOVERY_SINGLE_CHAR_ACTIONS
                if action in self.hot_words.action_set
            )
        )
        self._query_keywords = tuple(sorted(
            set(self.QUERY_KEYWORDS)
            | set(self.hot_words.actions.get("query", []))
            | self._semantic_words("query"),
            key=len,
            reverse=True,
        ))
        self._scene_keywords = tuple(sorted(
            set(self.SCENE_KEYWORDS)
            | self._semantic_words("scene", "mode"),
            key=len,
            reverse=True,
        ))
        self._condition_keywords = tuple(sorted(
            set(self.CONDITION_KEYWORDS)
            | self._semantic_words("condition"),
            key=len,
            reverse=True,
        ))
        self._automation_keywords = tuple(sorted(
            set(self.AUTOMATION_KEYWORDS)
            | self._semantic_words("automation"),
            key=len,
            reverse=True,
        ))
        self._scene_action_keywords = tuple(sorted(
            set(self.SCENE_ACTION_KEYWORDS)
            | set(self.hot_words.actions.get("open", []))
            | set(self.hot_words.actions.get("close", []))
            | set(self.hot_words.actions.get("set", [])),
            key=len,
            reverse=True,
        ))
        protected_terms = (
            self.hot_words.device_set
            | self.hot_words.location_set
            | self.hot_words.parameter_set
        )
        self._alias_protected_terms_by_len: Dict[int, Set[str]] = {}
        for term in protected_terms:
            if len(term) < 2:
                continue
            self._alias_protected_terms_by_len.setdefault(len(term), set()).add(term)
        self._alias_protected_max_len = (
            max(self._alias_protected_terms_by_len) if self._alias_protected_terms_by_len else 0
        )
        # 语气词配置支持从 hot_words_config.json 注入，缺失时回退类默认值。
        self.FILLER_CHARS = self._resolve_filler_chars()
        self.FILLER_PHRASES = self._resolve_filler_phrases()

        # 每个引擎实例拥有独立的模板匹配器，避免全局单例绑定错误热词
        self._template_matcher = TemplateMatcher(self.hot_words)

        # 预编译正则表达式
        self._compile_patterns()

        logger.info(f"SmartHome 规则引擎初始化完成，热词总数: {self.hot_words.total_words()}")
        logger.info(f"Action aliases loaded: {len(self._action_aliases)}")
        logger.info(f"Device aliases loaded: {len(self._device_aliases)}")

    def _compile_word_pattern(self, words: Set[str]) -> re.Pattern:
        """按长度降序编译词模式，空集返回永不匹配模式。"""
        if not words:
            return re.compile(r"$^")
        return re.compile("|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)))

    def _resolve_filler_chars(self) -> str:
        """解析配置中的填充字符，缺失时回退类默认值。"""
        configured = ''.join(
            dict.fromkeys(
                ''.join(str(token).strip() for token in getattr(self.hot_words, "filler_chars", []) if str(token).strip())
            )
        )
        default_chars = str(type(self).FILLER_CHARS)
        return configured or default_chars

    def _resolve_filler_phrases(self) -> List[str]:
        """解析配置中的填充短语，并补齐脏词短语兜底。"""
        configured = [
            str(token).strip()
            for token in getattr(self.hot_words, "filler_phrases", [])
            if str(token).strip()
        ]
        base = configured or list(type(self).FILLER_PHRASES)
        merged = list(dict.fromkeys(base + list(self._ALL_DIRTY_WORDS)))
        return merged

    def _compile_patterns(self):
        """预编译正则表达式"""
        # 动作词正则（按长度降序，优先匹配长词）
        self._action_pattern = self._compile_word_pattern(self.hot_words.action_set)

        # 设备词正则（按长度降序）
        self._device_pattern = self._compile_word_pattern(self.hot_words.device_set)

        # 位置词正则，额外支持动态楼层（四楼、12楼）。
        location_words = sorted(self.hot_words.location_set, key=len, reverse=True)
        location_part = "|".join(re.escape(w) for w in location_words) if location_words else r"$^"
        self._location_pattern = re.compile(
            rf"(?:{location_part}|{_ARABIC_FLOOR_PATTERN.pattern}|{_CN_FLOOR_PATTERN.pattern})"
        )

        # 连接词正则
        self._connector_pattern = self._compile_word_pattern(self.hot_words.connector_set)

        # 填充字符正则
        if self.FILLER_CHARS:
            self._filler_char_pattern = re.compile(f"[{re.escape(self.FILLER_CHARS)}]+")
        else:
            self._filler_char_pattern = re.compile(r"$^")
        if self.FILLER_PHRASES:
            self._filler_phrase_pattern = re.compile(
                '|'.join(re.escape(p) for p in sorted(self.FILLER_PHRASES, key=len, reverse=True))
            )
        else:
            self._filler_phrase_pattern = re.compile(r"$^")
        connector_words = sorted(self.hot_words.connector_set, key=len, reverse=True)
        connector_part = "|".join(re.escape(c) for c in connector_words) if connector_words else r"$^"
        self._command_split_pattern = re.compile(rf"(?:；|;|，|,|、|{connector_part})")
        self._value_pattern = re.compile(r"(百分之[一二三四五六七八九十百两\d]+|\d+(?:\.\d+)?)(摄氏度|度|%|％)?")

        # 脏词变体正则（预编译，避免每次调用重建）- 包含拼音和中文
        all_dirty = set()
        # 添加拼音变体
        for base_word, variants in self.DIRTY_WORD_VARIANTS.items():
            all_dirty.add(base_word.lower())
            all_dirty.update(v.lower() for v in variants)
        # 添加中文脏词
        for variants in self.CHINESE_DIRTY_WORDS.values():
            all_dirty.update(variants)
        all_dirty.discard('')
        self._dirty_variants_pattern = re.compile(
            '|'.join(re.escape(w) for w in sorted(all_dirty, key=len, reverse=True)),
            flags=re.IGNORECASE,
        )

    def _load_action_aliases(self) -> Dict[str, str]:
        """加载动作同义词映射。"""
        alias_path = Path(__file__).resolve().parent / "action_aliases.json"
        aliases = dict(self.DEFAULT_ACTION_ALIASES)
        try:
            with open(alias_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            file_aliases = data.get("action_aliases", {})
            if isinstance(file_aliases, dict):
                aliases.update({str(k): str(v) for k, v in file_aliases.items() if k and v})
        except FileNotFoundError:
            logger.info("action_aliases.json not found, using default action aliases")
        except Exception as e:
            logger.warning(f"Failed to load action aliases: {e}, using defaults")
        return aliases

    def _build_device_aliases(self) -> Dict[str, str]:
        """构建设备别名映射（配置优先，自动别名兜底）。"""
        aliases: Dict[str, str] = {}
        configured = getattr(self.hot_words, "device_aliases", {}) or {}
        if isinstance(configured, dict):
            for alias, canonical in configured.items():
                alias_text = str(alias).strip()
                canonical_text = str(canonical).strip()
                if not alias_text or not canonical_text:
                    continue
                if canonical_text not in self.hot_words.device_set:
                    continue
                if alias_text == canonical_text:
                    continue
                aliases[alias_text] = canonical_text

        # 自动别名：电X -> X（例如 电风扇 -> 风扇）
        for device in sorted(self.hot_words.device_set, key=len, reverse=True):
            if len(device) <= 2 or not device.startswith("电"):
                continue
            alias = device[1:]
            if not alias or alias in self.hot_words.device_set:
                continue
            aliases.setdefault(alias, device)

        return aliases

    def _canonicalize_device(self, device: str) -> str:
        """将设备别名归一为规范设备词。"""
        return self._device_aliases.get(device or "", device or "")

    def _build_canonical_action_map(self) -> Dict[str, str]:
        """构建动作词到标准动作的映射。"""
        mapping: Dict[str, str] = {}
        for category, words in self.hot_words.actions.items():
            canonical = self.CATEGORY_CANONICAL_ACTION.get(category)
            if not canonical and words:
                canonical = words[0]
            for word in words:
                mapping[word] = canonical or word
        return mapping

    def _build_category_lookup(self, grouped_words: Dict[str, List[str]]) -> Dict[str, str]:
        """构建词到类别的倒排表。"""
        mapping: Dict[str, str] = {}
        for category, words in grouped_words.items():
            for word in words:
                mapping[word] = category
        return mapping

    def _semantic_words(self, *categories: str) -> Set[str]:
        """按分类提取语义词；不传分类时返回全部语义词。"""
        if not self.hot_words.semantics:
            return set()
        if not categories:
            return {
                str(word).strip()
                for words in self.hot_words.semantics.values()
                for word in words
                if str(word).strip()
            }
        terms: Set[str] = set()
        for category in categories:
            for word in self.hot_words.semantics.get(category, []):
                token = str(word).strip()
                if token:
                    terms.add(token)
        return terms

    def _canonicalize_action(self, action: str) -> str:
        """将动作归一化为标准动作词。"""
        if not action:
            return action
        alias_mapped = self._action_aliases.get(action, action)
        return self._canonical_action_map.get(alias_mapped, alias_mapped)

    def _normalize_action_aliases(self, text: str) -> str:
        """在文本层做多字动作别名归一（不处理单字，避免污染设备词如"开关"）。"""
        normalized = text
        for src, dst in sorted(self._action_aliases.items(), key=lambda x: len(x[0]), reverse=True):
            if len(src) < 2 or src == dst:
                continue
            rebuilt: List[str] = []
            i = 0
            while i < len(normalized):
                if normalized.startswith(src, i) and not self._is_inside_protected_term(normalized, i):
                    rebuilt.append(dst)
                    i += len(src)
                    continue
                rebuilt.append(normalized[i])
                i += 1
            normalized = "".join(rebuilt)
        return normalized

    def _is_inside_protected_term(self, text: str, index: int) -> bool:
        """避免把动作别名替换到已有热词内部，例如"空调为"里的"调为"."""
        if index <= 0 or not self._alias_protected_terms_by_len:
            return False

        for length, terms in self._alias_protected_terms_by_len.items():
            start_min = max(0, index - length + 1)
            start_max = min(index - 1, len(text) - length)
            for start in range(start_min, start_max + 1):
                if text[start:start + length] in terms and start < index < start + length:
                    return True
        return False

    def parse(self, text: str) -> ParseResult:
        """
        解析智能家居指令（带缓存）

        Args:
            text: 输入文本

        Returns:
            ParseResult
        """
        # 使用缓存包装的解析函数
        result = cached_rule_engine_parse(text, self._parse_uncached)

        # 更新原始输入
        result.raw_input = text

        logger.debug(f"规则解析: '{text}' → '{result}' (confidence={result.confidence:.2f}, needs_glm={result.needs_glm})")

        return result

    def _parse_uncached(self, text: str) -> ParseResult:
        """
        未缓存的解析实现（内部使用）

        Args:
            text: 输入文本

        Returns:
            ParseResult
        """
        result = ParseResult(raw_input=text)

        if not text or not text.strip():
            return result

        # 1. 预处理：去除填充词
        cleaned_text = self._preprocess(text)

        # 2. 分割多指令
        segments = self._split_commands(cleaned_text)

        # 3. 解析每个指令段（支持动作继承：如"打开客厅灯和卧室灯"）
        inherited_action = ""
        inherited_device = ""
        inherited_location = ""
        # 标记是否整个输入未被分割（无标点/连接词），
        # 此时单命令解析可能只覆盖前缀，需要更积极地尝试恢复。
        is_single_unsplit_segment = len(segments) == 1 and len(segments[0]) > 15
        for segment in segments:
            segment = segment.strip()
            if not segment:
                continue

            mixed_commands = self._parse_mixed_ba_segment(
                segment,
                inherited_action=inherited_action,
                inherited_device=inherited_device,
                inherited_location=inherited_location,
            )
            if mixed_commands:
                for mixed in mixed_commands:
                    result.commands.append(mixed)
                    inherited_action = mixed.action or inherited_action
                    inherited_device = mixed.device or inherited_device
                    inherited_location = mixed.location or inherited_location
                continue

            command = self._parse_single_command(
                segment,
                inherited_action=inherited_action,
                inherited_device=inherited_device,
                inherited_location=inherited_location,
            )
            if command:
                # 当整个输入未被分割且单命令只覆盖一小部分时，
                # 尝试用锚点恢复提取更多命令，优先采用恢复结果。
                if is_single_unsplit_segment:
                    cmd_len = len(command.action or "") + len(command.device or "") + len(command.location or "") + len(command.value or "")
                    if cmd_len < len(segment) * 0.5:
                        recovered_commands = self._recover_commands_from_noisy_segment(
                            segment,
                            inherited_action=inherited_action,
                            inherited_device=inherited_device,
                            inherited_location=inherited_location,
                        )
                        if recovered_commands and len(recovered_commands) > 1:
                            for recovered in recovered_commands:
                                result.commands.append(recovered)
                                inherited_action = recovered.action or inherited_action
                                inherited_device = recovered.device or inherited_device
                                inherited_location = recovered.location or inherited_location
                            continue
                result.commands.append(command)
                inherited_action = command.action or inherited_action
                inherited_device = command.device or inherited_device
                inherited_location = command.location or inherited_location
                continue

            recovered_commands = self._recover_commands_from_noisy_segment(
                segment,
                inherited_action=inherited_action,
                inherited_device=inherited_device,
                inherited_location=inherited_location,
            )
            if recovered_commands:
                for recovered in recovered_commands:
                    result.commands.append(recovered)
                    inherited_action = recovered.action or inherited_action
                    inherited_device = recovered.device or inherited_device
                    inherited_location = recovered.location or inherited_location

        # 3.1 后处理：参数命令位置继承（按当前需求，不做去重）
        result.commands = self._inherit_location_for_parameter_commands(result.commands)

        # 4. 计算整体置信度
        result.confidence = self._calculate_confidence(result, text, cleaned_text)

        # 5. 判断是否需要 GLM 精修
        result.needs_glm = self._needs_glm_refinement(result, text)

        return result

    def _parse_mixed_ba_segment(
        self,
        text: str,
        inherited_action: str = "",
        inherited_device: str = "",
        inherited_location: str = "",
    ) -> List[Command]:
        """
        解析"前半动作控制 + 后半把字设定"混合片段。

        示例：
        - 打开我的射灯把空调为16度
          -> 打开射灯；设置为空调16度
        """
        clean_text = self._normalize_action_aliases((text or "").strip())
        if not clean_text or clean_text.startswith("把") or "把" not in clean_text:
            return []

        split_indexes = [idx for idx, char in enumerate(clean_text) if char == "把" and idx > 0]
        for idx in split_indexes:
            prefix = clean_text[:idx].strip(" ，,；;")
            suffix = clean_text[idx:].strip(" ，,；;")
            if len(prefix) < 2 or len(suffix) < 3:
                continue

            prefix_command = self._parse_single_command(
                prefix,
                inherited_action=inherited_action,
                inherited_device=inherited_device,
                inherited_location=inherited_location,
            )
            if not prefix_command:
                # 前缀夹杂噪声时，尝试截取最后一个动作词之后的尾部再解析。
                tail_prefix = self._extract_action_tail(prefix)
                if tail_prefix and tail_prefix != prefix:
                    prefix_command = self._parse_single_command(
                        tail_prefix,
                        inherited_action=inherited_action,
                        inherited_device=inherited_device,
                        inherited_location=inherited_location,
                    )
            if not prefix_command or not prefix_command.action or not prefix_command.device:
                continue

            suffix_command = self._parse_single_command(
                suffix,
                inherited_action=prefix_command.action or inherited_action,
                inherited_device=prefix_command.device or inherited_device,
                inherited_location=prefix_command.location or inherited_location,
            )
            suffix_commands: List[Command] = []
            if suffix_command:
                suffix_commands = [suffix_command]
            else:
                suffix_commands = self._recover_commands_from_noisy_segment(
                    suffix,
                    inherited_action=prefix_command.action or inherited_action,
                    inherited_device=prefix_command.device or inherited_device,
                    inherited_location=prefix_command.location or inherited_location,
                )
            if not suffix_commands:
                continue

            deduped_commands: List[Command] = []
            seen_signatures: Set[Tuple[str, str, str, str, str, str]] = set()

            for candidate in [prefix_command, *suffix_commands]:
                signature = (
                    candidate.action,
                    candidate.location,
                    candidate.device,
                    candidate.parameter,
                    candidate.value,
                    candidate.unit,
                )
                if signature in seen_signatures:
                    continue
                seen_signatures.add(signature)
                deduped_commands.append(candidate)

            if deduped_commands:
                return deduped_commands

        return []

    def _extract_action_tail(self, text: str) -> str:
        """提取最后一个动作词起始的尾部，便于从噪声前缀中恢复有效命令。"""
        if not text:
            return ""
        matches = list(self._action_pattern.finditer(text))
        if not matches:
            return ""
        last = matches[-1]
        return text[last.start():].strip(" ，,；;")

    def _inherit_location_for_parameter_commands(self, commands: List[Command]) -> List[Command]:
        """对无位置的参数设定命令，继承最近同设备位置。"""
        if not commands:
            return []

        inherited_commands: List[Command] = []
        last_location_by_device: Dict[str, str] = {}
        last_location_by_category: Dict[str, str] = {}
        set_like_actions = {"设置为", "调高", "调低", "调亮", "调暗", "把调高", "把调低", "把调亮", "把调暗"}

        for command in commands:
            cmd = command
            device = (cmd.device or "").strip()
            category = self._device_category_map.get(device, "")
            is_parameter_command = bool(cmd.parameter or cmd.value or cmd.unit) or cmd.action in set_like_actions

            if not cmd.location and device and is_parameter_command:
                inherited_location = (
                    last_location_by_device.get(device)
                    or (last_location_by_category.get(category) if category else "")
                )
                if inherited_location:
                    cmd = Command(
                        action=cmd.action,
                        device=cmd.device,
                        location=inherited_location,
                        parameter=cmd.parameter,
                        value=cmd.value,
                        unit=cmd.unit,
                        confidence=cmd.confidence,
                    )

            if cmd.location and device:
                last_location_by_device[device] = cmd.location
                if category:
                    last_location_by_category[category] = cmd.location

            inherited_commands.append(cmd)

        return inherited_commands

    def _deduplicate_less_specific_commands(self, commands: List[Command]) -> List[Command]:
        """去重：同一核心命令下，优先保留带位置的更具体指令。"""
        if not commands:
            return []

        deduped: List[Command] = []
        for command in commands:
            skip_current = False
            replace_index: Optional[int] = None

            for idx, kept in enumerate(deduped):
                same_core = (
                    command.action == kept.action
                    and command.device == kept.device
                    and command.parameter == kept.parameter
                    and command.value == kept.value
                    and command.unit == kept.unit
                )
                if not same_core:
                    continue

                if command.location == kept.location:
                    skip_current = True
                    break
                if not command.location and kept.location:
                    skip_current = True
                    break
                if command.location and not kept.location:
                    replace_index = idx
                    break

            if skip_current:
                continue
            if replace_index is not None:
                deduped[replace_index] = command
            else:
                deduped.append(command)

        return deduped

    def _preprocess(self, text: str) -> str:
        """
        预处理文本：去除填充词

        Args:
            text: 原始文本

        Returns:
            清理后的文本
        """
        cleaned = text

        # 1. 去除脏词及其变体
        cleaned = self._remove_dirty_words_with_variants(cleaned)

        # 2. 去除连续填充字符（保留单个）
        cleaned = self._remove_consecutive_filler_chars(cleaned)

        # 3. 去除首尾填充词簇（但不包括开头的空格）
        # 先去除空格
        cleaned = cleaned.strip()

        # 去除首尾填充字符
        if self.FILLER_CHARS:
            cleaned = re.sub(r'^[{0}]{{2,}}'.format(re.escape(self.FILLER_CHARS)), '', cleaned)
            cleaned = re.sub(r'[{0}]{{2,}}$'.format(re.escape(self.FILLER_CHARS)), '', cleaned)

        # 4. 去除多余的"的"（脏词去除后可能遗留）
        cleaned = self._remove_extra_de(cleaned)

        # 5. 去除礼貌请求前缀，避免"请帮我打开客厅灯"之类口语阻断规则命中
        cleaned = self._remove_polite_request_prefixes(cleaned)

        # 6. 归一化动作别名（多字动作）
        cleaned = self._normalize_action_aliases(cleaned)

        # 7. 口语化数字/单位/时间表达规范化
        cleaned = self._normalize_numeric_expressions(cleaned)

        # 8. 去除多余空格（但保留单个空格用于分隔）
        cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()

        return cleaned

    def _remove_polite_request_prefixes(self, text: str) -> str:
        """去除句首礼貌请求前缀，只处理明显不承载设备语义的固定短语。"""
        if not text:
            return text

        cleaned = text.strip()
        prefix_patterns = [
            r'^(?:请帮我|麻烦帮我|麻烦你帮我|帮我|麻烦你|麻烦|请你|请)\s*',
            r'^(?:请帮忙|帮忙)\s*',
        ]
        changed = True
        while changed and cleaned:
            changed = False
            for pattern in prefix_patterns:
                updated = re.sub(pattern, '', cleaned)
                if updated != cleaned:
                    cleaned = updated.strip()
                    changed = True
        return cleaned

    def _normalize_numeric_expressions(self, text: str) -> str:
        """规范化口语化数字、单位和简单时间表达。"""
        if not text:
            return text

        normalized = text
        normalized = re.sub(
            r'([零〇一二三四五六七八九十百两\d])\s+([零〇一二三四五六七八九十百两\d])',
            r'\1\2',
            normalized,
        )

        normalized = re.sub(
            r'百分之([零〇一二三四五六七八九十百两\d]+)',
            lambda m: f"{self._normalize_spoken_number_token(m.group(1))}%",
            normalized,
        )

        normalized = re.sub(
            r'([零〇一二三四五六七八九十百两\d]+)(摄氏度|度|分钟|小时|天|分|级|档)',
            lambda m: f"{self._normalize_spoken_number_token(m.group(1))}{m.group(2)}",
            normalized,
        )

        normalized = re.sub(
            r'((?:每天|每晚|每早|每日|工作日|周末|今晚|明早|明天|今天|早上|上午|中午|下午|晚上|凌晨)?)([零〇一二三四五六七八九十百两\d]+)点([零〇一二三四五六七八九十百两\d]+)?分?',
            lambda m: (
                f"{m.group(1)}{self._normalize_spoken_number_token(m.group(2))}点"
                f"{self._normalize_spoken_number_token(m.group(3)) if m.group(3) else ''}"
                f"{'分' if m.group(3) else ''}"
            ),
            normalized,
        )

        normalized = re.sub(
            r'((?:亮度|灯光|窗帘|开合|风速|档位|等级|级别)(?:调到|设到|设置为|设置成|调为|调成)?)([零〇一二三四五六七八九两]{2,3})(?![度%％级档分点小时天])',
            lambda m: f"{m.group(1)}{self._normalize_spoken_number_token(m.group(2))}",
            normalized,
        )
        normalized = re.sub(
            r'((?:亮度|灯光|开合|风速|档位|等级|级别)(?:调到|设到|设置为|设置成|调为|调成)?)(\d{1,3})(?![%％度级档分点小时天])',
            lambda m: f"{m.group(1)}{m.group(2)}{self._infer_unit_from_parameter_kind(self._infer_parameter_kind(m.group(1), m.group(1)))}",
            normalized,
        )

        return normalized

    def _normalize_spoken_number_token(self, token: Optional[str]) -> str:
        """将口语化数字 token 归一为阿拉伯数字字符串。"""
        if not token:
            return ""
        token = re.sub(r"\s+", "", str(token))
        if not token:
            return ""
        if token.isdigit():
            return token

        cn_chars = set(self.CN_DIGIT_MAP) | set(self.CN_UNIT_MAP)
        if all(ch in self.CN_DIGIT_MAP for ch in token):
            return "".join(str(self.CN_DIGIT_MAP[ch]) for ch in token)
        if not all(ch in cn_chars for ch in token):
            return token

        total = 0
        section = 0
        number = 0
        for ch in token:
            if ch in self.CN_DIGIT_MAP:
                number = self.CN_DIGIT_MAP[ch]
                continue
            unit = self.CN_UNIT_MAP.get(ch)
            if unit is None:
                return token
            if unit == 10000:
                section = (section + (number or 0)) * unit
                total += section
                section = 0
            else:
                section += (number or 1) * unit
            number = 0
        total += section + number
        return str(total) if total else token

    def _infer_unit_from_parameter_kind(self, parameter_kind: Optional[str], text: str = "") -> Optional[str]:
        """按参数类型推断缺失单位。"""
        if not parameter_kind:
            return None
        if parameter_kind == "temperature":
            return "度"
        if parameter_kind in ("brightness", "ratio"):
            return "%"
        if parameter_kind in ("speed", "level"):
            if any(token in text for token in ("风速", "档", "档位")):
                return "级"
            return self.PARAMETER_DEFAULT_UNIT.get(parameter_kind)
        return self.PARAMETER_DEFAULT_UNIT.get(parameter_kind)

    def _is_value_out_of_range(self, parameter_kind: Optional[str], value_raw: Optional[str]) -> bool:
        """按参数类型判断数值是否超出合理范围。"""
        if not parameter_kind or not value_raw:
            return False
        try:
            value = float(value_raw)
        except (TypeError, ValueError):
            return False
        range_config = self.PARAMETER_VALUE_RANGE.get(parameter_kind)
        if not range_config:
            return False
        low, high = range_config
        return value < low or value > high

    def _remove_dirty_words_with_variants(self, text: str) -> str:
        """去除脏词及其变体（使用预编译正则，IGNORECASE）"""
        # 注意：_dirty_variants_pattern 包含所有脏词（拼音+中文），优先使用它
        # _filler_phrase_pattern 可能包含部分重叠词，放在后面处理
        cleaned = self._dirty_variants_pattern.sub('', text)
        cleaned = self._filler_phrase_pattern.sub('', cleaned)
        return re.sub(r'\s+', ' ', cleaned).strip()

    def _remove_consecutive_filler_chars(self, text: str) -> str:
        """去除连续填充字符（>3个保留1个，≤3个全部删除），单次扫描"""
        return self._filler_char_pattern.sub(
            lambda m: m.group()[0] if len(m.group()) > 3 else '',
            text,
        )

    def _remove_extra_de(self, text: str) -> str:
        """
        去除多余的"的"（脏词去除后可能遗留）

        Args:
            text: 待处理文本

        Returns:
            处理后的文本
        """
        cleaned = text

        # 模式1: 动作词 + "的" → 去除"的"
        # 例如："开tmd的" → "开"
        action_patterns = [
            r'打开的', r'关闭的', r'开启的',
            r'关掉的', r'停止的', r'点亮的',
            r'调高的', r'调低的', r'调亮的', r'调暗的',
            r'设置的', r'调成的',
        ]
        for pattern in action_patterns:
            cleaned = re.sub(pattern, pattern.replace('的', ''), cleaned)

        # 模式2: "把" + 变体 + "的" → "把"
        # 例如："把tmdd的" → "把"
        # 匹配 "把" + 任意数字/字母组合 + "的"
        cleaned = re.sub(r'把[a-z]*\d+[a-z]*\d*\的', r'把', cleaned, flags=re.IGNORECASE)

        # 模式3: 设备词前 + 脏词 + "的" → 设备词
        # 例如："射灯tmd的" → "射灯"
        device_pattern = r'(灯|窗帘|空调|电视|音响|系统)[a-z]*\d+[a-z]*\d*\的'
        cleaned = re.sub(device_pattern, lambda m: m.group(1), cleaned, flags=re.IGNORECASE)

        return cleaned

    def _split_commands(self, text: str) -> List[str]:
        """
        分割多指令

        优先级：分号 > 连接词 > 逗号

        Args:
            text: 输入文本

        Returns:
            指令段列表
        """
        raw_segments = [seg.strip() for seg in self._command_split_pattern.split(text) if seg and seg.strip()]
        if not raw_segments:
            return []
        return self._decompose_compound_segments(self._merge_split_segments(raw_segments))

    def extract_semantic_blocks(self, text: str, preprocess: bool = True) -> List[str]:
        """抽取适合缓存和局部解析的语义块。"""
        if not text or not text.strip():
            return []
        working_text = self._preprocess(text) if preprocess else text.strip()
        segments = [seg for seg in self._split_commands(working_text) if seg and seg.strip()]
        if not segments:
            return []

        expanded: List[str] = []
        for seg in segments:
            mixed_commands = self._parse_mixed_ba_segment(seg)
            if mixed_commands:
                expanded.extend(str(cmd) for cmd in mixed_commands if str(cmd).strip())
                continue

            clause = self._analyze_clause(seg)
            if clause.clause_type not in {"noisy_clause", "unknown"}:
                expanded.append(seg)
                continue

            recovered_commands = self._recover_commands_from_noisy_segment(seg)
            if recovered_commands:
                expanded.extend(str(cmd) for cmd in recovered_commands if str(cmd).strip())
            else:
                expanded.append(seg)

        return expanded

    def _merge_split_segments(self, segments: List[str]) -> List[str]:
        """
        合并切分后明显不完整的片段，减少误切分导致的信息丢失。
        """
        merged: List[str] = []
        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue
            if not merged:
                merged.append(seg)
                continue

            # 单字残片或纯参数片段并回前一条
            if len(seg) <= 1:
                merged[-1] = f"{merged[-1]}{seg}"
                continue
            if self._value_pattern.fullmatch(seg):
                merged[-1] = f"{merged[-1]}{seg}"
                continue

            merged.append(seg)
        return merged

    def _split_by_comma(self, text: str) -> List[str]:
        """按逗号分割文本（智能处理）"""
        segments = text.split('，')
        if len(segments) <= 1:
            return segments

        # 检查是否应该合并某些段
        merged_segments = []
        for i, seg in enumerate(segments):
            seg = seg.strip()
            if i == 0:
                # 第一段，总是保留
                merged_segments.append(seg)
            else:
                prev = merged_segments[-1].strip()
                # 如果前一段很短且没有完整指令，尝试合并
                if len(prev) < 5 and not self._is_complete_command(prev):
                    merged_segments[-1] = f"{prev}，{seg}"
                else:
                    merged_segments.append(seg)
        return merged_segments

    def _is_complete_command(self, text: str) -> bool:
        """
        检查文本是否是完整指令

        Args:
            text: 文本

        Returns:
            是否完整
        """
        clause = self._analyze_clause(text)
        return clause.clause_type == "complete_command"

    def _analyze_clause(self, text: str) -> ClauseSegment:
        """分析候选片段的槽位和成形类型。"""
        clean_text = self._normalize_action_aliases((text or "").strip())
        if not clean_text:
            return ClauseSegment(text="")

        location = self._extract_location(clean_text)
        device = self._extract_device(clean_text, location=location)
        parameter, value_raw, unit_raw = self._extract_parameter_components(clean_text)
        action = self._extract_action(clean_text)
        condition = self._extract_condition_clause(clean_text)
        time_expr = self._extract_time_expression(clean_text)

        has_value_payload = bool(parameter or value_raw or unit_raw)
        clause_type = "unknown"

        if condition and (action or device or parameter or value_raw or unit_raw):
            clause_type = "complete_command"
        elif time_expr and (action or device or parameter or value_raw or unit_raw):
            clause_type = "complete_command"
        elif condition or (time_expr and not (action or device)):
            clause_type = "modifier_clause"
        elif action and device:
            clause_type = "complete_command"
        elif device and (parameter or value_raw):
            clause_type = "dependent_clause"
        elif action and (parameter or value_raw):
            clause_type = "dependent_clause"
        elif device:
            clause_type = "dependent_clause"
        elif has_value_payload:
            clause_type = "dependent_clause"

        if clause_type in ("complete_command", "dependent_clause") and self._has_unparsed_core_fragment(
            clean_text,
            action,
            location,
            device,
            parameter,
            value_raw,
            unit_raw,
        ):
            clause_type = "noisy_clause"

        return ClauseSegment(
            text=clean_text,
            clause_type=clause_type,
            action=action,
            location=location,
            device=device,
            parameter=parameter,
            value=value_raw or "",
            unit=unit_raw or "",
        )

    def _decompose_compound_segments(self, segments: List[str]) -> List[str]:
        """对切分后的候选片段做二次拆解与修复。"""
        if not segments:
            return []

        analyzed = [self._analyze_clause(seg) for seg in segments if seg and seg.strip()]
        if not analyzed:
            return []

        decomposed: List[ClauseSegment] = []
        for idx, clause in enumerate(analyzed):
            text = clause.text.strip()
            if not text:
                continue

            # 纯修饰片段优先并回后一段，例如"如果下雨" + "关闭窗帘"
            if clause.clause_type == "modifier_clause" and idx + 1 < len(analyzed):
                next_text = analyzed[idx + 1].text.strip()
                analyzed[idx + 1] = self._analyze_clause(f"{text}{next_text}")
                continue

            # 句首动作共享：如"打开客厅灯和卧室空调"
            if decomposed:
                prev = decomposed[-1]
                self._forward_fill_shared_clause(prev, clause)

                # 句尾共享动作/参数回填：如"客厅灯和卧室空调打开""客厅灯和卧室灯调到50%"
                if clause.clause_type == "complete_command" and clause.action:
                    backfill_index = len(decomposed) - 1
                    while backfill_index >= 0:
                        prev_clause = decomposed[backfill_index]
                        if not self._backfill_shared_clause(prev_clause, clause):
                            break
                        backfill_index -= 1

            decomposed.append(clause)

        # 再做一次尾部修复：单独参数片段归为独立子句，交给后续继承补槽
        return [clause.text for clause in decomposed if clause.text]

    def _forward_fill_shared_clause(self, prev_clause: ClauseSegment, clause: ClauseSegment) -> None:
        """把前一段已知动作/位置前向补给后一段。"""
        if clause.clause_type == "noisy_clause" or prev_clause.clause_type == "noisy_clause":
            return
        if not clause.device:
            return

        changed = False
        if not clause.action and prev_clause.action:
            clause.action = prev_clause.action
            changed = True
        if not clause.location and prev_clause.location:
            followup_markers = ("它", "这个", "那个", "再", "也", "继续")
            possessive_markers = ("我的", "你的", "他的", "她的", "它的")
            if (
                not clause.device
                or (prev_clause.device and clause.device == prev_clause.device)
                or any(marker in clause.text for marker in followup_markers)
            ) and not any(marker in clause.text for marker in possessive_markers):
                clause.location = prev_clause.location
                changed = True

        if changed:
            clause.clause_type = "complete_command" if clause.action and clause.device else "dependent_clause"
            clause.text = self._render_clause_segment_text(clause)

    def _backfill_shared_clause(self, prev_clause: ClauseSegment, clause: ClauseSegment) -> bool:
        """把后一段的共享动作/设备/参数回填给前面的并列片段。"""
        if clause.clause_type == "noisy_clause" or prev_clause.clause_type == "noisy_clause":
            return False
        shareable_prefix = (
            (prev_clause.device and not prev_clause.action) or
            (prev_clause.location and not prev_clause.device) or
            (prev_clause.action and not prev_clause.device)
        )
        if not shareable_prefix or not clause.action or not clause.device:
            return False

        if not prev_clause.action:
            prev_clause.action = clause.action
        if not prev_clause.device:
            prev_clause.device = clause.device

        if clause.parameter or clause.value or clause.unit:
            shared_parameter = self._normalize_shared_parameter_for_device(
                prev_clause.device,
                clause.parameter,
                clause.value,
                clause.unit,
            )
            if shared_parameter and not prev_clause.parameter:
                prev_clause.parameter = shared_parameter
            if clause.value and not prev_clause.value:
                prev_clause.value = clause.value
            if clause.unit and not prev_clause.unit:
                prev_clause.unit = clause.unit

        if prev_clause.action and prev_clause.device:
            prev_clause.clause_type = "complete_command"
        elif prev_clause.device or prev_clause.location or prev_clause.action:
            prev_clause.clause_type = "dependent_clause"
        prev_clause.text = self._render_clause_segment_text(prev_clause)
        return prev_clause.clause_type == "complete_command"

    def _render_clause_segment_text(self, clause: ClauseSegment) -> str:
        """把补槽后的子句渲染成更稳定的规范文本。"""
        parts: List[str] = []
        if clause.action:
            parts.append(self._canonicalize_action(clause.action))
        if clause.location:
            parts.append(clause.location)
        if clause.device:
            parts.append(clause.device)
        if clause.value:
            parameter_display = self._parameter_display_text(clause.parameter)
            if parameter_display:
                parts.append(parameter_display)
            parts.append(clause.value)
            if clause.unit:
                parts.append(clause.unit)
        elif clause.parameter:
            parts.append(self._parameter_display_text(clause.parameter))
        return "".join(parts) or clause.text

    def _parameter_display_text(self, parameter: str) -> str:
        """将参数标识渲染成人类可读的稳定文本。"""
        display_map = {
            "temperature": "温度",
            "brightness": "亮度",
            "color": "颜色",
            "speed": "风速",
            "level": "档位",
            "power_state": "",
            "device_state": "",
            "ratio": "",
        }
        return display_map.get(parameter, parameter or "")

    def _normalize_shared_parameter_for_device(
        self,
        device: str,
        parameter: str,
        value: str,
        unit: str,
    ) -> str:
        """按目标设备归一共享参数，避免把灯的 50% 保留成开合比例。"""
        parameter_kind = self._infer_parameter_kind(f"{parameter}{value}{unit}", parameter or "")
        if not parameter_kind:
            return parameter

        device_category = self._device_category_map.get(device, "")
        if parameter_kind == "ratio" and device_category == "light":
            return "brightness"
        if parameter_kind == "temperature":
            return "temperature"
        if parameter_kind == "brightness":
            return "brightness"
        if parameter_kind == "speed":
            return "speed"
        if parameter_kind == "color":
            return "color"
        if parameter_kind == "level":
            return "level"
        return parameter or parameter_kind

    def _extract_action(self, text: str) -> str:
        """抽取动作词（优先最早位置，其次最长匹配）。"""
        matches: List[Tuple[int, int, str]] = []
        for action in self.hot_words.action_set:
            idx = text.find(action)
            if idx >= 0:
                matches.append((idx, -len(action), action))
        if matches:
            matches.sort()
            return matches[0][2]

        # 设备状态后缀：如"客厅灯开"
        state_suffix_map = {
            "开": "打开",
            "关": "关闭",
            "亮": "调亮",
            "暗": "调暗",
            "高": "调高",
            "低": "调低",
        }
        if text and text[-1] in state_suffix_map:
            prefix = text[:-1]
            if any(device in prefix for device in self.hot_words.device_set):
                return state_suffix_map[text[-1]]
        return ""

    def _is_cjk_char(self, char: str) -> bool:
        return bool(char) and '\u4e00' <= char <= '\u9fff'

    def _find_best_slot_term(self, text: str, terms: Set[str], slot_kind: str) -> str:
        """按最长优先、最早出现为辅的规则选择稳定槽位词。"""
        candidates: List[Tuple[int, int, str]] = []
        for term in terms:
            start = text.find(term)
            while start >= 0:
                end = start + len(term)
                if not self._should_block_slot_term(text, start, end, term, slot_kind):
                    candidates.append((-len(term), start, term))
                start = text.find(term, start + 1)

        if not candidates:
            return ""

        candidates.sort()
        return candidates[0][2]

    def _should_block_slot_term(
        self,
        text: str,
        start: int,
        end: int,
        term: str,
        slot_kind: str,
    ) -> bool:
        left = text[start - 1] if start > 0 else ""
        right = text[end] if end < len(text) else ""
        following = text[end:]

        if slot_kind == "parameter":
            if term in self.hot_words.action_set:
                return True
            if len(term) == 1 and self._is_cjk_char(left):
                return True
            return False

        if slot_kind == "location":
            if len(term) == 1 and term in {"东", "西", "南", "北", "左", "右"}:
                if right and self._is_cjk_char(right):
                    if not any(
                        following.startswith(prefix)
                        for prefix in ("边", "侧", "面", "门", "区", "翼", "廊")
                    ):
                        return True
            return False

        if slot_kind != "device":
            return False

        if len(term) > 2 or not self._is_cjk_char(right):
            return False

        if any(
            following.startswith(prefix)
            for prefix in (
                "的", "开", "关", "调", "设", "到", "成", "为", "亮", "暗", "高", "低",
                "温度", "亮度", "颜色", "风速", "档位", "状态", "开合",
            )
        ):
            return False
        if any(following.startswith(action) for action in self.hot_words.action_set):
            return False
        if right.isdigit():
            return False
        return True

    def _looks_like_unknown_device_phrase(
        self,
        text: str,
        action: str,
        location: str,
        current_device: str,
    ) -> bool:
        """已有设备未命中时，避免把未知设备短语误兜底成默认设备。"""
        if current_device:
            return False

        payload = self._extract_device_residue_payload(text, action, location)
        if not payload:
            return False
        # 未知短残片（如"空"）不应触发默认设备兜底。
        if len(payload) <= 2 and any(self._is_cjk_char(char) for char in payload):
            return True
        if any(payload.endswith(suffix) for suffix in ("系统", "模式", "场景", "面板", "设备")):
            return True
        return any(char in payload for char in "灯帘调风系统锁屏机门")

    def _extract_device_residue_payload(self, text: str, action: str, location: str) -> str:
        """提取去掉动作/位置/数值后的设备残片。"""
        payload = (text or "").strip()
        for token in filter(None, [action, location]):
            payload = payload.replace(token, "")
        payload = re.sub(
            r"(把|的|到|调到|调为|设置|设置为|设置成|调成|变成|保持|"
            r"百分之[一二三四五六七八九十百两\d]+|\d+(?:\.\d+)?|摄氏度|度|%|％)",
            "",
            payload,
        )
        return payload.strip()

    def _build_char_homophone_index(self) -> Dict[str, int]:
        """构建字符到同音组 ID 的映射。"""
        index: Dict[str, int] = {}
        for gid, group in enumerate(self._DOMAIN_HOMOPHONE_GROUPS):
            for char in group:
                index[char] = gid
        return index

    def _char_homophone_ratio(self, left: str, right: str) -> float:
        """按位置计算同音/同字比例（仅等长）。"""
        if not left or not right or len(left) != len(right):
            return 0.0
        matched = 0
        for left_char, right_char in zip(left, right):
            if left_char == right_char:
                matched += 1
                continue
            left_gid = self._char_homophone_index.get(left_char)
            right_gid = self._char_homophone_index.get(right_char)
            if left_gid is not None and left_gid == right_gid:
                matched += 1
        return matched / len(left)

    def _to_pinyin_tokens(self, text: str) -> Tuple[str, ...]:
        """将文本转换为拼音 token 序列（无 pypinyin 时回退到字符序列）。"""
        payload = (text or "").strip()
        if not payload:
            return tuple()
        cached = self._pinyin_cache.get(payload)
        if cached is not None:
            return cached

        if pypinyin is not None:
            tokens = tuple(pypinyin.lazy_pinyin(payload))
        else:
            tokens = tuple(payload)
        self._pinyin_cache[payload] = tokens
        return tokens

    def _pinyin_similarity(self, left: str, right: str) -> float:
        """计算两段文本的拼音相似度。"""
        left_tokens = self._to_pinyin_tokens(left)
        right_tokens = self._to_pinyin_tokens(right)
        if not left_tokens or not right_tokens:
            return 0.0
        return SequenceMatcher(None, " ".join(left_tokens), " ".join(right_tokens)).ratio()

    def _fragment_infer_threshold(self, fragment_len: int) -> float:
        """不同残片长度使用不同放行阈值。"""
        if fragment_len <= 1:
            return 0.86
        if fragment_len == 2:
            return 0.66
        if fragment_len == 3:
            return 0.66
        return 0.60

    def _score_device_fragment_candidate(
        self,
        fragment: str,
        candidate: str,
        action: str,
        parameter_kind: Optional[str],
        category_priority: Dict[str, int],
    ) -> float:
        """对设备候选进行综合打分（前缀/编辑距离/拼音/能力约束）。"""
        if not fragment or not candidate:
            return 0.0

        prefix_bonus = 0.28 if candidate.startswith(fragment) else 0.0
        contains_bonus = 0.12 if (fragment in candidate and not candidate.startswith(fragment)) else 0.0
        char_similarity = SequenceMatcher(None, fragment, candidate).ratio()
        pinyin_similarity = self._pinyin_similarity(fragment, candidate)
        homophone_ratio = self._char_homophone_ratio(fragment, candidate[:len(fragment)])
        capability_bonus = 0.08 if self._device_supports_parameter(candidate, parameter_kind or "power_state") else 0.0
        category = self._device_category_map.get(candidate, "")
        category_rank = category_priority.get(category, 99)
        category_bonus = max(0.0, 0.07 - category_rank * 0.02) if category_rank < 4 else 0.0
        length_penalty = min(abs(len(candidate) - len(fragment)) * 0.03, 0.15)

        score = (
            0.42 * char_similarity
            + 0.36 * pinyin_similarity
            + 0.18 * homophone_ratio
            + prefix_bonus
            + contains_bonus
            + capability_bonus
            + category_bonus
            - length_penalty
        )
        return max(0.0, min(1.0, score))

    def _infer_device_from_fragment(
        self,
        fragment: str,
        action: str,
        parameter_kind: Optional[str],
    ) -> Tuple[str, float, str]:
        """从未知设备残片推断设备（支持前缀/近似拼音）。"""
        payload = (fragment or "").strip()
        if not payload:
            return "", 0.0, "empty_fragment"
        if len(payload) > 6 or any(not self._is_cjk_char(char) for char in payload):
            return "", 0.0, "fragment_out_of_scope"

        candidates: Set[str] = set()
        for device in self.hot_words.device_set:
            if payload.startswith(device):
                candidates.add(device)
                continue
            if device.startswith(payload) or payload in device:
                candidates.add(device)
        for alias, canonical in self._device_aliases.items():
            if payload.startswith(alias):
                candidates.add(canonical)
                continue
            if alias.startswith(payload) or payload in alias:
                candidates.add(canonical)

        if not candidates:
            relaxed_candidates: Set[str] = set()
            for device in self.hot_words.device_set:
                char_similarity = SequenceMatcher(None, payload, device).ratio()
                pinyin_similarity = self._pinyin_similarity(payload, device)
                homophone_ratio = self._char_homophone_ratio(payload, device[:len(payload)])
                if max(char_similarity, pinyin_similarity, homophone_ratio) >= 0.68:
                    relaxed_candidates.add(device)
            candidates = relaxed_candidates
            if not candidates:
                return "", 0.0, "no_candidate"

        category_priority = {
            category: idx
            for idx, category in enumerate(
                self._candidate_device_categories(payload, parameter_kind, action)
            )
        }

        scored_candidates: List[Tuple[float, str]] = []
        for candidate in candidates:
            score = self._score_device_fragment_candidate(
                payload,
                candidate,
                action,
                parameter_kind,
                category_priority,
            )
            scored_candidates.append((score, candidate))
        scored_candidates.sort(key=lambda item: (-item[0], len(item[1]), item[1]))

        best_score, best_candidate = scored_candidates[0]
        min_threshold = self._fragment_infer_threshold(len(payload))
        if best_score < min_threshold:
            return "", best_score, "score_too_low"

        infer_mode = "prefix" if best_candidate.startswith(payload) else "fuzzy"
        confidence = max(0.70, min(0.96, best_score))
        return best_candidate, confidence, infer_mode

    def _infer_device_from_short_fragment(
        self,
        fragment: str,
        action: str,
        parameter_kind: Optional[str],
    ) -> str:
        """兼容旧接口：返回短残片推断设备。"""
        inferred_device, _, _ = self._infer_device_from_fragment(fragment, action, parameter_kind)
        return inferred_device

    def _has_unparsed_core_fragment(
        self,
        text: str,
        action: str,
        location: str,
        device: str,
        parameter: str,
        value_raw: Optional[str],
        unit_raw: Optional[str],
        extra_consumed_tokens: Optional[List[str]] = None,
    ) -> bool:
        """槽位抽取后若仍残留中文核心片段，则认为解析不稳。"""
        residue = (text or "").strip()
        for token in filter(None, [action, location, device, parameter, value_raw, unit_raw]):
            residue = residue.replace(token, "", 1)
        for token in extra_consumed_tokens or []:
            if token:
                residue = residue.replace(token, "", 1)
        residue = re.sub(r"(把|将|的|到|为|成|设置|设置为|设置成|调到|调为|调成)", "", residue)
        residue = re.sub(r"[，。、；：？！\s]", "", residue)
        residue = re.sub(r"[\d一二三四五六七八九十百两%％]+", "", residue)
        # "我的/你的/他的..."是所属代词，不是位置槽位。
        # 对短句如"打开我的射灯"，若设备已明确且仅残留单个代词，允许通过。
        if (
            residue in {"我", "你", "他", "她", "它"}
            and device in self.hot_words.device_set
            and not parameter
            and not value_raw
            and not unit_raw
        ):
            return False
        if any(token in residue for token in ("我", "你", "他", "她", "它", "咱", "俺")):
            return True
        return len(residue) >= 2

    def _extract_location(self, text: str) -> str:
        static_location = self._find_best_slot_term(text, self.hot_words.location_set, "location")
        dynamic_location = self._find_dynamic_floor_location(text)
        return self._pick_preferred_location(text, static_location, dynamic_location)

    def _extract_device(self, text: str, location: str = "") -> str:
        # 优先抽取与位置绑定的设备
        if location:
            location_bound_candidates = {
                device for device in self.hot_words.device_set
                if f"{location}的{device}" in text or f"{location}{device}" in text
            }
            location_bound_device = self._find_best_slot_term(text, location_bound_candidates, "device")
            if location_bound_device:
                return location_bound_device
        # 兜底：最长设备词匹配
        direct_device = self._find_best_slot_term(text, self.hot_words.device_set, "device")
        if direct_device:
            return direct_device
        return self._extract_device_alias(text, location=location)

    def _extract_device_alias(self, text: str, location: str = "") -> str:
        """在设备热词未命中时，按别名命中设备词。"""
        if not self._device_aliases:
            return ""
        alias_terms = set(self._device_aliases.keys())
        if location:
            location_bound_alias = {
                alias for alias in alias_terms
                if f"{location}的{alias}" in text or f"{location}{alias}" in text
            }
            location_alias = self._find_best_slot_term(text, location_bound_alias, "device")
            if location_alias:
                return location_alias
        matched_alias = self._find_best_slot_term(text, alias_terms, "device")
        if not matched_alias:
            return ""
        return matched_alias

    def _extract_parameter(self, text: str) -> str:
        # 优先抽取参数名
        return self._find_best_slot_term(text, self.hot_words.parameter_set, "parameter")

    def _strip_time_fragments_for_value_parse(self, text: str) -> str:
        """去除时间表达，避免把定时数字误抽成参数值。"""
        if not text:
            return text
        stripped = text
        patterns = [
            r'(?:每周[一二三四五六日天]|周[一二三四五六日天])(?:早上|上午|中午|下午|晚上|凌晨)?\d{1,2}点(?:\d{1,2}分?)?',
            r'(?:每天|每晚|每早|每日|工作日|周末|今晚|明早|明天|今天|早上|上午|中午|下午|晚上|凌晨)?\d{1,2}点(?:\d{1,2}分?)?',
            r'(?:每天|每晚|每早|每日|工作日|周末|今晚|明早|明天|今天|早上|上午|中午|下午|晚上|凌晨)?\d{1,2}[:：]\d{1,2}',
            r'\d+\s*(?:分钟|小时|天)后',
        ]
        for pattern in patterns:
            stripped = re.sub(pattern, "", stripped)
        return stripped

    def _extract_parameter_components(self, text: str) -> Tuple[str, Optional[str], Optional[str]]:
        """抽取参数名、值、单位。"""
        parameter = self._extract_parameter(text)
        text_for_value = self._strip_time_fragments_for_value_parse(text)
        value_raw, unit_raw = self._extract_value_and_unit(text_for_value)
        inferred_kind = self._infer_parameter_kind(text, text) or ""

        value_like_parameter = False
        if parameter:
            parameter_category = self._parameter_category_map.get(parameter, "")
            if value_raw and (parameter == f"{value_raw}{unit_raw or ''}" or parameter == value_raw):
                value_like_parameter = True
            elif parameter in ("度", "摄氏度", "%", "％", "一半", "全开", "全关"):
                value_like_parameter = True
            elif parameter_category in ("ratio", "level", "temperature") and parameter not in ("温度", "亮度", "颜色", "风速", "状态"):
                value_like_parameter = True

        if inferred_kind and (not parameter or value_like_parameter):
            parameter = inferred_kind

        if (parameter == "ratio" or inferred_kind == "ratio") and not value_raw:
            if "一半" in text:
                value_raw, unit_raw = "50", "%"
            elif "全开" in text:
                value_raw, unit_raw = "100", "%"
            elif "全关" in text:
                value_raw, unit_raw = "0", "%"

        parameter_kind = parameter or inferred_kind
        if value_raw and not unit_raw:
            unit_raw = self._infer_unit_from_parameter_kind(parameter_kind, text)

        return parameter_kind, value_raw, unit_raw

    def _device_supports_parameter(self, device: str, parameter_kind: Optional[str]) -> bool:
        """判断设备是否支持某类参数。"""
        device = self._canonicalize_device(device)
        if not device or not parameter_kind:
            return True
        device_category = self._device_category_map.get(device, "")
        supported = self.DEVICE_CAPABILITY_MAP.get(device_category)
        if not supported:
            return True
        return parameter_kind in supported

    def _extract_device_by_categories(
        self,
        text: str,
        categories: List[str],
        location: str = "",
    ) -> str:
        """按设备类别优先抽取设备。"""
        if not categories:
            return ""
        category_set = set(categories)
        candidates = [
            device for device in sorted(self.hot_words.device_set, key=len, reverse=True)
            if self._device_category_map.get(device, "") in category_set
        ]
        if location:
            location_bound_candidates = {
                device for device in candidates
                if f"{location}的{device}" in text or f"{location}{device}" in text
            }
            location_bound_device = self._find_best_slot_term(text, location_bound_candidates, "device")
            if location_bound_device:
                return location_bound_device
        matched_device = self._find_best_slot_term(text, set(candidates), "device")
        if matched_device:
            return matched_device

        if not self._device_aliases:
            return ""
        alias_candidates = {
            alias
            for alias, canonical in self._device_aliases.items()
            if self._device_category_map.get(canonical, "") in category_set
        }
        if location:
            location_bound_alias = {
                alias for alias in alias_candidates
                if f"{location}的{alias}" in text or f"{location}{alias}" in text
            }
            location_alias = self._find_best_slot_term(text, location_bound_alias, "device")
            if location_alias:
                return location_alias
        matched_alias = self._find_best_slot_term(text, alias_candidates, "device")
        if matched_alias:
            return matched_alias
        return ""

    def _candidate_device_categories(
        self,
        text: str,
        parameter_kind: Optional[str],
        action: str = "",
    ) -> List[str]:
        """根据参数和动作推断候选设备类别。"""
        categories: List[str] = []

        def _append(items: List[str]) -> None:
            for item in items:
                if item and item not in categories:
                    categories.append(item)

        def _prepend(items: List[str]) -> None:
            for item in reversed(items):
                if not item:
                    continue
                if item in categories:
                    categories.remove(item)
                categories.insert(0, item)

        _append(self.PARAMETER_TO_DEVICE_HINTS.get(parameter_kind or "", []))
        action_category = self._action_category_map.get(action or "", "")
        _append(self.ACTION_TO_DEVICE_HINTS.get(action_category, []))

        if parameter_kind == "temperature" and any(token in text for token in ("制热", "暖", "热")):
            _prepend(["heater", "ac"])
        if parameter_kind == "temperature" and any(token in text for token in ("制冷", "冷气", "空调")):
            _prepend(["ac"])
        if parameter_kind == "ratio" or any(token in text for token in ("拉开", "拉上", "开合", "一半", "全开", "全关")):
            _prepend(["curtain"])
        if parameter_kind == "brightness" or any(token in text for token in ("亮度", "亮一点", "暗一点", "灯光")):
            _prepend(["light"])
        if parameter_kind == "speed" and any(token in text for token in ("音量", "声音")):
            _prepend(["audio"])

        return categories

    def _resolve_device_by_capability(
        self,
        text: str,
        location: str,
        action: str,
        parameter_kind: Optional[str],
        current_device: str = "",
        allow_default: bool = True,
    ) -> str:
        """使用参数/动作能力约束解析或修正设备。"""
        categories = self._candidate_device_categories(text, parameter_kind, action)

        if current_device and self._device_supports_parameter(current_device, parameter_kind):
            return current_device

        preferred_device = self._extract_device_by_categories(text, categories, location=location)
        if preferred_device:
            return preferred_device

        if current_device:
            return current_device

        if allow_default and categories:
            for category in categories:
                default_device = self.CATEGORY_DEFAULT_DEVICE.get(category, "")
                if default_device:
                    return default_device

        return ""

    def _infer_device_from_context(self, text: str, parameter: str) -> str:
        """在缺失设备时基于参数/上下文补全设备。"""
        parameter_kind = self._infer_parameter_kind(text, parameter)
        action = self._extract_action(text)
        return self._resolve_device_by_capability(
            text=text,
            location=self._extract_location(text),
            action=action,
            parameter_kind=parameter_kind,
            current_device="",
        )

    def _split_location_and_device(self, text: str) -> Tuple[str, str]:
        """把"位置+设备"前缀拆成两个槽位。"""
        location = ""
        device = (text or "").strip()

        for loc_word in sorted(self.hot_words.location_set, key=len, reverse=True):
            if device.startswith(loc_word):
                location = loc_word
                device = device[len(loc_word):].strip()
                break

        if not location:
            dynamic_location = self._match_dynamic_floor_prefix(device)
            if dynamic_location:
                location = dynamic_location
                device = device[len(dynamic_location):].strip()

        if not device and location:
            device = location
            location = ""

        return location, device

    def _find_dynamic_floor_location(self, text: str) -> str:
        """在任意位置抽取楼层模式词，如"四楼""12楼"."""
        candidates: List[Tuple[int, int, str]] = []
        for pattern in (_ARABIC_FLOOR_PATTERN, _CN_FLOOR_PATTERN):
            for match in pattern.finditer(text or ""):
                term = match.group()
                if self._should_block_slot_term(text, match.start(), match.end(), term, "location"):
                    continue
                candidates.append((-len(term), match.start(), term))
        if not candidates:
            return ""
        candidates.sort()
        return candidates[0][2]

    def _match_dynamic_floor_prefix(self, text: str) -> str:
        """在前缀位置匹配楼层模式词。"""
        payload = (text or "").strip()
        for pattern in (_ARABIC_FLOOR_PATTERN, _CN_FLOOR_PATTERN):
            match = pattern.match(payload)
            if match:
                return match.group()
        return ""

    def _pick_preferred_location(self, text: str, *locations: str) -> str:
        """在静态热词和动态楼层之间选择更稳定的位置词。"""
        candidates: List[Tuple[int, int, str]] = []
        for location in locations:
            if not location:
                continue
            start = text.find(location)
            if start < 0:
                continue
            candidates.append((-len(location), start, location))
        if not candidates:
            return ""
        candidates.sort()
        return candidates[0][2]

    def _extract_recovery_anchors(self, text: str) -> List[int]:
        """抽取局部组合恢复用的动作锚点位置。"""
        clean_text = (text or "").strip()
        if not clean_text:
            return []

        anchor_terms = sorted(
            {term for term in self.hot_words.action_set if len(term) >= 2} | {"把"},
            key=len,
            reverse=True,
        )
        anchors: Dict[int, str] = {}
        for term in anchor_terms:
            start = 0
            while True:
                idx = clean_text.find(term, start)
                if idx < 0:
                    break
                prev = anchors.get(idx)
                if prev is None or len(term) > len(prev):
                    anchors[idx] = term
                start = idx + 1

        # 单字动作锚点（如"开/关"）默认不进入主锚点集合，
        # 仅在上下文明确具备设备/位置信号时放行，避免噪声触发。
        for action in self._recovery_single_char_actions:
            start = 0
            while True:
                idx = clean_text.find(action, start)
                if idx < 0:
                    break
                start = idx + 1
                if self._single_char_anchor_covered_by_multi_action(clean_text, idx, action):
                    continue
                if not self._is_valid_single_char_recovery_anchor(clean_text, idx, action):
                    continue
                prev = anchors.get(idx)
                if prev is None or len(action) > len(prev):
                    anchors[idx] = action

        return sorted(anchors.keys())

    def _single_char_anchor_covered_by_multi_action(self, text: str, index: int, action: str) -> bool:
        """单字动作若已被多字动作覆盖，则不重复作为锚点。"""
        for term in self.hot_words.action_set:
            if len(term) <= 1:
                continue
            if term.startswith(action) and text.startswith(term, index):
                return True
            if term.endswith(action):
                start = index - len(term) + 1
                if start >= 0 and text.startswith(term, start):
                    return True
        return False

    def _is_valid_single_char_recovery_anchor(self, text: str, index: int, action: str) -> bool:
        """校验单字动作锚点是否具备命令恢复价值。"""
        if not action or len(action) != 1:
            return False

        tail = (text or "")[index + 1:]
        if not tail:
            return False

        probe = tail[:14]
        location = self._extract_location(probe)
        device = self._extract_device(probe, location=location)
        if device:
            return True

        # 兜底：短窗口内出现典型设备词根时也可放行
        return any(token in probe[:8] for token in ("灯", "空调", "窗帘", "风扇", "门锁", "射灯"))

    def _is_implausible_command_candidate(
        self,
        action: str,
        location: str,
        device: str,
        parameter: str,
        value_raw: Optional[str],
        unit_raw: Optional[str],
    ) -> bool:
        """过滤明显不合理的候选命令，避免噪声误拼装。"""
        canonical_action = self._canonicalize_action(action)
        if canonical_action in ("打开", "关闭") and (parameter or value_raw or unit_raw):
            return True
        if len(location) == 1 and location in {"东", "西", "南", "北", "左", "右"} and (parameter or value_raw):
            return True
        return False

    def _recover_commands_from_noisy_segment(
        self,
        text: str,
        inherited_action: str = "",
        inherited_device: str = "",
        inherited_location: str = "",
    ) -> List[Command]:
        """在解析失败的长噪声片段中，按动作锚点回收局部命令。"""
        clean_text = self._normalize_action_aliases((text or "").strip())
        if len(clean_text) < 6:
            return []

        window_recovered = self._recover_commands_from_anchor_windows(
            clean_text,
            inherited_action=inherited_action,
            inherited_device=inherited_device,
            inherited_location=inherited_location,
        )
        if window_recovered:
            return window_recovered

        anchors = self._extract_recovery_anchors(clean_text)
        if len(anchors) < 2:
            return []

        recovered: List[Command] = []
        seen: Set[Tuple[str, str, str, str, str, str]] = set()
        local_action = inherited_action
        local_device = inherited_device
        local_location = inherited_location

        for idx, start in enumerate(anchors):
            end = anchors[idx + 1] if idx + 1 < len(anchors) else len(clean_text)
            span = clean_text[start:end].strip(" ，,；;")
            if len(span) < 2:
                continue
            command = self._parse_single_command(
                span,
                inherited_action=local_action,
                inherited_device=local_device,
                inherited_location=local_location,
            )
            if not command:
                continue
            if self._is_implausible_command_candidate(
                command.action,
                command.location,
                command.device,
                command.parameter,
                command.value,
                command.unit,
            ):
                continue

            signature = (
                command.action,
                command.location,
                command.device,
                command.parameter,
                command.value,
                command.unit,
            )
            if signature in seen:
                continue
            seen.add(signature)
            recovered.append(command)
            local_action = command.action or local_action
            local_device = command.device or local_device
            local_location = command.location or local_location

        return recovered

    def _recover_commands_from_anchor_windows(
        self,
        clean_text: str,
        inherited_action: str = "",
        inherited_device: str = "",
        inherited_location: str = "",
    ) -> List[Command]:
        """基于动作锚点 + 低歧义设备锚点的局部窗口恢复。"""
        candidates = self._collect_anchor_window_candidates(
            clean_text,
            inherited_action=inherited_action,
            inherited_device=inherited_device,
            inherited_location=inherited_location,
        )
        if not candidates:
            return []

        return self._select_recovery_candidates(candidates)

    def _collect_anchor_window_candidates(
        self,
        clean_text: str,
        inherited_action: str = "",
        inherited_device: str = "",
        inherited_location: str = "",
    ) -> List[Tuple[int, int, Command, float]]:
        """围绕动作锚点 + 设备锚点收集局部候选。"""
        candidates: List[Tuple[int, int, Command, float]] = []
        anchors = self._extract_recovery_anchors(clean_text)

        prefix_window_limit = 22
        suffix_window_limit = 14

        # 第一通道：保留现有动作锚点解析
        for anchor in anchors:
            max_end = min(len(clean_text), anchor + prefix_window_limit)
            for end in range(anchor + 2, max_end + 1):
                span = clean_text[anchor:end].strip(" ，,；;")
                if len(span) < 2:
                    continue
                command = self._parse_single_command(
                    span,
                    inherited_action=inherited_action,
                    inherited_device=inherited_device,
                    inherited_location=inherited_location,
                )
                if not command:
                    continue
                if not self._is_viable_recovery_candidate(span, command):
                    continue
                if self._is_implausible_command_candidate(
                    command.action,
                    command.location,
                    command.device,
                    command.parameter,
                    command.value,
                    command.unit,
                ):
                    continue
                score = self._score_recovery_candidate(anchor, end, command)
                candidates.append((anchor, end, command, score))

        action_terms = sorted(
            {term for term in self.hot_words.action_set if len(term) >= 2}
            | set(self._recovery_single_char_actions),
            key=len,
            reverse=True,
        )
        seen_suffix_positions: Set[Tuple[int, str]] = set()
        for action in action_terms:
            start = 0
            while True:
                idx = clean_text.find(action, start)
                if idx < 0:
                    break
                key = (idx, action)
                start = idx + 1
                if key in seen_suffix_positions:
                    continue
                if len(action) == 1:
                    if self._single_char_anchor_covered_by_multi_action(clean_text, idx, action):
                        continue
                    if not self._is_valid_single_char_recovery_anchor(clean_text, idx, action):
                        continue
                seen_suffix_positions.add(key)

                end = idx + len(action)
                min_start = max(0, idx - suffix_window_limit)
                for candidate_start in range(min_start, idx):
                    span = clean_text[candidate_start:end].strip(" ，,；;")
                    if len(span) < len(action) + 2:
                        continue
                    command = self._parse_single_command(
                        span,
                        inherited_action=inherited_action,
                        inherited_device=inherited_device,
                        inherited_location=inherited_location,
                    )
                    if not command:
                        continue
                    if not self._is_viable_recovery_candidate(span, command):
                        continue
                    if self._is_implausible_command_candidate(
                        command.action,
                        command.location,
                        command.device,
                        command.parameter,
                        command.value,
                        command.unit,
                    ):
                        continue
                    score = self._score_recovery_candidate(candidate_start, end, command)
                    candidates.append((candidate_start, end, command, score))

        # 第二通道：低歧义设备锚点解析（仅作为动作锚点补充）
        device_window_limit = 20
        device_anchor_terms = self._extract_low_ambiguity_device_anchors(clean_text)
        for device_term, idx in device_anchor_terms:
            device_end = idx + len(device_term)
            start_min = max(0, idx - device_window_limit)
            end_max = min(len(clean_text), device_end + device_window_limit)

            # 组合前后窗口，优先保留较短 span 以减少噪声干扰
            start_candidates = range(start_min, idx + 1)
            end_candidates = range(device_end, end_max + 1)
            for candidate_start in start_candidates:
                for candidate_end in end_candidates:
                    if candidate_end - candidate_start < len(device_term) + 1:
                        continue
                    span = clean_text[candidate_start:candidate_end].strip(" ，,；;")
                    if len(span) < 3:
                        continue
                    command = self._parse_single_command(
                        span,
                        inherited_action=inherited_action,
                        inherited_device=inherited_device,
                        inherited_location=inherited_location,
                    )
                    if not command:
                        continue
                    if not self._is_valid_device_anchor_structure(span, command, device_term):
                        continue
                    if not self._is_viable_recovery_candidate(span, command):
                        continue
                    if self._is_implausible_command_candidate(
                        command.action,
                        command.location,
                        command.device,
                        command.parameter,
                        command.value,
                        command.unit,
                    ):
                        continue
                    score = self._score_recovery_candidate(candidate_start, candidate_end, command) - 0.03
                    candidates.append((candidate_start, candidate_end, command, score))

        # 第三通道：降噪恢复 —— 从锚点窗口中仅保留热词 token，拼合后重新解析。
        # 适用于 ASR 噪声严重但核心热词仍存在的场景，如 "打开大嘎嘎德国二楼锁定嘎嘎个射灯"。
        all_hot_terms = sorted(
            self.hot_words.action_set | self.hot_words.device_set | self.hot_words.location_set,
            key=len,
            reverse=True,
        )
        for anchor in anchors:
            max_end = min(len(clean_text), anchor + prefix_window_limit)
            raw_span = clean_text[anchor:max_end]
            # 从 raw_span 中按顺序提取所有热词 token
            denoised_tokens: List[str] = []
            scan_pos = 0
            while scan_pos < len(raw_span):
                matched = False
                for term in all_hot_terms:
                    if raw_span[scan_pos:scan_pos + len(term)] == term:
                        denoised_tokens.append(term)
                        scan_pos += len(term)
                        matched = True
                        break
                if not matched:
                    # 保留结构词（的/把/到/为/成）和数字+单位
                    ch = raw_span[scan_pos]
                    if ch in "的把到为成" or ch.isdigit():
                        denoised_tokens.append(ch)
                    scan_pos += 1
            denoised_span = "".join(denoised_tokens)
            if denoised_span and denoised_span != raw_span and len(denoised_span) >= 3:
                command = self._parse_single_command(
                    denoised_span,
                    inherited_action=inherited_action,
                    inherited_device=inherited_device,
                    inherited_location=inherited_location,
                )
                if command and not self._is_implausible_command_candidate(
                    command.action, command.location, command.device,
                    command.parameter, command.value, command.unit,
                ):
                    score = self._score_recovery_candidate(anchor, max_end, command) - 0.05
                    candidates.append((anchor, max_end, command, score))

        return candidates

    def _extract_low_ambiguity_device_anchors(self, clean_text: str) -> List[Tuple[str, int]]:
        """提取低歧义设备锚点，避免"灯/系统"等泛词触发。"""
        ambiguous_devices = {"灯", "灯光", "系统", "设备", "开关", "模式", "场景"}
        device_terms = sorted(
            {d for d in self.hot_words.device_set if len(d) >= 2 and d not in ambiguous_devices},
            key=len,
            reverse=True,
        )
        anchors: List[Tuple[str, int]] = []
        for term in device_terms:
            start = 0
            while True:
                idx = clean_text.find(term, start)
                if idx < 0:
                    break
                anchors.append((term, idx))
                start = idx + 1
        return anchors

    def _is_valid_device_anchor_structure(self, span: str, command: Command, anchor_device: str) -> bool:
        """
        设备锚点合法结构校验，仅放行：
        - 动作 + 设备
        - 动作 + 位置 + 设备
        - 设置类动作 + 设备 + 值（必须有值）
        """
        explicit_action = self._extract_action(span)
        if not explicit_action:
            return False

        command_device = (command.device or "").strip()
        if not command_device:
            return False
        if anchor_device and anchor_device not in command_device and command_device not in anchor_device:
            return False

        canonical_action = self._canonicalize_action(command.action)
        if canonical_action in ("设置为", "把调高", "把调低", "把调亮", "把调暗"):
            return bool(command.value)
        if canonical_action in ("打开", "关闭", "开", "关"):
            return True
        # 其余动作保持保守，不走设备锚点通道
        return False

    def _is_viable_recovery_candidate(self, span: str, command: Optional[Command]) -> bool:
        """过滤窗口恢复里的伪命令，只保留槽位可信的候选。"""
        if not command:
            return False
        if not command.device or command.device not in self.hot_words.device_set:
            return False
        if command.location:
            if (
                command.location not in self.hot_words.location_set
                and not self._match_dynamic_floor_prefix(command.location)
            ):
                return False
        if any(token in span for token in ("我的", "你的", "他的", "她的", "它的")):
            device_category = self._device_category_map.get(command.device, "")
            explicit_action = self._canonicalize_action(self._extract_action(span) or "")
            # "我的+灯类"不再一刀切拦截：明确开关动作 + 非泛词设备允许通过（如"打开我的射灯"）。
            if device_category == "light":
                if explicit_action not in {"打开", "关闭", "开", "关"}:
                    return False
                if command.device in {"灯", "灯光"}:
                    return False
        if self._has_recovery_residue(span, command):
            return False
        return True

    def _has_recovery_residue(self, span: str, command: Command) -> bool:
        """检查候选 span 是否仍残留未消费的核心文本。"""
        positions: List[Tuple[int, int]] = []

        action_text = self._extract_action(span)
        if action_text:
            action_pos = span.find(action_text)
            if action_pos >= 0:
                positions.append((action_pos, action_pos + len(action_text)))

        for token in filter(None, [command.location, command.device, command.value, command.unit]):
            token_pos = span.find(token)
            if token_pos < 0:
                # 设备可能是推断出来的（如"设置为26度"推断出空调），
                # 此时设备词不在 span 中，不应视为残留。
                if token == command.device:
                    continue
                return True
            positions.append((token_pos, token_pos + len(token)))

        if not positions:
            return True

        head_end = min(start for start, _ in positions)
        tail_start = max(end for _, end in positions)
        head_residue = self._clean_recovery_residue_text(span[:head_end])
        tail_residue = self._clean_recovery_residue_text(span[tail_start:])

        if any(self._is_cjk_char(ch) or ch.isdigit() for ch in head_residue):
            return True
        if any(self._is_cjk_char(ch) or ch.isdigit() for ch in tail_residue):
            return True

        if command.location and command.value:
            loc_pos = span.find(command.location)
            value_pos = span.find(command.value)
            if loc_pos >= 0 and value_pos >= 0 and loc_pos > value_pos:
                return True

        return False

    def _clean_recovery_residue_text(self, text: str) -> str:
        """清理候选 span 头尾允许残留的结构词。"""
        residue = re.sub(r"[，。、；：？！\s]", "", text or "")
        residue = re.sub(r"(把|将|的|到|为|成|设置|设置为|设置成|调到|调为|调成)", "", residue)
        return residue

    def _score_recovery_candidate(self, start: int, end: int, command: Command) -> float:
        """为局部恢复候选打分，偏向高置信、短窗口、信息完整。"""
        span_len = max(0, end - start)
        score = command.confidence
        score += min(span_len, 16) * 0.01
        if command.location:
            score += 0.02
        if command.value:
            score += 0.02
        return score

    def _select_recovery_candidates(
        self,
        candidates: List[Tuple[int, int, Command, float]],
    ) -> List[Command]:
        """从局部恢复候选里选择一组不重叠且稳定的命令。"""
        if not candidates:
            return []

        ranked = sorted(candidates, key=lambda item: (item[0], -item[3], item[1]))
        selected: List[Tuple[int, int, Command, float]] = []
        seen_signatures: Set[Tuple[str, str, str, str, str, str]] = set()

        for start, end, command, score in ranked:
            signature = (
                command.action,
                command.location,
                command.device,
                command.parameter,
                command.value,
                command.unit,
            )
            if signature in seen_signatures:
                continue
            if any(not (end <= chosen_start or start >= chosen_end) for chosen_start, chosen_end, _, _ in selected):
                continue
            selected.append((start, end, command, score))
            seen_signatures.add(signature)

        selected.sort(key=lambda item: item[0])
        return [command for _, _, command, _ in selected]

    def _parse_by_semantic_slots(
        self,
        text: str,
        inherited_action: str = "",
        inherited_device: str = "",
        inherited_location: str = "",
    ) -> Optional[Command]:
        """槽位优先解析：action/location/device/value。"""
        location = self._extract_location(text)
        device = self._extract_device(text, location=location)
        parameter, value_raw, unit_raw = self._extract_parameter_components(text)
        action = self._extract_action(text)
        parameter_kind = self._infer_parameter_kind(text, parameter or "")

        if not action and (parameter_kind or value_raw or unit_raw):
            if any(token in text for token in ("调到", "调为", "设置为", "设置成", "调成", "变成", "到", "为")):
                action = "设置为"

        if not action and inherited_action and device:
            action = inherited_action
        elif not action and inherited_action:
            action = inherited_action

        if not location and inherited_location and (device or parameter or value_raw or unit_raw):
            followup_markers = ("它", "这个", "那个", "再", "也", "继续")
            possessive_markers = ("我的", "你的", "他的", "她的", "它的")
            if (
                not device
                or (inherited_device and device == inherited_device)
                or any(marker in text for marker in followup_markers)
            ) and not any(marker in text for marker in possessive_markers):
                location = inherited_location

        if parameter_kind == "ratio" and inherited_device:
            inherited_category = self._device_category_map.get(inherited_device, "")
            if inherited_category == "light":
                parameter_kind = "brightness"
                if parameter in ("", "ratio"):
                    parameter = "亮度"

        device_residue = ""
        looks_like_unknown_device = False
        fragment_infer_confidence: Optional[float] = None
        inferred_fragment_token = ""
        if not device:
            device_residue = self._extract_device_residue_payload(text, action, location)
            inferred_device, inferred_confidence, infer_mode = self._infer_device_from_fragment(
                device_residue,
                action,
                parameter_kind,
            )
            if inferred_device:
                device = inferred_device
                fragment_infer_confidence = inferred_confidence
                inferred_fragment_token = device_residue
                logger.debug(
                    "设备残片补齐: '%s' -> '%s' (mode=%s, conf=%.2f)",
                    device_residue,
                    inferred_device,
                    infer_mode,
                    inferred_confidence,
                )
            else:
                looks_like_unknown_device = self._looks_like_unknown_device_phrase(
                    text,
                    action,
                    location,
                    device,
                )

        device = self._resolve_device_by_capability(
            text=text,
            location=location,
            action=action,
            parameter_kind=parameter_kind,
            current_device=device,
            allow_default=not looks_like_unknown_device,
        )

        if not device and inherited_device and (
            action or parameter_kind or value_raw or unit_raw or parameter
        ) and not looks_like_unknown_device:
            inherited_parameter_kind = parameter_kind or self._infer_parameter_kind(text, parameter or "")
            if self._device_supports_parameter(inherited_device, inherited_parameter_kind or "power_state") or (
                action and not parameter_kind
            ):
                device = inherited_device

        if self._has_unparsed_core_fragment(
            text,
            action,
            location,
            device,
            parameter,
            value_raw,
            unit_raw,
            extra_consumed_tokens=[inferred_fragment_token] if inferred_fragment_token else None,
        ):
            return None

        if not action or not device:
            return None
        if self._is_implausible_command_candidate(
            action,
            location,
            device,
            parameter,
            value_raw,
            unit_raw,
        ):
            return None

        canonical_action = self._canonicalize_action(action)
        confidence = 0.93 if (parameter or value_raw) else 0.90
        if fragment_infer_confidence is not None:
            confidence = min(confidence, fragment_infer_confidence)
        return Command(
            action=canonical_action,
            device=device,
            location=location,
            parameter=parameter,
            value=value_raw or "",
            unit=unit_raw or "",
            confidence=confidence,
        )

    def _parse_single_command(
        self,
        text: str,
        inherited_action: str = "",
        inherited_device: str = "",
        inherited_location: str = "",
    ) -> Optional[Command]:
        """
        解析单个指令

        模式匹配优先级：
        1. 模板匹配（新增）：
           - "打开{设备}"、"关{设备}"
           - "把{房间}{设备}{状态}"
           - 设备状态（如"灯光开"）
        2. "把X调Y" 或 "把X动作Y" 智能模式
        3. 动作-位置-设备-参数
        4. 动作-设备

        Args:
            text: 指令文本

        Returns:
            Command 或 None
        """
        clean_text = self._normalize_action_aliases(text.strip())

        # 槽位优先解析（支持动作继承）
        slot_command = self._parse_by_semantic_slots(
            clean_text,
            inherited_action=inherited_action,
            inherited_device=inherited_device,
            inherited_location=inherited_location,
        )
        if slot_command:
            return slot_command

        # 模板匹配兜底（当槽位解析失败时）
        template_matches = self._template_matcher.match_multiple_templates(clean_text)
        if template_matches:
            best_match = max(template_matches, key=lambda x: x.confidence)
            location = best_match.location or self._extract_location(clean_text)
            device = self._extract_device(clean_text, location=location) or self._extract_device(best_match.device)
            if device:
                parameter, value_raw, unit_raw = self._extract_parameter_components(clean_text)
                if self._has_unparsed_core_fragment(
                    clean_text,
                    best_match.action,
                    location,
                    device,
                    parameter or best_match.parameter,
                    value_raw,
                    unit_raw,
                ):
                    return None
                return Command(
                    action=self._canonicalize_action(best_match.action),
                    device=device,
                    location=location,
                    parameter=parameter or best_match.parameter,
                    value=value_raw or "",
                    unit=unit_raw or "",
                    confidence=best_match.confidence,
                )

        # 模式1：智能检查"把..."模式
        ba_idx = clean_text.find("把")
        if ba_idx >= 0:
            # 提取"把"后面的内容
            ba_content = clean_text[ba_idx:].strip()

            # 去掉开头的"把"
            content = ba_content[1:].strip()

            # 查找"调为"、"到"、"设置"、"调成"、"调高"、"调低"、"调亮"、"调暗"
            adjust_keywords = ["调为", "设置为", "调成", "到", "为", "设置", "调高", "调低", "调亮", "调暗"]
            for keyword in adjust_keywords:
                if keyword in content:
                    parts = content.split(keyword, 1)
                    if len(parts) >= 2:
                        # 提取位置和设备/值
                        remaining = parts[0].strip()
                        value_text = parts[1].strip()
                        location, device = self._split_location_and_device(remaining)

                        # 避免把"空调为16度"误切成"空 + 调为16度"。
                        if keyword.startswith("调"):
                            merged_remaining = f"{remaining}{keyword[0]}"
                            merged_location, merged_device = self._split_location_and_device(merged_remaining)
                            if merged_device in self.hot_words.device_set:
                                location, device = merged_location, merged_device

                        parameter, value_raw, unit_raw = self._extract_parameter_components(value_text)
                        parameter_kind = self._infer_parameter_kind(value_text, parameter or "")

                        if keyword in ["调高", "调低", "调亮", "调暗", "拉开", "关闭"]:
                            action = f"把{keyword}"
                        else:
                            action = "设置为"

                        device = self._resolve_device_by_capability(
                            text=clean_text,
                            location=location,
                            action=action,
                            parameter_kind=parameter_kind,
                            current_device=device,
                            allow_default=not self._looks_like_unknown_device_phrase(
                                clean_text,
                                action,
                                location,
                                device,
                            ),
                        )

                        if not device:
                            continue
                        if len(device) == 1 and device not in self.hot_words.device_set:
                            continue
                        if self._has_unparsed_core_fragment(
                            clean_text,
                            action,
                            location,
                            device,
                            parameter,
                            value_raw,
                            unit_raw,
                        ):
                            continue

                        return Command(
                            action=self._canonicalize_action(action),
                            device=device,
                            location=location,
                            parameter=parameter,
                            value=value_raw or value_text,
                            unit=unit_raw or "",
                            confidence=0.95,
                        )

        # 模式2：动作-位置-设备
        # 提取动作
        action_match = self._action_pattern.search(clean_text)
        if not action_match:
            split_indexes = [idx for idx, char in enumerate(clean_text) if char == "把" and idx > 0]
            for idx in reversed(split_indexes):
                suffix = clean_text[idx:].strip(" ，,；;")
                if len(suffix) < 4:
                    continue
                recovered = self._parse_single_command(suffix)
                if recovered and recovered.action == "设置为" and recovered.device and recovered.value:
                    return recovered
            return None

        action = action_match.group()
        text_after_action = clean_text[action_match.end():].strip()

        # 尝试匹配 动作-位置-设备
        location_match = self._location_pattern.search(text_after_action)
        if location_match:
            location = location_match.group()
            text_after_location = text_after_action[location_match.end():].strip()

            # 优先匹配最长设备词
            device_match = self._device_pattern.search(text_after_location)
            if device_match:
                device = device_match.group()
                # 检查是否有参数
                remaining = text_after_location[device_match.end():].strip()

                # 如果设备词后面还有字符，检查是否应该合并到设备名还是作为参数
                if remaining and len(remaining) <= 2:
                    # 短字符可能属于设备名（如"灯光"中的"光"）
                    device = device + remaining
                    remaining = ""

                parameter, value_raw, unit_raw = self._extract_parameter_components(remaining)
                if self._has_unparsed_core_fragment(
                    clean_text,
                    action,
                    location,
                    device,
                    parameter,
                    value_raw,
                    unit_raw,
                ):
                    # 留给更窄的尾部恢复逻辑处理
                    pass
                elif not self._is_implausible_command_candidate(
                    action,
                    location,
                    device,
                    parameter,
                    value_raw,
                    unit_raw,
                ):
                    return Command(
                        action=self._canonicalize_action(action),
                        device=device,
                        location=location,
                        parameter=parameter,
                        value=value_raw or "",
                        unit=unit_raw or "",
                        confidence=0.95,
                    )

        # 模式3：动作-设备
        device_match = self._device_pattern.search(text_after_action)
        if device_match:
            device = device_match.group()
            remaining = text_after_action[device_match.end():].strip()

            # 如果设备词后面还有字符，检查是否应该合并到设备名还是作为参数
            if remaining and len(remaining) <= 2:
                # 短字符可能属于设备名
                device = device + remaining
                remaining = ""

            parameter, value_raw, unit_raw = self._extract_parameter_components(remaining)
            if not self._has_unparsed_core_fragment(
                clean_text,
                action,
                "",
                device,
                parameter,
                value_raw,
                unit_raw,
            ) and not self._is_implausible_command_candidate(
                action,
                "",
                device,
                parameter,
                value_raw,
                unit_raw,
            ):
                return Command(
                    action=self._canonicalize_action(action),
                    device=device,
                    location="",
                    parameter=parameter,
                    value=value_raw or "",
                    unit=unit_raw or "",
                    confidence=0.9,
                )

        # 尾部恢复：整段失败时，仅回收最后一个稳定的"把...设值"子命令
        split_indexes = [idx for idx, char in enumerate(clean_text) if char == "把" and idx > 0]
        for idx in reversed(split_indexes):
            suffix = clean_text[idx:].strip(" ，,；;")
            if len(suffix) < 4:
                continue
            recovered = self._parse_single_command(suffix)
            if recovered and recovered.action == "设置为" and recovered.device and recovered.value:
                return recovered

        return None

    def _calculate_confidence(self, result: ParseResult, original: str, cleaned: str) -> float:
        """
        计算解析置信度

        Args:
            result: 解析结果
            original: 原始输入
            cleaned: 清理后输入

        Returns:
            置信度 (0-1)
        """
        if not result.commands:
            return 0.0

        # 基础置信度：指令数量 / 原始长度（避免过度解析）
        base_confidence = 0.8

        # 命中的指令数
        command_count = len(result.commands)
        if command_count == 1:
            base_confidence += 0.1
        elif command_count > 3:
            # 指令过多，可能解析错误
            base_confidence -= 0.2

        # 清理比例：清理后长度 / 原始长度
        if len(original) > 0:
            clean_ratio = len(cleaned) / len(original)
            if clean_ratio < 0.5:
                # 清理过多，可能丢失信息
                base_confidence -= 0.2
            elif clean_ratio > 0.8:
                # 清理较少，说明输入较干净
                base_confidence += 0.1

        # 特殊处理：如果"把"模式被匹配，降低置信度（因为这种模式更复杂）
        for cmd in result.commands:
            if cmd.action.startswith("把") and cmd.action != "把":
                # "把"模式匹配
                base_confidence -= 0.05

        # 限制范围
        return max(0.0, min(1.0, base_confidence))

    def _needs_glm_refinement(self, result: ParseResult, original: str) -> bool:
        """
        判断是否需要 GLM 精修

        Args:
            result: 解析结果
            original: 原始输入

        Returns:
            是否需要 GLM
        """
        # 置信度低，需要 GLM
        if result.confidence < 0.8:
            return True

        # 没有解析出指令，需要 GLM
        if not result.commands:
            return True

        # 指令参数过长，可能需要 GLM
        for cmd in result.commands:
            raw_param_payload = f"{cmd.parameter}{cmd.value}{cmd.unit}"
            if raw_param_payload and len(raw_param_payload) > 10:
                # 参数过长，可能需要进一步解析
                return True

        # 如果原文包含脏词但规则层未处理，需要 GLM
        dirty_words = self._ALL_DIRTY_WORDS if hasattr(self, '_ALL_DIRTY_WORDS') else set()
        # 转换为小写进行匹配
        original_lower = original.lower()
        result_lower = str(result).lower()
        has_dirty = any(dw.lower() in original_lower for dw in dirty_words)
        if has_dirty:
            # 检查规则层是否去除了脏词
            removed_count = sum(original_lower.count(dw.lower()) for dw in dirty_words)
            remaining_count = sum(result_lower.count(dw.lower()) for dw in dirty_words)
            if remaining_count >= removed_count * 0.5:
                # 规则层没有去除大部分脏词，需要 GLM
                return True

        return False

    def _make_slot(
        self,
        raw: str,
        normalized: Optional[str] = None,
        canonical_id: Optional[str] = None,
        confidence: float = 1.0,
    ) -> Optional[SlotValue]:
        """构造统一槽位。"""
        raw = (raw or "").strip()
        if not raw:
            return None
        return SlotValue(
            raw=raw,
            normalized=(normalized or raw).strip(),
            canonical_id=canonical_id,
            confidence=max(0.0, min(1.0, confidence)),
        )

    def _infer_parameter_kind(self, text: str, raw_parameter: str) -> Optional[str]:
        """根据文本和参数原文推断参数类型。"""
        combined = f"{text}{raw_parameter}"
        if any(token in combined for token in ("状态", "开着", "关着", "开没开", "关没关", "有没有打开", "有没有关闭")):
            return "power_state"
        if any(token in combined for token in ("亮着", "暗着")):
            return "brightness"
        if any(token in combined for token in ("亮度", "调亮", "调暗", "最亮", "最暗", "灯光")):
            return "brightness"
        if any(token in combined for token in ("温度", "度", "摄氏度", "制热", "制冷")):
            return "temperature"
        if any(token in combined for token in ("颜色", "变红", "变蓝", "变绿", "彩虹")):
            return "color"
        if any(token in combined for token in ("风速", "档", "开大", "开小", "高档", "低档")):
            return "speed"
        if any(token in combined for token in ("%", "％", "百分之", "一半")):
            return "ratio"
        return None

    def _extract_value_and_unit(self, raw_parameter: str) -> Tuple[Optional[str], Optional[str]]:
        """从参数串中拆出值和单位。"""
        if not raw_parameter:
            return None, None
        match = self._value_pattern.search(raw_parameter)
        if not match:
            return None, None
        return match.group(1), match.group(2)

    def _infer_relation(self, text: str, command_count: int) -> str:
        """推断命令关系类型。"""
        if "如果" in text and "就" in text:
            return "condition"
        if "先" in text and ("再" in text or "然后" in text):
            return "sequence"
        if command_count > 1:
            return "parallel"
        return "single"

    def _extract_condition_clause(self, text: str) -> Optional[str]:
        """抽取简单条件从句。"""
        if "如果" in text and "就" in text:
            start = text.find("如果")
            end = text.find("就", start)
            if start >= 0 and end > start:
                return text[start:end + 1].strip()
        return None

    def _extract_scene_name(self, text: str) -> str:
        """抽取场景/模式名称。"""
        match = re.search(r'([一-龥A-Za-z0-9]{1,12}(?:场景|模式))', text)
        if match:
            scene_name = match.group(1)
            for action in self._scene_action_keywords:
                if scene_name.startswith(action):
                    scene_name = scene_name[len(action):]
                    break
            return scene_name

        for keyword in self._scene_keywords:
            if keyword in ("模式", "场景"):
                continue
            if keyword in text:
                if f"{keyword}模式" in text:
                    return f"{keyword}模式"
                if f"{keyword}场景" in text:
                    return f"{keyword}场景"
                return keyword
        return ""

    def _extract_time_expression(self, text: str) -> str:
        """抽取简单时间表达，用于自动化规则。"""
        patterns = [
            r'((?:每周[一二三四五六日天]|周[一二三四五六日天])(?:早上|上午|中午|下午|晚上|凌晨)?(?:\d{1,2}|[一二三四五六七八九十两]{1,3})点(?:\d{1,2}|[一二三四五六七八九十两]{1,3})?分?)',
            r'(\d+\s*(?:分钟|小时|天)后)',
            r'([一二三四五六七八九十两]+\s*(?:分钟|小时|天)后)',
            r'((?:每天|每晚|每早|每日|工作日|周末|今晚|明早|明天|今天|早上|上午|中午|下午|晚上|凌晨)?\s*(?:\d{1,2}|[一二三四五六七八九十两]{1,3})点(?:\d{1,2}|[一二三四五六七八九十两]{1,3})?分?)',
            r'((?:每天|每晚|每早|每日|工作日|周末|今晚|明早|明天|今天|早上|上午|中午|下午|晚上|凌晨)?\s*\d{1,2}[:：]\d{1,2})',
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return re.sub(r'\s+', '', match.group(1))
        return ""

    def _extract_query_phrase(self, text: str) -> str:
        """抽取查询短语。"""
        for keyword in self._query_keywords:
            if keyword in text:
                return keyword
        if text.endswith("吗"):
            return "查询"
        return ""

    def _extract_implicit_signals(self, text: str) -> List[str]:
        """从自然口语或无关陈述中提取隐含场景信号。"""
        if not text:
            return []
        signals: List[str] = []
        for signal_name, patterns in self.IMPLICIT_SIGNAL_PATTERNS:
            if any(re.search(pattern, text) for pattern in patterns):
                signals.append(signal_name)
        return signals

    def _infer_query_type(self, text: str, device: str, parameter_kind: Optional[str]) -> str:
        """细分查询类型。"""
        if any(token in text for token in ("是否", "有没有")) or text.endswith("吗") or text.endswith("呢"):
            return "binary_check"
        if parameter_kind in ("temperature", "brightness", "color", "speed", "ratio"):
            return "environment_metric" if not device or device in ("温湿度计", "传感器") else "device_metric"
        if parameter_kind in ("power_state", "device_state"):
            return "device_state"
        if "状态" in text or device:
            return "device_state"
        return "unknown"

    def _infer_trigger_type(self, text: str, condition_clause: Optional[str], time_expr: str) -> str:
        """细分自动化触发类型。"""
        has_condition = bool(condition_clause)
        has_time = bool(time_expr)
        if has_condition and has_time:
            return "hybrid"
        if has_condition:
            return "condition"
        if has_time:
            if "后" in time_expr:
                return "delay"
            return "schedule"
        if "自动" in text or "定时" in text:
            return "schedule"
        return "unknown"

    def _infer_schedule_recurrence(self, text: str, time_expr: str) -> Optional[str]:
        """推断定时触发的重复类型。"""
        combined = f"{text}{time_expr}"
        if any(token in combined for token in ("每天", "每日", "每晚", "每早")):
            return "daily"
        if any(token in combined for token in ("工作日",)):
            return "workday"
        if any(token in combined for token in ("周末",)):
            return "weekend"
        if "每周" in combined or re.search(r'周[一二三四五六日天]', combined):
            return "weekly"
        if any(token in combined for token in ("明天", "今天", "今晚", "明早")):
            return "one_shot"
        if time_expr and "后" not in time_expr:
            return "one_shot"
        return None

    def _extract_weekdays(self, text: str) -> List[str]:
        """抽取周几列表。"""
        weekdays = re.findall(r'(?:每周|周)([一二三四五六日天])', text)
        mapping = {
            "一": "mon",
            "二": "tue",
            "三": "wed",
            "四": "thu",
            "五": "fri",
            "六": "sat",
            "日": "sun",
            "天": "sun",
        }
        return [mapping[d] for d in weekdays if d in mapping]

    def _build_trigger_spec(self, text: str, condition_clause: Optional[str], time_expr: str, trigger_type: str) -> TriggerSpec:
        """构造结构化触发对象。"""
        recurrence = self._infer_schedule_recurrence(text, time_expr)
        weekdays = self._extract_weekdays(text)
        schedule_type = None
        delay_expression = None

        if trigger_type == "delay":
            schedule_type = "relative"
            delay_expression = time_expr or None
        elif trigger_type in ("schedule", "hybrid"):
            schedule_type = "absolute"

        return TriggerSpec(
            type=trigger_type,
            condition_text=condition_clause,
            time_expression=time_expr or None,
            schedule_type=schedule_type,
            recurrence=recurrence,
            delay_expression=delay_expression,
            weekdays=weekdays,
            raw_text=text,
        )

    def _extract_automation_target_text(self, text: str) -> str:
        """抽取自动化规则中的动作目标段。"""
        working = text
        if "如果" in working and "就" in working:
            working = working.split("就", 1)[1]

        time_expr = self._extract_time_expression(working)
        if time_expr:
            working = working.replace(time_expr, "", 1)

        for token in ("自动", "定时", "的时候", "时", "请", "帮我"):
            working = working.replace(token, "")

        return working.strip(" ，,；;")

    def _build_query_semantic_command(self, text: str, source: str, relation: str) -> Optional[SemanticCommand]:
        """构造状态查询语义命令。"""
        query_phrase = self._extract_query_phrase(text)
        if not query_phrase:
            return None

        location = self._extract_location(text)
        device = self._extract_device(text, location=location)
        parameter_text = self._extract_parameter(text)
        parameter_kind = self._infer_parameter_kind(text, parameter_text)
        device = self._resolve_device_by_capability(
            text=text,
            location=location,
            action=query_phrase,
            parameter_kind=parameter_kind,
            current_device=device,
            allow_default=False,
        )
        query_type = self._infer_query_type(text, device, parameter_kind)

        if not device and parameter_kind:
            device = self.DEFAULT_QUERY_DEVICE.get(parameter_kind, "")

        missing_slots: List[str] = []
        if not device and not parameter_kind:
            missing_slots.append("query_target")

        confidence = 0.90
        if missing_slots:
            confidence -= 0.12

        return SemanticCommand(
            intent="state_query",
            query_type=query_type,
            action=self._make_slot(
                raw=query_phrase,
                normalized="查询",
                canonical_id=self.QUERY_ACTION_CANONICAL_ID,
                confidence=confidence,
            ),
            device=self._make_slot(
                raw=device,
                normalized=device,
                canonical_id=f"device.{self._device_category_map.get(device, '')}" if device else None,
                confidence=max(0.0, confidence - 0.03),
            ),
            location=self._make_slot(
                raw=location,
                normalized=location,
                canonical_id=f"location.{self._location_category_map.get(location, '')}" if location else None,
                confidence=max(0.0, confidence - 0.05),
            ),
            parameter=self._make_slot(
                raw=parameter_text or parameter_kind or "",
                normalized=parameter_kind or parameter_text or "",
                canonical_id=self.PARAMETER_CANONICAL_IDS.get(parameter_kind or ""),
                confidence=max(0.0, confidence - 0.03),
            ),
            relation=relation,
            raw_text=text,
            rendered_text=text,
            source=source,
            confidence=confidence,
            missing_slots=missing_slots,
            warnings=([] if not missing_slots else ["incomplete_query_target"]) + (
                [] if query_type != "unknown" else ["unknown_query_type"]
            ),
        )

    def _build_scene_semantic_command(self, text: str, source: str, relation: str) -> Optional[SemanticCommand]:
        """构造场景激活语义命令。"""
        scene_name = self._extract_scene_name(text)
        if not scene_name:
            return None

        action_raw = next((kw for kw in self._scene_action_keywords if kw in text), "打开")
        action_normalized = "关闭" if action_raw == "关闭" else "启动"
        confidence = 0.93 if scene_name.endswith(("场景", "模式")) else 0.88

        return SemanticCommand(
            intent="scene_activate",
            action=self._make_slot(
                raw=action_raw,
                normalized=action_normalized,
                canonical_id=self.SCENE_ACTION_CANONICAL_ID,
                confidence=confidence,
            ),
            device=self._make_slot(
                raw=scene_name,
                normalized=scene_name,
                canonical_id=f"scene.{scene_name}",
                confidence=max(0.0, confidence - 0.02),
            ),
            relation=relation,
            raw_text=text,
            rendered_text=f"{action_normalized}{scene_name}",
            source=source,
            confidence=confidence,
            missing_slots=[],
            warnings=[],
        )

    def _build_automation_semantic_command(self, text: str, source: str, relation: str) -> Optional[SemanticCommand]:
        """构造自动化创建语义命令。"""
        if not any(token in text for token in self._automation_keywords) and not self._extract_time_expression(text):
            return None

        condition_clause = self._extract_condition_clause(text)
        time_expr = self._extract_time_expression(text)
        trigger_type = self._infer_trigger_type(text, condition_clause, time_expr)
        trigger = self._build_trigger_spec(text, condition_clause, time_expr, trigger_type)
        target_text = self._extract_automation_target_text(text)
        target_text = target_text or text

        target_location = self._extract_location(target_text)
        target_parameter = self._extract_parameter(target_text)
        target_device = self._extract_device(target_text, location=target_location)
        target_action = self._extract_action(target_text)
        parameter_kind = self._infer_parameter_kind(target_text, target_parameter)
        target_device = self._resolve_device_by_capability(
            text=target_text,
            location=target_location,
            action=target_action,
            parameter_kind=parameter_kind,
            current_device=target_device,
        )

        missing_slots: List[str] = []
        if not target_action:
            missing_slots.append("action")
        if not target_device:
            missing_slots.append("device")

        confidence = 0.90
        if condition_clause or time_expr:
            confidence += 0.03
        if missing_slots:
            confidence -= 0.15

        value_raw, unit_raw = self._extract_value_and_unit(target_parameter)

        return SemanticCommand(
            intent="automation_create",
            trigger_type=trigger_type,
            trigger=trigger,
            action=self._make_slot(
                raw=target_action or "自动化",
                normalized=self._canonicalize_action(target_action) if target_action else "创建自动化",
                canonical_id=self.AUTOMATION_ACTION_CANONICAL_ID,
                confidence=confidence,
            ),
            device=self._make_slot(
                raw=target_device,
                normalized=target_device,
                canonical_id=f"device.{self._device_category_map.get(target_device, '')}" if target_device else None,
                confidence=max(0.0, confidence - 0.03),
            ),
            location=self._make_slot(
                raw=target_location,
                normalized=target_location,
                canonical_id=f"location.{self._location_category_map.get(target_location, '')}" if target_location else None,
                confidence=max(0.0, confidence - 0.05),
            ),
            parameter=self._make_slot(
                raw=target_parameter or parameter_kind or "",
                normalized=parameter_kind or target_parameter or "",
                canonical_id=self.PARAMETER_CANONICAL_IDS.get(parameter_kind or ""),
                confidence=max(0.0, confidence - 0.04),
            ),
            value=self._make_slot(
                raw=value_raw or "",
                normalized=value_raw or "",
                canonical_id="value.numeric" if value_raw else None,
                confidence=max(0.0, confidence - 0.07),
            ),
            unit=self._make_slot(
                raw=unit_raw or "",
                normalized=unit_raw or "",
                canonical_id=f"unit.{unit_raw}" if unit_raw else None,
                confidence=max(0.0, confidence - 0.07),
            ),
            time=self._make_slot(
                raw=time_expr,
                normalized=time_expr,
                canonical_id="time.expression" if time_expr else None,
                confidence=max(0.0, confidence - 0.02),
            ),
            condition=condition_clause,
            relation="condition" if condition_clause else relation,
            raw_text=text,
            rendered_text=text,
            source=source,
            confidence=max(0.0, min(1.0, confidence)),
            missing_slots=missing_slots,
            warnings=([] if not missing_slots else ["incomplete_automation_target"]) + (
                [] if trigger_type != "unknown" else ["unknown_trigger_type"]
            ),
        )

    def _build_special_intent_command(self, text: str, source: str, relation: str) -> Optional[SemanticCommand]:
        """为查询/场景/自动化构造专用语义命令。"""
        intent = self._infer_intent(text, self._extract_device(text), self._extract_parameter(text))
        if intent == "state_query":
            return self._build_query_semantic_command(text, source, relation)
        if intent == "scene_activate":
            return self._build_scene_semantic_command(text, source, relation)
        if intent == "automation_create":
            return self._build_automation_semantic_command(text, source, relation)
        return None

    def _infer_intent(self, text: str, device: str = "", parameter: str = "") -> str:
        """根据文本内容推断意图。"""
        if any(token in text for token in self._condition_keywords):
            return "automation_create"
        if "自动" in text or "定时" in text:
            return "automation_create"
        if self._extract_time_expression(text) and any(
            action in text for action in (*self.hot_words.action_set, "打开", "关闭", "设置为", "调高", "调低")
        ):
            return "automation_create"
        if any(token in text for token in self._query_keywords):
            return "state_query"
        if text.endswith("吗") or text.endswith("呢"):
            if device or parameter or self._extract_parameter(text) or self._extract_device(text):
                return "state_query"
        if any(token in text for token in self._scene_keywords) and ("打开" in text or "启动" in text or "关闭" in text):
            return "scene_activate"
        if self._extract_scene_name(text):
            return "scene_activate"
        if device and ("场景" in device or "模式" in device):
            return "scene_activate"
        if device or parameter or self._extract_action(text):
            return "device_control"
        return "unknown"

    def _build_confirmation_message(self, rendered_text: str, unresolved_slots: List[str]) -> Optional[str]:
        """构造确认文案。"""
        if not rendered_text:
            return None
        if unresolved_slots:
            return f"请确认缺失槽位后再执行：{rendered_text}"
        return f"请确认是否执行：{rendered_text}"

    def _render_semantic_command_summary(self, cmd: SemanticCommand) -> str:
        """生成单条语义命令的人类可读摘要。"""
        if cmd.rendered_text:
            return cmd.rendered_text

        parameter_display_map = {
            "temperature": "温度",
            "brightness": "亮度",
            "color": "颜色",
            "speed": "风速",
            "ratio": "开合",
            "level": "档位",
        }

        action = cmd.action.normalized if cmd.action else ""
        location = cmd.location.normalized if cmd.location else ""
        device = cmd.device.normalized if cmd.device else ""
        parameter = cmd.parameter.normalized if cmd.parameter else ""
        parameter_display = parameter_display_map.get(parameter, parameter)
        device_text = device
        if cmd.scope == "all_same_type_in_location" and device:
            device_text = f"{location}所有{device}" if location else f"所有{device}"
        elif location and device and location not in device:
            device_text = f"{location}{device}"
        elif location and not device:
            device_text = location

        if cmd.delta is not None:
            delta_value = int(cmd.delta) if float(cmd.delta).is_integer() else cmd.delta
            delta_text = f"{delta_value}{cmd.delta_unit or ''}".strip()
            if action in ("调高", "调低", "调亮", "调暗"):
                if parameter_display and device_text:
                    return f"{action}{device_text}{parameter_display}{delta_text}"
                if device_text:
                    return f"{action}{device_text}{delta_text}"

        parts: List[str] = []
        if action:
            parts.append(action)
        if device_text:
            parts.append(device_text)

        value_part = ""
        if cmd.value:
            value_part = cmd.value.normalized
            if cmd.unit:
                value_part += cmd.unit.normalized

        if action == "设置为":
            if value_part:
                if parameter_display and parameter_display not in ("", "状态"):
                    if device_text:
                        return f"设置{device_text}{parameter_display}为{value_part}"
                    return f"设置{parameter_display}为{value_part}"
                if device_text:
                    return f"设置{device_text}为{value_part}"
                return f"设置为{value_part}"
            if parameter_display and parameter_display not in ("", "状态"):
                if device_text:
                    return f"设置{device_text}{parameter_display}"
                return f"设置{parameter_display}"
            if device_text:
                return f"设置{device_text}"
            return "设置"

        if value_part:
            parts.append(value_part)
        elif cmd.parameter and cmd.parameter.normalized not in ("temperature", "brightness", "color", "speed", "ratio", "level", "power_state", "device_state"):
            parts.append(cmd.parameter.normalized)

        rendered = "".join(parts).strip()
        return rendered or cmd.raw_text

    def _build_execution_plan(
        self,
        commands: List[SemanticCommand],
        relation: str,
        condition_clause: Optional[str] = None,
    ) -> List[ExecutionStep]:
        """根据命令列表构造执行计划。"""
        if not commands:
            return []

        normalized_relation = relation if relation in ("single", "parallel", "sequence", "condition") else "single"
        group_id = None
        if normalized_relation in ("parallel", "sequence", "condition") and len(commands) > 1:
            group_id = f"{normalized_relation}_1"

        plan: List[ExecutionStep] = []
        for index, cmd in enumerate(commands):
            execution_relation = normalized_relation
            depends_on: List[int] = []

            if normalized_relation == "single":
                execution_relation = "single"
            elif normalized_relation == "parallel":
                execution_relation = "parallel"
            elif normalized_relation == "sequence":
                execution_relation = "sequence"
                if index > 0:
                    depends_on = [index - 1]
            elif normalized_relation == "condition":
                execution_relation = "condition"

            if cmd.intent == "automation_create" and cmd.trigger_type in ("condition", "hybrid"):
                execution_relation = "condition"

            cmd.execution_relation = execution_relation
            cmd.depends_on = list(depends_on)
            cmd.group_id = group_id

            plan.append(
                ExecutionStep(
                    step_id=f"step_{index + 1}",
                    command_index=index,
                    relation=execution_relation,
                    depends_on=list(depends_on),
                    group_id=group_id,
                    condition=cmd.condition or condition_clause,
                    trigger_type=cmd.trigger_type,
                    summary=self._render_semantic_command_summary(cmd),
                )
            )

        return plan

    def parse_semantic(
        self,
        text: str,
        parse_result: Optional[ParseResult] = None,
        source: str = "rule",
        rendered_text: Optional[str] = None,
    ) -> SemanticDecision:
        """
        将规则解析结果转换为统一语义结构。

        Args:
            text: 原始或归一化后的文本
            parse_result: 可选的规则解析结果，避免重复计算
            source: 结果来源（rule/hybrid 等）
            rendered_text: 已有渲染文本，默认使用规则结果或清洗文本
        """
        text = text or ""
        implicit_signals = self._extract_implicit_signals(text)
        cleaned = self._preprocess(text) if text.strip() else ""

        if parse_result is None:
            parse_result = self.parse(text) if text.strip() else ParseResult(raw_input=text)

        relation = self._infer_relation(text, len(parse_result.commands))
        condition = self._extract_condition_clause(text)
        commands: List[SemanticCommand] = []
        unresolved_slots: List[str] = []

        special_command = self._build_special_intent_command(cleaned, source, relation)
        if special_command is not None:
            rendered = (rendered_text or special_command.rendered_text or cleaned).strip()
            unresolved_slots = sorted(set(special_command.missing_slots))
            requires_confirmation = bool(unresolved_slots) or special_command.confidence < 0.85
            execution_plan = self._build_execution_plan([special_command], special_command.relation, special_command.condition)
            return SemanticDecision(
                commands=[special_command],
                normalized_text=cleaned,
                rendered_text=rendered,
                implicit_signals=implicit_signals,
                unresolved_slots=unresolved_slots,
                execution_plan=execution_plan,
                requires_confirmation=requires_confirmation,
                confirmation_message=self._build_confirmation_message(rendered, unresolved_slots) if requires_confirmation else None,
                source=source,
                overall_confidence=special_command.confidence,
                debug={
                    "rule_confidence": parse_result.confidence,
                    "relation": special_command.relation,
                    "command_count": 1,
                    "needs_glm": parse_result.needs_glm,
                    "special_intent": special_command.intent,
                },
            )

        for index, cmd in enumerate(parse_result.commands):
            command_text = str(cmd)
            action_slot = self._make_slot(
                raw=cmd.action,
                normalized=self._canonicalize_action(cmd.action),
                canonical_id=self.ACTION_CANONICAL_IDS.get(self._action_category_map.get(cmd.action, "")),
                confidence=cmd.confidence,
            )
            device_category = self._device_category_map.get(cmd.device, "")
            device_slot = self._make_slot(
                raw=cmd.device,
                normalized=cmd.device,
                canonical_id=f"device.{device_category}" if device_category else None,
                confidence=cmd.confidence,
            )
            location_category = self._location_category_map.get(cmd.location, "")
            location_slot = self._make_slot(
                raw=cmd.location,
                normalized=cmd.location,
                canonical_id=f"location.{location_category}" if location_category else None,
                confidence=max(0.0, cmd.confidence - 0.05),
            )

            parameter_text = cmd.parameter or f"{cmd.value}{cmd.unit}"
            parameter_kind = self._infer_parameter_kind(command_text, parameter_text)
            parameter_slot = self._make_slot(
                raw=cmd.parameter or parameter_kind or "",
                normalized=parameter_kind or cmd.parameter or "",
                canonical_id=self.PARAMETER_CANONICAL_IDS.get(parameter_kind or ""),
                confidence=max(0.0, cmd.confidence - 0.05),
            )
            value_slot = self._make_slot(
                raw=cmd.value or "",
                normalized=cmd.value or "",
                canonical_id="value.numeric" if cmd.value else None,
                confidence=max(0.0, cmd.confidence - 0.08),
            )
            unit_slot = self._make_slot(
                raw=cmd.unit or "",
                normalized=cmd.unit or "",
                canonical_id=f"unit.{cmd.unit}" if cmd.unit else None,
                confidence=max(0.0, cmd.confidence - 0.08),
            )

            missing_slots: List[str] = []
            warnings: List[str] = []
            if not action_slot:
                missing_slots.append("action")
            if not device_slot and self._infer_intent(command_text, parameter=parameter_text) == "device_control":
                missing_slots.append("device")
            if parameter_text and not parameter_slot and not value_slot:
                warnings.append("parameter_untyped")
            if cmd.device and cmd.device not in cleaned and (parameter_text or "温度" in cleaned or "亮度" in cleaned):
                warnings.append("device_inferred")
            if self._is_value_out_of_range(parameter_kind, cmd.value):
                warnings.append("value_out_of_range")

            confidence = max(
                0.0,
                min(1.0, cmd.confidence - 0.05 * len(missing_slots) - 0.03 * len(warnings)),
            )
            intent = self._infer_intent(command_text, device=cmd.device, parameter=parameter_text)

            semantic_cmd = SemanticCommand(
                intent=intent,
                action=action_slot,
                device=device_slot,
                location=location_slot,
                parameter=parameter_slot,
                value=value_slot,
                unit=unit_slot,
                condition=condition,
                sequence_index=index,
                relation=relation,
                raw_text=command_text,
                rendered_text=command_text,
                source=source,
                confidence=confidence,
                missing_slots=missing_slots,
                warnings=warnings,
            )
            commands.append(semantic_cmd)
            unresolved_slots.extend(missing_slots)

        if not commands:
            fallback_intent = self._infer_intent(cleaned)
            action = self._extract_action(cleaned)
            device = self._extract_device(cleaned)
            location = self._extract_location(cleaned)
            parameter, value_raw, unit_raw = self._extract_parameter_components(cleaned)
            fallback_missing = []
            if fallback_intent == "device_control" and not action:
                fallback_missing.append("action")
            if fallback_intent == "device_control" and not device:
                fallback_missing.append("device")
            if fallback_intent != "unknown":
                commands.append(
                    SemanticCommand(
                        intent=fallback_intent,
                        action=self._make_slot(
                            raw=action,
                            normalized=self._canonicalize_action(action),
                            canonical_id=self.ACTION_CANONICAL_IDS.get(self._action_category_map.get(action, "")),
                            confidence=0.65,
                        ),
                        device=self._make_slot(
                            raw=device,
                            normalized=device,
                            canonical_id=f"device.{self._device_category_map.get(device, '')}" if device else None,
                            confidence=0.65,
                        ),
                        location=self._make_slot(
                            raw=location,
                            normalized=location,
                            canonical_id=f"location.{self._location_category_map.get(location, '')}" if location else None,
                            confidence=0.60,
                        ),
                        parameter=self._make_slot(
                            raw=parameter or self._infer_parameter_kind(cleaned, parameter or "") or "",
                            normalized=self._infer_parameter_kind(cleaned, parameter or "") or parameter or "",
                            canonical_id=self.PARAMETER_CANONICAL_IDS.get(self._infer_parameter_kind(cleaned, parameter or "") or ""),
                            confidence=0.60,
                        ),
                        value=self._make_slot(
                            raw=value_raw or "",
                            normalized=value_raw or "",
                            canonical_id="value.numeric" if value_raw else None,
                            confidence=0.58,
                        ),
                        unit=self._make_slot(
                            raw=unit_raw or "",
                            normalized=unit_raw or "",
                            canonical_id=f"unit.{unit_raw}" if unit_raw else None,
                            confidence=0.58,
                        ),
                        condition=condition,
                        relation=relation,
                        raw_text=cleaned,
                        rendered_text=cleaned,
                        source=source,
                        confidence=0.60,
                        missing_slots=fallback_missing,
                        warnings=(
                            ["fallback_semantic_inference", "value_out_of_range"]
                            if self._is_value_out_of_range(
                                self._infer_parameter_kind(cleaned, parameter or "") or parameter or "",
                                value_raw,
                            )
                            else ["fallback_semantic_inference"]
                        ),
                    )
                )
                unresolved_slots.extend(fallback_missing)

        final_rendered_text = (rendered_text or str(parse_result) or cleaned).strip()
        execution_plan = self._build_execution_plan(commands, relation, condition)
        overall_confidence = max((cmd.confidence for cmd in commands), default=parse_result.confidence)
        requires_confirmation = bool(unresolved_slots) or overall_confidence < 0.85 or any(
            warning in cmd.warnings
            for cmd in commands
            for warning in ("device_inferred", "value_out_of_range")
        )

        return SemanticDecision(
            commands=commands,
            normalized_text=cleaned,
            rendered_text=final_rendered_text,
            implicit_signals=implicit_signals,
            unresolved_slots=sorted(set(unresolved_slots)),
            execution_plan=execution_plan,
            requires_confirmation=requires_confirmation,
            confirmation_message=self._build_confirmation_message(
                final_rendered_text,
                sorted(set(unresolved_slots)),
            ) if requires_confirmation else None,
            source=source,
            overall_confidence=overall_confidence,
            debug={
                "rule_confidence": parse_result.confidence,
                "relation": relation,
                "command_count": len(commands),
                "needs_glm": parse_result.needs_glm,
            },
        )

    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        return _rule_cache.stats()

    def clear_cache(self) -> None:
        """清空缓存"""
        _rule_cache.clear()

    def cache_hit_rate(self) -> float:
        """获取缓存命中率"""
        stats = self.get_cache_stats()
        return stats['hit_rate'] if 'hit_rate' in stats else 0.0
