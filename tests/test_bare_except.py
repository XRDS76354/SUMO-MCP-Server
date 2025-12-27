import builtins

import pytest


def test_is_additional_file_does_not_swallow_keyboard_interrupt(monkeypatch, tmp_path) -> None:
    from workflows.signal_opt import _is_additional_file

    file_path = tmp_path / "dummy.xml"
    file_path.write_text("<additional/>", encoding="utf-8")

    def raise_keyboard_interrupt(*args, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(builtins, "open", raise_keyboard_interrupt)

    with pytest.raises(KeyboardInterrupt):
        _is_additional_file(str(file_path))

