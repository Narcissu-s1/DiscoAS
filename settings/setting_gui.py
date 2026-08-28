import contextlib
import datetime
import os
import sys

from PyQt6.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from platforms.KugouMusic.get_json import PlaylistAlbumJson as KugouPlaylistAlbumJson

# 静态导入所有平台的 get_json 模块
from platforms.NeteaseCloudMusic.get_json import PlaylistAlbumJson as NeteasePlaylistAlbumJson
from platforms.QQMusic.get_json import PlaylistAlbumJson as QQMusicPlaylistAlbumJson
from platforms.Spotify.get_json import PlaylistAlbumJson as SpotifyPlaylistAlbumJson

# 导入统一的路径管理模块
from settings.user_data_path import get_resource_dir

# 平台 PlaylistAlbumJson 类映射
PLATFORM_JSON_MAP = {
    'NeteaseCloudMusic': NeteasePlaylistAlbumJson,
    'QQMusic': QQMusicPlaylistAlbumJson,
    'Spotify': SpotifyPlaylistAlbumJson,
    'KugouMusic': KugouPlaylistAlbumJson,
}


def _get_src_path():
    """获取 src 目录路径，支持打包后的环境"""
    return os.path.join(get_resource_dir(), "src")


def _get_platforms_path():
    """获取 platforms 目录路径，支持打包后的环境"""
    return os.path.join(get_resource_dir(), "platforms")

# 导入 i18n 模块
try:
    from settings import i18n
    _ = i18n.t
except ImportError:
    # 如果导入失败，创建一个简单的翻译函数
    def _(key):
        return key

# 导入你修改后的类
try:
    from settings.gui_setting import GuiSetting
    from settings.music_setting import PASetting, PlaylistAlbum
except ImportError:
    print("错误: 无法导入设置类，请确保 music_setting.py 和 gui_setting.py 在同一目录下。")
    sys.exit(1)


class ColorPreviewWidget(QWidget):
    """用于显示颜色的小方块 (可点击弹出调色盘)"""
    color_changed = pyqtSignal(str)  # 颜色变更信号

    def __init__(self, color_hex, parent=None):
        super().__init__(parent)
        self.setFixedSize(24, 24)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)  # 鼠标悬停时显示手型
        self.color_hex = color_hex if color_hex else "#FFFFFF"
        self.update_style()

    def update_style(self):
        display_color = "#FFFFFF" if not QColor(self.color_hex).isValid() else self.color_hex

        self.setStyleSheet(f"""
            background-color: {display_color};
            border: 1px solid #888;
            border-radius: 3px;
        """)

    def set_color(self, color_hex):
        self.color_hex = color_hex
        self.update_style()

    def mousePressEvent(self, event):
        """点击时弹出颜色选择器"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_color_picker()
        super().mousePressEvent(event)

    def open_color_picker(self):
        """打开系统颜色选择器"""
        initial_color = QColor(self.color_hex) if QColor(self.color_hex).isValid() else QColor("#FFFFFF")
        color = QColorDialog.getColor(initial_color, self, "选择颜色")
        if color.isValid():
            self.color_hex = color.name()
            self.update_style()
            self.color_changed.emit(self.color_hex)  # 发出颜色变更信号


class FloatSlider(QWidget):
    """
    自定义控件：带有数值显示的浮点数滑动条
    QSlider 本身只支持整数，这里通过倍率转换实现浮点控制
    """
    valueChanged = pyqtSignal(float)

    def __init__(self, initial_value, min_val=0.5, max_val=3.0, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 滑动条 (内部使用整数，精度 0.01 -> 放大100倍)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(int(min_val * 100), int(max_val * 100))
        self.slider.setValue(int(initial_value * 100))
        self.slider.setTracking(True) # 允许实时触发

        # 数值显示标签
        self.label = QLabel(f"{initial_value:.2f}")
        self.label.setFixedWidth(40) # 固定宽度防止抖动
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.slider)
        layout.addWidget(self.label)

        self.slider.valueChanged.connect(self._on_slider_changed)

    def _on_slider_changed(self, int_value):
        float_value = int_value / 100.0
        self.label.setText(f"{float_value:.2f}")
        self.valueChanged.emit(float_value)

    def value(self):
        return self.slider.value() / 100.0

    def setValue(self, value):
        self.slider.setValue(int(value * 100))


class SettingsWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._autosave_ready = False
        self._playlist_save_scheduled = False

        # 1. 加载后端逻辑
        self.pa_setting = PASetting()
        self.pa_setting.load()

        self.gui_setting = GuiSetting()
        self.gui_setting.load()

        # 加载保存的语言到 i18n 模块
        try:
            from settings import i18n
            i18n.set_language(self.gui_setting.language)
        except ImportError:
            pass

        # 2. 初始化界面
        self.setWindowTitle(_("app_name") + " - Settings")

        # 设置窗口图标 - 使用 get_app_root() 支持打包后环境
        icon_path = os.path.join(_get_src_path(), "Icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        self.resize(1450, 750)

        # 中央部件 - 使用水平布局
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ========== 左侧导航栏 ==========
        left_widget = QWidget()
        left_widget.setFixedWidth(200)
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(15, 20, 15, 20)
        left_layout.setSpacing(10)

        # Logo
        logo_label = QLabel()
        logo_pixmap = QPixmap(os.path.join(_get_src_path(), "DiscoAS.png"))
        scaled_pixmap = logo_pixmap.scaled(120, 120, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        logo_label.setPixmap(scaled_pixmap)
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(logo_label)
        left_layout.addSpacing(10)

        # 导航按钮
        nav_buttons = [
            (_("about"), 0),
            (_("discover_settings"), 1),
            (_("gui_settings"), 2),
            (_("other_settings"), 3),
        ]

        self.btn_group = QButtonGroup(self)
        self.nav_buttons = {}

        for text, idx in nav_buttons:
            btn = QPushButton(text)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.btn_group.addButton(btn, idx)
            self.nav_buttons[idx] = btn
            left_layout.addWidget(btn)

        self.btn_group.buttonClicked.connect(self.switch_page)

        left_layout.addStretch()

        # 设置自动保存，仅保留关闭按钮。
        self.lbl_save_status = QLabel("")
        self.lbl_save_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_close = QPushButton(_("close"))
        self.btn_close.setMinimumHeight(40)
        self.btn_close.clicked.connect(self.close)

        left_layout.addWidget(self.lbl_save_status)
        left_layout.addWidget(self.btn_close)

        main_layout.addWidget(left_widget)

        # 分割线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        main_layout.addWidget(line)

        # ========== 右侧内容区 ==========
        self.stack = QStackedWidget()
        main_layout.addWidget(self.stack, 1)

        # 创建四个页面
        self.init_about_page()
        self.init_music_page()
        self.init_gui_page()
        self.init_other_settings_page()

        # 默认显示关于页面
        self.btn_group.button(0).setChecked(True)
        self.stack.setCurrentIndex(0)

        # 初始渲染
        self.apply_gui_theme()

        self._gui_save_timer = QTimer(self)
        self._gui_save_timer.setSingleShot(True)
        self._gui_save_timer.setInterval(250)
        self._gui_save_timer.timeout.connect(self._save_gui_preferences)
        self._connect_auto_save_signals()
        self._autosave_ready = True


    def switch_page(self, button):
        """切换页面"""
        page_id = self.btn_group.id(button)
        self.stack.setCurrentIndex(page_id)


    def _connect_auto_save_signals(self):
        """在全部控件初始化完成后绑定自动保存，避免构建界面时误写配置。"""
        for spin_box in (
            self.spin_discovered,
            self.spin_mystery_num,
            self.spin_cache_batches,
        ):
            spin_box.valueChanged.connect(lambda _value: self._save_music_preferences())
        self.chk_mystery.toggled.connect(lambda _checked: self._save_music_preferences())
        self.chk_refresh.toggled.connect(lambda _checked: self._save_music_preferences())
        self.edit_mystery_cover.editingFinished.connect(self._save_music_preferences)
        self.edit_shortcut.editingFinished.connect(self._save_shortcut)

        self.slider_card_size.valueChanged.connect(self._schedule_gui_save)
        self.slider_cancel_size.valueChanged.connect(self._schedule_gui_save)
        self.slider_setting_size.valueChanged.connect(self._schedule_gui_save)

        for mode_inputs in self.color_inputs.values():
            for color_input in mode_inputs.values():
                color_input.editingFinished.connect(self._save_gui_preferences)
        for mode_previews in self.color_previews.values():
            for color_preview in mode_previews.values():
                color_preview.color_changed.connect(lambda _color: self._save_gui_preferences())

        self.chk_auto_start.toggled.connect(self._on_auto_start_toggled)


    def _mark_saved(self):
        if hasattr(self, "lbl_save_status"):
            self.lbl_save_status.setText(_("auto_saved"))


    def _schedule_gui_save(self, _value=None):
        if self._autosave_ready:
            self._gui_save_timer.start()


    def init_about_page(self):
        """关于页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(40, 40, 40, 40)

        # 标题
        title = QLabel(_("about_title"))
        title_font = QFont()
        title_font.setPointSize(24)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)

        layout.addSpacing(20)

        # 简介
        intro = QLabel(_("about_intro"))
        intro.setWordWrap(True)
        intro_font = QFont()
        intro_font.setPointSize(12)
        intro.setFont(intro_font)
        layout.addWidget(intro)

        layout.addSpacing(30)

        # 功能列表
        features_title = QLabel(_("features_title"))
        features_title.setFont(QFont("", weight=QFont.Weight.Bold))
        layout.addWidget(features_title)

        features = QLabel(_("features_list"))
        layout.addWidget(features)

        layout.addSpacing(30)

        # 使用说明
        usage_title = QLabel(_("usage_title"))
        usage_title.setFont(QFont("", weight=QFont.Weight.Bold))
        layout.addWidget(usage_title)

        usage = QLabel(_("usage_steps"))
        layout.addWidget(usage)

        layout.addSpacing(30)

        # 版本信息（可点击超链接）
        version_title = QLabel(f'<a href="https://github.com/Narcissu-s1/DiscoAS">{_("version")}: v1.1.1</a>')
        version_title.setFont(QFont("", weight=QFont.Weight.Bold))
        version_title.setOpenExternalLinks(True)
        layout.addWidget(version_title)

        layout.addSpacing(20)

        # 语言选择
        language_title = QLabel(_("language"))
        language_title.setFont(QFont("", weight=QFont.Weight.Bold))
        layout.addWidget(language_title)

        language_row = QHBoxLayout()
        self.combo_language = QComboBox()

        # 获取可用语言
        try:
            from settings.i18n import LANGUAGES, get_language
            for code, name in LANGUAGES.items():
                self.combo_language.addItem(name, code)

            current_lang = get_language()
            index = self.combo_language.findData(current_lang)
            if index >= 0:
                self.combo_language.setCurrentIndex(index)

            self.combo_language.currentIndexChanged.connect(self.on_language_changed)
        except ImportError:
            self.combo_language.addItem("简体中文", "zh_CN")
            self.combo_language.addItem("English", "en_US")

        language_row.addWidget(self.combo_language)
        language_row.addStretch()
        layout.addLayout(language_row)

        layout.addStretch()

        self.stack.addWidget(page)


    def init_music_page(self):
        """发现设置页面"""
        self.music_page = QWidget()
        layout = QVBoxLayout(self.music_page)
        layout.setContentsMargins(20, 20, 20, 20)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content_widget = QWidget()
        scroll.setWidget(content_widget)

        v_layout = QVBoxLayout(content_widget)
        v_layout.setSpacing(15)

        # --- 参数区 ---
        group_basic = QGroupBox(_("basic_params"))
        form_basic = QFormLayout(group_basic)
        form_basic.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)

        self.spin_discovered = QSpinBox()
        self.spin_discovered.setRange(1, 999)
        self.spin_discovered.setValue(self.pa_setting.number_of_discovered_songs)
        self.spin_discovered.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.spin_discovered.setMinimumWidth(120)
        form_basic.addRow(_("discovered_songs_count"), self.spin_discovered)

        self.chk_mystery = QCheckBox(_("mystery_mode"))
        self.chk_mystery.setChecked(self.pa_setting.have_mystery_song)
        form_basic.addRow(self.chk_mystery)

        self.spin_mystery_num = QSpinBox()
        self.spin_mystery_num.setRange(0, 50)
        self.spin_mystery_num.setValue(self.pa_setting.num_of_mystery_song)
        self.spin_mystery_num.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.spin_mystery_num.setMinimumWidth(120)
        form_basic.addRow(_("mystery_songs_count"), self.spin_mystery_num)

        # 缓存批数设置
        self.spin_cache_batches = QSpinBox()
        self.spin_cache_batches.setRange(0, 10)
        self.spin_cache_batches.setValue(self.pa_setting.cache_batches)
        self.spin_cache_batches.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.spin_cache_batches.setMinimumWidth(120)
        form_basic.addRow(_("cache_batches"), self.spin_cache_batches)

        self.chk_refresh = QCheckBox(_("refresh_after_cancel"))
        self.chk_refresh.setChecked(self.pa_setting.refreshing_after_cancel)
        form_basic.addRow(self.chk_refresh)

        # 快捷键设置
        shortcut_container = QWidget()
        shortcut_layout = QHBoxLayout(shortcut_container)
        shortcut_layout.setContentsMargins(0, 0, 0, 0)

        self.edit_shortcut = QLineEdit()
        self.edit_shortcut.setText(self.pa_setting.shortcut_key)
        self.edit_shortcut.setPlaceholderText(_("shortcut_placeholder"))
        self.edit_shortcut.setMinimumWidth(200)
        shortcut_layout.addWidget(self.edit_shortcut)

        # 添加快捷键录制按钮
        self.btn_set_shortcut = QPushButton(_("set_shortcut"))
        self.btn_set_shortcut.setFixedWidth(150)
        self.btn_set_shortcut.clicked.connect(self.start_shortcut_recording)
        shortcut_layout.addWidget(self.btn_set_shortcut)

        form_basic.addRow(_("global_shortcut"), shortcut_container)

        v_layout.addWidget(group_basic)

        # --- 秘密歌曲封面设置 ---
        group_mystery_cover = QGroupBox(_("mystery_cover"))
        form_cover = QFormLayout(group_mystery_cover)

        hint_label = QLabel(_("mystery_cover_hint"))
        hint_label.setWordWrap(True)
        form_cover.addRow(hint_label)

        cover_input_row = QWidget()
        cover_input_layout = QHBoxLayout(cover_input_row)
        cover_input_layout.setContentsMargins(0, 0, 0, 0)

        self.edit_mystery_cover = QLineEdit()
        self.edit_mystery_cover.setText(self.pa_setting.mystery_song_cover)
        self.edit_mystery_cover.setPlaceholderText(_("mystery_cover_placeholder"))
        cover_input_layout.addWidget(self.edit_mystery_cover)

        btn_browse_cover = QPushButton(_("browse"))
        btn_browse_cover.setFixedWidth(120)
        btn_browse_cover.clicked.connect(self._browse_mystery_cover)
        cover_input_layout.addWidget(btn_browse_cover)

        form_cover.addRow(_("cover_source"), cover_input_row)

        v_layout.addWidget(group_mystery_cover)

        # --- 列表区 ---
        group_list = QGroupBox(_("playlist_management"))
        v_list = QVBoxLayout(group_list)

        self.table_pl = QTableWidget()
        self.table_pl.setColumnCount(6)
        self.table_pl.setHorizontalHeaderLabels([
            _("table_platform"), _("table_id"), _("table_type"),
            _("table_name"), _("table_enabled"), _("table_action")
        ])
        self.table_pl.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table_pl.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self.table_pl.setColumnWidth(0, 150)   # 平台
        self.table_pl.setColumnWidth(1, 220)   # 分享链接或 ID
        self.table_pl.setColumnWidth(2, 100)   # 类型
        self.table_pl.setColumnWidth(4, 80)   # 启用
        self.table_pl.setColumnWidth(5, 150) # 操作
        self.table_pl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table_pl.verticalHeader().setDefaultSectionSize(50)
        v_list.addWidget(self.table_pl)

        h_btn = QHBoxLayout()
        btn_add = QPushButton(_("add_playlist"))
        btn_add.clicked.connect(self.add_playlist_row)
        h_btn.addWidget(btn_add)
        h_btn.addStretch()
        v_list.addLayout(h_btn)

        v_layout.addWidget(group_list)

        layout.addWidget(scroll)

        # 加载数据
        self.load_playlist_table()

        self.stack.addWidget(self.music_page)


    def init_gui_page(self):
        """界面设置页面"""
        self.gui_page = QWidget()
        layout = QVBoxLayout(self.gui_page)
        layout.setContentsMargins(20, 20, 20, 20)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content_widget = QWidget()
        scroll.setWidget(content_widget)

        main_layout = QVBoxLayout(content_widget)
        main_layout.setSpacing(15)

        # --- 全局 ---
        group_global = QGroupBox(_("global_settings"))
        form_global = QFormLayout(group_global)

        self.mode_toggle_layout = QHBoxLayout()
        self.btn_day_mode = QPushButton(_("day_mode"))
        self.btn_night_mode = QPushButton(_("night_mode"))

        self.btn_day_mode.setCheckable(True)
        self.btn_night_mode.setCheckable(True)

        self.mode_group = QButtonGroup()
        self.mode_group.addButton(self.btn_day_mode, 0)
        self.mode_group.addButton(self.btn_night_mode, 1)

        if self.gui_setting.night_mode:
            self.btn_night_mode.setChecked(True)
        else:
            self.btn_day_mode.setChecked(True)

        self.btn_day_mode.clicked.connect(self.switch_to_day_mode)
        self.btn_night_mode.clicked.connect(self.switch_to_night_mode)

        self.mode_toggle_layout.addWidget(self.btn_day_mode)
        self.mode_toggle_layout.addWidget(self.btn_night_mode)
        form_global.addRow(_("interface_mode"), self.mode_toggle_layout)

        # 尺寸设置
        self.slider_card_size = FloatSlider(self.gui_setting.card_size)
        form_global.addRow(_("card_size"), self.slider_card_size)

        self.slider_cancel_size = FloatSlider(self.gui_setting.cancel_button_size)
        form_global.addRow(_("cancel_button_size"), self.slider_cancel_size)

        self.slider_setting_size = FloatSlider(self.gui_setting.setting_size)
        self.slider_setting_size.valueChanged.connect(self.live_update_setting_size)
        form_global.addRow(_("setting_size"), self.slider_setting_size)

        main_layout.addWidget(group_global)

        # --- 颜色配置 ---
        self.color_inputs = {}
        self.color_previews = {}

        def create_color_section(layout, mode_name, setting_dict, prefix):
            box = QGroupBox(mode_name)
            box_layout = QFormLayout(box)

            self.color_inputs[prefix] = {}
            self.color_previews[prefix] = {}

            fields = [
                (_("color_card_background"), "card", "background"),
                (_("color_card_hover"), "card", "background_hover"),
                (_("color_card_border"), "card", "border"),
                (_("color_card_font"), "card", "font_color"),

                (_("color_cancel_background"), "cancel_button", "background"),
                (_("color_cancel_hover"), "cancel_button", "background_hover"),
                (_("color_cancel_border"), "cancel_button", "border"),
                (_("color_cancel_font"), "cancel_button", "font_color"),

                (_("color_setting_background"), "setting", "background"),
                (_("color_setting_font"), "setting", "font_color"),
            ]

            for label, main_key, sub_key in fields:
                sub_dict = setting_dict.get(main_key, {})
                current_color = sub_dict.get(sub_key, "#FFFFFF")

                color_input = QLineEdit()
                color_input.setText(current_color)
                color_input.setFixedWidth(100)

                color_preview = ColorPreviewWidget(current_color)

                from functools import partial

                # 连接输入框文本变化到预览更新
                color_input.textChanged.connect(partial(self.update_color_preview, color_preview))

                # 连接预览点击后的颜色变化到输入框更新
                color_preview.color_changed.connect(color_input.setText)

                input_container = QWidget()
                input_layout = QHBoxLayout(input_container)
                input_layout.setContentsMargins(0, 0, 0, 0)
                input_layout.addWidget(color_input)
                input_layout.addWidget(color_preview)
                input_layout.addStretch()

                box_layout.addRow(label, input_container)

                self.color_inputs[prefix][f"{main_key}_{sub_key}"] = color_input
                self.color_previews[prefix][f"{main_key}_{sub_key}"] = color_preview

            layout.addWidget(box)

        day_data = {
            "card": self.gui_setting.card,
            "cancel_button": self.gui_setting.cancel_button,
            "setting": self.gui_setting.setting
        }

        night_data = {
            "card": self.gui_setting.card_night_mode,
            "cancel_button": self.gui_setting.cancel_button_night_mode,
            "setting": self.gui_setting.setting_night_mode
        }

        h_colors = QHBoxLayout()
        w_day = QWidget()
        l_day = QVBoxLayout(w_day)
        l_day.setContentsMargins(0,0,0,0)
        create_color_section(l_day, _("day_color_scheme"), day_data, "day")

        w_night = QWidget()
        l_night = QVBoxLayout(w_night)
        l_night.setContentsMargins(0,0,0,0)
        create_color_section(l_night, _("night_color_scheme"), night_data, "night")

        h_colors.addWidget(w_day)
        h_colors.addWidget(w_night)

        main_layout.addLayout(h_colors)

        layout.addWidget(scroll)

        self.stack.addWidget(self.gui_page)


    def init_other_settings_page(self):
        """其他设置页面"""
        self.other_page = QWidget()
        layout = QVBoxLayout(self.other_page)
        layout.setContentsMargins(20, 20, 20, 20)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content_widget = QWidget()
        scroll.setWidget(content_widget)

        main_layout = QVBoxLayout(content_widget)
        main_layout.setSpacing(15)

        # --- 开机自启动 ---
        self.chk_auto_start = QCheckBox(_("auto_start"))
        # 读取当前开机自启动状态
        self.chk_auto_start.setChecked(self._get_auto_start_status())
        main_layout.addWidget(self.chk_auto_start)

        # --- 查看日志 ---
        btn_view_log = QPushButton(_("view_log"))
        btn_view_log.clicked.connect(self._open_log_folder)
        main_layout.addWidget(btn_view_log)

        main_layout.addStretch()

        layout.addWidget(scroll)

        self.stack.addWidget(self.other_page)


    def _get_auto_start_status(self):
        """获取开机自启动状态"""
        import winreg
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_READ
            )
            try:
                value = winreg.QueryValueEx(key, "DiscoAS")
                print(f"[_get_auto_start_status] current registry value={value[0]}")
                winreg.CloseKey(key)
                return True
            except FileNotFoundError:
                print("[_get_auto_start_status] no registry value found")
                winreg.CloseKey(key)
                return False
        except Exception as e:
            print(f"[_get_auto_start_status] error: {e}")
            return False

    def _open_log_folder(self):
        """打开日志文件夹"""
        import os

        from settings.user_data_path import get_resource_dir
        log_dir = os.path.join(get_resource_dir(), "log")
        if os.path.exists(log_dir):
            os.startfile(log_dir)
        else:
            QMessageBox.warning(self, _("error"), "日志目录不存在")

    def _set_auto_start(self, enable):
        """设置开机自启动"""
        import os
        import sys
        import winreg

        print(f"[_set_auto_start] sys.frozen={getattr(sys, 'frozen', None)}, hasattr(_MEIPASS)={hasattr(sys, '_MEIPASS')}")
        print(f"[_set_auto_start] sys.executable={sys.executable}")

        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_WRITE
            )

            if enable:
                # 始终优先查找 DiscoAS.exe
                exe_dir = os.path.dirname(sys.executable)
                exe_path = os.path.join(exe_dir, "DiscoAS.exe")
                if os.path.exists(exe_path):
                    startup_cmd = f'"{os.path.realpath(exe_path)}"'
                    print(f"[_set_auto_start] EXE: cmd={startup_cmd}")
                else:
                    # 找不到 DiscoAS.exe fallback 到 conda run
                    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    script_path = os.path.join(base_dir, "main.py")
                    conda_path = r"D:\anaconda\Scripts\conda.exe"
                    startup_cmd = f'"{conda_path}" run -n DiscoverASong python "{script_path}"'
                    print(f"[_set_auto_start] CONDA FALLBACK: cmd={startup_cmd}")

                winreg.SetValueEx(key, "DiscoAS", 0, winreg.REG_SZ, startup_cmd)
            else:
                with contextlib.suppress(FileNotFoundError):
                    winreg.DeleteValue(key, "DiscoAS")

            winreg.CloseKey(key)
            return True
        except Exception as e:
            print(f"设置开机自启动失败: {e}")
            return False

    def _on_auto_start_toggled(self, enabled):
        if not self._autosave_ready:
            return
        if self._set_auto_start(enabled):
            self._mark_saved()
            return

        self.chk_auto_start.blockSignals(True)
        self.chk_auto_start.setChecked(not enabled)
        self.chk_auto_start.blockSignals(False)
        QMessageBox.warning(self, _("error"), _("auto_start_failed"))

    def start_shortcut_recording(self):
        """开始快捷键录制"""
        # 禁用按钮
        self.btn_set_shortcut.setEnabled(False)
        self.edit_shortcut.clear()
        self.edit_shortcut.setPlaceholderText(_("shortcut_recording"))
        self.edit_shortcut.setFocus()

        # 安装事件过滤器来捕获按键事件
        self.edit_shortcut.installEventFilter(self)
        self._recording_shortcut = True

    def stop_shortcut_recording(self):
        """停止快捷键录制"""
        self._recording_shortcut = False
        self.edit_shortcut.removeEventFilter(self)
        self.btn_set_shortcut.setEnabled(True)
        self.edit_shortcut.setPlaceholderText(_("shortcut_placeholder"))

    def eventFilter(self, obj, event):
        """事件过滤器，用于捕获快捷键输入"""
        if (
            obj == self.edit_shortcut
            and getattr(self, '_recording_shortcut', False)
            and event.type() == QEvent.Type.KeyPress
        ):
            key = event.key()

            # 按 ESC 取消录制
            if key == Qt.Key.Key_Escape:
                self.stop_shortcut_recording()
                self.edit_shortcut.setText(self.pa_setting.shortcut_key)
                return True

            # 构建快捷键字符串
            modifiers = []
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                modifiers.append("Ctrl")
            if event.modifiers() & Qt.KeyboardModifier.AltModifier:
                modifiers.append("Alt")
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                modifiers.append("Shift")

            # 获取按键名称
            Qt.Key(key)
            key_text = ""

            # 功能键
            if key in (Qt.Key.Key_F1, Qt.Key.Key_F2, Qt.Key.Key_F3, Qt.Key.Key_F4,
                       Qt.Key.Key_F5, Qt.Key.Key_F6, Qt.Key.Key_F7, Qt.Key.Key_F8,
                       Qt.Key.Key_F9, Qt.Key.Key_F10, Qt.Key.Key_F11, Qt.Key.Key_F12):
                key_text = f"F{key - Qt.Key.Key_F1 + 1}"
            # 特殊键
            elif key == Qt.Key.Key_Space:
                key_text = "Space"
            elif key == Qt.Key.Key_Tab:
                key_text = "Tab"
            elif key == Qt.Key.Key_Backspace:
                key_text = "Backspace"
            elif key == Qt.Key.Key_Return:
                key_text = "Return"
            elif key == Qt.Key.Key_Enter:
                key_text = "Enter"
            elif key == Qt.Key.Key_Delete:
                key_text = "Delete"
            elif key == Qt.Key.Key_Insert:
                key_text = "Insert"
            elif key == Qt.Key.Key_Home:
                key_text = "Home"
            elif key == Qt.Key.Key_End:
                key_text = "End"
            elif key == Qt.Key.Key_PageUp:
                key_text = "PageUp"
            elif key == Qt.Key.Key_PageDown:
                key_text = "PageDown"
            elif key == Qt.Key.Key_Up:
                key_text = "Up"
            elif key == Qt.Key.Key_Down:
                key_text = "Down"
            elif key == Qt.Key.Key_Left:
                key_text = "Left"
            elif key == Qt.Key.Key_Right:
                key_text = "Right"
            # 单个字符键
            elif key >= Qt.Key.Key_A and key <= Qt.Key.Key_Z or key >= Qt.Key.Key_0 and key <= Qt.Key.Key_9:
                key_text = chr(key)

            if key_text:
                shortcut_str = "+".join(modifiers + [key_text])
                self.edit_shortcut.setText(shortcut_str)
                self.stop_shortcut_recording()
                self._save_shortcut()
                return True

        return super().eventFilter(obj, event)


    def load_playlist_table(self):
        self.table_pl.setRowCount(0)
        for pl in self.pa_setting.playlist_albums:
            self.add_playlist_row(data=pl)


    def _get_playlist_name_from_json(self, platform, playlist_id, typename):
        """从JSON文件读取歌单名称"""
        try:
            # 导入 Playlist 类
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
            from load_playlist_json import Playlist
            playlist = Playlist(platform, typename, playlist_id)
            return playlist.get_playlist_name()
        except Exception as e:
            print(f"读取歌单名称失败: {e}")
            return ""

    def add_playlist_row(self, data=None):
        row = self.table_pl.rowCount()
        self.table_pl.insertRow(row)

        # 表格中下拉框的样式（使用占位符，稍后由apply_gui_theme更新）
        combo_style_template = """
            QComboBox {
                background-color: #PLACEHOLDER_BG#;
                border: 1px solid #PLACEHOLDER_BORDER#;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QComboBox:hover {
                border: 1px solid #PLACEHOLDER_BORDER#;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 3px solid transparent;
                border-right: 3px solid transparent;
                border-top: 5px solid #666666;
                margin-right: 4px;
            }
        """

        # 保存原始样式模板供后续动态更新
        if not hasattr(self, '_combo_style_template'):
            self._combo_style_template = combo_style_template

        # 如果已经有颜色值就直接替换，否则使用默认值
        if hasattr(self, '_current_card_hover') and hasattr(self, '_current_card_border'):
            combo_style = self._combo_style_template.replace('#PLACEHOLDER_BG#', self._current_card_hover).replace('#PLACEHOLDER_BORDER#', self._current_card_border)
        else:
            # 使用默认日间模式颜色
            combo_style = self._combo_style_template.replace('#PLACEHOLDER_BG#', '#d0ebf0').replace('#PLACEHOLDER_BORDER#', '#76e8fd')

        # 1. Platform
        cmb_platform = QComboBox()
        cmb_platform.setStyleSheet(combo_style)
        platforms = [
            ("NeteaseCloudMusic", _("platform_NeteaseCloudMusic")),
            ("QQMusic", _("platform_QQMusic")),
            ("KugouMusic", _("platform_KugouMusic")),
            ("Spotify", _("platform_Spotify")),
        ]
        for platform_id, platform_name in platforms:
            cmb_platform.addItem(platform_name, platform_id)
        if data:
            # 找到对应的索引
            index = cmb_platform.findData(data.name)
            if index >= 0:
                cmb_platform.setCurrentIndex(index)
        self.table_pl.setCellWidget(row, 0, cmb_platform)

        # 2. 分享链接或 ID
        edit_id = QLineEdit()
        edit_id.setPlaceholderText(_("collection_link_or_id_placeholder"))
        if data:
            edit_id.setText(str(data.playlist_album_id))
        self.table_pl.setCellWidget(row, 1, edit_id)

        # 3. Type
        cmb_type = QComboBox()
        cmb_type.setStyleSheet(combo_style)
        types = [
            ("playlist", _("type_playlist")),
            ("album", _("type_album"))
        ]
        for type_id, type_name in types:
            cmb_type.addItem(type_name, type_id)
        if data:
            index = cmb_type.findData(data.typename)
            if index >= 0:
                cmb_type.setCurrentIndex(index)
        self.table_pl.setCellWidget(row, 2, cmb_type)

        # 4. Name (只读，从JSON读取)
        label_name = QLabel()
        label_name.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        if data:
            # 尝试从JSON文件读取歌单名称
            name = self._get_playlist_name_from_json(data.name, data.playlist_album_id, data.typename)
            if not name:
                name = data.playlist_album_name or "未加载"
            label_name.setText(name)
        self.table_pl.setCellWidget(row, 3, label_name)

        # 5. Enabled
        chk_widget = QWidget()
        chk_layout = QHBoxLayout(chk_widget)
        chk_layout.setContentsMargins(0,0,0,0)
        chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chk_enabled = QCheckBox()
        if data and data.enabled:
            chk_enabled.setChecked(True)
        chk_layout.addWidget(chk_enabled)
        self.table_pl.setCellWidget(row, 4, chk_widget)
        chk_enabled.setObjectName("chk_enabled")

        chk_enabled.toggled.connect(self.handle_enabled_checkbox_toggled)

        # 6. Delete & Load
        btn_load = QPushButton(_("load"))
        btn_load.setStyleSheet("color: white; background-color: #3e8ed6; border: none; border-radius: 3px; padding: 0px;")
        btn_load.setFixedSize(60, 32)
        btn_load.clicked.connect(lambda: self.load_playlist_data(row))

        btn_del = QPushButton(_("delete"))
        btn_del.setStyleSheet("color: white; background-color: #d6533e; border: none; border-radius: 3px; padding: 0px;")
        btn_del.setFixedSize(60, 32)
        btn_del.clicked.connect(self.delete_current_row)

        cell_widget_del = QWidget()
        layout_del = QHBoxLayout(cell_widget_del)
        layout_del.setContentsMargins(2,0,2,0)
        layout_del.setSpacing(4)
        layout_del.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout_del.addWidget(btn_del)
        layout_del.addWidget(btn_load)

        self.table_pl.setCellWidget(row, 5, cell_widget_del)


    def load_playlist_data(self, row):
        """加载歌单/专辑数据"""
        platform = self.table_pl.cellWidget(row, 0).currentData()
        playlist_id = self.table_pl.cellWidget(row, 1).text().strip()
        typename = self.table_pl.cellWidget(row, 2).currentData()

        if not playlist_id:
            QMessageBox.warning(self, _("load_failed"), _("enter_id_first"))
            return

        try:
            # 使用静态导入的 PlaylistAlbumJson 类
            PlaylistAlbumJson = PLATFORM_JSON_MAP.get(platform)

            if not PlaylistAlbumJson:
                raise ValueError(f"不支持的平台: {platform}")

            playlist_album = PlaylistAlbumJson(playlist_id, typename).refresh()
            if not playlist_album.is_stale:
                playlist_album.save()

            normalized_id = playlist_album.get_id()
            if normalized_id != playlist_id:
                self.table_pl.cellWidget(row, 1).setText(normalized_id)

            remark_widget = self.table_pl.cellWidget(row, 3)
            remark_widget.setText(playlist_album.get_name())

            chk_widget = self.table_pl.cellWidget(row, 4)
            checkbox = chk_widget.findChild(QCheckBox, "chk_enabled")
            if not self._save_playlist_table(force_runtime_reload=bool(checkbox and checkbox.isChecked())):
                return
            QMessageBox.information(self, _("load_success"), _("loaded_successfully").format(name=playlist_album.get_name()))
        except Exception as e:
            QMessageBox.critical(self, _("load_failed"), _("load_error").format(error=str(e)))


    def handle_enabled_checkbox_toggled(self, checked):
        sender = self.sender()
        if checked:
            for row in range(self.table_pl.rowCount()):
                chk_widget = self.table_pl.cellWidget(row, 4)
                chk = chk_widget.findChild(QCheckBox, "chk_enabled")
                if chk and chk != sender:
                    chk.setChecked(False)
        else:
            enabled_count = 0
            for row in range(self.table_pl.rowCount()):
                chk_widget = self.table_pl.cellWidget(row, 4)
                chk = chk_widget.findChild(QCheckBox, "chk_enabled")
                if chk and chk.isChecked():
                    enabled_count += 1

            if enabled_count == 0:
                sender.setChecked(True)
                QMessageBox.warning(self, _("must_enable_one"), _("must_enable_one_msg"))

        self._schedule_playlist_save()


    def delete_current_row(self):
        button = self.sender()
        if button:
            for r in range(self.table_pl.rowCount()):
                cell_w = self.table_pl.cellWidget(r, 5)
                if cell_w.isAncestorOf(button):
                    chk_widget = self.table_pl.cellWidget(r, 4)
                    chk = chk_widget.findChild(QCheckBox, "chk_enabled")
                    # 如果要删除的歌单已启用，直接禁止
                    if chk and chk.isChecked():
                        QMessageBox.warning(self, _("cannot_delete_enabled"), _("cannot_delete_enabled_msg"))
                        return

                    # 未启用歌单，询问确认
                    reply = QMessageBox.question(
                        self,
                        _("confirm_delete_title"),
                        _("confirm_delete_msg"),
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No
                    )

                    if reply == QMessageBox.StandardButton.Yes:
                        self.table_pl.removeRow(r)
                        self._save_playlist_table()
                    return


    def _browse_mystery_cover(self):
        """打开文件选择对话框"""
        file_path, file_filter = QFileDialog.getOpenFileName(
            self,
            _("select_cover_image"),
            "",
            _("image_files_filter")
        )
        if file_path:
            self.edit_mystery_cover.setText(file_path)
            self._save_music_preferences()


    def switch_to_day_mode(self):
        self.gui_setting.night_mode = False
        self.apply_gui_theme()
        self._save_gui_preferences()

    def switch_to_night_mode(self):
        self.gui_setting.night_mode = True
        self.apply_gui_theme()
        self._save_gui_preferences()


    def on_language_changed(self, index):
        """语言切换处理"""
        lang_code = self.combo_language.currentData()
        if lang_code:
            try:
                from settings import i18n
                i18n.set_language(lang_code)
                self.gui_setting.language = lang_code
                self.gui_setting.save()
                import Discover_gui

                Discover_gui.refresh_translated_ui()
                if Discover_gui._global_discover_app:
                    Discover_gui.apply_runtime_settings(
                        Discover_gui._global_discover_app,
                        reload_visual=True,
                    )

                Discover_gui.reopen_settings_window(self)
            except Exception as e:
                print(f"语言切换失败: {e}")


    def update_color_preview(self, color_preview, text):
        color_preview.set_color(text)


    def get_input_color(self, mode_prefix, main_key, sub_key):
        return self.color_inputs[mode_prefix][f"{main_key}_{sub_key}"].text()


    def live_update_setting_size(self, value):
        self.gui_setting.setting_size = value
        self.apply_gui_theme()


    def _save_music_preferences(self):
        """保存会影响抽歌结果的普通设置，并刷新当前运行态。"""
        if not self._autosave_ready:
            return

        cover = self.edit_mystery_cover.text().strip()
        if cover and not cover.lower().startswith(("http://", "https://")) and not os.path.isfile(cover):
            QMessageBox.warning(self, _("error"), _("invalid_cover_path"))
            self.edit_mystery_cover.setText(self.pa_setting.mystery_song_cover)
            return

        self.pa_setting.number_of_discovered_songs = self.spin_discovered.value()
        self.pa_setting.have_mystery_song = self.chk_mystery.isChecked()
        self.pa_setting.num_of_mystery_song = self.spin_mystery_num.value()
        self.pa_setting.mystery_song_cover = cover
        self.pa_setting.cache_batches = self.spin_cache_batches.value()
        self.pa_setting.refreshing_after_cancel = self.chk_refresh.isChecked()
        self.pa_setting.save()
        self.notify_settings_changed(music_changed=True)
        self._mark_saved()

    def _save_shortcut(self):
        if not self._autosave_ready:
            return
        shortcut = self.edit_shortcut.text().strip()
        if not shortcut:
            self.edit_shortcut.setText(self.pa_setting.shortcut_key)
            return
        self.pa_setting.shortcut_key = shortcut
        self.pa_setting.save()
        self.notify_settings_changed(shortcut_changed=True)
        self._mark_saved()

    def _save_gui_preferences(self):
        """校验并保存主题、颜色和尺寸设置。"""
        if not self._autosave_ready:
            return

        for mode_inputs in self.color_inputs.values():
            for color_input in mode_inputs.values():
                if not QColor(color_input.text()).isValid():
                    QMessageBox.warning(self, _("error"), _("invalid_color"))
                    return

        self.gui_setting.night_mode = self.btn_night_mode.isChecked()
        self.gui_setting.card_size = self.slider_card_size.value()
        self.gui_setting.cancel_button_size = self.slider_cancel_size.value()
        self.gui_setting.setting_size = self.slider_setting_size.value()

        for main_key in ["card", "cancel_button", "setting"]:
            target_dict = getattr(self.gui_setting, main_key)
            for sub_key in ["background", "background_hover", "border", "font_color"]:
                lookup_key = f"{main_key}_{sub_key}"
                if lookup_key in self.color_inputs["day"]:
                    target_dict[sub_key] = self.get_input_color("day", main_key, sub_key)

        night_keys = {
            "card": "card_night_mode",
            "cancel_button": "cancel_button_night_mode",
            "setting": "setting_night_mode",
        }
        for main_key, attr_name in night_keys.items():
            target_dict = getattr(self.gui_setting, attr_name)
            for sub_key in ["background", "background_hover", "border", "font_color"]:
                lookup_key = f"{main_key}_{sub_key}"
                if lookup_key in self.color_inputs["night"]:
                    target_dict[sub_key] = self.get_input_color("night", main_key, sub_key)

        self.gui_setting.save()
        self.apply_gui_theme()
        self.notify_settings_changed(gui_changed=True)
        self._mark_saved()

    @staticmethod
    def _enabled_playlist_key(playlists):
        for playlist in playlists:
            if playlist.enabled:
                return playlist.name, playlist.typename, playlist.playlist_album_id
        return None

    def _restore_enabled_playlist(self, enabled_key):
        for row in range(self.table_pl.rowCount()):
            platform = self.table_pl.cellWidget(row, 0).currentData()
            playlist_id = self.table_pl.cellWidget(row, 1).text().strip()
            typename = self.table_pl.cellWidget(row, 2).currentData()
            chk_widget = self.table_pl.cellWidget(row, 4)
            checkbox = chk_widget.findChild(QCheckBox, "chk_enabled")
            checkbox.blockSignals(True)
            checkbox.setChecked((platform, typename, playlist_id) == enabled_key)
            checkbox.blockSignals(False)

    def _save_playlist_table(self, *, force_runtime_reload=False):
        """仅提交非空且已加载的歌单行；活动歌单变化后执行进程内热切换。"""
        if not self._autosave_ready:
            return False

        old_enabled_key = self._enabled_playlist_key(self.pa_setting.playlist_albums)
        new_playlists = []
        new_enabled_key = None

        for row in range(self.table_pl.rowCount()):
            platform = self.table_pl.cellWidget(row, 0).currentData()
            playlist_id = self.table_pl.cellWidget(row, 1).text().strip()
            typename = self.table_pl.cellWidget(row, 2).currentData()
            name_label = self.table_pl.cellWidget(row, 3)
            playlist_name = name_label.text() if name_label else ""
            chk_widget = self.table_pl.cellWidget(row, 4)
            checkbox = chk_widget.findChild(QCheckBox, "chk_enabled")
            enabled = checkbox.isChecked() if checkbox else False

            if not playlist_id:
                if enabled:
                    self._restore_enabled_playlist(old_enabled_key)
                    QMessageBox.warning(self, _("load_failed"), _("enter_id_first"))
                    return False
                continue

            if enabled:
                try:
                    from load_playlist_json import Playlist

                    Playlist.clear_cache()
                    Playlist(platform, typename, playlist_id)
                except Exception:
                    self._restore_enabled_playlist(old_enabled_key)
                    QMessageBox.warning(self, _("load_failed"), _("load_before_enable"))
                    return False
                new_enabled_key = (platform, typename, playlist_id)

            playlist_data = {
                "name": platform,
                "playlist_album_id": playlist_id,
                "typename": typename,
                "playlist_album_name": playlist_name,
                "playlist_album_remark": "",
                "update_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "enabled": enabled,
            }
            new_playlists.append(PlaylistAlbum(playlist_data))

        self.pa_setting.playlist_albums = new_playlists
        self.pa_setting.save()
        playlist_changed = old_enabled_key != new_enabled_key
        if playlist_changed or force_runtime_reload:
            self.notify_settings_changed(music_changed=True)
        self._mark_saved()
        return True

    def _schedule_playlist_save(self):
        if not self._autosave_ready or self._playlist_save_scheduled:
            return
        self._playlist_save_scheduled = True

        def commit():
            self._playlist_save_scheduled = False
            self._save_playlist_table()

        QTimer.singleShot(0, commit)

    def notify_settings_changed(self, *, music_changed=False, gui_changed=False, shortcut_changed=False):
        try:
            import Discover_gui

            if gui_changed:
                from settings.gui_setting import reload_global_gui_setting

                reload_global_gui_setting()

            if shortcut_changed and Discover_gui._global_app and Discover_gui._global_discover_app:
                Discover_gui.reregister_shortcut(Discover_gui._global_app, Discover_gui._global_discover_app)
                print("快捷键已重新注册")

            if Discover_gui._global_discover_app and (music_changed or gui_changed):
                Discover_gui.apply_runtime_settings(
                    Discover_gui._global_discover_app,
                    reload_songs=music_changed,
                    reload_visual=gui_changed,
                )
        except Exception as e:
            print(f"刷新浮窗失败: {e}")

    def closeEvent(self, event):
        """关闭前提交仍处于防抖等待中的最后一次界面修改。"""
        if hasattr(self, "_gui_save_timer") and self._gui_save_timer.isActive():
            self._gui_save_timer.stop()
            self._save_gui_preferences()
        super().closeEvent(event)


    def apply_gui_theme(self):
        is_night = self.gui_setting.night_mode or self.btn_night_mode.isChecked()

        if is_night:
            s_conf = self.gui_setting.setting_night_mode
            btn_conf = self.gui_setting.cancel_button_night_mode
            input_conf = self.gui_setting.card_night_mode
        else:
            s_conf = self.gui_setting.setting
            btn_conf = self.gui_setting.cancel_button
            input_conf = self.gui_setting.card

        bg = s_conf.get("background", "#F0F0F0")
        fg = s_conf.get("font_color", "#000000")

        btn_conf.get("background", "#E0E0E0")
        btn_fg = btn_conf.get("font_color", "#000000")
        btn_conf.get("border", "#888888")
        btn_conf.get("background_hover", "#CCCCCC")

        input_bg = input_conf.get("background", "#FFFFFF")
        input_bd = input_conf.get("border", "#AAAAAA")
        input_fg = input_conf.get("font_color", "#000000")

        # 卡片悬停色和边框色（用于表格下拉框）
        card_hover = input_conf.get("background_hover", "#d0ebf0")
        card_border = input_conf.get("border", "#76e8fd")

        # 保存当前颜色值供新增行时使用
        self._current_card_hover = card_hover
        self._current_card_border = card_border

        current_setting_scale = self.gui_setting.setting_size
        base_font_size = 14
        scaled_font_size = int(base_font_size * current_setting_scale)
        scaled_font_size = max(8, scaled_font_size)

        # 左侧导航栏背景
        left_bg = bg
        if is_night:
            left_bg = "#2d2d2d"

        # 滚动条颜色 - 将十六进制颜色转换为RGBA格式
        def hex_to_rgba(hex_color, alpha='80'):
            """将十六进制颜色转换为RGBA格式"""
            if hex_color.startswith('#') and len(hex_color) == 7:
                r = hex_color[1:3]
                g = hex_color[3:5]
                b = hex_color[5:7]
                return f"rgba({int(r,16)}, {int(g,16)}, {int(b,16)}, 0.5)"
            return hex_color

        scroll_handle = hex_to_rgba(card_hover)
        scroll_hover = hex_to_rgba(card_hover)

        style = f"""
            QMainWindow, QWidget {{
                background-color: {bg};
                color: {fg};
                font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
                font-size: {scaled_font_size}px;
            }}
            QGroupBox {{
                margin-top: 10px;
                padding-top: 10px;
                font-weight: bold;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 8px;
                color: {fg};
            }}
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
                background-color: {input_bg};
                color: {input_fg};
                border: 1px solid {input_bd};
                padding: 6px 8px;
                border-radius: 6px;
                min-height: 24px;
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox::down-arrow {{
                width: 10px;
                height: 10px;
            }}
            /* 现代表格样式 */
            QTableWidget, QTableView {{
                background-color: {input_bg};
                alternate-background-color: {bg};
                gridline-color: transparent;
                border: none;
                border-radius: 8px;
                padding: 4px;
            }}
            QTableWidget::item {{
                padding: 6px;
                border: none;
                background-color: transparent;
            }}
            QTableWidget::item:selected {{
                background-color: transparent;
                color: {fg};
            }}
            QTableWidget::item:hover {{
                background-color: transparent;
            }}
            QHeaderView::section:horizontal {{
                background-color: {bg};
                color: {btn_fg};
                padding: 8px 4px;
                border: none;
                border-right: 1px solid {card_border};
                font-weight: bold;
            }}
            QHeaderView::section:horizontal:first {{
                border-left: 1px solid {card_border};
            }}
            /* 现代滚动条样式 */
            QScrollBar:vertical {{
                background: transparent;
                width: 10px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {scroll_handle};
                min-height: 40px;
                border-radius: 5px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {scroll_hover};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar:horizontal {{
                background: transparent;
                height: 10px;
                margin: 0px;
            }}
            QScrollBar::handle:horizontal {{
                background: {scroll_handle};
                min-width: 40px;
                border-radius: 5px;
                margin: 2px;
            }}
            QScrollBar::handle:horizontal:hover {{
                background: {scroll_hover};
            }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
            /* 现代滑块样式 */
            QSlider::groove:horizontal {{
                height: 6px;
                background: {card_hover};
                border-radius: 3px;
                margin: 4px 0;
            }}
            QSlider::handle:horizontal {{
                width: 18px;
                height: 18px;
                margin: -6px 0;
                background: {card_border};
                border-radius: 9px;
            }}
            QSlider::handle:horizontal:hover {{
                background: {card_hover};
            }}
            QPushButton {{
                background-color: {bg};
                color: {btn_fg};
                border: 1px solid {card_border};
                border-radius: 6px;
                padding: 8px 16px;
            }}
            QPushButton:hover {{
                background-color: {card_hover};
            }}
            QPushButton:checked {{
                background-color: {card_border};
                color: white;
            }}
            QCheckBox {{
                color: {fg};
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 2px solid {card_border};
                background: {input_bg};
            }}
            QCheckBox::indicator:checked {{
                background: {card_border};
            }}
            QScrollArea {{
                border: none;
                background: transparent;
            }}
        """
        self.setStyleSheet(style)

        # 设置左侧导航栏特殊样式
        self.centralWidget().layout().itemAt(0).widget().setStyleSheet(f"""
            QWidget {{
                background-color: {left_bg};
            }}
            QPushButton {{
                background-color: transparent;
                border: none;
                text-align: left;
                padding: 12px 15px;
                color: {fg};
                font-size: {scaled_font_size + 1}px;
            }}
            QPushButton:hover {{
                background-color: {card_hover};
            }}
            QPushButton:checked {{
                background-color: {card_border};
                color: white;
                border-radius: 4px;
            }}
        """)

        # 更新表格下拉框样式（使用card的悬停色和边框色）
        if hasattr(self, '_combo_style_template'):
            combo_style = self._combo_style_template.replace('#PLACEHOLDER_BG#', card_hover).replace('#PLACEHOLDER_BORDER#', card_border)
            # 遍历表格中的下拉框并更新样式
            for row in range(self.table_pl.rowCount()):
                cmb_platform = self.table_pl.cellWidget(row, 0)
                if cmb_platform and isinstance(cmb_platform, QComboBox):
                    cmb_platform.setStyleSheet(combo_style)
                cmb_type = self.table_pl.cellWidget(row, 2)
                if cmb_type and isinstance(cmb_type, QComboBox):
                    cmb_type.setStyleSheet(combo_style)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    if hasattr(Qt.ApplicationAttribute, 'AA_EnableHighDpiScaling'):
        app.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt.ApplicationAttribute, 'AA_UseHighDpiPixmaps'):
        app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    window = SettingsWindow()
    window.show()
    sys.exit(app.exec())
