# -*- coding: utf-8 -*-
"""
集中式 i18n 助手：
- tr(): 优先命中 QTranslator(.qm)；未命中且当前语言为中文时，回退内置中文词典
- load_translator() / unload_translator(): QTranslator 生命周期（在插件主类中调用）

源文本为英文；简体中文由 i18n/QuickFieldBrush_zh_CN.qm 或内置词典提供（双保险）。
"""

import os
from PyQt5.QtCore import QCoreApplication, QLocale, QTranslator
from qgis.core import QgsSettings

from .i18n_strings import _zh_translations

CONTEXT = "QuickFieldBrush"


def tr(text, disambiguation=None):
    """翻译一个静态英文源文本。严禁传入 f-string（动态内容请用 {0} 占位 + .format()）"""
    res = QCoreApplication.translate(CONTEXT, text, disambiguation)
    if res == text:
        locale_name = QgsSettings().value("locale/userLocale", QLocale.system().name())
        if locale_name and str(locale_name).lower().startswith("zh"):
            return _zh_translations.get(text, text)
    return res


def load_translator(plugin_dir):
    """按 QGIS 覆盖语言或系统语言加载 i18n/QuickFieldBrush_<locale>.qm；返回 translator 或 None"""
    override_flag = QgsSettings().value("locale/overrideFlag", False, type=bool)
    if override_flag:
        locale_name = QgsSettings().value("locale/userLocale", "")
    else:
        locale_name = QLocale.system().name()

    if not locale_name:
        locale_name = "en"

    # 标准化 locale（如 zh-hans -> zh_CN）
    locale_clean = str(locale_name).replace("-", "_").lower()
    if locale_clean in ("zh_cn", "zh_hans", "zh"):
        locale_clean = "zh_CN"
    elif locale_clean in ("zh_tw", "zh_hk", "zh_hant"):
        locale_clean = "zh_TW"

    qm_path = os.path.join(plugin_dir, "i18n", "QuickFieldBrush_{}.qm".format(locale_clean))
    if not os.path.exists(qm_path):
        # 回退到短代号（如 ja_JP -> ja）
        short_code = locale_clean.split("_")[0]
        qm_path = os.path.join(plugin_dir, "i18n", "QuickFieldBrush_{}.qm".format(short_code))

    if os.path.exists(qm_path):
        translator = QTranslator()
        if translator.load(qm_path):
            QCoreApplication.installTranslator(translator)
            return translator
    return None


def unload_translator(translator):
    """卸载翻译器，避免影响其他插件"""
    if translator is not None:
        QCoreApplication.removeTranslator(translator)
    return None
