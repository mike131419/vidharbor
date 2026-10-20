"""Entry point. Order matters: tool paths and the engine import hook must be
set up before anything imports yt_dlp."""
from __future__ import annotations

import os
import sys


def create_app():
    from vidharbor import engine
    engine.add_bins_to_path()
    engine.install_engine_finder()

    # WebEngine must be imported before the QApplication is created.
    from PySide6.QtWebEngineCore import QWebEngineProfile  # noqa: F401
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
    from PySide6.QtWidgets import QApplication

    if sys.platform == 'win32':
        try:  # own taskbar icon/group instead of python.exe
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('VidHarbor.Downloader')
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName('VidHarbor')
    app.setOrganizationName('VidHarbor')
    app.setStyle('Fusion')
    from pathlib import Path
    from PySide6.QtGui import QIcon
    icon = Path(getattr(sys, '_MEIPASS', engine.app_dir())) / 'assets' / 'icon.png'
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    if sys.platform == 'win32':
        app.setFont(QFont('Microsoft YaHei UI', 9))  # renders Chinese titles cleanly

    dark = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    accent = QColor('#e0533d')
    pal = QPalette()
    if dark:
        base, alt, window, text = '#1e1f22', '#25262a', '#17181a', '#e8e8ea'
    else:
        base, alt, window, text = '#ffffff', '#f6f6f7', '#efeff1', '#1d1d1f'
    pal.setColor(QPalette.ColorRole.Window, QColor(window))
    pal.setColor(QPalette.ColorRole.Base, QColor(base))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(alt))
    pal.setColor(QPalette.ColorRole.Button, QColor(base))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        pal.setColor(role, QColor(text))
    pal.setColor(QPalette.ColorRole.Highlight, accent)
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor('#ffffff'))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor('#8a8a90'))
    app.setPalette(pal)
    border = '#3a3b40' if dark else '#d6d6db'
    app.setStyleSheet(f"""
        QPushButton {{ padding: 6px 14px; border: 1px solid {border}; border-radius: 6px; }}
        QPushButton:hover {{ border-color: {accent.name()}; }}
        QPushButton#primary {{ background: {accent.name()}; color: white; border: none; font-weight: 600; }}
        QPushButton#primary:hover {{ background: {accent.darker(112).name()}; }}
        QPushButton:disabled {{ color: #8a8a90; }}
        QLineEdit, QPlainTextEdit, QComboBox, QSpinBox {{ border: 1px solid {border}; border-radius: 6px; padding: 4px 6px; }}
        QLineEdit:focus, QPlainTextEdit:focus {{ border-color: {accent.name()}; }}
        QTreeWidget {{ border: 1px solid {border}; border-radius: 6px; }}
        QProgressBar {{ border: none; border-radius: 4px; background: {border}; }}
        QProgressBar::chunk {{ border-radius: 4px; background: {accent.name()}; }}
    """)
    return app


def selftest() -> int:
    """`VidHarbor.exe --selftest`: report engine/tools status, also to a file
    (a windowed .exe has no console)."""
    from vidharbor import engine
    engine.add_bins_to_path()
    src = engine.install_engine_finder()
    import yt_dlp
    from yt_dlp.extractor import gen_extractor_classes
    lines = [
        f'yt-dlp {yt_dlp.version.__version__} ({src}) from {yt_dlp.__file__}',
        f'extractors: {len(list(gen_extractor_classes()))}',
        f'ffmpeg: {engine.exe("ffmpeg")}', f'deno: {engine.exe("deno")}',
    ]
    try:
        import yt_dlp_ejs
        lines.append(f'yt-dlp-ejs: {yt_dlp_ejs.__file__}')
    except ImportError as e:
        lines.append(f'yt-dlp-ejs: MISSING ({e})')
    try:
        import curl_cffi
        lines.append(f'curl_cffi: {curl_cffi.__version__}')
    except ImportError:
        lines.append('curl_cffi: missing (optional)')
    text = '\n'.join(lines)
    print(text)
    (engine.data_dir() / 'selftest.txt').write_text(text + '\n', 'utf-8')
    return 0


def main() -> int:
    if '--selftest' in sys.argv:
        return selftest()
    app = create_app()
    from vidharbor.ui import MainWindow
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
