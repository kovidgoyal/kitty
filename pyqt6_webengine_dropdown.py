#!/usr/bin/env python3
"""
A simple PyQt6 script that displays an HTML page with a select dropdown
using QWebEngine.
"""

import sys

from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QMainWindow

HTML_CONTENT = """
<!DOCTYPE html>
<html>
<head>
    <title>Select Dropdown Demo</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            padding: 20px;
            background-color: #f5f5f5;
        }
        h1 {
            color: #333;
        }
        label {
            display: block;
            margin-bottom: 10px;
            font-weight: bold;
        }
        select {
            padding: 10px;
            font-size: 16px;
            border: 1px solid #ccc;
            border-radius: 4px;
            background-color: white;
            min-width: 200px;
        }
        select:focus {
            outline: none;
            border-color: #007bff;
        }
    </style>
</head>
<body>
    <h1>PyQt6 WebEngine Demo</h1>
    <label for="fruit-select">Choose a fruit:</label>
    <select id="fruit-select" name="fruits">
        <option value="">-- Select an option --</option>
        <option value="apple">Apple</option>
        <option value="banana">Banana</option>
        <option value="cherry">Cherry</option>
        <option value="date">Date</option>
        <option value="elderberry">Elderberry</option>
    </select>
</body>
</html>
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyQt6 QWebEngine Dropdown Example")
        self.setGeometry(100, 100, 600, 400)

        # Create web view and set HTML content
        self.web_view = QWebEngineView()
        self.web_view.setHtml(HTML_CONTENT, QUrl("about:blank"))

        self.setCentralWidget(self.web_view)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
