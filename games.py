"""
通用桌宠 · 内置休闲小游戏

提供与桌宠风格一致的轻量小游戏：
- 2048（方向键合并数字，目标 2048）
- 推箱子 Sokoban（方向键/WASD 推箱入位，18 个递进关卡，含撤销/重开）
- 贪吃蛇 Snake（方向键控制，吃到食物变长，撞墙/撞自己结束）
- 石头剪刀布（窗口版，点按钮出拳，与心情/好感联动）
- 扫雷 Minesweeper（鼠标左键翻开、右键插旗；初级 9x9/中级 16x16/高级 30x16 三档）
- 俄罗斯方块 Tetris（方向键移动/旋转、空格硬降、消行计分、等级加速）
- 五子棋 Gomoku（15x15，玩家执黑对战简易 AI 白棋，先连五子者胜）

所有游戏窗口均为无边框、半透明、置顶，跟随同一套粉色视觉风格。
键盘游戏通过方向键操作；游戏结束时通过 game_over 信号回调，可给桌宠一点小奖励。
"""
import os
import random
import sys

from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

PANEL_STYLE = (
    "QWidget#gamePanel{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
    "stop:0 #fff0f6, stop:1 #ffe3ef);border-radius:18px;"
    "border:2px solid #ff9ec2;}"
)
TITLE_STYLE = "color:#d6336c;font-size:15px;font-weight:bold;background:transparent;border:none;"
HINT_STYLE = "color:#868e96;font-size:11px;background:transparent;border:none;"


class GameWindowBase(QWidget):
    """小游戏通用外壳：无边框 / 半透明 / 置顶 / 可拖动 / 有关闭按钮。

    game_over 信号在游戏结束时发出，参数为“得分”（具体含义由各游戏决定）。
    """

    game_over = Signal(int)

    def __init__(self, parent=None, title="桌宠小游戏"):
        super().__init__(parent)
        self._title = title
        self._drag_pos = None
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.installEventFilter(self)
        self.resize(440, 560)

        container = QWidget(self)
        container.setObjectName("gamePanel")
        container.setStyleSheet(PANEL_STYLE)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(container)

        v = QVBoxLayout(container)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(10)

        # 标题栏（兼作拖拽区）
        bar = QHBoxLayout()
        bar.setSpacing(6)
        title_label = QLabel(title, container)
        title_label.setStyleSheet(TITLE_STYLE)
        bar.addWidget(title_label)
        bar.addStretch(1)
        close_btn = QPushButton("×", container)
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(
            "QPushButton{background:#ff9ec2;color:#fff;border:none;border-radius:8px;"
            "font-size:16px;font-weight:bold;}"
            "QPushButton:hover{background:#ff7aa8;}"
        )
        close_btn.clicked.connect(self.close)
        bar.addWidget(close_btn)
        v.addLayout(bar)

        # 内容区：用 QStackedWidget 在「开始界面」与「游戏界面」之间切换
        self.stack = QStackedWidget(self)
        v.addWidget(self.stack, 1)

        # 游戏界面页（子类往这里添加控件）
        self.game_page = QWidget(self)
        self.body_layout = QVBoxLayout(self.game_page)
        self.body_layout.setSpacing(10)
        self.stack.addWidget(self.game_page)

        # 开始界面页（含玩法说明 + 开始按钮）
        self.start_page = QWidget(self)
        self._build_start_page()
        self.stack.addWidget(self.start_page)
        self.stack.setCurrentWidget(self.start_page)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.position().toPoint())
            if isinstance(child, QPushButton):
                self._drag_pos = None
            else:
                self._drag_pos = event.globalPosition().toPoint() - self.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def handle_game_key(self, key):
        """子类实现：消费某个按键则返回 True。基类默认不处理。"""
        return False

    def eventFilter(self, obj, event):
        # 本过滤器只接收本窗口及其子控件的事件，可安全拦截方向键
        if event.type() == QEvent.Type.KeyPress:
            if self.handle_game_key(event.key()):
                return True
        return super().eventFilter(obj, event)

    def showEvent(self, event):
        super().showEvent(event)
        try:
            from PySide6.QtWidgets import QApplication
            QApplication.setActiveWindow(self)
        except Exception:
            pass
        self.raise_()
        self.activateWindow()
        self.setFocus()
        # 按钮点击后不应抢走键盘焦点，否则方向键会去切换按钮而非控制游戏
        for btn in self.findChildren(QPushButton):
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.grabKeyboard()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.releaseKeyboard()

    def closeEvent(self, event):
        self.releaseKeyboard()
        super().closeEvent(event)

    def center_on_screen(self):
        try:
            sg = self.screen().availableGeometry() if self.screen() else None
        except Exception:
            sg = None
        if sg is None:
            try:
                from PySide6.QtWidgets import QApplication
                sg = QApplication.primaryScreen().availableGeometry()
            except Exception:
                return
        self.move(
            sg.center().x() - self.width() // 2,
            max(40, sg.center().y() - self.height() // 2 - 30),
        )

    # ------------------------------------------------------------------
    # 开始界面（通用）
    # ------------------------------------------------------------------
    def game_help(self):
        """返回开始界面显示的玩法说明；子类用 HELP_TEXT 提供，无需覆写方法。"""
        return getattr(self, "HELP_TEXT", "（暂无说明）")

    def on_game_start(self):
        """点击「开始游戏」后调用；子类在此启动计时器等。默认无操作。"""
        pass

    def _build_start_page(self):
        layout = QVBoxLayout(self.start_page)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)
        title = QLabel(self._title, self.start_page)
        title.setStyleSheet(
            "color:#d6336c;font-size:18px;font-weight:bold;background:transparent;border:none;"
        )
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        sub = QLabel("— 游戏说明 —", self.start_page)
        sub.setStyleSheet(
            "color:#868e96;font-size:12px;background:transparent;border:none;"
        )
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sub)
        scroll = QScrollArea(self.start_page)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        help_widget = QWidget(scroll)
        hl = QVBoxLayout(help_widget)
        hl.setContentsMargins(6, 6, 6, 6)
        help_label = QLabel(self.game_help(), help_widget)
        help_label.setWordWrap(True)
        help_label.setStyleSheet(
            "color:#495057;font-size:13px;line-height:1.7;background:transparent;border:none;"
        )
        hl.addWidget(help_label)
        scroll.setWidget(help_widget)
        layout.addWidget(scroll, 1)
        start_btn = QPushButton("开始游戏 ▶", self.start_page)
        start_btn.setFixedHeight(46)
        start_btn.setStyleSheet(
            "QPushButton{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 #ff9ec2,stop:1 #ff6b9d);color:#fff;border:none;border-radius:14px;"
            "font-size:16px;font-weight:bold;} QPushButton:hover{background:#ff7aa8;}"
        )
        start_btn.clicked.connect(self._on_start_clicked)
        layout.addWidget(start_btn, alignment=Qt.AlignmentFlag.AlignCenter)

    def _on_start_clicked(self):
        self.stack.setCurrentWidget(self.game_page)
        self.on_game_start()

# --------------------------------------------------------------------------
# 2048
# --------------------------------------------------------------------------
class Game2048(GameWindowBase):
    HELP_TEXT = (
        "方向键或 WASD 移动方块，相同数字相撞即合并。\n"
        "把方块一路凑到 2048 即算取胜；棋盘填满且无法再合并时本局结束。"
    )
    SIZE = 4
    TILE = 78
    COLORS = {
        2: ("#eee4da", "#6b5b4f"),
        4: ("#ede0c8", "#6b5b4f"),
        8: ("#f2b179", "#ffffff"),
        16: ("#f59563", "#ffffff"),
        32: ("#f67c5f", "#ffffff"),
        64: ("#f65e3b", "#ffffff"),
        128: ("#edcf72", "#ffffff"),
        256: ("#edcc61", "#ffffff"),
        512: ("#edc850", "#ffffff"),
        1024: ("#edc53f", "#ffffff"),
        2048: ("#edc22e", "#ffffff"),
    }

    def __init__(self, parent=None):
        super().__init__(parent, title="桌宠 · 2048")
        self.score = 0
        self.best = 0
        self.won = False
        self.over = False
        self.board = [[0] * self.SIZE for _ in range(self.SIZE)]
        self._build_ui()
        self._new_game()

    def _build_ui(self):
        top = QHBoxLayout()
        self.score_label = QLabel("分数 0", self)
        self.score_label.setStyleSheet(
            "color:#d6336c;font-size:13px;font-weight:bold;background:transparent;border:none;"
        )
        top.addWidget(self.score_label)
        top.addStretch(1)
        restart_btn = QPushButton("重开", self)
        restart_btn.setFixedSize(60, 28)
        restart_btn.setStyleSheet(
            "QPushButton{background:#ffd6e7;color:#c2255c;border:1px solid #ff9ec2;"
            "border-radius:10px;font-size:12px;} QPushButton:hover{background:#ffc2d6;}"
        )
        restart_btn.clicked.connect(self._new_game)
        top.addWidget(restart_btn)
        self.body_layout.addLayout(top)

        grid_widget = QWidget(self)
        grid_widget.setStyleSheet(
            "background:#bbada0;border-radius:10px;padding:8px;"
        )
        grid = QGridLayout(grid_widget)
        grid.setSpacing(8)
        self.cells = []
        for r in range(self.SIZE):
            row = []
            for c in range(self.SIZE):
                cell = QLabel("", grid_widget)
                cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cell.setFixedSize(self.TILE, self.TILE)
                grid.addWidget(cell, r, c)
                row.append(cell)
            self.cells.append(row)
        self.body_layout.addWidget(grid_widget, alignment=Qt.AlignmentFlag.AlignCenter)

        self.hint = QLabel("方向键移动，相同数字合并，凑出 2048！", self)
        self.hint.setStyleSheet(HINT_STYLE)
        self.body_layout.addWidget(self.hint)

    def _new_game(self):
        self.score = 0
        self.won = False
        self.over = False
        self.board = [[0] * self.SIZE for _ in range(self.SIZE)]
        self._spawn()
        self._spawn()
        self._render()

    @staticmethod
    def _slide_line(line):
        nums = [v for v in line if v != 0]
        res = []
        gained = 0
        i = 0
        while i < len(nums):
            if i + 1 < len(nums) and nums[i] == nums[i + 1]:
                merged = nums[i] * 2
                res.append(merged)
                gained += merged
                i += 2
            else:
                res.append(nums[i])
                i += 1
        while len(res) < Game2048.SIZE:
            res.append(0)
        return res, gained

    def _move(self, direction):
        if self.over:
            return
        before = [row[:] for row in self.board]
        if direction == 3:  # 左
            for r in range(self.SIZE):
                new, g = self._slide_line(self.board[r])
                self.board[r] = new
                self.score += g
        elif direction == 1:  # 右
            for r in range(self.SIZE):
                new, g = self._slide_line(self.board[r][::-1])
                self.board[r] = new[::-1]
                self.score += g
        elif direction == 0:  # 上
            for c in range(self.SIZE):
                col = [self.board[r][c] for r in range(self.SIZE)]
                new, g = self._slide_line(col)
                for r in range(self.SIZE):
                    self.board[r][c] = new[r]
                self.score += g
        elif direction == 2:  # 下
            for c in range(self.SIZE):
                col = [self.board[r][c] for r in range(self.SIZE)][::-1]
                new, g = self._slide_line(col)
                new = new[::-1]
                for r in range(self.SIZE):
                    self.board[r][c] = new[r]
                self.score += g

        if self.board != before:
            self._spawn()
            self.best = max(self.best, self.score)
            self._render()
            self._check_state()

    def _spawn(self):
        empties = [
            (r, c)
            for r in range(self.SIZE)
            for c in range(self.SIZE)
            if self.board[r][c] == 0
        ]
        if not empties:
            return
        r, c = random.choice(empties)
        self.board[r][c] = 4 if random.random() < 0.1 else 2

    def _check_state(self):
        # 胜利判定
        for r in range(self.SIZE):
            for c in range(self.SIZE):
                if self.board[r][c] == 2048 and not self.won:
                    self.won = True
                    self.hint.setText("达成 2048！可以继续挑战更大数字~")
                    self.game_over.emit(self.score)
        # 失败判定
        empties = any(self.board[r][c] == 0 for r in range(self.SIZE) for c in range(self.SIZE))
        if empties:
            return
        for r in range(self.SIZE):
            for c in range(self.SIZE):
                v = self.board[r][c]
                if c + 1 < self.SIZE and self.board[r][c + 1] == v:
                    return
                if r + 1 < self.SIZE and self.board[r + 1][c] == v:
                    return
        self.over = True
        self.hint.setText("没有可移动的格子啦，游戏结束！点“重开”再来~")
        self.game_over.emit(self.score)

    def _render(self):
        for r in range(self.SIZE):
            for c in range(self.SIZE):
                v = self.board[r][c]
                cell = self.cells[r][c]
                if v == 0:
                    cell.setText("")
                    cell.setStyleSheet(
                        "background:#cdc1b4;border-radius:8px;"
                    )
                else:
                    bg, fg = self.COLORS.get(v, ("#3c3a32", "#ffffff"))
                    cell.setText(str(v))
                    cell.setStyleSheet(
                        f"background:{bg};color:{fg};border-radius:8px;"
                        f"font-size:{26 if v < 1000 else 20}px;font-weight:bold;"
                    )
        self.score_label.setText(f"分数 {self.score}　最高 {self.best}")

    def handle_game_key(self, key):
        if key == Qt.Key.Key_Left:
            self._move(3)
        elif key == Qt.Key.Key_Right:
            self._move(1)
        elif key == Qt.Key.Key_Up:
            self._move(0)
        elif key == Qt.Key.Key_Down:
            self._move(2)
        else:
            return False
        return True

    def keyPressEvent(self, event):
        if self.handle_game_key(event.key()):
            event.accept()
        else:
            super().keyPressEvent(event)


# --------------------------------------------------------------------------
# 推箱子 Sokoban
# --------------------------------------------------------------------------
SOKOBAN_LEVELS = [
        [
            "#######",
            "# ..# #",
            "# $   #",
            "#   $ #",
            "#  $@ #",
            "# .   #",
            "#######",
        ],
        [
            "#######",
            "##  . #",
            "#  $* #",
            "#  $@ #",
            "#   . #",
            "#     #",
            "#######",
        ],
        [
            "#######",
            "#   . #",
            "# $$  #",
            "# #@$ #",
            "#  .. #",
            "#     #",
            "#######",
        ],
        [
            "#######",
            "#   . #",
            "# #$# #",
            "#  @ .#",
            "# $ $ #",
            "#    .#",
            "#######",
        ],
        [
            "########",
            "# ## # #",
            "# . .  #",
            "# $.   #",
            "# #$#  #",
            "# @$  ##",
            "#   #  #",
            "########",
        ],
        [
            "########",
            "# .    #",
            "# $#   #",
            "#  @   #",
            "# $$ # #",
            "# .    #",
            "#.     #",
            "########",
        ],
        [
            "########",
            "#      #",
            "# * #  #",
            "#  # *.#",
            "#      #",
            "#  $@$ #",
            "#  . ###",
            "########",
        ],
        [
            "########",
            "#      #",
            "#   .* #",
            "# $@  ##",
            "# .$ $ #",
            "#      #",
            "#.     #",
            "########",
        ],
        [
            "#########",
            "#       #",
            "# .  .$ #",
            "#   .#  #",
            "# # $@$ #",
            "#  # $  #",
            "##.     #",
            "#     # #",
            "#########",
        ],
        [
            "#########",
            "#   #   #",
            "# $ # . #",
            "#  .  $ #",
            "# . .#@ #",
            "#     $ #",
            "# $  #  #",
            "#      ##",
            "#########",
        ],
        [
            "#########",
            "# #     #",
            "#.   $.##",
            "#       #",
            "#   $@ ##",
            "# #  *  #",
            "# *     #",
            "#       #",
            "#########",
        ],
        [
            "#########",
            "# #     #",
            "#   $ #.#",
            "#       #",
            "### $ $ #",
            "# #  .  #",
            "#   @$  #",
            "#   . . #",
            "#########",
        ],
        [
            "##########",
            "#     #  #",
            "#  # * * #",
            "##    # ##",
            "# $     ##",
            "# .$ # @ #",
            "#      * #",
            "# .      #",
            "# #      #",
            "##########",
        ],
        [
            "##########",
            "#        #",
            "# $  #   #",
            "# .  #  ##",
            "#  * # # #",
            "##      .#",
            "#    @$  #",
            "# $  ### #",
            "# .   .$ #",
            "##########",
        ],
        [
            "##########",
            "#  #  #  #",
            "##  $    #",
            "# $ #    #",
            "# @   #  #",
            "#.   .   #",
            "# $    $ #",
            "#. # $.  #",
            "# #   #. #",
            "##########",
        ],
        [
            "##########",
            "#        #",
            "##       #",
            "#   @### #",
            "#   $ .. #",
            "#     *$*#",
            "#    $   #",
            "#        #",
            "# .      #",
            "##########",
        ],
        [
            "###########",
            "#     #   #",
            "#     #   #",
            "# $       #",
            "# # #     #",
            "#..$    $.#",
            "#         #",
            "#    $@#  #",
            "#$        #",
            "#.#.      #",
            "###########",
        ],
        [
            "###########",
            "#         #",
            "#  ..  .  #",
            "# $   #  ##",
            "#  $    ###",
            "#     #$. #",
            "#    .# $ #",
            "#      #  #",
            "# $   #   #",
            "# @ #  #  #",
            "###########",
        ],
]


class GameSokoban(GameWindowBase):
    HELP_TEXT = (
        "方向键或 WASD 移动桌宠，把箱子📦推到星星⭐上，全部入位即过关。\n"
        "R 键重开本关，Z 键撤销一步。共 18 关，网格与箱子数逐级增加，越往后越需要规划推动顺序。"
    )
    CELL = 38

    def __init__(self, parent=None):
        super().__init__(parent, title="桌宠 · 推箱子")
        self.avatar = self._load_avatar()
        self.level_idx = 0
        self.total_levels = len(SOKOBAN_LEVELS)
        self._build_ui()
        self.load_level(0)

    def _load_avatar(self):
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        for cand in (os.path.join(base, "icon.ico"),
                     os.path.join(os.path.dirname(base), "icon.ico")):
            if os.path.exists(cand):
                return QPixmap(cand)
        return QPixmap()

    def _build_ui(self):
        top = QHBoxLayout()
        self.info_label = QLabel("第 1 关", self)
        self.info_label.setStyleSheet(
            "color:#d6336c;font-size:13px;font-weight:bold;background:transparent;border:none;"
        )
        top.addWidget(self.info_label)
        top.addStretch(1)
        undo_btn = QPushButton("撤销", self)
        undo_btn.setFixedSize(56, 28)
        undo_btn.setStyleSheet(
            "QPushButton{background:#ffe0ec;color:#c2255c;border:1px solid #ff9ec2;"
            "border-radius:10px;font-size:12px;} QPushButton:hover{background:#ffd0e0;}"
        )
        undo_btn.clicked.connect(self._undo)
        top.addWidget(undo_btn)
        restart_btn = QPushButton("重开", self)
        restart_btn.setFixedSize(56, 28)
        restart_btn.setStyleSheet(
            "QPushButton{background:#ffd6e7;color:#c2255c;border:1px solid #ff9ec2;"
            "border-radius:10px;font-size:12px;} QPushButton:hover{background:#ffc2d6;}"
        )
        restart_btn.clicked.connect(lambda: self.load_level(self.level_idx))
        top.addWidget(restart_btn)
        self.body_layout.addLayout(top)

        self.grid_widget = QWidget(self)
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(2)
        self.body_layout.addWidget(self.grid_widget, alignment=Qt.AlignmentFlag.AlignCenter)

        self.hint = QLabel("方向键 / WASD 移动，把箱子📦推到星星⭐上。", self)
        self.hint.setStyleSheet(HINT_STYLE)
        self.body_layout.addWidget(self.hint)

    def load_level(self, idx):
        self.level_idx = idx
        rows = SOKOBAN_LEVELS[idx]
        self.H = len(rows)
        self.W = max(len(r) for r in rows)
        # 格子大小随关卡自适应，保证大关卡也能放进窗口
        self.CELL = max(20, min(38, 460 // max(self.H, self.W)))
        self.walls = set()
        self.targets = set()
        self.boxes = set()
        self.px = self.py = None
        self.undo_stack = []
        self.won = False
        for r, row in enumerate(rows):
            for c, ch in enumerate(row):
                if ch == "#":
                    self.walls.add((r, c))
                if ch in ".+*":
                    self.targets.add((r, c))
                if ch in "$*":
                    self.boxes.add((r, c))
                if ch in "@+":
                    self.px, self.py = r, c
        self.info_label.setText(f"第 {idx + 1} / {self.total_levels} 关")
        self.hint.setText("方向键 / WASD 移动，把箱子📦推到星星⭐上。")
        self._build_cells()
        self._render()

    def _build_cells(self):
        # 重建固定尺寸的格子
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.cell_labels = {}
        for r in range(self.H):
            for c in range(self.W):
                lab = QLabel("", self.grid_widget)
                lab.setFixedSize(self.CELL, self.CELL)
                lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lab.setStyleSheet("border-radius:6px;font-size:18px;")
                self.grid_layout.addWidget(lab, r, c)
                self.cell_labels[(r, c)] = lab

    def _move(self, dx, dy):
        if self.won:
            return
        nx, ny = self.px + dx, self.py + dy
        if (nx, ny) in self.walls:
            return
        if (nx, ny) in self.boxes:
            bx, by = nx + dx, ny + dy
            if (bx, by) in self.walls or (bx, by) in self.boxes:
                return
            # 记录可撤销状态
            self.undo_stack.append((self.px, self.py, set(self.boxes)))
            self.boxes.discard((nx, ny))
            self.boxes.add((bx, by))
            self.px, self.py = nx, ny
        else:
            self.undo_stack.append((self.px, self.py, set(self.boxes)))
            self.px, self.py = nx, ny
        self._render()
        if self._is_solved():
            self._on_solved()

    def _undo(self):
        if self.won or not self.undo_stack:
            return
        self.px, self.py, boxes = self.undo_stack.pop()
        self.boxes = set(boxes)
        self._render()

    def _is_solved(self):
        return self.boxes == self.targets

    def _on_solved(self):
        self.won = True
        if self.level_idx + 1 < self.total_levels:
            self.hint.setText("本关完成！点“下一关”继续~")
            # 自动弹出下一关按钮（复用重开按钮右侧新按钮）
            self._show_next_button()
        else:
            self.hint.setText("全部关卡通关！你真厉害~")
            self.game_over.emit(self.total_levels)

    def _show_next_button(self):
        # 在提示下方临时加一个“下一关”按钮
        if getattr(self, "_next_btn", None) is not None:
            return
        btn = QPushButton("下一关 ▶", self)
        btn.setFixedSize(100, 30)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        btn.setStyleSheet(
            "QPushButton{background:#69db7c;color:#fff;border:none;border-radius:10px;"
            "font-size:13px;font-weight:bold;} QPushButton:hover{background:#51cf66;}"
        )
        btn.clicked.connect(self._next_level)
        self.body_layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)
        self._next_btn = btn

    def _next_level(self):
        if getattr(self, "_next_btn", None) is not None:
            self._next_btn.deleteLater()
            self._next_btn = None
        self.load_level(self.level_idx + 1)

    def _render(self):
        size = max(12, self.CELL - 4)
        for (r, c), lab in self.cell_labels.items():
            lab.setText("")
            lab.setPixmap(QPixmap())
            if (r, c) in self.walls:
                lab.setStyleSheet("background:#8d6e8f;border-radius:6px;")
            elif (r, c) == (self.px, self.py):
                # 角色永远优先绘制，避免被目标点盖住；站在目标上时用琥珀底色提示
                if self.avatar.isNull():
                    lab.setText("🦊")
                else:
                    lab.setPixmap(self.avatar.scaled(
                        size, size, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation))
                if (r, c) in self.targets:
                    lab.setStyleSheet("background:#ffe08a;border-radius:6px;")
                else:
                    lab.setStyleSheet("background:#fff0f6;border-radius:6px;")
            elif (r, c) in self.targets:
                if (r, c) in self.boxes:
                    lab.setText("✅")
                    lab.setStyleSheet("background:#ffd6e7;border-radius:6px;")
                else:
                    lab.setText("⭐")
                    lab.setStyleSheet("background:#ffe3ef;border-radius:6px;")
            elif (r, c) in self.boxes:
                lab.setText("📦")
                lab.setStyleSheet("background:#ffc2d6;border-radius:6px;")
            else:
                lab.setStyleSheet("background:#fff0f6;border-radius:6px;")

    def handle_game_key(self, key):
        moves = {
            Qt.Key.Key_Left: (0, -1),
            Qt.Key.Key_Right: (0, 1),
            Qt.Key.Key_Up: (-1, 0),
            Qt.Key.Key_Down: (1, 0),
            Qt.Key.Key_A: (0, -1),
            Qt.Key.Key_D: (0, 1),
            Qt.Key.Key_W: (-1, 0),
            Qt.Key.Key_S: (1, 0),
        }
        if key in moves:
            self._move(*moves[key])
            return True
        if key == Qt.Key.Key_R:
            self.load_level(self.level_idx)
            return True
        if key == Qt.Key.Key_Z:
            self._undo()
            return True
        return False

    def keyPressEvent(self, event):
        if self.handle_game_key(event.key()):
            event.accept()
        else:
            super().keyPressEvent(event)


# --------------------------------------------------------------------------
# 贪吃蛇 Snake
# --------------------------------------------------------------------------
class SnakeBoard(QWidget):
    def __init__(self, n=20, cell=18):
        super().__init__()
        self.n = n
        self.cell = cell
        self.setFixedSize(n * cell, n * cell)
        self.snake = []
        self.food = None
        self.setStyleSheet("background:#fff0f6;border-radius:8px;")

    def set_state(self, snake, food):
        self.snake = snake
        self.food = food
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#fff0f6"))
        p.setPen(QPen(QColor("#ffe0ec"), 1))
        for i in range(self.n + 1):
            p.drawLine(i * self.cell, 0, i * self.cell, self.n * self.cell)
            p.drawLine(0, i * self.cell, self.n * self.cell, i * self.cell)
        if self.food:
            fx, fy = self.food
            p.setBrush(QColor("#ff6b6b"))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(fx * self.cell + 2, fy * self.cell + 2, self.cell - 4, self.cell - 4)
        p.setBrush(QColor("#d6336c"))
        p.setPen(Qt.PenStyle.NoPen)
        for sx, sy in self.snake:
            p.drawRoundedRect(
                sx * self.cell + 1, sy * self.cell + 1, self.cell - 2, self.cell - 2, 4, 4
            )
        if self.snake:
            hx, hy = self.snake[0]
            p.setBrush(QColor("#a61e4d"))
            p.drawRoundedRect(
                hx * self.cell + 1, hy * self.cell + 1, self.cell - 2, self.cell - 2, 4, 4
            )
        p.end()


class GameSnake(GameWindowBase):
    HELP_TEXT = (
        "方向键控制桌宠小蛇移动，吃到🍎会变长，每吃一个略微加速。\n"
        "撞到墙或咬到自己就结束。空格键可随时暂停 / 继续。"
    )
    N = 20
    CELL = 18
    SPEED_START = 240

    def __init__(self, parent=None):
        super().__init__(parent, title="桌宠 · 贪吃蛇")
        self.alive = True
        self.score = 0
        self.speed = self.SPEED_START
        self.snake = [(self.N // 2, self.N // 2)]
        self.dir = (0, -1)
        self.food = None
        self._build_ui()
        self._new_food()
        self.board.set_state(self.snake, self.food)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)

    def _build_ui(self):
        top = QHBoxLayout()
        self.score_label = QLabel("长度 1", self)
        self.score_label.setStyleSheet(
            "color:#d6336c;font-size:13px;font-weight:bold;background:transparent;border:none;"
        )
        top.addWidget(self.score_label)
        top.addStretch(1)
        restart_btn = QPushButton("重开", self)
        restart_btn.setFixedSize(60, 28)
        restart_btn.setStyleSheet(
            "QPushButton{background:#ffd6e7;color:#c2255c;border:1px solid #ff9ec2;"
            "border-radius:10px;font-size:12px;} QPushButton:hover{background:#ffc2d6;}"
        )
        restart_btn.clicked.connect(self._restart)
        top.addWidget(restart_btn)
        self.body_layout.addLayout(top)

        self.board = SnakeBoard(self.N, self.CELL)
        self.body_layout.addWidget(self.board, alignment=Qt.AlignmentFlag.AlignCenter)

        self.hint = QLabel("方向键控制移动，吃到🍎变长，别撞墙也别咬到自己~", self)
        self.hint.setStyleSheet(HINT_STYLE)
        self.body_layout.addWidget(self.hint)

    def _new_food(self):
        occupied = set(self.snake)
        empties = [
            (r, c)
            for r in range(self.N)
            for c in range(self.N)
            if (r, c) not in occupied
        ]
        self.food = random.choice(empties) if empties else None

    def _tick(self):
        if not self.alive:
            return
        head = self.snake[0]
        nx, ny = head[0] + self.dir[0], head[1] + self.dir[1]
        # 撞墙
        if not (0 <= nx < self.N and 0 <= ny < self.N):
            self._die()
            return
        will_eat = (nx, ny) == self.food
        # 撞自己（吃到时尾巴不缩，需检查整条；否则检查除尾外的身体）
        body = self.snake if will_eat else self.snake[:-1]
        if (nx, ny) in body:
            self._die()
            return
        new_head = (nx, ny)
        if will_eat:
            self.snake.insert(0, new_head)
            self.score += 1
            self._new_food()
            # 略微加速（但保持可玩，最低不低于 150ms）
            self.speed = max(150, self.speed - 4)
            self.timer.setInterval(self.speed)
        else:
            self.snake = [new_head] + self.snake[:-1]
        self.board.set_state(self.snake, self.food)
        self.score_label.setText(f"长度 {len(self.snake)}")

    def _die(self):
        self.alive = False
        self.timer.stop()
        self.hint.setText(f"游戏结束！最终长度 {len(self.snake)}，点“重开”再战~")
        self.game_over.emit(len(self.snake))

    def _restart(self):
        self.alive = True
        self.score = 0
        self.speed = self.SPEED_START
        self.snake = [(self.N // 2, self.N // 2)]
        self.dir = (0, -1)
        self._new_food()
        self.board.set_state(self.snake, self.food)
        self.hint.setText("方向键控制移动，吃到🍎变长，别撞墙也别咬到自己~")
        self.score_label.setText(f"长度 {len(self.snake)}")
        self.timer.start(self.speed)

    def _toggle_pause(self):
        if not self.alive:
            return
        if self.timer.isActive():
            self.timer.stop()
            self.hint.setText("已暂停，按空格继续~")
        else:
            self.timer.start(self.speed)
            self.hint.setText("方向键控制移动，吃到🍎变长，别撞墙也别咬到自己~")

    def on_game_start(self):
        if not self.timer.isActive():
            self.timer.start(self.speed)

    def handle_game_key(self, key):
        if key == Qt.Key.Key_Space:
            self._toggle_pause()
            return True
        if not self.alive:
            return False
        # 注意：蛇坐标约定为 (x, y)，x=横向、y=纵向
        moves = {
            Qt.Key.Key_Left: (-1, 0),
            Qt.Key.Key_Right: (1, 0),
            Qt.Key.Key_Up: (0, -1),
            Qt.Key.Key_Down: (0, 1),
        }
        new_dir = moves.get(key)
        if new_dir is not None:
            # 禁止反向（长度>1 时）
            if self.snake and new_dir == (-self.dir[0], -self.dir[1]) and len(self.snake) > 1:
                return True  # 反向无效，但消费该按键
            self.dir = new_dir
            return True
        return False

    def keyPressEvent(self, event):
        if self.handle_game_key(event.key()):
            event.accept()
        else:
            super().keyPressEvent(event)


# --------------------------------------------------------------------------
# 石头剪刀布（窗口版）
# --------------------------------------------------------------------------
class GameRPS(GameWindowBase):
    HELP_TEXT = (
        "点击 🪨石头 / ✂️剪刀 / 📄布 出拳，和桌宠实时对战。\n"
        "赢一局心情 +2、好感 +1；输一局心情 +1。比拼战绩与连胜吧~"
    )
    """窗口版石头剪刀布：点按钮出拳，与心情/好感轻度联动。"""

    CHOICES = [("🪨 石头", "石头"), ("✂️ 剪刀", "剪刀"), ("📄 布", "布")]
    EMOJI = {"石头": "🪨", "剪刀": "✂️", "布": "📄"}
    BEATS = {"石头": "剪刀", "剪刀": "布", "布": "石头"}

    def __init__(self, parent=None, on_round=None):
        super().__init__(parent, title="桌宠 · 石头剪刀布")
        self.on_round = on_round
        self.wins = self.losses = self.draws = 0
        self.streak = 0
        self.best_streak = 0
        self._build_ui()

    def _build_ui(self):
        self.score_label = QLabel("战绩  你 0 · 桌宠 0 · 平 0", self)
        self.score_label.setStyleSheet(
            "color:#d6336c;font-size:13px;font-weight:bold;background:transparent;border:none;"
        )
        self.body_layout.addWidget(self.score_label)

        self.arena = QLabel("选一个出吧！", self)
        self.arena.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.arena.setStyleSheet(
            "background:#fff0f6;border-radius:12px;color:#a61e4d;"
            "font-size:15px;padding:18px;min-height:64px;"
        )
        self.body_layout.addWidget(self.arena)

        row = QHBoxLayout()
        row.setSpacing(10)
        for label, choice in self.CHOICES:
            btn = QPushButton(label, self)
            btn.setFixedSize(108, 44)
            btn.setStyleSheet(
                "QPushButton{background:#ffd6e7;color:#c2255c;border:1px solid #ff9ec2;"
                "border-radius:12px;font-size:14px;font-weight:bold;}"
                "QPushButton:hover{background:#ffc2d6;}"
            )
            btn.clicked.connect(lambda checked, c=choice: self._play(c))
            row.addWidget(btn)
        self.body_layout.addLayout(row)

        self.hint = QLabel("点按钮出拳，赢了桌宠心情+2、好感+1~", self)
        self.hint.setStyleSheet(HINT_STYLE)
        self.body_layout.addWidget(self.hint)

    def _play(self, user):
        pet = random.choice([c[1] for c in self.CHOICES])
        if user == pet:
            res = "平局"
            self.draws += 1
            self.streak = 0
        elif self.BEATS[user] == pet:
            res = "你赢"
            self.wins += 1
            self.streak += 1
            self.best_streak = max(self.best_streak, self.streak)
        else:
            res = "桌宠赢"
            self.losses += 1
            self.streak = 0
        self.arena.setText(f"你 {self.EMOJI[user]}  VS  {self.EMOJI[pet]} 桌宠\n→ {res}！")
        self.score_label.setText(
            f"战绩  你 {self.wins} · 桌宠 {self.losses} · 平 {self.draws}（连胜 {self.streak}）"
        )
        if self.on_round is not None:
            self.on_round(res, user, pet)


# --------------------------------------------------------------------------
# 扫雷
# --------------------------------------------------------------------------
class MineCell(QLabel):
    leftClicked = Signal(int, int)
    rightClicked = Signal(int, int)

    def __init__(self, r, c, parent=None):
        super().__init__(parent)
        self.r, self.c = r, c
        self.setFixedSize(26, 26)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            "border:1px solid #f0b8d4;border-radius:4px;background:#ffe3ef;"
            "font-size:14px;font-weight:bold;"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.rightClicked.emit(self.r, self.c)
        else:
            self.leftClicked.emit(self.r, self.c)
        super().mousePressEvent(event)


class GameMinesweeper(GameWindowBase):
    HELP_TEXT = (
        "左键翻开格子，右键插旗🚩标记疑似地雷。数字表示周围 8 格的雷数。\n"
        "窗口内可切换三档难度：初级 9×9/10 雷、中级 16×16/40 雷、高级 16×30/99 雷。找出全部地雷即获胜。"
    )
    DIFF = {
        "初级": (9, 9, 10),
        "中级": (16, 16, 40),
        "高级": (16, 30, 99),
    }

    def __init__(self, parent=None, difficulty="初级"):
        super().__init__(parent, title="桌宠 · 扫雷")
        self.difficulty = difficulty
        self.rows, self.cols, self.mines = self.DIFF[difficulty]
        self.over = False
        self.won = False
        self.revealed = set()
        self.flags = set()
        self._build_ui()
        self._new_game()

    def _build_ui(self):
        top = QHBoxLayout()
        self.info_label = QLabel("", self)
        self.info_label.setStyleSheet(
            "color:#d6336c;font-size:13px;font-weight:bold;background:transparent;border:none;"
        )
        top.addWidget(self.info_label)
        top.addStretch(1)
        restart_btn = QPushButton("重开", self)
        restart_btn.setFixedSize(56, 26)
        restart_btn.setStyleSheet(
            "QPushButton{background:#ffd6e7;color:#c2255c;border:1px solid #ff9ec2;"
            "border-radius:10px;font-size:12px;} QPushButton:hover{background:#ffc2d6;}"
        )
        restart_btn.clicked.connect(self._new_game)
        top.addWidget(restart_btn)
        self.body_layout.addLayout(top)

        diff_row = QHBoxLayout()
        diff_row.addStretch(1)
        self.diff_btns = {}
        for name in self.DIFF:
            b = QPushButton(name, self)
            b.setFixedSize(64, 26)
            b.setCheckable(True)
            b.setStyleSheet(
                "QPushButton{background:#ffe3ef;color:#c2255c;border:1px solid #ff9ec2;"
                "border-radius:10px;font-size:12px;} QPushButton:hover{background:#ffd0e0;}"
                " QPushButton:checked{background:#ff9ec2;color:#fff;}"
            )
            b.clicked.connect(lambda checked, n=name: self._set_difficulty(n))
            diff_row.addWidget(b)
            self.diff_btns[name] = b
        diff_row.addStretch(1)
        self.body_layout.addLayout(diff_row)
        self.diff_btns[self.difficulty].setChecked(True)

        self.grid_widget = QWidget(self)
        self.grid_layout = QGridLayout(self.grid_widget)
        self.grid_layout.setSpacing(2)
        self.cells = {}
        self.body_layout.addWidget(self.grid_widget, alignment=Qt.AlignmentFlag.AlignCenter)

        self.hint = QLabel("左键翻开，右键插旗🚩，找出全部地雷~", self)
        self.hint.setStyleSheet(HINT_STYLE)
        self.body_layout.addWidget(self.hint)
        self._build_board()

    def _set_difficulty(self, name):
        if name == self.difficulty and self.cells:
            return
        self.difficulty = name
        for n, b in self.diff_btns.items():
            b.setChecked(n == name)
        self.rows, self.cols, self.mines = self.DIFF[name]
        self._build_board()
        self._new_game()

    def _build_board(self):
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.cells = {}
        cell = 24 if self.cols <= 16 else 20
        for r in range(self.rows):
            for c in range(self.cols):
                cw = MineCell(r, c, self.grid_widget)
                cw.setFixedSize(cell, cell)
                cw.leftClicked.connect(self._reveal)
                cw.rightClicked.connect(self._toggle_flag)
                self.grid_layout.addWidget(cw, r, c)
                self.cells[(r, c)] = cw
        board_w = self.cols * (cell + 2)
        board_h = self.rows * (cell + 2)
        self.resize(max(360, board_w + 44), board_h + 150)
        self.center_on_screen()

    def _new_game(self):
        self.over = False
        self.won = False
        self.revealed = set()
        self.flags = set()
        positions = [(r, c) for r in range(self.rows) for c in range(self.cols)]
        mine_set = set(random.sample(positions, self.mines))
        self.mines_set = mine_set
        self.counts = {}
        for (r, c) in positions:
            if (r, c) in mine_set:
                self.counts[(r, c)] = -1
                continue
            n = 0
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    if (r + dr, c + dc) in mine_set:
                        n += 1
            self.counts[(r, c)] = n
        self.info_label.setText("💣 %d" % self.mines)
        self._render()

    def _reveal(self, r, c):
        if self.over or (r, c) in self.revealed or (r, c) in self.flags:
            return
        if (r, c) in self.mines_set:
            self._lose(r, c)
            return
        stack = [(r, c)]
        while stack:
            cr, cc = stack.pop()
            if (cr, cc) in self.revealed or (cr, cc) in self.flags:
                continue
            self.revealed.add((cr, cc))
            if self.counts[(cr, cc)] == 0:
                for dr in (-1, 0, 1):
                    for dc in (-1, 0, 1):
                        nr, nc = cr + dr, cc + dc
                        if 0 <= nr < self.rows and 0 <= nc < self.cols:
                            if (nr, nc) not in self.revealed and (nr, nc) not in self.mines_set:
                                stack.append((nr, nc))
        self._check_win()
        self._render()

    def _toggle_flag(self, r, c):
        if self.over or (r, c) in self.revealed:
            return
        if (r, c) in self.flags:
            self.flags.discard((r, c))
        else:
            self.flags.add((r, c))
        self.info_label.setText("💣 %d" % (self.mines - len(self.flags)))
        self._render()

    def _lose(self, r, c):
        self.over = True
        self.revealed.add((r, c))
        self.hint.setText("踩到地雷啦！点“重开”再来~")
        self._render()

    def _check_win(self):
        if len(self.revealed) == self.rows * self.cols - self.mines:
            self.over = True
            self.won = True
            self.flags = set(self.mines_set)
            self.hint.setText("全部找出啦，你真厉害！")
            self._render()
            self.game_over.emit(self.mines)

    def _render(self):
        num_colors = {
            1: "#1971c2", 2: "#2f9e44", 3: "#e03131", 4: "#6741d9",
            5: "#a61e4d", 6: "#0c8599", 7: "#343a40", 8: "#868e96",
        }
        for (r, c), cell in self.cells.items():
            if (r, c) in self.revealed:
                if (r, c) in self.mines_set:
                    cell.setText("💣")
                    cell.setStyleSheet(
                        "border:1px solid #f0b8d4;border-radius:4px;background:#ffc9c9;"
                    )
                else:
                    n = self.counts[(r, c)]
                    cell.setText("" if n == 0 else str(n))
                    cell.setStyleSheet(
                        "border:1px solid #f5c9de;border-radius:4px;background:#fff5fa;"
                        "color:%s;font-size:14px;font-weight:bold;" % num_colors.get(n, "#343a40")
                    )
            elif (r, c) in self.flags:
                cell.setText("🚩")
                cell.setStyleSheet(
                    "border:1px solid #f0b8d4;border-radius:4px;background:#ffe3ef;font-size:14px;"
                )
            else:
                cell.setText("")
                cell.setStyleSheet(
                    "border:1px solid #f0b8d4;border-radius:4px;background:#ffe3ef;font-size:14px;"
                )


def launch_game(kind: str, parent=None, on_game_over=None, **kwargs):
    """按类型启动对应小游戏窗口。

    kind: "2048" / "sokoban" / "snake" / "rps" / "minesweeper" / "tetris" / "gomoku"
    on_game_over: 可选回调，签名 (score:int) -> None，游戏结束时触发。
    kwargs: 透传给具体游戏构造（如 rps 的 on_round）。
    """
    mapping = {
        "2048": Game2048,
        "sokoban": GameSokoban,
        "snake": GameSnake,
        "rps": GameRPS,
        "minesweeper": GameMinesweeper,
        "tetris": GameTetris,
        "gomoku": GameGomoku,
    }
    cls = mapping.get(kind)
    if cls is None:
        return None
    win = cls(parent, **kwargs)
    if on_game_over is not None:
        win.game_over.connect(on_game_over)
    win.center_on_screen()
    win.show()
    win.activateWindow()
    win.setFocus()
    return win

# --------------------------------------------------------------------------
# 俄罗斯方块 Tetris
# --------------------------------------------------------------------------
class TetrisBoard(QWidget):
    def __init__(self, rows, cols, cell, parent=None):
        super().__init__(parent)
        self.rows = rows
        self.cols = cols
        self.cell = cell
        self.setFixedSize(cols * cell, rows * cell)
        self.board = [[0] * cols for _ in range(rows)]
        self.cur = None  # (mat, row, col, color)
        self.setStyleSheet("background:#fff0f6;border-radius:8px;")

    def set_state(self, board, cur):
        self.board = board
        self.cur = cur
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#fff0f6"))
        # 网格
        p.setPen(QPen(QColor("#ffe0ec"), 1))
        for r in range(self.rows + 1):
            p.drawLine(0, r * self.cell, self.cols * self.cell, r * self.cell)
        for c in range(self.cols + 1):
            p.drawLine(c * self.cell, 0, c * self.cell, self.rows * self.cell)
        # 已落定方块
        for r in range(self.rows):
            for c in range(self.cols):
                v = self.board[r][c]
                if v:
                    self._draw(p, r, c, TET_COLORS[v])
        # 当前下落方块
        if self.cur:
            mat, row, col, color = self.cur
            for r, line in enumerate(mat):
                for c, ch in enumerate(line):
                    if ch == "X":
                        br, bc = row + r, col + c
                        if br >= 0:
                            self._draw(p, br, bc, TET_COLORS[color])
        p.end()

    def _draw(self, p, r, c, color):
        x = c * self.cell + 1
        y = r * self.cell + 1
        s = self.cell - 2
        p.fillRect(x, y, s, s, QColor(color))
        p.setPen(QPen(QColor("#ffffff"), 1))
        p.drawRect(x, y, s, s)


class GameTetris(GameWindowBase):
    HELP_TEXT = (
        "←→ 左右移动，↑ 旋转，↓ 软降（加速下落），空格 硬降（直接落底）。\n"
        "方块落地后若填满整行即消除并得分，随等级提升逐渐加速。"
    )
    COLS = 10
    ROWS = 20
    CELL = 22
    # 每个方块的基础形状（4x4/3x3/2x2），X 表示实心
    BASE = {
        "I": ["....", "XXXX", "....", "...."],
        "O": ["XX", "XX"],
        "T": [".X.", "XXX", "..."],
        "S": [".XX", "XX.", "..."],
        "Z": ["XX.", ".XX", "..."],
        "J": ["X..", "XXX", "..."],
        "L": ["..X", "XXX", "..."],
    }
    NAMES = list(BASE.keys())

    def __init__(self, parent=None):
        super().__init__(parent, title="桌宠 · 俄罗斯方块")
        self.board = [[0] * self.COLS for _ in range(self.ROWS)]
        self.score = 0
        self.lines = 0
        self.level = 1
        self.over = False
        self.next_name = random.choice(self.NAMES)
        self._build_ui()
        self._spawn()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.resize(440, 620)
        self.center_on_screen()

    def _interval(self):
        return max(120, 500 - (self.level - 1) * 40)

    @staticmethod
    def _rotations(mat):
        rots = []
        seen = set()
        m = mat
        for _ in range(4):
            key = tuple(m)
            if key not in seen:
                seen.add(key)
                rots.append(m)
            n = len(m)
            m = ["".join(m[n - 1 - c][r] for c in range(n)) for r in range(n)]
        return rots

    def _build_ui(self):
        top = QHBoxLayout()
        self.score_label = QLabel("得分 0", self)
        self.score_label.setStyleSheet(
            "color:#d6336c;font-size:13px;font-weight:bold;background:transparent;border:none;"
        )
        top.addWidget(self.score_label)
        top.addStretch(1)
        restart_btn = QPushButton("重开", self)
        restart_btn.setFixedSize(56, 28)
        restart_btn.setStyleSheet(
            "QPushButton{background:#ffd6e7;color:#c2255c;border:1px solid #ff9ec2;"
            "border-radius:10px;font-size:12px;} QPushButton:hover{background:#ffc2d6;}"
        )
        restart_btn.clicked.connect(self._restart)
        top.addWidget(restart_btn)
        self.body_layout.addLayout(top)

        mid = QHBoxLayout()
        self.board_w = TetrisBoard(self.ROWS, self.COLS, self.CELL, self)
        mid.addWidget(self.board_w, alignment=Qt.AlignmentFlag.AlignCenter)

        side = QVBoxLayout()
        side.addWidget(QLabel("下一个", self))
        self.next_w = TetrisBoard(4, 4, 18, self)
        self.next_w.setFixedSize(4 * 18, 4 * 18)
        side.addWidget(self.next_w, alignment=Qt.AlignmentFlag.AlignCenter)
        self.level_label = QLabel("等级 1", self)
        self.level_label.setStyleSheet("color:#868e96;font-size:12px;background:transparent;border:none;")
        side.addWidget(self.level_label)
        side.addStretch(1)
        self.hint = QLabel("←→移动   ↑旋转\n↓软降   空格硬降", self)
        self.hint.setStyleSheet(HINT_STYLE)
        side.addWidget(self.hint)
        mid.addLayout(side)
        self.body_layout.addLayout(mid)

    def _spawn(self):
        name = self.next_name
        self.next_name = random.choice(self.NAMES)
        rots = self._rotations(self.BASE[name])
        mat = rots[0]
        top = min(r for r, line in enumerate(mat) if "X" in line)
        row = -top
        col = (self.COLS - len(mat[0])) // 2
        color = self.NAMES.index(name) + 1
        if self._collide(mat, row, col):
            self._game_over()
            return
        self.cur = {"mat": mat, "row": row, "col": col, "color": color, "rots": rots, "ri": 0}
        self._draw_next()

    def _draw_next(self):
        mat = self._rotations(self.BASE[self.next_name])[0]
        nb = [[0] * 4 for _ in range(4)]
        off = (4 - len(mat[0])) // 2
        for r, line in enumerate(mat):
            for c, ch in enumerate(line):
                if ch == "X":
                    nb[r][c + off] = self.NAMES.index(self.next_name) + 1
        self.next_w.set_state(nb, None)

    def _collide(self, mat, row, col):
        for r, line in enumerate(mat):
            for c, ch in enumerate(line):
                if ch != "X":
                    continue
                br, bc = row + r, col + c
                if bc < 0 or bc >= self.COLS or br >= self.ROWS:
                    return True
                if br >= 0 and self.board[br][bc] != 0:
                    return True
        return False

    def _lock(self):
        mat = self.cur["mat"]
        row, col, color = self.cur["row"], self.cur["col"], self.cur["color"]
        for r, line in enumerate(mat):
            for c, ch in enumerate(line):
                if ch == "X":
                    br, bc = row + r, col + c
                    if br < 0:
                        self._game_over()
                        return
                    self.board[br][bc] = color
        self._clear_lines()
        self._spawn()

    def _clear_lines(self):
        cleared = 0
        new_board = []
        for r in range(self.ROWS):
            if all(v != 0 for v in self.board[r]):
                cleared += 1
            else:
                new_board.append(self.board[r])
        for _ in range(cleared):
            new_board.insert(0, [0] * self.COLS)
        self.board = new_board
        if cleared:
            self.lines += cleared
            self.score += cleared * 100 * self.level
            self.level = 1 + self.lines // 10
            self.level_label.setText(f"等级 {self.level}")
        self.score_label.setText(f"得分 {self.score}")

    def _tick(self):
        if self.over:
            return
        if self._collide(self.cur["mat"], self.cur["row"] + 1, self.cur["col"]):
            self._lock()
        else:
            self.cur["row"] += 1
        self._render()

    def _render(self):
        cur = (self.cur["mat"], self.cur["row"], self.cur["col"], self.cur["color"]) if self.cur else None
        self.board_w.set_state(self.board, cur)

    def _move(self, dr, dc):
        if self.over or not self.cur:
            return
        if not self._collide(self.cur["mat"], self.cur["row"] + dr, self.cur["col"] + dc):
            self.cur["row"] += dr
            self.cur["col"] += dc
            self._render()

    def _rotate(self):
        if self.over or not self.cur:
            return
        rots = self.cur["rots"]
        ri = (self.cur["ri"] + 1) % len(rots)
        mat = rots[ri]
        for dc in (0, -1, 1, -2, 2):
            if not self._collide(mat, self.cur["row"], self.cur["col"] + dc):
                self.cur["mat"] = mat
                self.cur["ri"] = ri
                self.cur["col"] += dc
                self._render()
                return

    def _hard_drop(self):
        if self.over or not self.cur:
            return
        while not self._collide(self.cur["mat"], self.cur["row"] + 1, self.cur["col"]):
            self.cur["row"] += 1
        self._lock()
        self._render()

    def _game_over(self):
        self.over = True
        self.timer.stop()
        self.hint.setText(f"游戏结束！得分 {self.score}，点“重开”再战~")
        self.game_over.emit(self.score)

    def _restart(self):
        self.board = [[0] * self.COLS for _ in range(self.ROWS)]
        self.score = 0
        self.lines = 0
        self.level = 1
        self.over = False
        self.score_label.setText("得分 0")
        self.level_label.setText("等级 1")
        self.hint.setText("←→移动   ↑旋转\n↓软降   空格硬降")
        self.next_name = random.choice(self.NAMES)
        self._spawn()
        self.timer.start(self._interval())
        self._render()

    def on_game_start(self):
        if not self.timer.isActive():
            self.timer.start(self._interval())

    def handle_game_key(self, key):
        if self.over:
            return False
        if key == Qt.Key.Key_Left:
            self._move(0, -1); return True
        if key == Qt.Key.Key_Right:
            self._move(0, 1); return True
        if key == Qt.Key.Key_Down:
            self._move(1, 0); return True
        if key == Qt.Key.Key_Up:
            self._rotate(); return True
        if key == Qt.Key.Key_Space:
            self._hard_drop(); return True
        return False

    def keyPressEvent(self, event):
        if self.handle_game_key(event.key()):
            event.accept()
        else:
            super().keyPressEvent(event)


# --------------------------------------------------------------------------
# 五子棋 Gomoku
# --------------------------------------------------------------------------
class GomokuBoard(QWidget):
    cellClicked = Signal(int, int)

    def __init__(self, size, cell, parent=None):
        super().__init__(parent)
        self.size = size
        self.cell = cell
        self.setFixedSize(size * cell, size * cell)
        self.board = [[0] * size for _ in range(size)]  # 0空 1黑 2白
        self.last = None
        self.setStyleSheet("background:#fff8e6;border-radius:6px;")

    def set_board(self, board, last=None):
        self.board = board
        self.last = last
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#fff8e6"))
        s = self.size
        c = self.cell
        p.setPen(QPen(QColor("#caa472"), 1))
        for i in range(s):
            p.drawLine(c // 2 + i * c, c // 2, c // 2 + i * c, c // 2 + (s - 1) * c)
            p.drawLine(c // 2, c // 2 + i * c, c // 2 + (s - 1) * c, c // 2 + i * c)
        for r in range(s):
            for cc in range(s):
                v = self.board[r][cc]
                if v:
                    x = c // 2 + cc * c - c // 2 + 1
                    y = c // 2 + r * c - c // 2 + 1
                    cx, cy = c // 2 + cc * c, c // 2 + r * c
                    if v == 1:
                        p.setBrush(QColor("#2b2b2b"))
                    else:
                        p.setBrush(QColor("#f1f3f5"))
                    p.setPen(QPen(QColor("#868e96"), 1))
                    p.drawEllipse(cx - c // 2 + 2, cy - c // 2 + 2, c - 4, c - 4)
        if self.last:
            lr, lc = self.last
            cx, cy = c // 2 + lc * c, c // 2 + lr * c
            p.setPen(QPen(QColor("#e03131"), 2))
            p.drawEllipse(cx - 4, cy - 4, 8, 8)
        p.end()

    def mousePressEvent(self, event):
        x, y = event.position().x(), event.position().y()
        c = self.cell
        col = round((x - c // 2) / c)
        row = round((y - c // 2) / c)
        if 0 <= row < self.size and 0 <= col < self.size:
            self.cellClicked.emit(row, col)
        super().mousePressEvent(event)


class GameGomoku(GameWindowBase):
    HELP_TEXT = (
        "你执黑（●）先手，桌宠执白（○）。鼠标点击交叉点落子，\n"
        "横 / 竖 / 斜任意方向先连成 5 子者获胜。红圈标记最近一手棋。"
    )
    SIZE = 15
    CELL = 30

    def __init__(self, parent=None):
        super().__init__(parent, title="桌宠 · 五子棋")
        self.board = [[0] * self.SIZE for _ in range(self.SIZE)]
        self.over = False
        self.winner = 0
        self.last_move = None
        self._build_ui()
        self.resize(500, 560)
        self.center_on_screen()

    def _build_ui(self):
        top = QHBoxLayout()
        self.info_label = QLabel("你执黑（●），桌宠执白（○）", self)
        self.info_label.setStyleSheet(
            "color:#d6336c;font-size:13px;font-weight:bold;background:transparent;border:none;"
        )
        top.addWidget(self.info_label)
        top.addStretch(1)
        restart_btn = QPushButton("重开", self)
        restart_btn.setFixedSize(56, 28)
        restart_btn.setStyleSheet(
            "QPushButton{background:#ffd6e7;color:#c2255c;border:1px solid #ff9ec2;"
            "border-radius:10px;font-size:12px;} QPushButton:hover{background:#ffc2d6;}"
        )
        restart_btn.clicked.connect(self._restart)
        top.addWidget(restart_btn)
        self.body_layout.addLayout(top)

        self.board_w = GomokuBoard(self.SIZE, self.CELL, self)
        self.board_w.cellClicked.connect(self._on_click)
        self.body_layout.addWidget(self.board_w, alignment=Qt.AlignmentFlag.AlignCenter)

        self.hint = QLabel("点交叉点落子，先连成五子者胜~", self)
        self.hint.setStyleSheet(HINT_STYLE)
        self.body_layout.addWidget(self.hint)

    def _on_click(self, r, c):
        if self.over or self.board[r][c] != 0:
            return
        self.board[r][c] = 1
        self.last_move = (r, c)
        self._render()
        if self._check_win(r, c, 1):
            self._finish(1)
            return
        # AI 落子
        ar, ac = self._ai_move()
        if ar is not None:
            self.board[ar][ac] = 2
            self.last_move = (ar, ac)
            self._render()
            if self._check_win(ar, ac, 2):
                self._finish(2)
                return

    def _finish(self, winner):
        self.over = True
        self.winner = winner
        if winner == 1:
            self.hint.setText("你赢了！桌宠甘拜下风~ 红圈处即制胜一手")
        else:
            self.hint.setText("桌宠连成五子，你输啦~ 再来一局？")
        # 先让最后一手（含红圈）渲染出来，稍后再触发结束回调关闭窗口
        t = QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(lambda: self.game_over.emit(winner))
        t.start(1000)

    def _render(self):
        self.board_w.set_board(self.board, self.last_move)

    def _restart(self):
        self.board = [[0] * self.SIZE for _ in range(self.SIZE)]
        self.over = False
        self.winner = 0
        self.last_move = None
        self.hint.setText("点交叉点落子，先连成五子者胜~")
        self._render()

    def _check_win(self, r, c, player):
        for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
            cnt = 1
            for s in (1, -1):
                nr, nc = r + dr * s, c + dc * s
                while 0 <= nr < self.SIZE and 0 <= nc < self.SIZE and self.board[nr][nc] == player:
                    cnt += 1
                    nr += dr * s
                    nc += dc * s
            if cnt >= 5:
                return True
        return False

    def _score_line(self, r, c, player):
        total = 0
        for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
            seq = []
            for s in range(-4, 5):
                nr, nc = r + dr * s, c + dc * s
                if 0 <= nr < self.SIZE and 0 <= nc < self.SIZE:
                    if s == 0:
                        # 目标格若为空，视作已落子
                        v = 1 if self.board[nr][nc] == 0 else (1 if self.board[nr][nc] == player else 0)
                    else:
                        v = 1 if self.board[nr][nc] == player else 0
                    seq.append(v)
                else:
                    seq.append(0)
            best = 0
            run = 0
            for v in seq:
                if v == 1:
                    run += 1
                    best = max(best, run)
                else:
                    run = 0
            total += self._pat(best)
        return total

    @staticmethod
    def _pat(n):
        return {0: 0, 1: 1, 2: 10, 3: 100, 4: 1000, 5: 100000}.get(n, 100000)

    def _ai_move(self):
        best = None
        best_score = -1
        for r in range(self.SIZE):
            for c in range(self.SIZE):
                if self.board[r][c] != 0:
                    continue
                atk = self._score_line(r, c, 2)
                def_ = self._score_line(r, c, 1)
                s = atk * 1.1 + def_
                if s > best_score:
                    best_score = s
                    best = (r, c)
        return best


# 方块配色（索引对应 NAMES 顺序 I O T S Z J L）
TET_COLORS = {
    1: "#4dabf7", 2: "#ffd43b", 3: "#cc5de8", 4: "#69db7c",
    5: "#ff6b6b", 6: "#5c7cfa", 7: "#ff922b",
}
