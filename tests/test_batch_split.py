from __future__ import annotations

from runtime.api_gateway import SmartHomeRuntime


def test_split_preserves_ba_clause() -> None:
    """把…调为… should NOT be split at the inner verb."""
    chunks = SmartHomeRuntime._split_multi_commands(
        "把小孩房间的温度调为26度打开客厅的森环系统打开二楼的射灯"
    )
    assert any("调为26度" in c for c in chunks), f"把…调为 clause broken: {chunks}"
    assert any("小孩房间" in c for c in chunks), f"把 object lost: {chunks}"


def test_split_preserves_jiang_clause() -> None:
    """将…设为… should NOT be split at the inner verb."""
    chunks = SmartHomeRuntime._split_multi_commands("将空调温度设为26度打开客厅灯")
    assert len(chunks) == 2
    assert "设为26度" in chunks[0]
    assert "打开客厅灯" in chunks[1]


def test_split_ba_followed_by_unrelated_action() -> None:
    """把 clause + unrelated action should split between them."""
    chunks = SmartHomeRuntime._split_multi_commands(
        "把小孩房间的温度调为26度打开客厅的森环系统打开二楼的射灯"
    )
    # Should produce 3 chunks: 把-clause, 打开客厅, 打开二楼
    assert len(chunks) == 3, f"expected 3 chunks, got {len(chunks)}: {chunks}"
    assert "调为26度" in chunks[0]
    assert "森环系统" in chunks[1]
    assert "射灯" in chunks[2]


def test_split_full_noisy_pipeline() -> None:
    """Full denoised multi-command with 把 clause."""
    chunks = SmartHomeRuntime._split_multi_commands(
        "打开射灯打开二楼的窗帘并且把小孩房间的温度调为26度打开客厅的森环系统打开二楼的射灯"
    )
    # 把…调为26度 must stay together
    ba_chunks = [c for c in chunks if "小孩房间" in c or "调为" in c]
    merged = " ".join(ba_chunks)
    assert "调为26度" in merged, f"把 clause broken: {chunks}"


def test_split_plain_multi_action() -> None:
    """No 把 — should split at every action verb."""
    chunks = SmartHomeRuntime._split_multi_commands("打开客厅灯关闭卧室空调")
    assert len(chunks) == 2
    assert "打开" in chunks[0]
    assert "关闭" in chunks[1]


def test_split_single_ba_command() -> None:
    """Single 把 command — no split needed."""
    chunks = SmartHomeRuntime._split_multi_commands("把空调温度调到25度")
    assert len(chunks) == 1
    assert "调到25度" in chunks[0]


def test_split_ba_gei_clause() -> None:
    """给…调到… should also be preserved."""
    chunks = SmartHomeRuntime._split_multi_commands("给小孩房间温度调到26度打开客厅灯")
    assert any("调到26度" in c for c in chunks), f"给…调到 clause broken: {chunks}"
    assert any("打开客厅灯" in c for c in chunks)
