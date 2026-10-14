"""Edge Notes: a binder-divider tab on the screen edge that slides out a notes panel.

Run with: ./run.sh   (after ./setup.sh), or any Python 3.9+ with PyQt6: python3 edge_notes.py
"""

import json
import os
import signal
import sys
from pathlib import Path

from PyQt6.QtCore import QEasingCurve, QLoggingCategory, QPoint, QPropertyAnimation, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup, QColor, QFont, QKeySequence, QPainter, QPainterPath, QPen, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QColorDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

# ---- Look and feel (change these freely) ----
TAB_COLOR = "#FFCC00"          # default tab color; pick another any time from the tab's right-click menu
PAPER_COLOR = "#FBF7EE"
IDEAS_BG_COLOR = "#F6F0E2"
INK_COLOR = "#3A3229"
DONE_COLOR = "#A39A8E"
TAB_W, TAB_H = 22, 72
PANEL_W, PANEL_H = 380, 600
ANIM_MS = 280
EASE_OUT = (0.22, 1.0, 0.36, 1.0)   # cubic-bezier for opening (fast start, soft landing)
EASE_IN = (0.55, 0.0, 0.75, 0.3)    # cubic-bezier for closing
SAVE_DEBOUNCE_MS = 400
DRAG_THRESHOLD = 4

# See-through levels: how opaque the paper and tab are. Text always stays fully solid.
SEE_THROUGH = {"off": 1.0, "light": 0.85, "medium": 0.7, "strong": 0.55}
DEFAULT_SEE_THROUGH = "medium"

# Panel style: "glass" uses macOS Liquid Glass behind the panel, "paper" is the flat sheet.
STYLES = {"glass": "Liquid glass", "paper": "Paper"}
DEFAULT_STYLE = "glass"
GLASS_TINT_LIGHT = (0.99, 0.97, 0.93, 0.35)   # warm paper-white tint (r, g, b, alpha) for light mode
GLASS_TINT_DARK = (0.10, 0.09, 0.08, 0.25)    # smoky tint for dark mode
GLASS_DARK_INK = "#F1ECE4"                    # text on dark glass
GLASS_DARK_DONE = "#8E887E"
GLASS_RADIUS = 16
GLASS_EDGE_OVERHANG = 20                 # glass runs past the screen edge so only the inner corners look rounded
GLASS_MERGE = 20                         # distance at which the tab and panel glass melt together
TAB_RADIUS = 8
TAB_GLASS_TUCK = 14                      # tab glass tucks this far under the panel so the two fuse
TAB_GLASS_ALPHA = 0.82                   # tab color painted over the glass tab
GLASS_STYLE_REGULAR = 0                  # NSGlassEffectViewStyleRegular; older pyobjc lacks the named constant

DATA_PATH = Path.home() / ".edge_notes" / "notes.json"
DEFAULT_DATA = {
    "todos": [], "ideas": "", "tab_offset": 0,
    "edge": "right", "tab_color": TAB_COLOR, "see_through": DEFAULT_SEE_THROUGH,
    "style": DEFAULT_STYLE,
}

# Optional macOS integration: hide the Dock icon, show on every Space, native animation.
try:
    import objc
    import AppKit
except ImportError:
    objc = AppKit = None


# ---------------------------------------------------------------- persistence

def load_data():
    """Load notes.json. Anything missing or malformed falls back to defaults."""
    data = dict(DEFAULT_DATA)
    try:
        raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return data
    if not isinstance(raw, dict):
        return data
    todos = raw.get("todos")
    if isinstance(todos, list):
        data["todos"] = [
            {"text": str(t.get("text", "")), "done": bool(t.get("done", False))}
            for t in todos if isinstance(t, dict) and str(t.get("text", "")).strip()
        ]
    if isinstance(raw.get("ideas"), str):
        data["ideas"] = raw["ideas"]
    if isinstance(raw.get("tab_offset"), (int, float)):
        data["tab_offset"] = int(raw["tab_offset"])
    if raw.get("edge") in ("left", "right"):
        data["edge"] = raw["edge"]
    if isinstance(raw.get("tab_color"), str) and QColor.isValidColorName(raw["tab_color"]):
        data["tab_color"] = raw["tab_color"]
    if raw.get("see_through") in SEE_THROUGH:
        data["see_through"] = raw["see_through"]
    if raw.get("style") in STYLES:
        data["style"] = raw["style"]
    return data


def save_data(data):
    """Write atomically: temp file in the same folder, then rename over the original."""
    try:
        DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = DATA_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, DATA_PATH)
    except OSError as e:
        print(f"Edge Notes: could not save notes: {e}", file=sys.stderr)


# ---------------------------------------------------------------- color helpers

def is_light(color):
    """True for colors where dark text reads better than light text (perceived luminance)."""
    return 0.2126 * color.redF() + 0.7152 * color.greenF() + 0.0722 * color.blueF() > 0.55


def readable_on(color):
    """A dark or light shade of the same hue that reads well on top of `color`."""
    hue = max(color.hueF(), 0.0)
    if is_light(color):
        return QColor.fromHslF(hue, min(color.saturationF(), 0.8), 0.18)
    return QColor.fromHslF(hue, min(color.saturationF(), 0.3), 0.96)


def accent_on_paper(color):
    """The tab color, darkened if needed so headings stay readable on light paper."""
    if is_light(color):
        return QColor.fromHslF(max(color.hueF(), 0.0), color.saturationF(), 0.32)
    return color


def rgba(color, alpha):
    return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha:.2f})"


# ---------------------------------------------------------------- the tab

class Tab(QWidget):
    """The binder divider. Click toggles, drag moves it anywhere, right click shows the menu."""

    clicked = pyqtSignal()
    dragged = pyqtSignal(QPoint)       # global top-left the window should move to
    drag_finished = pyqtSignal()
    menu_requested = pyqtSignal(QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(TAB_W, TAB_H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Edge Notes")
        self.count = 0
        self.color = QColor(TAB_COLOR)
        self.opacity = 1.0
        self.edge = "right"
        self.glass = False
        self._press_global = None
        self._press_window_pos = QPoint()
        self._dragging = False

    def set_count(self, n):
        if n != self.count:
            self.count = n
            self.update()

    def set_look(self, color=None, opacity=None, edge=None, glass=None):
        if glass is not None:
            self.glass = glass
        if color is not None:
            self.color = QColor(color)
        if opacity is not None:
            self.opacity = opacity
        if edge is not None:
            self.edge = edge
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h, r = float(self.width()), float(self.height()), float(TAB_RADIUS)

        # Rounded on the side facing the screen, square where it meets the edge/panel.
        p.save()
        if self.edge == "left":
            p.translate(w, 0)
            p.scale(-1, 1)
        path = QPainterPath()
        path.moveTo(w, 0)
        path.lineTo(r, 0)
        path.quadTo(0, 0, 0, r)
        path.lineTo(0, h - r)
        path.quadTo(0, h, r, h)
        path.lineTo(w, h)
        path.closeSubpath()

        fill = QColor(self.color)
        fill.setAlphaF(TAB_GLASS_ALPHA if self.glass else self.opacity)
        p.fillPath(path, fill)
        if not self.glass:
            # Outline only the outer three sides: no line where the tab meets the edge or panel.
            outer = QPainterPath()
            outer.moveTo(w, 0.5)
            outer.lineTo(r, 0.5)
            outer.quadTo(0.5, 0.5, 0.5, r)
            outer.lineTo(0.5, h - r)
            outer.quadTo(0.5, h - 0.5, r, h - 0.5)
            outer.lineTo(w, h - 0.5)
            outline = self.color.darker(118)
            outline.setAlphaF(min(1.0, self.opacity + 0.2))
            p.setPen(QPen(outline, 1))
            p.drawPath(outer)
        p.restore()

        # Just the number of unfinished to dos; nothing when all is done.
        if self.count:
            font = QFont(self.font())
            font.setPointSizeF(10)
            font.setBold(True)
            p.setFont(font)
            p.setPen(readable_on(self.color))
            p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, str(self.count))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press_global = e.globalPosition().toPoint()
            self._press_window_pos = self.window().pos()
            self._dragging = False

    def mouseMoveEvent(self, e):
        if self._press_global is None:
            return
        delta = e.globalPosition().toPoint() - self._press_global
        if not self._dragging and delta.manhattanLength() > DRAG_THRESHOLD:
            self._dragging = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        if self._dragging:
            self.dragged.emit(self._press_window_pos + delta)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or self._press_global is None:
            return
        if self._dragging:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.drag_finished.emit()
        else:
            self.clicked.emit()
        self._press_global = None
        self._dragging = False

    def contextMenuEvent(self, e):
        self.menu_requested.emit(e.globalPos())


# ---------------------------------------------------------------- the panel

class Panel(QFrame):
    """The paper sheet: to dos on top, free-form ideas below."""

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.setFixedSize(PANEL_W, PANEL_H)
        self.ink, self.done_ink = INK_COLOR, DONE_COLOR

        self.todo_input = QLineEdit(placeholderText="Add a to do and press Enter")
        self.todo_input.returnPressed.connect(self._add_from_input)

        self.todo_list = QListWidget()
        self.todo_list.setEditTriggers(QListWidget.EditTrigger.DoubleClicked)
        self.todo_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.todo_list.customContextMenuRequested.connect(self._list_menu)
        self.todo_list.itemChanged.connect(self._item_changed)
        for key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            sc = QShortcut(QKeySequence(key), self.todo_list)
            sc.setContext(Qt.ShortcutContext.WidgetShortcut)
            sc.activated.connect(self._delete_selected)

        clear_btn = QPushButton("clear done")
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.clicked.connect(self._clear_done)

        self.ideas = QPlainTextEdit(placeholderText="Ideas, scraps, anything…")
        self.ideas.textChanged.connect(self.changed)

        todo_header = QHBoxLayout()
        todo_header.addWidget(QLabel("TO DO"))
        todo_header.addStretch()
        todo_header.addWidget(clear_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 16, 16)
        layout.setSpacing(8)
        layout.addLayout(todo_header)
        layout.addWidget(self.todo_input)
        layout.addWidget(self.todo_list, 3)
        layout.addSpacing(6)
        layout.addWidget(QLabel("IDEAS"))
        layout.addWidget(self.ideas, 2)

        self.apply_look(QColor(TAB_COLOR), SEE_THROUGH[DEFAULT_SEE_THROUGH], "right", glass=False)

    def apply_look(self, accent, opacity, edge, glass=False, dark=False):
        """Restyle for the tab color, see-through level, style, and which screen edge we're on.

        With glass on, the native glass layer behind the window provides the background, so
        the paper is nearly clear (alpha just above zero so clicks still land on the panel).
        """
        side = "left" if edge == "right" else "right"
        corner = f"bottom-{side}"
        dark = glass and dark
        heading = (accent if dark and is_light(accent) else
                   accent.lighter(170) if dark else accent_on_paper(accent)).name()
        self.ink = GLASS_DARK_INK if dark else INK_COLOR
        self.done_ink = GLASS_DARK_DONE if dark else DONE_COLOR
        ink, muted = self.ink, ("#A8A196" if dark else "#8C806F")
        if glass:
            # The glass behind provides the sheet and its edge; the tab already carries the color.
            paper = "rgba(255, 255, 255, 0.02)"
            ideas_bg = "rgba(255, 255, 255, 0.08)" if dark else "rgba(255, 255, 255, 0.30)"
            panel_edge = f"border-{corner}-radius: {GLASS_RADIUS}px;"
            field = rgba(QColor("#FFFFFF"), 0.12 if dark else 0.55)
            todo_input = f"""
            QLineEdit {{
                background: {field}; border: 1px solid {rgba(QColor(ink), 0.22)};
                border-radius: 8px; padding: 7px 10px;
            }}
            QLineEdit:focus {{ border: 1px solid {accent.name()}; }}"""
        else:
            paper = rgba(QColor(PAPER_COLOR), opacity)
            ideas_bg = rgba(QColor(IDEAS_BG_COLOR), opacity)
            panel_edge = f"border-{side}: 3px solid {accent.name()}; border-{corner}-radius: 12px;"
            todo_input = f"""
            QLineEdit {{ border-bottom: 1px solid {rgba(QColor(ink), 0.18)}; padding: 6px 2px; }}
            QLineEdit:focus {{ border-bottom: 1px solid {accent.name()}; }}"""
        placeholder = rgba(QColor(ink), 0.6 if glass else 0.45)
        self.setStyleSheet(f"""
            #panel {{
                background: {paper};
                {panel_edge}
            }}
            QLabel {{ color: {heading}; font-size: 11px; font-weight: 700; letter-spacing: 1px; }}
            QLineEdit, QPlainTextEdit, QListWidget {{
                background: transparent; color: {ink}; font-size: 13px; border: none;
                selection-background-color: {rgba(accent, 0.45)}; selection-color: {ink};
            }}
            {todo_input}
            QListWidget::item {{ padding: 3px 0; }}
            QLineEdit, QPlainTextEdit {{ placeholder-text-color: {placeholder}; }}
            QListWidget::item:selected {{ background: {rgba(accent, 0.30)}; color: {ink}; }}
            QPlainTextEdit {{
                background: {ideas_bg}; border-radius: 6px; padding: 6px;
            }}
            QPushButton {{
                background: transparent; color: {muted}; border: none; font-size: 11px; padding: 2px 4px;
            }}
            QPushButton:hover {{ color: {heading}; }}
        """)
        self.todo_list.blockSignals(True)
        for i in range(self.todo_list.count()):
            self._style_item(self.todo_list.item(i))
        self.todo_list.blockSignals(False)

    # -- to do helpers

    def add_todo(self, text, done=False):
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                      | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsUserCheckable)
        self.todo_list.blockSignals(True)
        item.setCheckState(Qt.CheckState.Checked if done else Qt.CheckState.Unchecked)
        self.todo_list.addItem(item)
        self._style_item(item)
        self.todo_list.blockSignals(False)

    def _style_item(self, item):
        done = item.checkState() == Qt.CheckState.Checked
        font = item.font()
        font.setStrikeOut(done)
        item.setFont(font)
        item.setForeground(QColor(self.done_ink if done else self.ink))

    def _add_from_input(self):
        text = self.todo_input.text().strip()
        if text:
            self.add_todo(text)
            self.todo_input.clear()
            self.changed.emit()

    def _item_changed(self, item):
        if not item.text().strip():         # edited down to nothing: drop it
            self.todo_list.takeItem(self.todo_list.row(item))
        else:
            self.todo_list.blockSignals(True)
            self._style_item(item)
            self.todo_list.blockSignals(False)
        self.changed.emit()

    def _delete_selected(self):
        for item in self.todo_list.selectedItems():
            self.todo_list.takeItem(self.todo_list.row(item))
        self.changed.emit()

    def _list_menu(self, pos):
        item = self.todo_list.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        delete = QAction("Delete", menu)
        menu.addAction(delete)
        if menu.exec(self.todo_list.viewport().mapToGlobal(pos)) == delete:
            self.todo_list.takeItem(self.todo_list.row(item))
            self.changed.emit()

    def _clear_done(self):
        for i in reversed(range(self.todo_list.count())):
            if self.todo_list.item(i).checkState() == Qt.CheckState.Checked:
                self.todo_list.takeItem(i)
        self.changed.emit()

    # -- data in / out

    def todos(self):
        items = (self.todo_list.item(i) for i in range(self.todo_list.count()))
        return [{"text": it.text(), "done": it.checkState() == Qt.CheckState.Checked} for it in items]

    def open_count(self):
        return sum(1 for t in self.todos() if not t["done"])

    def load(self, data):
        self.todo_list.clear()
        for t in data["todos"]:
            self.add_todo(t["text"], t["done"])
        self.ideas.blockSignals(True)
        self.ideas.setPlainText(data["ideas"])
        self.ideas.blockSignals(False)


# ---------------------------------------------------------------- main window

class EdgeWindow(QWidget):
    """One frameless window holding the tab and the panel.

    Collapsed, the window is just the tab, flush to its screen edge (left or right).
    Expanding grows the window with the panel hanging off-screen, then slides the whole
    thing inward. Only the position animates, so the tab travels with the panel like a
    real divider.
    """

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
        self.setWindowTitle("Edge Notes")

        self.tab = Tab(self)
        self.panel = Panel(self)
        self.panel.hide()

        self.expanded = False
        self._activated_since_expand = False
        data = load_data()
        self.edge = data["edge"]
        self.tab_color = QColor(data["tab_color"])
        self.see_through = data["see_through"]
        self.style = data["style"]
        self.glass_win = None             # native window holding the Liquid Glass views (macOS only)
        self._glass_tab = None            # glass shape under the tab (fuses with the panel's)
        self._glass_panel = None
        self.tab_offset = data["tab_offset"]
        self.panel.load(data)
        self.tab.set_count(self.panel.open_count())
        self._apply_look()

        self.nswin = None                 # set by apply_mac_window_behavior when pyobjc is present
        self._animating = False
        self._anim_generation = 0         # ignores completions from superseded animations
        self.anim = QPropertyAnimation(self, b"pos", self)   # fallback when pyobjc is missing
        self.anim.setDuration(ANIM_MS)
        self.anim.finished.connect(self._anim_done)

        self.save_timer = QTimer(self, singleShot=True, interval=SAVE_DEBOUNCE_MS)
        self.save_timer.timeout.connect(self.save)

        self.tab.clicked.connect(self.toggle)
        self.tab.dragged.connect(self._drag_to)
        self.tab.drag_finished.connect(self._drop)
        self.tab.menu_requested.connect(self._show_menu)
        self.panel.changed.connect(self._on_change)
        QApplication.instance().applicationStateChanged.connect(self._app_state_changed)
        QApplication.styleHints().colorSchemeChanged.connect(lambda _: self._apply_look())

        self.tab_offset = self._clamp_offset(self.tab_offset)
        self._layout_collapsed()
        self.panel.ensurePolished()
        self.panel.grab()                 # warm up layout, stylesheet and fonts before the first slide

    # -- look

    def _glass_on(self):
        return self.style == "glass" and self.glass_win is not None

    def _apply_look(self):
        glass = self._glass_on()
        dark = QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        opacity = 1.0 if glass else SEE_THROUGH[self.see_through]
        self.tab.set_look(self.tab_color, opacity, self.edge, glass=glass and self._glass_tab is not None)
        self.panel.apply_look(self.tab_color, opacity, self.edge, glass=glass, dark=dark)
        if glass:
            try:
                tint = GLASS_TINT_DARK if dark else GLASS_TINT_LIGHT
                self._glass_panel.setTintColor_(AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(*tint))
            except Exception:
                pass
        else:
            self._hide_glass()

    # -- Liquid Glass

    def _create_glass_window(self):
        """A borderless native window holding the glass, attached below our Qt window as a
        child so it moves with it. On macOS 26 the tab and panel are two NSGlassEffectViews
        inside an NSGlassEffectContainerView, which melts them into one liquid shape.
        Older macOS gets a frosted NSVisualEffectView under the panel only."""
        rect = AppKit.NSMakeRect(0, 0, PANEL_W, PANEL_H)
        win = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel,
            AppKit.NSBackingStoreBuffered, False)
        win.setOpaque_(False)
        win.setBackgroundColor_(AppKit.NSColor.clearColor())
        win.setHasShadow_(True)
        win.setIgnoresMouseEvents_(True)
        win.setReleasedWhenClosed_(False)
        win.setCollectionBehavior_(self.nswin.collectionBehavior())

        if hasattr(AppKit, "NSGlassEffectContainerView"):
            container = AppKit.NSGlassEffectContainerView.alloc().initWithFrame_(rect)
            container.setSpacing_(GLASS_MERGE)
            inner = AppKit.NSView.alloc().initWithFrame_(rect)
            container.setContentView_(inner)
            panel = AppKit.NSGlassEffectView.alloc().initWithFrame_(rect)
            panel.setStyle_(GLASS_STYLE_REGULAR)
            panel.setCornerRadius_(GLASS_RADIUS)
            tab = AppKit.NSGlassEffectView.alloc().initWithFrame_(rect)
            tab.setStyle_(GLASS_STYLE_REGULAR)
            tab.setCornerRadius_(TAB_RADIUS)
            inner.addSubview_(panel)
            inner.addSubview_(tab)
            win.setContentView_(container)
            self._glass_tab, self._glass_panel = tab, panel
        else:
            view = AppKit.NSVisualEffectView.alloc().initWithFrame_(rect)
            view.setMaterial_(AppKit.NSVisualEffectMaterialPopover)
            view.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
            view.setState_(AppKit.NSVisualEffectStateActive)
            view.setWantsLayer_(True)
            view.layer().setCornerRadius_(GLASS_RADIUS)
            view.layer().setMasksToBounds_(True)
            win.setContentView_(view)
            self._glass_tab, self._glass_panel = None, view
        return win

    def _sync_glass(self, win_x, win_y, expanded, tab_y):
        """Shape and place the glass for a window whose top-left is (win_x, win_y).

        All rects are in Qt screen coordinates (origin top-left) and converted to Cocoa's
        bottom-left origin at the end. The glass overhangs the screen edge so the corners
        there stay hidden, and the tab glass tucks under the panel so they fuse.
        """
        if not self._glass_on():
            return
        try:
            right = self.edge == "right"
            rects = []
            # Tab glass. Its local x inside the Qt window: 0 on the right edge, or PANEL_W
            # on the left edge when expanded (0 when collapsed).
            tab_x = win_x + (0 if right or not expanded else PANEL_W)
            if right:
                tab_rect = (tab_x, win_y + tab_y, TAB_W + TAB_GLASS_TUCK, TAB_H)
            else:
                tab_rect = (tab_x - TAB_GLASS_TUCK, win_y + tab_y, TAB_W + TAB_GLASS_TUCK, TAB_H)
            if self._glass_tab is not None:
                rects.append(tab_rect)
            panel_rect = None
            if expanded:
                if right:
                    panel_rect = (win_x + TAB_W, win_y, PANEL_W + GLASS_EDGE_OVERHANG, PANEL_H)
                else:
                    panel_rect = (win_x - GLASS_EDGE_OVERHANG, win_y, PANEL_W + GLASS_EDGE_OVERHANG, PANEL_H)
                rects.append(panel_rect)
            if not rects:
                self._hide_glass()
                return

            bx = min(r[0] for r in rects)
            by = min(r[1] for r in rects)
            bw = max(r[0] + r[2] for r in rects) - bx
            bh = max(r[1] + r[3] for r in rects) - by

            def local(r):   # Qt screen rect -> Cocoa rect inside the glass window
                return AppKit.NSMakeRect(r[0] - bx, bh - (r[1] - by) - r[3], r[2], r[3])

            screen_h = AppKit.NSScreen.screens()[0].frame().size.height
            self.glass_win.setFrame_display_(AppKit.NSMakeRect(bx, screen_h - by - bh, bw, bh), False)
            content = self.glass_win.contentView()
            content.setFrame_(AppKit.NSMakeRect(0, 0, bw, bh))
            if self._glass_tab is not None:
                content.contentView().setFrame_(AppKit.NSMakeRect(0, 0, bw, bh))
                self._glass_tab.setFrame_(local(tab_rect))
                self._glass_panel.setHidden_(panel_rect is None)
                if panel_rect is not None:
                    self._glass_panel.setFrame_(local(panel_rect))
            elif panel_rect is not None:
                self._glass_panel.setFrame_(local(panel_rect))

            if self.glass_win.parentWindow() is None:
                self.nswin.addChildWindow_ordered_(self.glass_win, AppKit.NSWindowBelow)
            self.glass_win.orderWindow_relativeTo_(AppKit.NSWindowBelow, self.nswin.windowNumber())
        except Exception as e:
            print(f"Edge Notes: glass unavailable, using paper: {e}", file=sys.stderr)
            self._hide_glass()
            self.glass_win = None
            self._apply_look()

    def _hide_glass(self):
        if self.glass_win is None:
            return
        try:
            if self.glass_win.parentWindow() is not None:
                self.nswin.removeChildWindow_(self.glass_win)
            self.glass_win.orderOut_(None)
        except Exception:
            pass

    # -- geometry

    def _screen(self):
        return QApplication.primaryScreen().availableGeometry()

    def _clamp_offset(self, offset):
        return max(0, min(offset, self._screen().height() - TAB_H))

    def _tab_top(self):
        return self._screen().y() + self.tab_offset

    def _collapsed_x(self):
        g = self._screen()
        return g.x() if self.edge == "left" else g.x() + g.width() - TAB_W

    def _parked_x(self):
        """Window x with the panel hidden off-screen and only the tab showing."""
        g = self._screen()
        return g.x() - PANEL_W if self.edge == "left" else g.x() + g.width() - TAB_W

    def _open_x(self):
        g = self._screen()
        return g.x() if self.edge == "left" else g.x() + g.width() - TAB_W - PANEL_W

    def _layout_collapsed(self):
        self.panel.hide()
        self.tab.move(0, 0)
        self.setFixedSize(TAB_W, TAB_H)
        self.move(self._collapsed_x(), self._tab_top())
        self._sync_glass(self._collapsed_x(), self._tab_top(), False, 0)

    def _expanded_top(self):
        # Keep the tab where it is; only shift the panel up if it would run off the bottom.
        g = self._screen()
        return max(g.y(), min(self._tab_top(), g.y() + g.height() - PANEL_H))

    # -- open / close

    def toggle(self):
        self.collapse() if self.expanded else self.expand()

    def expand(self):
        if self.expanded:
            return
        self.expanded = True
        self._activated_since_expand = False
        top = self._expanded_top()
        if not self._animating:
            # Grow the window with the panel parked off-screen, and paint it now so the
            # slide never has to wait on a first render.
            self.setFixedSize(TAB_W + PANEL_W, PANEL_H)
            tab_x, panel_x = (PANEL_W, 0) if self.edge == "left" else (0, TAB_W)
            self.tab.move(tab_x, self._tab_top() - top)
            self.panel.move(panel_x, 0)
            self.panel.show()
            self.move(self._parked_x(), top)
            self._sync_glass(self._parked_x(), top, True, self._tab_top() - top)
            self.repaint()
        self._slide_to(QPoint(self._open_x(), top), EASE_OUT, QEasingCurve.Type.OutCubic)

        self.raise_()
        self.activateWindow()
        if AppKit is not None:
            AppKit.NSApp.activateIgnoringOtherApps_(True)
        self.panel.todo_input.setFocus()

    def collapse(self):
        if not self.expanded:
            return
        self.expanded = False
        self._slide_to(QPoint(self._parked_x(), self.y()), EASE_IN, QEasingCurve.Type.InCubic)
        self.save()

    def _slide_to(self, target, bezier, qt_curve):
        """Slide the window to `target`. Uses the native macOS window animation when
        available (driven by the window server at the display's refresh rate, so it
        stays smooth on 120Hz screens); falls back to a Qt animation otherwise."""
        self._animating = True
        self._anim_generation += 1
        generation = self._anim_generation
        if self.nswin is not None:
            try:
                self._native_slide(target, bezier, generation)
                return
            except Exception as e:
                print(f"Edge Notes: native animation failed, using Qt: {e}", file=sys.stderr)
                self.nswin = None
        self.anim.stop()
        self.anim.setEasingCurve(qt_curve)
        self.anim.setStartValue(self.pos())
        self.anim.setEndValue(target)
        self.anim.start()

    def _native_slide(self, target, bezier, generation):
        # Cocoa puts the origin at the bottom-left of the primary screen.
        screen_h = AppKit.NSScreen.screens()[0].frame().size.height
        frame = AppKit.NSMakeRect(target.x(), screen_h - target.y() - self.height(),
                                  self.width(), self.height())
        timing = objc.lookUpClass("CAMediaTimingFunction").functionWithControlPoints____(*bezier)

        def animate(ctx):
            ctx.setDuration_(ANIM_MS / 1000)
            ctx.setTimingFunction_(timing)
            self.nswin.animator().setFrame_display_(frame, True)

        def finished():
            if generation == self._anim_generation:
                self._anim_done()

        AppKit.NSAnimationContext.runAnimationGroup_completionHandler_(animate, finished)

        # Safety net: if the display sleeps mid-slide the completion may never arrive,
        # so snap to the end position shortly after the animation should have finished.
        def ensure_finished():
            if generation == self._anim_generation and self._animating:
                self.nswin.setFrame_display_(frame, True)
                self._anim_done()

        QTimer.singleShot(ANIM_MS + 250, ensure_finished)

    def _anim_done(self):
        self._animating = False
        if not self.expanded:
            self._layout_collapsed()

    # -- moving the tab

    def _drag_to(self, top_left):
        if self.expanded or self._animating:
            return
        self.move(top_left)

    def _drop(self):
        """Snap to whichever side edge is closer, keeping the height where it was dropped."""
        if self.expanded or self._animating:
            return
        g = self._screen()
        self.edge = "left" if self.x() + TAB_W / 2 < g.center().x() else "right"
        self.tab_offset = self._clamp_offset(self.y() - g.y())
        self._apply_look()
        self._sync_glass(self.x(), self.y(), False, 0)
        self._slide_to(QPoint(self._collapsed_x(), self._tab_top()), EASE_OUT, QEasingCurve.Type.OutCubic)
        self._schedule_save()

    # -- right-click menu

    def _show_menu(self, global_pos):
        menu = QMenu(self)
        menu.addAction("Tab color…", self._pick_color)

        style_menu = menu.addMenu("Style")
        style_group = QActionGroup(style_menu)
        for key, label in STYLES.items():
            action = style_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(key == self.style)
            action.setActionGroup(style_group)
            if key == "glass" and self.nswin is None:
                action.setEnabled(False)      # needs pyobjc
            action.triggered.connect(lambda _=False, k=key: self._set_style(k))

        see_menu = menu.addMenu("See-through")
        see_menu.setEnabled(not self._glass_on())
        group = QActionGroup(see_menu)
        for key in SEE_THROUGH:
            action = see_menu.addAction(key.capitalize())
            action.setCheckable(True)
            action.setChecked(key == self.see_through)
            action.setActionGroup(group)
            action.triggered.connect(lambda _=False, k=key: self._set_see_through(k))

        menu.addSeparator()
        menu.addAction("Quit Edge Notes", QApplication.quit)
        menu.exec(global_pos)

    def _set_style(self, key):
        self.style = key
        self._apply_look()
        self._sync_glass(self.x(), self.y(), self.expanded, self.tab.y() if self.expanded else 0)
        self._schedule_save()

    def _set_see_through(self, key):
        self.see_through = key
        self._apply_look()
        self._schedule_save()

    def _pick_color(self):
        """Open the macOS color picker (color wheel) with a live preview on the tab."""
        original = QColor(self.tab_color)
        dialog = QColorDialog(original, self)
        dialog.setWindowTitle("Tab color")

        def preview(color):
            if color.isValid():
                self.tab_color = color
                self._apply_look()

        dialog.currentColorChanged.connect(preview)
        if AppKit is not None:
            try:
                AppKit.NSColorPanel.sharedColorPanel().setMode_(AppKit.NSColorPanelModeWheel)
            except Exception:
                pass
        if dialog.exec() and dialog.selectedColor().isValid():
            self.tab_color = dialog.selectedColor()
        else:
            self.tab_color = original
        self._apply_look()
        self._schedule_save()

    # -- events

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape and self.expanded:
            self.collapse()
        else:
            super().keyPressEvent(e)

    def _app_state_changed(self, state):
        # Clicking anywhere outside our window activates another app: collapse.
        if state == Qt.ApplicationState.ApplicationActive:
            self._activated_since_expand = True
        elif self.expanded and self._activated_since_expand:
            self.collapse()

    def _on_change(self):
        self.tab.set_count(self.panel.open_count())
        self._schedule_save()

    # -- saving

    def _schedule_save(self):
        self.save_timer.start()

    def save(self):
        self.save_timer.stop()
        save_data({
            "todos": self.panel.todos(),
            "ideas": self.panel.ideas.toPlainText(),
            "tab_offset": self.tab_offset,
            "edge": self.edge,
            "tab_color": self.tab_color.name(),
            "see_through": self.see_through,
            "style": self.style,
        })

    # -- macOS niceties

    def apply_mac_window_behavior(self):
        """Show on every Space and over full-screen apps, and never hide on deactivate."""
        if objc is None:
            return
        try:
            view = objc.objc_object(c_void_p=int(self.winId()))
            nswin = view.window()
            nswin.setCollectionBehavior_(
                AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                | AppKit.NSWindowCollectionBehaviorStationary
                | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
            )
            nswin.setHidesOnDeactivate_(False)
            self.nswin = nswin
        except Exception as e:  # cosmetic only, never fatal
            print(f"Edge Notes: macOS window tweaks skipped: {e}", file=sys.stderr)
            return
        try:
            self.glass_win = self._create_glass_window()
        except Exception as e:
            print(f"Edge Notes: glass unavailable, using paper: {e}", file=sys.stderr)
            self.glass_win = None
        self._apply_look()
        if not self.expanded:
            self._layout_collapsed()      # re-place the tab (macOS can nudge a new window) and its glass


# ---------------------------------------------------------------- entry point

def hide_dock_icon():
    if AppKit is None:
        return
    try:
        AppKit.NSApp.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    except Exception as e:
        print(f"Edge Notes: could not hide Dock icon: {e}", file=sys.stderr)


def main():
    # Older Qt builds spam harmless color-profile warnings on some Macs.
    QLoggingCategory.setFilterRules("qt.gui.icc=false")
    app = QApplication(sys.argv)
    app.setApplicationName("Edge Notes")
    app.setQuitOnLastWindowClosed(False)
    if AppKit is not None:
        AppKit.NSApplication.sharedApplication()
    hide_dock_icon()

    window = EdgeWindow()
    window.show()
    window.apply_mac_window_behavior()
    app.aboutToQuit.connect(window.save)

    # Ctrl+C in the terminal or SIGTERM from launchctl: quit cleanly so notes get saved.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    ticker = QTimer(interval=300)
    ticker.timeout.connect(lambda: None)  # lets Python handle signals while Qt runs
    ticker.start()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
