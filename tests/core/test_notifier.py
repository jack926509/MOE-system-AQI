from core.notifier import _split_for_telegram


def test_split_short_text():
    assert _split_for_telegram("hi") == ["hi"]


def test_split_keeps_lines_together():
    text = "\n".join([f"line {i}" for i in range(10)])
    assert _split_for_telegram(text, limit=200) == [text]


def test_split_multi_chunk_on_newline():
    text = "\n".join(["x" * 50] * 10)  # 10 lines × 51 chars = ~510
    chunks = _split_for_telegram(text, limit=120)
    assert len(chunks) >= 4
    for c in chunks:
        assert len(c) <= 120
    # 重組應等於原文（換行邊界拆，剛好切換行）
    assert "\n".join(chunks) == text


def test_split_hard_break_long_line():
    text = "y" * 350
    chunks = _split_for_telegram(text, limit=100)
    assert len(chunks) == 4
    assert all(len(c) <= 100 for c in chunks)
    assert "".join(chunks) == text
