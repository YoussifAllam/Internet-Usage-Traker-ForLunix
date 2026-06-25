#!/usr/bin/env python3
"""NetTracker — launch the internet usage tracker GUI."""

import sys

from PyQt5.QtWidgets import QApplication

from nettracker.app import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("NetTracker")
    window = MainWindow()
    if not getattr(window, "start_hidden", False):
        window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
