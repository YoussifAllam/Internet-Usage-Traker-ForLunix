"""Color themes and QSS generation for NetTracker.

Each theme defines a small set of anchor colors (background, surface, text,
accent…). The rest of the shades used by the stylesheet are derived from those
anchors, so a palette only needs a handful of values. ``swatches`` is the list
of colors shown on the theme's card in the Settings tab.
"""


def _clamp(v):
    return max(0, min(255, int(round(v))))


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(_clamp(c) for c in rgb)


def _mix(h1, h2, t):
    """Blend h1 toward h2 by fraction t (0..1)."""
    a = _hex_to_rgb(h1)
    b = _hex_to_rgb(h2)
    return _rgb_to_hex(tuple(a[i] + (b[i] - a[i]) * t for i in range(3)))


def _lighten(h, t):
    return _mix(h, "#ffffff", t)


def _darken(h, t):
    return _mix(h, "#000000", t)


# Anchor colors per theme. Derived shades are computed in build_qss().
THEMES = [
    {
        "id": "midnight",
        "name": "Midnight",
        "swatches": ["#0d1117", "#161b22", "#1f6feb", "#e6edf3"],
        "bg": "#0d1117",
        "surface": "#161b22",
        "border": "#222b36",
        "text": "#e6edf3",
        "muted": "#9aa4b2",
        "accent": "#1f6feb",
        "accent_text": "#ffffff",
    },
    {
        "id": "sage",
        "name": "Sage",
        "swatches": ["#9CB080", "#618764", "#2B5748", "#273338"],
        "bg": "#273338",
        "surface": "#2B5748",
        "text": "#e8efe1",
        "muted": "#9CB080",
        "accent": "#618764",
        "accent_text": "#ffffff",
    },
    {
        "id": "ocean",
        "name": "Ocean",
        "swatches": ["#1B3C53", "#234C6A", "#456882", "#D2C1B6"],
        "bg": "#1B3C53",
        "surface": "#234C6A",
        "text": "#D2C1B6",
        "muted": "#9bb0c2",
        "accent": "#456882",
        "accent_text": "#ffffff",
    },
    {
        "id": "charcoal",
        "name": "Charcoal",
        "swatches": ["#121212", "#E0E0E0", "#888888", "#444444"],
        "bg": "#121212",
        "surface": "#1e1e1e",
        "border": "#444444",
        "text": "#E0E0E0",
        "muted": "#B0B0B0",
        "accent": "#888888",
        "accent_text": "#121212",
    },
    {
        "id": "ember",
        "name": "Ember",
        "swatches": ["#1C1C1C", "#F5E8D8", "#FF6F61", "#DAA520"],
        "bg": "#1C1C1C",
        "surface": "#262626",
        "text": "#F5E8D8",
        "muted": "#c9b8a6",
        "accent": "#FF6F61",
        "accent_text": "#1C1C1C",
    },
    {
        "id": "ruby",
        "name": "Ruby",
        "swatches": ["#1A1A1A", "#F0F0F0", "#822659", "#3E5641"],
        "bg": "#1A1A1A",
        "surface": "#242424",
        "text": "#F0F0F0",
        "muted": "#a8a8a8",
        "accent": "#822659",
        "accent_text": "#F0F0F0",
    },
]

DEFAULT_THEME = "midnight"

_BY_ID = {t["id"]: t for t in THEMES}


def get_theme(theme_id):
    return _BY_ID.get(theme_id) or _BY_ID[DEFAULT_THEME]


def chart_colors(theme_id):
    """(background, axis-text) colors for the hand-drawn QPainter charts."""
    t = get_theme(theme_id)
    bg = t["bg"]
    return _darken(t["surface"], 0.18), t["muted"], bg


def build_qss(theme_id):
    """Build the full application stylesheet for the given theme."""
    t = get_theme(theme_id)
    bg = t["bg"]
    surface = t["surface"]
    text = t["text"]
    muted = t["muted"]
    accent = t["accent"]
    accent_text = t.get("accent_text", "#ffffff")
    border = t.get("border", _lighten(surface, 0.10))

    hover = _lighten(surface, 0.06)
    button = _lighten(surface, 0.05)
    button_hover = _lighten(surface, 0.12)
    table_bg = _darken(surface, 0.18)
    accent_hover = _lighten(accent, 0.14)
    disabled = _mix(muted, bg, 0.5)

    return f"""
QMainWindow, QWidget {{ background: {bg}; color: {text}; }}
QTabWidget::pane {{ border: 1px solid {border}; border-radius: 8px; top: -1px; }}
QTabBar::tab {{
    background: {surface}; color: {muted}; padding: 8px 18px;
    border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px;
}}
QTabBar::tab:selected {{ background: {accent}; color: {accent_text}; }}
QTabBar::tab:hover:!selected {{ background: {hover}; }}
QComboBox {{
    background: {surface}; border: 1px solid {border}; border-radius: 6px;
    padding: 5px 10px; min-width: 130px;
}}
QComboBox::drop-down {{ border: none; }}
QComboBox QAbstractItemView {{
    background: {surface}; selection-background-color: {accent};
    selection-color: {accent_text}; border: 1px solid {border};
}}
QPushButton {{
    background: {button}; border: 1px solid {border}; border-radius: 6px;
    padding: 7px 16px; color: {text};
}}
QPushButton:hover {{ background: {button_hover}; }}
QPushButton:disabled {{ color: {disabled}; background: {surface}; }}
QPushButton#accent {{ background: {accent}; color: {accent_text}; border: none; }}
QPushButton#accent:hover {{ background: {accent_hover}; }}
QLabel#h1 {{ font-size: 22px; font-weight: 600; }}
QLabel#muted {{ color: {muted}; }}
QFrame#card {{ background: {surface}; border: 1px solid {border}; border-radius: 10px; }}
QFrame#themecard {{
    background: {surface}; border: 2px solid {border}; border-radius: 10px;
}}
QFrame#themecard:hover {{ border-color: {muted}; }}
QFrame#themecard[selected="true"] {{ border: 2px solid {accent}; }}
QTableWidget {{
    background: {table_bg}; gridline-color: {border}; border: 1px solid {border};
    border-radius: 8px;
}}
QHeaderView::section {{
    background: {surface}; color: {muted}; padding: 6px; border: none;
    border-bottom: 1px solid {border};
}}
QTableWidget::item:selected {{ background: {accent}; color: {accent_text}; }}
QMenuBar {{ background: {bg}; color: {text}; }}
QMenuBar::item:selected {{ background: {hover}; }}
QMenu {{ background: {surface}; color: {text}; border: 1px solid {border}; }}
QMenu::item:selected {{ background: {accent}; color: {accent_text}; }}
QDialog {{ background: {bg}; }}
QScrollArea {{ border: none; }}
QSpinBox, QDoubleSpinBox {{
    background: {surface}; border: 1px solid {border}; border-radius: 6px;
    padding: 4px 8px; color: {text};
}}
QCheckBox {{ color: {text}; }}
"""
