import os

class ThemeManager:
    THEMES = {
        'dark': 'resources/styles/dark.qss',
        'light': 'resources/styles/light.qss',
        'cyber_neon': 'resources/styles/cyber_neon.qss',
        'orange_black': 'resources/styles/orange_black.qss'
    }

    def __init__(self, app):
        self.app = app

    def apply_theme(self, theme_name):
        normalized = str(theme_name).strip().lower().replace(" ", "_")
        qss_file = self.THEMES.get(normalized, self.THEMES['dark'])
        if os.path.exists(qss_file):
            with open(qss_file, 'r', encoding='utf-8') as f:
                self.app.setStyleSheet(f.read())