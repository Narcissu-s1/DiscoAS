"""
tests/test_i18n.py
测试 i18n 模块的翻译加载
"""


def test_load_zh_cn():
    from settings.i18n import load_translations

    data = load_translations("zh_CN")
    assert len(data) > 100
    assert "discover" in data
    assert "settings" in data
    assert "version" in data


def test_load_zh_tw():
    from settings.i18n import load_translations

    data = load_translations("zh_TW")
    assert len(data) > 50
    assert "discover" in data


def test_load_en_us():
    from settings.i18n import load_translations

    data = load_translations("en_US")
    assert len(data) > 50
    assert "discover" in data


def test_set_language():
    from settings.i18n import set_language, t

    set_language("en_US")
    assert t("discover") == "Choose a Song"


def test_t_returns_key_when_missing():
    from settings.i18n import set_language, t

    set_language("zh_CN")
    assert t("nonexistent_key_xyz") == "nonexistent_key_xyz"


def test_t_returns_default_when_provided():
    from settings.i18n import set_language, t

    set_language("zh_CN")
    assert t("missing_key", default="fallback") == "fallback"


def test_languages_dict():
    from settings.i18n import LANGUAGES

    assert "zh_CN" in LANGUAGES
    assert "zh_TW" in LANGUAGES
    assert "en_US" in LANGUAGES
    assert LANGUAGES["zh_CN"] == "简体中文"
