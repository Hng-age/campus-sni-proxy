"""证书管理页：设备 CA 证书状态、信任库安装与私钥安全说明。"""

import os
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from gui.components.glass_panel import GlassPanel, KVGrid
from gui.workers import FuncWorker
from services import cert_service
from sni_proxy import config
from .base import Page

_TS_FMT = "%Y-%m-%d %H:%M:%S"


def _dt(value):
    """datetime -> 本地时间字符串；None -> '—'。"""
    return value.strftime(_TS_FMT) if value else "—"


def _tri(value, yes, no):
    """三态布尔（True/False/None）-> 文案；None 显示 '—'。"""
    if value is True:
        return yes
    if value is False:
        return no
    return "—"


def _fmt_fp(value):
    """指纹按 8 字符分组，避免 64 位无空格十六进制把整行撑宽。"""
    if not value:
        return "—"
    return " ".join(value[i:i + 8] for i in range(0, len(value), 8))


class CertificatesPage(Page):
    """证书管理：只读展示证书/ACL 状态，受控的安装、卸载与导出公开证书。"""

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self._acl_worker = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setAttribute(Qt.WA_StyledBackground, False)
        body_v = QVBoxLayout(body)
        body_v.setContentsMargins(20, 18, 20, 18)
        body_v.setSpacing(14)
        outer.addWidget(scroll)
        scroll.setWidget(body)
        body.setAutoFillBackground(False)
        scroll.viewport().setAutoFillBackground(False)

        # ---- 页面标题
        head = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("证书管理")
        title.setObjectName("TitleLabel")
        sub = QLabel("设备 CA 证书与私钥权限（界面不显示私钥内容）")
        sub.setObjectName("MutedLabel")
        title_col.addWidget(title)
        title_col.addWidget(sub)
        head.addLayout(title_col)
        head.addStretch(1)
        body_v.addLayout(head)

        # ---- 证书状态面板（数据来自实时快照 snap["cert"]）
        info = GlassPanel("证书状态（每 3 秒自动刷新）")
        self.grid = KVGrid()
        info.add(self.grid)
        v = self.grid.add_row("CA 证书文件存在性", "--", "exists")
        v.setToolTip(config.CA_CERT)
        self.grid.add_row("主题（CN）", "--", "subject_cn")
        self.grid.add_row("颁发者（CN）", "--", "issuer_cn")
        self.grid.add_row("有效期", "--", "validity")
        self.lab_days = self.grid.add_row("剩余天数", "--", "days_left")
        self.grid.add_row("SHA-256 指纹", "--", "sha256")
        self.grid.add_row("SHA-1 指纹（Windows Thumbprint）", "--", "sha1")
        self.grid.add_row("机器证书库安装状态", "--", "installed_machine")
        self.grid.add_row("当前用户证书库安装状态", "--", "installed_user")
        self.grid.add_row("通配符证书", "--", "wildcard")
        self.grid.add_row("CA 私钥文件", "--", "ca_key")
        self.lab_acl = self.grid.add_row("私钥 ACL 状态", "--", "key_acl")
        body_v.addWidget(info)

        # ---- 操作区
        ops = GlassPanel("证书操作")
        row = QHBoxLayout()
        row.setSpacing(10)

        self.btn_check = QPushButton("检查状态")
        self.btn_check.setToolTip("重新读取证书/信任库状态，并复查私钥 ACL")
        self.btn_export = QPushButton("导出公开证书")
        self.btn_export.setToolTip(
            "导出 CA 公开证书（仅 .crt/.cer/.pem，绝不导出私钥）")
        self.btn_install = QPushButton("安装根证书")
        self.btn_install.setObjectName("Primary")
        self.btn_install.setToolTip(
            "安装本工具生成的设备 CA 到受信任的根证书颁发机构")
        self.btn_remove = QPushButton("卸载本工具证书")
        self.btn_remove.setObjectName("Danger")
        self.btn_remove.setToolTip("按指纹匹配，仅移除本工具安装的 CA 证书")

        for b in (self.btn_check, self.btn_export, self.btn_install,
                  self.btn_remove):
            b.setCursor(Qt.PointingHandCursor)
            row.addWidget(b)
        row.addStretch(1)
        ops.add(row)

        self.status_lab = QLabel("")
        self.status_lab.setObjectName("MutedLabel")
        self.status_lab.setWordWrap(True)
        ops.add(self.status_lab)
        body_v.addWidget(ops)

        # ---- 安全说明
        sec = GlassPanel("安全说明")
        notes = (
            "· 不提供导出 CA 私钥的入口（“导出公开证书”仅复制公开证书文件）",
            "· 不在界面显示私钥内容，仅检查文件存在性与 ACL 是否收紧",
            "· 卸载只移除本工具确认安装的证书（按指纹匹配）",
            "· 上游 TLS 严格校验固定启用，无快捷开关"
            "（需以环境变量 SNI_STRICT_UPSTREAM=0 启动才能退回）",
        )
        for text in notes:
            lab = QLabel(text)
            lab.setObjectName("MutedLabel")
            lab.setWordWrap(True)
            sec.add(lab)
        body_v.addWidget(sec)

        # ---- footer
        self.updated_lab = QLabel("数据尚未更新")
        self.updated_lab.setObjectName("TinyLabel")
        body_v.addWidget(self.updated_lab)
        body_v.addStretch(1)

        # ---- wire up
        self.btn_check.clicked.connect(self._check)
        self.btn_export.clicked.connect(self._export)
        self.btn_install.clicked.connect(self._install_ca)
        self.btn_remove.clicked.connect(self._remove_ca)

    # ------------------------------------------------------------ ops
    def _check(self):
        """检查状态：刷新快照 + 后台复查一次私钥 ACL。"""
        self.ctx.refresh_now()
        self._refresh_acl()

    def _export(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出公开证书", "ca_cert.crt",
            "公开证书 (*.crt *.cer *.pem);;所有文件 (*)")
        if not path:
            return
        if path.lower().endswith(".key"):
            self.status_lab.setText("已取消：不允许保存为私钥扩展名（.key）")
            return
        try:
            dst = cert_service.export_public_cert(config.CA_CERT, path)
        except Exception as e:      # noqa: BLE001 - 页内反馈即可
            self.status_lab.setText(f"导出失败：{e}")
            return
        self.status_lab.setText(f"公开证书已导出：{dst}")

    def _install_ca(self):
        text = ("将执行：安装本工具生成的设备 CA 证书到本机"
                "「受信任的根证书颁发机构」。\n\n"
                "影响范围：仅安装本工具生成的设备 CA 到受信任的根证书颁发"
                "机构，不修改系统其他证书与设置。")
        self.ctx.confirm_and_run("install-ca", "安装根证书", text, "安装")

    def _remove_ca(self):
        text = ("将执行：按 SHA-1 指纹匹配，移除本工具安装的 CA 证书"
                "（机器证书库与当前用户证书库）。\n\n"
                "影响范围：仅移除本工具 CA（按指纹匹配），不影响系统其他证"
                "书；未安装时不做任何修改。")
        self.ctx.confirm_and_run("remove-ca", "卸载本工具证书", text, "卸载")

    def on_action_started(self, action):
        for b in (self.btn_install, self.btn_remove):
            b.setEnabled(False)

    def on_action_finished(self, ok):
        for b in (self.btn_install, self.btn_remove):
            b.setEnabled(True)
        self.status_lab.setText(
            "操作执行完成，状态已刷新" if ok else "操作失败，详见服务日志")
        self.ctx.refresh_now()

    def activate(self):
        # 进入页面时读一次私钥 ACL（icacls 不轻，不随快照轮询）
        self._refresh_acl()

    # ------------------------------------------------------------- acl
    def _refresh_acl(self):
        """后台线程读一次私钥 ACL，避免 icacls 卡住界面。"""
        if self._acl_worker and self._acl_worker.isRunning():
            return

        def job(on_progress):
            return cert_service.key_acl_report()

        self._acl_worker = FuncWorker(job, parent=self)
        self._acl_worker.done.connect(self._acl_done)
        self._acl_worker.start()

    def _acl_done(self, result, error):
        self._acl_worker = None
        if error or result is None:
            self.lab_acl.setStyleSheet("")
            self.grid.set_value(
                "key_acl", f"读取失败（{error or '未知错误'}）")
            return
        if not result.get("exists"):
            self.lab_acl.setStyleSheet("")
            self.grid.set_value("key_acl", "私钥文件不存在")
            return
        restricted = result.get("restricted")
        if restricted is True:
            self.grid.set_value("key_acl", "已收紧（未发现过宽授权）")
            self.lab_acl.setStyleSheet("color:#22C58B;")
        elif restricted is False:
            self.grid.set_value("key_acl", "存在过宽授权（Everyone/Users 等）")
            self.lab_acl.setStyleSheet("color:#EF6464;")
        else:
            self.lab_acl.setStyleSheet("")
            self.grid.set_value("key_acl", "无法解析（icacls 读取失败）")
        grants = result.get("grants") or []
        if grants:
            self.lab_acl.setToolTip("\n".join(grants))

    # ------------------------------------------------------------ state
    def update_snapshot(self, snap):
        cert = snap.get("cert") or {}

        self.grid.set_value(
            "exists",
            "存在" if cert.get("exists") else "不存在（启动服务时自动生成）")
        self.grid.set_value("subject_cn", cert.get("subject_cn") or "—")
        self.grid.set_value("issuer_cn", cert.get("issuer_cn") or "—")
        nb, na = cert.get("not_before"), cert.get("not_after")
        if nb or na:
            self.grid.set_value("validity", f"自 {_dt(nb)} 至 {_dt(na)}")
        else:
            self.grid.set_value("validity", "—")

        days = cert.get("days_left")
        expired = bool(cert.get("expired"))
        if days is None:
            self.grid.set_value("days_left", "—")
            self.lab_days.setStyleSheet("")
        elif expired or days < 0:
            self.grid.set_value("days_left", f"已过期 {-days} 天")
            self.lab_days.setStyleSheet("color:#EF6464;")
        else:
            self.grid.set_value("days_left", f"{days} 天")
            self.lab_days.setStyleSheet(
                "color:#EAB54A;" if days < 30 else "")

        self.grid.set_value("sha256", _fmt_fp(cert.get("sha256")))
        self.grid.set_value("sha1", _fmt_fp(cert.get("sha1")))
        self.grid.set_value(
            "installed_machine",
            _tri(cert.get("installed_machine"), "已安装", "未安装"))
        self.grid.set_value(
            "installed_user",
            _tri(cert.get("installed_user"), "已安装", "未安装"))
        self.grid.set_value(
            "wildcard",
            "已就绪" if cert.get("wildcard") else "未生成（启动服务时生成）")
        self.grid.set_value(
            "ca_key",
            "存在" if os.path.exists(config.CA_KEY) else "不存在")

        self.updated_lab.setText(
            f"数据更新于 {time.strftime('%H:%M:%S')} · "
            "证书状态来自实时读取 · 私钥 ACL 在进入页面或点击“检查状态”时复查")
