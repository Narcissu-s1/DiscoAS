import os
from unittest.mock import MagicMock, patch


def test_music_preferences_autosave_and_hot_reload():
    from settings.setting_gui import SettingsWindow

    window = MagicMock()
    window._autosave_ready = True
    window.edit_mystery_cover.text.return_value = ""
    window.spin_discovered.value.return_value = 5
    window.chk_mystery.isChecked.return_value = True
    window.spin_mystery_num.value.return_value = 2
    window.spin_cache_batches.value.return_value = 3
    window.chk_refresh.isChecked.return_value = False

    SettingsWindow._save_music_preferences(window)

    assert window.pa_setting.number_of_discovered_songs == 5
    assert window.pa_setting.num_of_mystery_song == 2
    assert window.pa_setting.cache_batches == 3
    window.pa_setting.save.assert_called_once_with()
    window.notify_settings_changed.assert_called_once_with(music_changed=True)
    window._mark_saved.assert_called_once_with()


def test_settings_window_has_no_manual_apply_button():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication, QTabWidget

    from settings.setting_gui import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with (
        patch.object(SettingsWindow, "_get_auto_start_status", return_value=False),
        patch.object(SettingsWindow, "_get_playlist_name_from_json", return_value="已加载"),
    ):
        window = SettingsWindow()

    assert not hasattr(window, "btn_apply")
    assert isinstance(window.stack, QTabWidget)
    assert window.stack.currentIndex() == 0
    assert [window.stack.tabText(i) for i in range(window.stack.count())] == [
        "选歌",
        "外观",
        "关于",
    ]
    assert not window.stack.isAncestorOf(window.chk_auto_start)
    assert not window.stack.isAncestorOf(window.btn_view_log)
    assert window.lbl_save_status.text() == ""
    window._mark_saved()
    assert window.lbl_save_status.text() == "修改已保存"
    window.close()
    app.processEvents()


def test_settings_window_flushes_pending_slider_save_on_close():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication

    from settings.setting_gui import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with (
        patch.object(SettingsWindow, "_get_auto_start_status", return_value=False),
        patch.object(SettingsWindow, "_get_playlist_name_from_json", return_value="已加载"),
    ):
        window = SettingsWindow()

    with patch.object(window, "_save_gui_preferences") as save_gui:
        window.slider_card_size.setValue(window.slider_card_size.value() + 0.01)
        assert window._gui_save_timer.isActive()
        window.close()

    save_gui.assert_called_once_with()
    app.processEvents()


def test_header_auto_start_toggle_keeps_autosave_behavior():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication

    from settings.setting_gui import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with (
        patch.object(SettingsWindow, "_get_auto_start_status", return_value=False),
        patch.object(SettingsWindow, "_get_playlist_name_from_json", return_value="已加载"),
    ):
        window = SettingsWindow()

    with patch.object(window, "_set_auto_start", return_value=True) as set_auto_start:
        window.chk_auto_start.setChecked(True)

    set_auto_start.assert_called_once_with(True)
    assert window.lbl_save_status.text() == "修改已保存"
    window.close()
    app.processEvents()


def test_playlist_address_stays_silent_until_load_succeeds():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication

    from settings.setting_gui import SettingsWindow

    app = QApplication.instance() or QApplication([])
    with (
        patch.object(SettingsWindow, "_get_auto_start_status", return_value=False),
        patch.object(SettingsWindow, "_get_playlist_name_from_json", return_value="已加载"),
    ):
        window = SettingsWindow()

    window.add_playlist_row()
    row = window.table_pl.rowCount() - 1
    id_editor = window.table_pl.cellWidget(row, 1)
    with patch.object(window.pa_setting, "save") as save_music:
        id_editor.setText("draft-id")
        id_editor.editingFinished.emit()

    assert window.lbl_save_status.text() == ""
    save_music.assert_not_called()
    window.close()
    app.processEvents()


def test_platform_combo_ignores_wheel_without_affecting_type_combo():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt6.QtWidgets import QApplication, QComboBox

    from settings.setting_gui import NoWheelComboBox, SettingsWindow

    app = QApplication.instance() or QApplication([])
    with (
        patch.object(SettingsWindow, "_get_auto_start_status", return_value=False),
        patch.object(SettingsWindow, "_get_playlist_name_from_json", return_value="已加载"),
    ):
        window = SettingsWindow()

    window.add_playlist_row()
    row = window.table_pl.rowCount() - 1
    platform_combo = window.table_pl.cellWidget(row, 0)
    type_combo = window.table_pl.cellWidget(row, 2)
    wheel_event = MagicMock()
    platform_combo.setCurrentIndex(1)
    platform_combo.wheelEvent(wheel_event)

    assert isinstance(platform_combo, NoWheelComboBox)
    assert type(type_combo) is QComboBox
    assert platform_combo.currentIndex() == 1
    wheel_event.ignore.assert_called_once_with()
    window.close()
    app.processEvents()


def test_runtime_music_reload_never_refreshes_remote_playlist():
    import Discover_gui

    discover_app = MagicMock()
    with (
        patch.object(Discover_gui, "_main_window", None),
        patch.object(Discover_gui, "invalidate_song_cache") as invalidate,
        patch.object(Discover_gui, "preload_next_batch") as preload,
    ):
        Discover_gui.apply_runtime_settings(discover_app, reload_songs=True)

    discover_app.gui_setting.load.assert_called_once_with()
    discover_app.music_setting.load.assert_called_once_with()
    discover_app._apply_settings.assert_called_once_with()
    discover_app._update_enabled_playlist.assert_not_called()
    invalidate.assert_called_once_with()
    preload.assert_called_once_with(discover_app)


def test_invalidating_song_cache_advances_generation_and_clears_data():
    import Discover_gui

    old_generation = Discover_gui._runtime_generation
    try:
        Discover_gui._cached_song_batches[:] = [["old song"]]
        Discover_gui._image_cache["old cover"] = b"data"
        with patch.object(Discover_gui.Playlist, "clear_cache") as clear_playlist_cache:
            new_generation = Discover_gui.invalidate_song_cache()

        assert new_generation == old_generation + 1
        assert Discover_gui._cached_song_batches == []
        assert Discover_gui._image_cache == {}
        clear_playlist_cache.assert_called_once_with()
    finally:
        Discover_gui._runtime_generation = old_generation
        Discover_gui._cached_song_batches.clear()
        Discover_gui._image_cache.clear()


def test_stale_preload_cannot_commit_after_settings_change():
    import Discover_gui

    class InlineThread:
        def __init__(self, target, daemon):
            self._target = target

        def is_alive(self):
            return False

        def start(self):
            self._target()

    discover_app = MagicMock()
    discover_app.music_setting.cache_batches = 1
    discover_app.discover_songs.side_effect = lambda: (
        Discover_gui.invalidate_song_cache() or [MagicMock()]
    )

    old_generation = Discover_gui._runtime_generation
    old_thread = Discover_gui._preload_thread
    old_thread_generation = Discover_gui._preload_thread_generation
    try:
        Discover_gui._preload_thread = None
        Discover_gui._preload_thread_generation = None
        with (
            patch.object(Discover_gui.threading, "Thread", InlineThread),
            patch.object(Discover_gui.Playlist, "clear_cache"),
        ):
            Discover_gui.preload_next_batch(discover_app)

        assert Discover_gui._cached_song_batches == []
        assert Discover_gui._image_cache == {}
    finally:
        Discover_gui._runtime_generation = old_generation
        Discover_gui._preload_thread = old_thread
        Discover_gui._preload_thread_generation = old_thread_generation
        Discover_gui._cached_song_batches.clear()
        Discover_gui._image_cache.clear()


def test_stale_overlay_result_is_ignored():
    import Discover_gui

    window = MagicMock()
    window._load_generation = 2
    window._runtime_generation = Discover_gui.get_runtime_generation()

    Discover_gui.DiscoverOverlay._on_songs_loaded(
        window,
        1,
        window._runtime_generation,
        ["old song"],
        [],
    )

    window._display_songs.assert_not_called()


def test_stale_overlay_error_does_not_show_dialog():
    import Discover_gui

    window = MagicMock()
    window.discover_app.discover_songs.side_effect = FileNotFoundError("old playlist")
    stale_generation = Discover_gui.get_runtime_generation() - 1

    with patch.object(Discover_gui.QMessageBox, "warning") as warning:
        Discover_gui.DiscoverOverlay._load_songs_async(window, 1, stale_generation)

    warning.assert_not_called()


def test_tray_translation_refresh_updates_existing_actions():
    import Discover_gui

    tray = MagicMock()
    discover_action = MagicMock()
    settings_action = MagicMock()
    shortcut_action = MagicMock()
    restart_action = MagicMock()
    quit_action = MagicMock()

    with (
        patch.object(Discover_gui, "_", side_effect=lambda key: f"translated:{key}"),
        patch.object(Discover_gui, "_tray_icon", tray),
        patch.object(Discover_gui, "_discover_action", discover_action),
        patch.object(Discover_gui, "_settings_action", settings_action),
        patch.object(Discover_gui, "_shortcut_action", shortcut_action),
        patch.object(Discover_gui, "_restart_action", restart_action),
        patch.object(Discover_gui, "_quit_action", quit_action),
        patch.object(Discover_gui, "_shortcut_enabled", True),
    ):
        Discover_gui.refresh_translated_ui()

    tray.setToolTip.assert_called_once_with("DiscoAS - translated:discover")
    discover_action.setText.assert_called_once_with("translated:discover")
    settings_action.setText.assert_called_once_with("translated:settings")
    shortcut_action.setText.assert_called_once_with("translated:pause_shortcut")
    restart_action.setText.assert_called_once_with("translated:restart")
    quit_action.setText.assert_called_once_with("translated:quit")
