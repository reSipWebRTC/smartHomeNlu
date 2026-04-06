# template_matcher.py
"""
模板匹配扩展器
支持常见模板模式的智能匹配
"""

import re
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass


@dataclass
class TemplateMatch:
    """模板匹配结果"""
    template_name: str
    action: str
    device: str
    location: str = ""
    parameter: str = ""
    confidence: float = 0.95
    matched_text: str = ""
    unmatched_text: str = ""




class TemplateMatcher:
    """
    模板匹配器

    支持的模板：
    1. "打开{设备}" - 基本设备操作
    2. "关{设备}" - 关闭设备
    3. "把{房间}{设备}{状态}" - 把房间设备状态
    4. "动作+设备" - 各种动作设备组合
    """

    def __init__(self, hot_words):
        """
        初始化模板匹配器

        Args:
            hot_words: 热词配置
        """
        self.hot_words = hot_words

        # 热词集合
        if hasattr(hot_words, 'action_set'):
            self.action_set = hot_words.action_set
            self.device_set = hot_words.device_set
            self.location_set = hot_words.location_set
            self.parameter_set = hot_words.parameter_set
        else:
            # 直接从 hot_words 获取属性
            self.action_set = getattr(hot_words, 'action_set', set())
            self.device_set = getattr(hot_words, 'device_set', set())
            self.location_set = getattr(hot_words, 'location_set', set())
            self.parameter_set = getattr(hot_words, 'parameter_set', set())

        # 预编译模板正则
        self._compile_patterns()

    def _compile_patterns(self):
        """预编译所有模板的正则表达式"""
        # 模板1: "打开{设备}" 及类似
        self._pattern1 = re.compile(
            r'^(打开|开启|点亮|开启|关掉|停止|熄灭|关|调高|调低|调亮|调暗|设置|设置成|设置为|调成|变成|保持|移动到|移到|放到)\s*([\u4e00-\u9fa5]{2,6})\s*([^,，；]*?)$'
        )

        # 模板2: "把{房间}{设备}{状态}"
        self._pattern2 = re.compile(
            r'^把\s*([\u4e00-\u9fa5]{2,4})\s*([\u4e00-\u9fa5]{2,6})\s*(调高|调低|调亮|调暗|打开|关闭|拉开|关上|设为|设置|调成|变成)\s*([^,，；]*?)$'
        )

        # 模板3: 动作+设备（分离的）
        # 动作集合（按长度降序，优先匹配长词）
        sorted_actions = sorted(self.action_set, key=len, reverse=True)
        action_pattern = '|'.join(re.escape(a) for a in sorted_actions)
        self._pattern3 = re.compile(
            rf'^({action_pattern})\s*([\u4e00-\u9fa5]{2,6})\s*([^,，；]*?)$'
        )

        # 模板4: 设备词+状态词
        state_words = ['开', '关', '亮', '暗', '高', '低']
        state_pattern = '|'.join(state_words)
        self._pattern4 = re.compile(
            rf'^([\u4e00-\u9fa5]{{2,6}})\s*({state_pattern})$'
        )

    def match_template(self, text: str) -> Optional[TemplateMatch]:
        """
        匹配模板

        Args:
            text: 输入文本

        Returns:
            TemplateMatch 或 None
        """
        text = text.strip()

        # 模板1: "打开{设备}" 及类似
        match = self._pattern1.match(text)
        if match:
            action = match.group(1)
            device = match.group(2)
            parameter = match.group(3).strip()

            # 检查设备是否有效
            if device in self.device_set or any(dev in device for dev in self.device_set):
                return TemplateMatch(
                    template_name="动作设备",
                    action=action,
                    device=device,
                    parameter=parameter,
                    confidence=0.95,
                    matched_text=text,
                )

        # 模板2: "把{房间}{设备}{状态}"
        match = self._pattern2.match(text)
        if match:
            location = match.group(1)
            device = match.group(2)
            action = f"把{match.group(3)}"
            parameter = match.group(4).strip()

            # 验证位置和设备
            if location in self.location_set and device in self.device_set:
                return TemplateMatch(
                    template_name="把房间设备状态",
                    action=action,
                    device=device,
                    location=location,
                    parameter=parameter,
                    confidence=0.95,
                    matched_text=text,
                )

        # 模板3: 动作+设备（分离的）
        match = self._pattern3.match(text)
        if match:
            action = match.group(1)
            device = match.group(2)
            parameter = match.group(3).strip()

            # 动作和设备都有效
            if action in self.action_set and device in self.device_set:
                return TemplateMatch(
                    template_name="动作设备分离",
                    action=action,
                    device=device,
                    parameter=parameter,
                    confidence=0.9,
                    matched_text=text,
                )

        # 模板4: 设备词+状态词
        match = self._pattern4.match(text)
        if match:
            device = match.group(1)
            state = match.group(2)
            parameter = ""  # pattern4 只有 2 个捕获组

            # 映射状态到动作
            state_to_action = {
                '开': '打开',
                '关': '关闭',
                '亮': '调亮',
                '暗': '调暗',
                '高': '调高',
                '低': '调低',
            }

            action = state_to_action.get(state, '操作')

            if device in self.device_set:
                return TemplateMatch(
                    template_name="设备状态",
                    action=action,
                    device=device,
                    parameter=parameter,
                    confidence=0.85,
                    matched_text=text,
                )

        return None

    def match_multiple_templates(self, text: str) -> List[TemplateMatch]:
        """
        尝试多个模板匹配（按优先级）

        Args:
            text: 输入文本

        Returns:
            匹配成功的模板列表
        """
        matches = []

        # 按优先级尝试所有模板
        templates = [
            (self._pattern1, "动作设备"),
            (self._pattern2, "把房间设备状态"),
            (self._pattern3, "动作设备分离"),
            (self._pattern4, "设备状态"),
        ]

        for pattern, template_name in templates:
            match = pattern.match(text)
            if match:
                # 根据不同模板创建匹配结果
                if template_name == "动作设备":
                    action = match.group(1)
                    device = match.group(2)
                    parameter = match.group(3).strip()

                    matches.append(TemplateMatch(
                        template_name=template_name,
                        action=action,
                        device=device,
                        parameter=parameter,
                        confidence=0.95,
                        matched_text=text,
                    ))

                elif template_name == "把房间设备状态":
                    location = match.group(1)
                    device = match.group(2)
                    action = f"把{match.group(3)}"
                    parameter = match.group(4).strip()

                    matches.append(TemplateMatch(
                        template_name=template_name,
                        action=action,
                        device=device,
                        location=location,
                        parameter=parameter,
                        confidence=0.95,
                        matched_text=text,
                    ))

                elif template_name == "动作设备分离":
                    action = match.group(1)
                    device = match.group(2)
                    parameter = match.group(3).strip()

                    matches.append(TemplateMatch(
                        template_name=template_name,
                        action=action,
                        device=device,
                        parameter=parameter,
                        confidence=0.9,
                        matched_text=text,
                    ))

                elif template_name == "设备状态":
                    device = match.group(1)
                    state = match.group(2)
                    parameter = ""  # pattern4 只有 2 个捕获组

                    state_to_action = {
                        '开': '打开',
                        '关': '关闭',
                        '亮': '调亮',
                        '暗': '调暗',
                        '高': '调高',
                        '低': '调低',
                    }

                    action = state_to_action.get(state, '操作')

                    matches.append(TemplateMatch(
                        template_name=template_name,
                        action=action,
                        device=device,
                        parameter=parameter,
                        confidence=0.85,
                        matched_text=text,
                    ))

        return matches

    def template_match_to_command(self, template_match: TemplateMatch) -> Dict:
        """
        将模板匹配转换为命令字典

        Args:
            template_match: 模板匹配结果

        Returns:
            命令字典
        """
        return {
            "action": template_match.action,
            "device": template_match.device,
            "location": template_match.location,
            "parameter": template_match.parameter,
            "confidence": template_match.confidence,
        }

    def get_template_stats(self) -> Dict[str, Any]:
        """获取模板匹配统计信息"""
        return {
            "template_patterns": 4,
            "action_words_count": len(self.action_set),
            "device_words_count": len(self.device_set),
            "location_words_count": len(self.location_set),
        }
