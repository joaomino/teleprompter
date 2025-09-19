#!/usr/bin/env python3
"""
Teleprompter App (PySide6)

Features
- Load a script from file (.txt, .md, .rtf basic text)
- Smooth auto-scroll with adjustable speed (pixels/sec)
- "Fit to duration" (auto-compute scroll speed to finish in a target time)
- Adjustable font family, size, line spacing, and margins
- Horizontal mirror mode for beam-splitter glass (toggle)
- Start/Pause/Stop, Jump, and Rewind controls + keyboard shortcuts
- Countdown overlay before start
- Optional focus band to keep eyes centered
- Fullscreen toggle

Shortcuts
- Space: Start/Pause
- Esc: Exit fullscreen / close dialogs
- F11: Toggle fullscreen
- Up/Down: Increase/Decrease speed
- Left/Right: Small backward/forward jump
- PageUp/PageDown: Large backward/forward jump
- +/-: Increase/Decrease font size
- M: Toggle mirror
- 0 (zero): Jump to top
- G: Go to percentage
- O: Open file
- R: Fit speed to duration (after setting a target)

Dependencies
- PySide6 (Qt for Python): `pip install PySide6`

Run
- `python teleprompter_app.py your_script.txt`
- or just `python teleprompter_app.py` and use File → Open
"""
from __future__ import annotations
import sys
import math
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF, QSize, Signal
from PySide6.QtGui import QAction, QFont, QKeySequence, QPainter, QTransform
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QFileDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QDoubleSpinBox,
    QComboBox,
    QCheckBox,
    QGroupBox,
    QGraphicsView,
    QGraphicsScene,
    QGraphicsTextItem,
    QScrollBar,
    QDialog,
    QFormLayout,
    QDialogButtonBox,
    QInputDialog,
)


class CountdownDialog(QDialog):
    def __init__(self, seconds: int = 3, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle("Starting…")
        self.seconds = seconds
        self.label = QLabel(str(self.seconds))
        self.label.setAlignment(Qt.AlignCenter)
        font = QFont()
        font.setPointSize(72)
        font.setBold(True)
        self.label.setFont(font)

        layout = QVBoxLayout()
        layout.addStretch(1)
        layout.addWidget(self.label)
        layout.addStretch(1)
        self.setLayout(layout)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)
        self.setFixedSize(300, 240)

    def _tick(self):
        self.seconds -= 1
        if self.seconds <= 0:
            self.accept()
        else:
            self.label.setText(str(self.seconds))


class TeleprompterView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameStyle(0)

        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)

        self.text_item = QGraphicsTextItem()
        self.scene.addItem(self.text_item)

        # Render hints for smoother text
        self.setRenderHints(self.renderHints() | QPainter.Antialiasing | QPainter.TextAntialiasing)

        # Parameters
        self._mirror = False
        self._font_family = "Helvetica"
        self._font_size = 50
        self._line_spacing_mult = 1.2
        self._margin_px = 80
        self._focus_band_ratio = 0.2  # 20% of height
        self._show_focus_band = True
        self._focus_band_y = int(self.viewport().height() * self._focus_band_ratio / 2)

        # Scrolling
        self._speed_px_s = 35.0
        self._running = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._last_tick_ms: Optional[int] = None

        # Theme
        self._text_color = "#FFFFFF"
        self._bg_color = "#000000"
        self.setStyleSheet(f"background: {self._bg_color};")

        self.update_text_format()

        # Track if we've reached the end
        self._at_bottom = False

    # --- Public controls ---
    def set_text(self, text: str):
        # Replace Windows newlines just in case
        text = text.replace("\r\n", "\n")
        self.text_item.setPlainText(text)
        self.update_text_format()
        self._relayout()
        self.to_top()

    def set_theme(self, fg: str, bg: str):
        self._text_color, self._bg_color = fg, bg
        self.update_text_format()
        self.setStyleSheet(f"background: {self._bg_color};")

    def set_font_family(self, family: str):
        self._font_family = family
        self.update_text_format()

    def set_font_size(self, pt: int):
        self._font_size = max(8, min(pt, 200))
        self.update_text_format()

    def adjust_font_size(self, delta: int):
        self.set_font_size(self._font_size + delta)

    def set_line_spacing(self, mult: float):
        self._line_spacing_mult = max(1.0, min(mult, 3.0))
        self.update_text_format()

    def set_margins(self, px: int):
        self._margin_px = max(0, min(px, 300))
        self._relayout()

    def set_speed(self, px_per_sec: float):
        self._speed_px_s = max(5.0, min(px_per_sec, 2000.0))

    def adjust_speed(self, delta: float):
        self.set_speed(self._speed_px_s + delta)

    def toggle_mirror(self):
        self._mirror = not self._mirror
        self._apply_mirror()

    def _apply_mirror(self):
        t = self.transform()
        t.reset()
        if self._mirror:
            t.scale(-1.0, 1.0)
            self.setTransform(t)
            # When mirrored, we also want the content to stay visible: move origin to the right
            # Use a horizontal translation equal to the viewport width in device coords via viewport transform.
        else:
            self.setTransform(t)
        # Trigger relayout to keep wrapping correct
        self._relayout()

    def toggle_focus_band(self, on: bool):
        self._show_focus_band = on
        self.viewport().update()

    def start(self):
        if self._running:
            return
        self._running = True
        self._last_tick_ms = None
        self._timer.start(16)  # ~60 FPS

    def pause(self):
        self._running = False
        self._timer.stop()

    def toggle(self):
        if self._running:
            self.pause()
        else:
            self.start()

    def stop(self):
        self.pause()
        self.to_top()

    def to_top(self):
        sb = self.verticalScrollBar()
        sb.setValue(0)
        # Offset so first line is visible inside the band
        band_offset = int(self.viewport().height() * 0.1)
        sb.setValue(min(sb.value(), sb.maximum() - band_offset))

    def jump_pixels(self, delta_px: int):
        sb: QScrollBar = self.verticalScrollBar()
        sb.setValue(max(0, min(sb.value() + delta_px, sb.maximum())))

    def go_to_percent(self, pct: float):
        pct = max(0.0, min(pct, 100.0))
        sb: QScrollBar = self.verticalScrollBar()
        sb.setValue(int(sb.maximum() * (pct / 100.0)))

    def remaining_ms(self) -> int:
        sb: QScrollBar = self.verticalScrollBar()
        remaining_px = sb.maximum() - sb.value()
        return int(1000 * remaining_px / self._speed_px_s) if self._speed_px_s > 0 else 0

    def total_scroll_px(self) -> int:
        sb: QScrollBar = self.verticalScrollBar()
        return sb.maximum()

    # --- Internals ---
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()

    def drawForeground(self, painter, rect):
        if not self._show_focus_band:
            return

        # Save current painter transform
        painter.save()

        # Reset transform so we draw in viewport coordinates
        painter.setWorldTransform(QTransform())

        h = self.viewport().height()
        band_h = int(h * self._focus_band_ratio)
        y = int(h * 0.1)  # for example, top 10% of viewport
        painter.setOpacity(0.15)
        painter.fillRect(0, y, self.viewport().width(), band_h, Qt.white)
        painter.setOpacity(1.0)

        # Restore painter transform
        painter.restore()

    def update_text_format(self):
        doc = self.text_item.document()
        default_font = QFont(self._font_family, self._font_size)
        doc.setDefaultFont(default_font)
        # Line spacing via default block format
        fmt = doc.defaultTextOption()
        fmt.setWrapMode(fmt.WrapMode.WordWrap)
        doc.setDefaultTextOption(fmt)

        # Apply block format spacing by brute force: set document-wide CSS-ish style
        css = f"""
            * {{
                color: {self._text_color};
                background-color: transparent;
                line-height: {self._line_spacing_mult};
            }}
        """
        doc.setDefaultStyleSheet(css)

    def _relayout(self):
        # Set text width to viewport width minus margins
        vw = self.viewport().width()
        if self._mirror:
            # When mirrored, Qt transform flips device coords. Text wrapping still uses logical width.
            text_width = max(100, vw - 2 * self._margin_px)
        else:
            text_width = max(100, vw - 2 * self._margin_px)
        self.text_item.setTextWidth(text_width)

        # Position the text with margins (x) and a top margin
        self.text_item.setPos(QPointF(self._margin_px, self._margin_px))

        # Resize scene rect to fit text and margins
        br: QRectF = self.text_item.boundingRect()
        w = br.width() + 2 * self._margin_px
        h = br.height() + 2 * self._margin_px
        self.scene.setSceneRect(0, 0, w, h)

        # Extend scrollable area so last line can reach top of viewport
        extra_scroll = max(0, self.viewport().height() - self._margin_px)
        self.scene.setSceneRect(0, 0, w, h + extra_scroll)


        # If mirrored, we want the origin adjustment so text remains visible after scale(-1,1).
        if self._mirror:
            # Translate view so that (0,0) is at right edge in device coords
            # Achieve by setting transform anchor and a translation on the view transform.
            t = self.transform()
            t.reset()
            t.scale(-1.0, 1.0)
            # Translate by viewport width in device coordinates
            self.setTransform(t)
            self.setSceneRect(self.scene.sceneRect())

        self.viewport().update()


    def _on_tick(self):
        if not self._running:
            return

        dt = self._timer.interval() / 1000.0
        if not hasattr(self, "_scroll_accum"):
            self._scroll_accum = 0.0

        self._scroll_accum += self._speed_px_s * dt
        move_px = int(self._scroll_accum)
        if move_px > 0:
            self.jump_pixels(move_px)
            self._scroll_accum -= move_px

        sb = self.verticalScrollBar()
        if sb.value() >= sb.maximum():
            self.pause()
            self._scroll_accum = 0.0
            self._at_bottom = True
            self.finished.emit()

    
    finished = Signal()

class ControlPanel(QWidget):
    def __init__(self, view: TeleprompterView):
        super().__init__()
        self.view = view
        self.view.finished.connect(self._on_finished)

        # --- Controls ---
        self.play_btn = QPushButton("Play")
        self.play_btn.clicked.connect(self._toggle_play)

        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(5, 1500)
        self.speed_slider.setValue(int(self.view._speed_px_s))
        self.speed_slider.valueChanged.connect(lambda v: self._set_speed(v))
        self.speed_label = QLabel("35 px/s")

        self.font_size = QSpinBox()
        self.font_size.setRange(8, 200)
        self.font_size.setValue(self.view._font_size)
        self.font_size.valueChanged.connect(self.view.set_font_size)

        self.line_spacing = QDoubleSpinBox()
        self.line_spacing.setDecimals(2)
        self.line_spacing.setSingleStep(0.05)
        self.line_spacing.setRange(1.0, 3.0)
        self.line_spacing.setValue(self.view._line_spacing_mult)
        self.line_spacing.valueChanged.connect(self.view.set_line_spacing)

        self.margins = QSpinBox()
        self.margins.setRange(0, 300)
        self.margins.setValue(self.view._margin_px)
        self.margins.valueChanged.connect(self.view.set_margins)

        self.mirror = QCheckBox("Mirror")
        self.mirror.stateChanged.connect(lambda _: self.view.toggle_mirror())

        self.focus_band = QCheckBox("Focus band")
        self.focus_band.setChecked(True)
        self.focus_band.stateChanged.connect(lambda s: self.view.toggle_focus_band(s == Qt.Checked))

        self.theme = QComboBox()
        self.theme.addItems(["Light", "Dark", "Amber", "Mint"]) 
        self.theme.currentTextChanged.connect(self._apply_theme)

        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(10, 60 * 120)  # 10s to 2h
        self.duration_spin.setValue(300)  # default 5m
        self.fit_btn = QPushButton("Fit to duration")
        self.fit_btn.clicked.connect(self._fit_to_duration)

        # Layout
        row1 = QHBoxLayout()
        row1.addWidget(self.play_btn)
        row1.addWidget(QLabel("Speed"))
        row1.addWidget(self.speed_slider)
        row1.addWidget(self.speed_label)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Font"))
        row2.addWidget(self.font_size)
        row2.addWidget(QLabel("Line"))
        row2.addWidget(self.line_spacing)
        row2.addWidget(QLabel("Margins"))
        row2.addWidget(self.margins)
        row2.addWidget(self.mirror)
        row2.addWidget(self.focus_band)
        row2.addWidget(QLabel("Theme"))
        row2.addWidget(self.theme)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Target (s)"))
        row3.addWidget(self.duration_spin)
        row3.addWidget(self.fit_btn)
        row3.addStretch(1)

        outer = QVBoxLayout(self)
        outer.addLayout(row1)
        outer.addLayout(row2)
        outer.addLayout(row3)
        self.setLayout(outer)
    
    
    def _on_finished(self):
        self.play_btn.setText("Play")


    def _toggle_play(self):
        if self.view._running:
            self.view.pause()
            self.play_btn.setText("Play")
        else:
            # If at bottom, reset to top
            if getattr(self.view, "_at_bottom", False):
                self.view.to_top()
                self.view._at_bottom = False

            # Countdown before starting
            dlg = CountdownDialog(3, self)
            if dlg.exec() == QDialog.Accepted:
                self.view.start()
                self.play_btn.setText("Pause")

    def _set_speed(self, v: int):
        self.view.set_speed(float(v))
        self.speed_label.setText(f"{v} px/s")

    def _apply_theme(self, name: str):
        themes = {
            "Light": ("#000000", "#FFFFFF"),
            "Dark": ("#FFFFFF", "#000000"),
            "Amber": ("#FFEEAA", "#222222"),
            "Mint": ("#DFF6E5", "#10221B"),
        }
        fg, bg = themes.get(name, ("#FFFFFF", "#000000"))
        self.view.set_theme(fg, bg)

    def _fit_to_duration(self):
        total_px = max(1, self.view.total_scroll_px())
        target_s = max(1, self.duration_spin.value())
        # speed = distance / time
        speed = total_px / target_s
        self.view.set_speed(speed)
        self.speed_slider.blockSignals(True)
        self.speed_slider.setValue(int(speed))
        self.speed_slider.blockSignals(False)
        self.speed_label.setText(f"{int(speed)} px/s")


class TeleprompterWindow(QMainWindow):
    def __init__(self, initial_text: str = ""):
        super().__init__()
        self.setWindowTitle("Teleprompter")
        self.resize(1100, 750)

        self.view = TeleprompterView()
        self.controls = ControlPanel(self.view)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.addWidget(self.view, 1)
        lay.addWidget(self.controls, 0)
        self.setCentralWidget(central)

        self._build_menu()
        if initial_text:
            self.view.set_text(initial_text)
        else:
            self.view.set_text("""\
TELEPROMPTER\n\nOpen a file (Ctrl+O) or paste your script.\n\nQuick tips:\n- Press Space to play/pause.\n- Use Up/Down to adjust speed.\n- Press + / - for font size.\n- Press M to mirror for a beam-splitter.\n- Press F11 for fullscreen.\n- Fit to a target time with the control below.\n\nHave a great read!\n""")

    # --- Menu and actions ---
    def _build_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        open_act = QAction("Open…", self)
        open_act.setShortcut(QKeySequence.Open)
        open_act.triggered.connect(self._open_file)
        file_menu.addAction(open_act)

        exit_act = QAction("Exit", self)
        exit_act.setShortcut("Ctrl+Q")
        exit_act.triggered.connect(self.close)
        file_menu.addAction(exit_act)

        view_menu = menubar.addMenu("&View")
        fs_act = QAction("Toggle Fullscreen", self)
        fs_act.setShortcut(Qt.Key_F11)
        fs_act.triggered.connect(self._toggle_fullscreen)
        view_menu.addAction(fs_act)

        mirror_act = QAction("Mirror", self)
        mirror_act.setShortcut("M")
        mirror_act.triggered.connect(self.view.toggle_mirror)
        view_menu.addAction(mirror_act)

        help_menu = menubar.addMenu("&Help")
        about_act = QAction("About Shortcuts", self)
        about_act.triggered.connect(self._show_shortcuts)
        help_menu.addAction(about_act)

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _show_shortcuts(self):
        text = (
            "Space: Play/Pause\n"
            "F11: Fullscreen\n"
            "Up/Down: Speed ±\n"
            "Left/Right: Nudge ±200 px\n"
            "PageUp/PageDown: Jump ±1200 px\n"
            "+/-: Font size ±2\n"
            "M: Mirror\n"
            "0: Top\n"
            "G: Go to percentage\n"
            "O: Open file\n"
            "R: Fit speed to duration\n"
        )
        QInputDialog.getMultiLineText(self, "Shortcuts", "", text)

    # --- File handling ---
    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Script", str(Path.cwd()), "Text Files (*.txt *.md *.rtf);;All Files (*)")
        if path:
            try:
                text = Path(path).read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = Path(path).read_text(errors="ignore")
            self.view.set_text(text)

    # --- Key handling ---
    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Space:
            self.controls._toggle_play()
            event.accept()
            return
        if key == Qt.Key_Up:
            self.view.adjust_speed(10)
            self.controls.speed_slider.setValue(int(self.view._speed_px_s))
            event.accept(); return
        if key == Qt.Key_Down:
            self.view.adjust_speed(-10)
            self.controls.speed_slider.setValue(int(self.view._speed_px_s))
            event.accept(); return
        if key == Qt.Key_Plus or key == Qt.Key_Equal:
            self.view.adjust_font_size(2)
            self.controls.font_size.setValue(self.view._font_size)
            event.accept(); return
        if key == Qt.Key_Minus:
            self.view.adjust_font_size(-2)
            self.controls.font_size.setValue(self.view._font_size)
            event.accept(); return
        if key == Qt.Key_M:
            self.view.toggle_mirror()
            self.controls.mirror.setChecked(self.view._mirror)
            event.accept(); return
        if key == Qt.Key_F11:
            self._toggle_fullscreen(); event.accept(); return
        if key == Qt.Key_0:
            self.view.to_top(); event.accept(); return
        if key == Qt.Key_Left:
            self.view.jump_pixels(-200); event.accept(); return
        if key == Qt.Key_Right:
            self.view.jump_pixels(200); event.accept(); return
        if key == Qt.Key_PageUp:
            self.view.jump_pixels(-1200); event.accept(); return
        if key == Qt.Key_PageDown:
            self.view.jump_pixels(1200); event.accept(); return
        if key == Qt.Key_G:
            pct, ok = QInputDialog.getInt(self, "Go to…", "Percent (0-100)", 0, 0, 100, 1)
            if ok:
                self.view.go_to_percent(float(pct))
            event.accept(); return
        if key == Qt.Key_O:
            self._open_file(); event.accept(); return
        if key == Qt.Key_R:
            self.controls._fit_to_duration(); event.accept(); return
        super().keyPressEvent(event)


def load_initial_text_from_argv() -> str:
    if len(sys.argv) > 1:
        p = Path(sys.argv[1])
        if p.exists():
            try:
                return p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                return p.read_text(errors="ignore")
    return ""


def main():
    app = QApplication(sys.argv)
    win = TeleprompterWindow(load_initial_text_from_argv())
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
