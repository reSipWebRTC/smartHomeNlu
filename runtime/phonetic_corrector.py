"""phonetic_corrector.py – Lightweight pypinyin-based ASR error correction.

Corrects common phonetic substitution errors in Chinese ASR output
(e.g. 窗连→窗帘, 森环→新风, 社等→射灯) before NLU processing.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Set, Tuple

try:
    import pypinyin  # type: ignore
except ImportError:
    pypinyin = None

from .debug_log import get_logger

logger = get_logger("phonetic_corrector")

# ── Homophone groups for common ASR confusions ────────────────────

_HOMOPHONE_GROUPS: List[Tuple[str, ...]] = [
    # 窗帘 ↔ 窗连 / 窗帘
    ("帘", "连", "莲", "联"),
    # 新风 ↔ 森环
    ("新", "心", "欣", "薪", "森"),
    ("风", "丰", "封", "峰", "锋", "蜂", "环"),
    # 射灯 ↔ 社等
    ("射", "社", "设", "舍", "涉"),
    ("灯", "等", "登", "邓", "蹬"),
    # 窗帘 ↔ 床帘
    ("窗", "床", "创", "闯"),
    # 空调 ↔ 恐挑
    ("空", "恐", "控", "孔"),
    ("调", "挑", "条", "跳", "铁"),
    # 加湿 ↔ 嘉实
    ("加", "嘉", "家", "佳", "假"),
    ("湿", "实", "十", "石", "时", "识"),
    # 湿度 ↔ 十度
    ("度", "杜", "肚", "读", "堵"),
]

# Build reverse lookup: char -> group index
_CHAR_TO_GROUP: Dict[str, int] = {}
for _idx, _group in enumerate(_HOMOPHONE_GROUPS):
    for _ch in _group:
        _CHAR_TO_GROUP.setdefault(_ch, _idx)


def _are_homophones(a: str, b: str) -> bool:
    """Check if two single chars belong to the same homophone group."""
    ga = _CHAR_TO_GROUP.get(a)
    gb = _CHAR_TO_GROUP.get(b)
    if ga is not None and gb is not None and ga == gb:
        return True
    return False


def _pinyin_similarity(a: str, b: str) -> float:
    """Compute pinyin-level similarity between two Chinese strings."""
    if pypinyin is None:
        return 0.0
    try:
        py_a = [item[0] for item in pypinyin.pinyin(a, style=pypinyin.NORMAL)]
        py_b = [item[0] for item in pypinyin.pinyin(b, style=pypinyin.NORMAL)]
    except Exception:
        return 0.0
    if not py_a or not py_b:
        return 0.0
    return SequenceMatcher(None, py_a, py_b).ratio()


def _char_homophone_ratio(a: str, b: str) -> float:
    """Ratio of homophone-matching characters between two strings."""
    if not a or not b:
        return 0.0
    min_len = min(len(a), len(b))
    if min_len == 0:
        return 0.0
    matches = 0
    for i in range(min_len):
        if _are_homophones(a[i], b[i]) or a[i] == b[i]:
            matches += 1
    return matches / max(len(a), len(b))


def _combined_similarity(fragment: str, candidate: str) -> float:
    """Weighted similarity: char + pinyin + homophone."""
    char_sim = SequenceMatcher(None, fragment, candidate).ratio()
    py_sim = _pinyin_similarity(fragment, candidate)
    homo_ratio = _char_homophone_ratio(fragment, candidate)

    # When all chars are homophone-group matches (common ASR errors),
    # give a strong boost even if pinyin differs
    all_homophones = (
        len(fragment) == len(candidate)
        and len(fragment) >= 2
        and homo_ratio >= 0.8
    )

    score = 0.30 * char_sim + 0.40 * py_sim + 0.30 * homo_ratio
    if all_homophones:
        score += 0.40
    if candidate.startswith(fragment) or fragment.startswith(candidate):
        score += 0.15
    if fragment in candidate or candidate in fragment:
        score += 0.08
    return min(score, 1.0)


class PhoneticCorrector:
    """Corrects ASR phonetic errors against a known vocabulary of hot words."""

    def __init__(self, hot_words: Optional[Set[str]] = None) -> None:
        self._vocabulary: List[str] = []
        self._vocabulary_set: Set[str] = set()
        if hot_words:
            self._vocabulary = sorted(hot_words, key=len, reverse=True)
            self._vocabulary_set = set(hot_words)

    def update_vocabulary(self, words: Set[str]) -> None:
        """Update the vocabulary used for correction."""
        self._vocabulary = sorted(words, key=len, reverse=True)
        self._vocabulary_set = set(words)

    def correct(self, text: str, threshold: float = 0.70) -> str:
        """Attempt to correct phonetic errors in *text*.

        Strategy: scan left-to-right, building a result string. At each
        position, try to match a window against vocabulary words using
        phonetic similarity. Replace if a good match is found.

        Returns the corrected text (may be unchanged).
        """
        if not self._vocabulary or not text:
            return text

        max_word_len = max(len(w) for w in self._vocabulary) if self._vocabulary else 6
        max_word_len = min(max_word_len, 8)

        result_parts: List[str] = []
        i = 0
        changes = 0

        while i < len(text):
            best_match: Optional[str] = None
            best_score = 0.0
            best_len = 0

            for window_len in range(min(max_word_len, len(text) - i), 1, -1):
                fragment = text[i : i + window_len]

                # Skip if fragment is already a vocabulary word
                if fragment in self._vocabulary_set:
                    break

                # Skip if fragment is too short
                if window_len < 2:
                    continue

                for word in self._vocabulary:
                    if len(word) != window_len:
                        continue
                    # Skip if any proper sub-fragment of this window is a vocab word
                    skip = False
                    for sub_start in range(0, window_len):
                        for sub_end in range(sub_start + 1, window_len):
                            if text[i + sub_start:i + sub_end] in self._vocabulary_set:
                                skip = True
                                break
                        if skip:
                            break
                    if skip:
                        continue
                    score = _combined_similarity(fragment, word)
                    if score > best_score and score >= threshold:
                        best_score = score
                        best_match = word
                        best_len = window_len

                if best_match and best_len == window_len:
                    break  # Found best match for this position

            if best_match and best_len > 0 and best_match != text[i : i + best_len]:
                result_parts.append(best_match)
                changes += 1
                i += best_len
            else:
                result_parts.append(text[i])
                i += 1

        if changes > 0:
            corrected = "".join(result_parts)
            logger.debug(
                "phonetic correct changes=%d text=%s → %s",
                changes,
                text,
                corrected,
            )
            return corrected
        return text
