"""Service manager page: lifecycle operations with confirmations + live log."""

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from gui.components.glass_panel import GlassPanel, KVGrid
from gui.components.log_viewer import LogViewer
from .base import Page


class ServicePage(Page):
    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setAttribute(Qt.WA_StyledBackground, False)
        body_v = QVBoxLayout(body)
        body_v.setContentsMargins(20, 16, 20, 16)
        body_v.setSpacing(12)
        outer.addWidget(scroll)
        scroll.setWidget(body)
        body.setAutoFillBackground(False)
        scroll.viewport().setAutoFillBackground(False)

        # ---- operation buttons
        ops = GlassPanel("服务操作（执行前会显示影响范围）")

        # 核心操作行
        row1 = QHBoxLayout()
        row1.setSpacing(10)

        self.btn_start = QPushButton("▶ 启动服务")
        self.btn_start.setObjectName("Primary")
        self.btn_start.setToolTip("设备证书 + 根证书 + 代理进程 + 系统代理")
        self.btn_restart = QPushButton("🔄 重启服务")
        self.btn_restart.setToolTip("安全停止后重新启动")
        self.btn_stop = QPushButton("■ 停止服务")
        self.btn_stop.setObjectName("Danger")
        self.btn_stop.setToolTip("恢复系统代理 + 结束进程 + 卸载根证书")
        self.btn_check = QPushButton("🔍 检查状态")
        self.btn_check.setToolTip("重新读取进程、端口、系统代理与证书状态")

        for b in (self.btn_start, self.btn_restart, self.btn_stop, self.btn_check):
            b.setCursor(Qt.PointingHandCursor)
            row1.addWidget(b)
        row1.addStretch(1)

        self.busy_lab = QLabel("")
        self.busy_lab.setObjectName("MutedLabel")
        row1.addWidget(self.busy_lab)
        ops.add(row1)

        # 高级与维护操作行
        row2 = QHBoxLayout()
        row2.setSpacing(10)

        adv_lab = QLabel("独立控制:")
        adv_lab.setObjectName("KVKey")
        row2.addWidget(adv_lab)

        self.btn_start_proxy = QPushButton("仅启动代理")
        self.btn_start_proxy.setToolTip("不修改系统设置，浏览器手动配 127.0.0.1:8888")
        self.btn_stop_proxy = QPushButton("仅停止代理")
        self.btn_stop_proxy.setToolTip("恢复系统代理并结束进程，保留证书")
        self.btn_restore = QPushButton("恢复系统设置")
        self.btn_restore.setToolTip("仅按备份恢复系统代理设置（无备份时不可用）")

        for b in (self.btn_start_proxy, self.btn_stop_proxy, self.btn_restore):
            b.setCursor(Qt.PointingHandCursor)
            row2.addWidget(b)
        row2.addStretch(1)
        ops.add(row2)

        body_v.addWidget(ops)

        # ---- status grid
        info = GlassPanel("运行状态（每 3 秒自动刷新）")
        self.grid = KVGrid()
        info.add(self.grid)
        self.grid.add_row("服务进程状态", "--", "proc")
        self.grid.add_row("健康检查（身份验证）", "--", "ident")
        self.grid.add_row("本地监听地址", "--", "listen")
        self.grid.add_row("进程 PID", "--", "pid")
        self.grid.add_row("进程名", "--", "pname")
        self.grid.add_row("启动时间", "--", "started")
        self.grid.add_row("运行时长", "--", "uptime")
        self.grid.add_row("最近一次启动记录", "--", "lastrun")
        self.grid.add_row("系统代理当前状态", "--", "sysproxy")
        self.grid.add_row("系统代理备份", "--", "backup")
        self.grid.add_row("守护标记", "--", "flag")
        self.grid.add_row("管理员权限", "--", "admin")
        body_v.addWidget(info)

        # ---- live action output
        output = GlassPanel("操作输出（实时）")
        self.log = LogViewer()
        output.add(self.log)
        body_v.addWidget(output, 1)

        # ---- wire up
        self.btn_start.clicked.connect(self._start)
        self.btn_restart.clicked.connect(self._restart)
        self.btn_stop.clicked.connect(self._stop)
        self.btn_start_proxy.clicked.connect(self._start_proxy)
        self.btn_stop_proxy.clicked.connect(self._stop_proxy)
        self.btn_restore.clicked.connect(self._restore)
        self.btn_check.clicked.connect(lambda: self.ctx.refresh_now())

    # ------------------------------------------------------------- ops
    def _start(self):
        self.ctx.confirm_and_run(
            "start", "启动服务",
            "将执行：初始化/检查设备证书 → 安装根证书 → 启动代理 → 设置系统代理。\n\n"
            "影响范围：本机根证书库与系统代理设置（会先备份，停止时自动恢复）。",
            "启动")

    def _restart(self):
        self.ctx.confirm_and_run(
            "restart", "重启服务",
            "将执行：安全停止（恢复系统代理 + 结束进程）→ 重新启动完整流程。\n\n"
            "影响范围：同“启动服务”，全程按备份恢复系统设置。",
            "重启")

    def _stop(self):
        self.ctx.confirm_and_run(
            "stop", "停止服务",
            "将执行：恢复启动前的系统代理（按备份）→ 结束代理与守护进程 → "
            "卸载本工具安装的根证书。\n\n"
            "影响范围：仅恢复/移除本工具修改过的配置。",
            "停止")

    def _start_proxy(self):
        self.ctx.confirm_and_run(
            "start-proxy", "仅启动代理",
            "将执行：初始化/检查设备证书 → 启动代理进程。\n\n"
            "影响范围：不修改系统代理设置；需在浏览器手动配置 127.0.0.1:8888。",
            "启动")

    def _stop_proxy(self):
        self.ctx.confirm_and_run(
            "stop-proxy", "仅停止代理",
            "将执行：结束代理与守护进程 → 按备份恢复系统代理。\n\n"
            "影响范围：保留根证书，仅恢复系统代理与进程。",
            "停止")

    def _restore(self):
        self.ctx.confirm_and_run(
            "restore-proxy", "恢复系统设置",
            "将执行：仅从备份文件恢复系统代理设置（HKCU 代理项与 WinHTTP），\n"
            "不结束进程、不卸载证书。\n\n"
            "注意：只恢复本工具记录过的备份；无备份时不做任何修改。",
            "恢复")

    # ------------------------------------------------------------- state
    def append_action_line(self, line):
        self.log.append_lines([line])

    def _set_busy(self, busy, action=""):
        self._busy = busy
        for b in (self.btn_start, self.btn_restart, self.btn_stop,
                  self.btn_start_proxy, self.btn_stop_proxy,
                 self.btn_restore, self.btn_check):
            b.setEnabled(not busy)
        self.busy_lab.setText(f"正在执行：{action}…" if busy else "")

    def on_action_started(self, action):
        self._set_busy(True, action)
        self.log.append_lines([f"===== 开始执行：{action} ====="])

    def on_action_finished(self, ok):
        self._set_busy(False)
        self.log.append_lines(
            [f"===== 执行{'完成' if ok else '失败'} "
             f"({time.strftime('%H:%M:%S')}) ====="])

    def update_snapshot(self, snap):
        running = snap["running"]
        conflict = snap["listener_pid"] and not running

        if running:
            proc_txt = "运行中"
        elif conflict:
            proc_txt = f"端口被其他进程占用（PID {snap['listener_pid']}）"
        else:
            proc_txt = "未运行"
        self.grid.set_value("proc", proc_txt)

        ident_map = {
            "pidfile": "通过（PID 文件与监听进程一致）",
            "py": "未通过（Python 进程但 PID 不匹配）",
            "foreign": "未通过（其他程序占用端口）",
            "none": "—",
        }
        self.grid.set_value("ident", ident_map.get(snap["identity"], "—"))
        self.grid.set_value("listen", snap["listen_addr"])
        self.grid.set_value("pid",
                            str(snap["listener_pid"]) if snap["listener_pid"]
                            else "—")
        self.grid.set_value("pname", snap["proc_name"] or "—")
        if running and snap.get("start_ts"):
            self.grid.set_value(
                "started", time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(snap["start_ts"])))
        else:
            self.grid.set_value("started", "—")
        self.grid.set_value("uptime", snap["uptime_str"] if running else "—")
        self.grid.set_value("lastrun", snap["log_last_run"] or "—")
        if snap["proxy"]["enabled"]:
            self.grid.set_value(
                "sysproxy",
                f"开启 · {snap['proxy']['server'] or '（未设置服务器）'}")
        else:
            self.grid.set_value("sysproxy", "关闭")
        self.grid.set_value(
            "backup",
            "已保存（含原始代理项 + WinHTTP）" if snap["backup_exists"]
            else "无备份文件")
        self.grid.set_value(
            "flag", "存在" if snap["watchdog_flag"] else "无")
        self.grid.set_value(
            "admin",
            "已提权（全部功能可用）" if snap["admin"]
            else "未提权（写操作会弹 UAC）")

        self.btn_restore.setEnabled(
            not getattr(self, "_busy", False) and snap["backup_exists"])
