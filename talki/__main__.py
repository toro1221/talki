"""Entry point for Talki."""

import sys
import logging

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt

from .config import Config
from .platform_utils import (
    get_platform,
    check_input_group,
    check_accessibility_permissions,
)
from .app import SpeechInjectorApp

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def check_permissions() -> bool:
    """Check platform permissions and warn if not configured."""
    platform = get_platform()

    if platform == "linux" and not check_input_group():
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Talki - Setup Required")
        msg.setText("Your user is not in the 'input' group.")
        msg.setInformativeText(
            "This is required for global hotkeys and text injection on Linux.\n\n"
            "Run the following command, then log out and back in:\n\n"
            "  sudo usermod -aG input $USER\n\n"
            "The application will start, but hotkeys may not work."
        )
        msg.setStandardButtons(
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        msg.setDefaultButton(QMessageBox.StandardButton.Ok)
        result = msg.exec()
        if result == QMessageBox.StandardButton.Cancel:
            return False

    if platform == "macos" and not check_accessibility_permissions():
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Talki - Setup Required")
        msg.setText("Accessibility permissions not granted.")
        msg.setInformativeText(
            "This is required for global hotkeys and text injection on macOS.\n\n"
            "Go to: System Settings > Privacy & Security > Accessibility\n"
            "Add and enable this application.\n\n"
            "The application will start, but hotkeys may not work."
        )
        msg.setStandardButtons(
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
        result = msg.exec()
        if result == QMessageBox.StandardButton.Cancel:
            return False

    return True


def main():
    # High-DPI support
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName("Talki")
    qt_app.setQuitOnLastWindowClosed(False)

    if not check_permissions():
        sys.exit(0)

    config = Config.load()
    logger.info("Config loaded: %s", config)

    app = SpeechInjectorApp(config)
    app.initialize()

    sys.exit(qt_app.exec())


if __name__ == "__main__":
    main()
