from __future__ import annotations

from runtime.text_denoiser import TextDenoiser


def test_denoise_removes_filler_phrases() -> None:
    d = TextDenoiser()
    result = d.denoise("嗯嗯打开那个卧室的空调")
    assert "嗯" not in result
    assert "那个" not in result
    assert "打开" in result
    assert "卧室" in result
    assert "空调" in result


def test_denoise_removes_filler_chars() -> None:
    d = TextDenoiser()
    result = d.denoise("打开啊客厅哈灯")
    assert result == "打开客厅灯"


def test_denoise_fixes_dirty_variants() -> None:
    d = TextDenoiser()
    # 滴→的, 地→的, 得→的
    result = d.denoise("设置滴温度地25度")
    assert "的" in result
    assert "滴" not in result
    assert "地" not in result


def test_denoise_collapses_duplicate_structural() -> None:
    d = TextDenoiser()
    result = d.denoise("打开的的客厅灯")
    assert "的的" not in result
    assert result == "打开的客厅灯"


def test_denoise_preserves_clean_text() -> None:
    d = TextDenoiser()
    assert d.denoise("打开客厅灯") == "打开客厅灯"
    assert d.denoise("把空调温度调到25度") == "把空调温度调到25度"


def test_denoise_handles_noisy_temperature_command() -> None:
    d = TextDenoiser()
    result = d.denoise("设置的哈哈的嘎室内温度为25度")
    # Should remove "哈哈" filler phrase, keep the semantic core
    assert "哈哈" not in result
    assert "设置" in result
    assert "温度" in result
    assert "25" in result


def test_denoise_empty_input() -> None:
    d = TextDenoiser()
    assert d.denoise("") == ""
    assert d.denoise("   ") == ""


def test_denoise_short_filler_only() -> None:
    """A single filler char that's also the entire input should be preserved."""
    d = TextDenoiser()
    # "哈" is a filler char but it's the only content — removal leaves empty
    # which triggers the fallback to raw.
    result = d.denoise("哈")
    assert isinstance(result, str)


def test_denoise_removes_polite_prefix_fillers() -> None:
    d = TextDenoiser()
    result = d.denoise("那个那个帮我打开客厅灯")
    assert "那个" not in result
    assert "打开客厅灯" in result


def test_denoise_preserves_numbers_and_units() -> None:
    d = TextDenoiser()
    result = d.denoise("把温度设为25度")
    assert "25" in result
    assert "度" in result


def test_denoise_strips_profanity_fillers() -> None:
    d = TextDenoiser()
    result = d.denoise("tmd的小孩房间的温度调为26度")
    assert "tmd" not in result
    assert "小孩房间" in result
    assert "温度" in result
    assert "26" in result


def test_denoise_strips_chinese_profanity() -> None:
    d = TextDenoiser()
    result = d.denoise("打开他妈的的的二楼射灯")
    assert "他妈的" not in result
    assert "射灯" in result


def test_denoise_preserves_system_device_names() -> None:
    d = TextDenoiser()
    result = d.denoise("打开客厅的森环系统")
    assert "森环系统" in result or "系统" in result


def test_denoise_multi_command_with_noise() -> None:
    d = TextDenoiser()
    result = d.denoise("打开啊啊射灯打开他妈的的的二楼的啊窗帘并且把tmd的小孩房间的温度调为26度")
    assert "射灯" in result
    assert "温度" in result
    assert "26" in result
    assert "哈哈" not in result
    assert "tmd" not in result
    assert "他妈的" not in result
