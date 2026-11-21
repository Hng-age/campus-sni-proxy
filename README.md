# 校园网 SNI 封锁绕过工具 2.1.0 · SNI Proxy Desktop

## 这是什么

校园网防火墙按 SNI（TLS 握手中的域名明文）封锁抖音/B站/小红书/豆包等网站。
本工具通过本地 MITM 代理改写 SNI 绕过封锁：

    浏览器 --HTTPS--> 本代理（本机自签证书） --HTTPS--> 真实服务器（SNI 换成放行域名）
    防火墙只看到放行域名，正常放行；Host 头保持真实域名，内容正常返回。

2.0.0 在 1.1.0 核心（Python 代理 + PowerShell 管理器）之上新增 PySide6 深色
玻璃拟态桌面 GUI：常用操作全部可在图形界面完成；命令行菜单原样保留，
作为故障恢复手段。

## 桌面 GUI（2.0.0 新增）

八个页面，覆盖日常使用全部场景：

| 页面 | 用途 |
|------|------|
| 仪表盘 | 一屏总览代理运行状态、监听端口、运行时长等关键指标 |
| 运行管理 | 启动 / 停止 / 重启代理，接管与恢复系统代理设置 |
| 规则管理 | 一键智能探测阻断域名，自动学习伪装 SNI 与边缘 IP 并写入分流规则 |
| 网络诊断 | 出口检测、连通性测试、测速对比与环境自检，报告支持 IP 脱敏 |
| 网络测速 | 直连与本地代理通道的带宽、延迟与抖动测速，支持历史记录导出 |
| 日志中心 | 实时查看运行日志，按级别筛选，自动滚动跟随最新输出 |
| 证书管理 | 设备 CA / 通配符证书状态查看，根证书安装与移除 |
| 设置中心 | 主题（深色/浅色）、玻璃强度、字体缩放、托盘行为等偏好设置 |

启动方式（任选其一）：

1. 双击 `启动桌面版.bat`（自动请求管理员权限；首次运行自动安装
   PySide6 依赖）
2. 命令行：`python main.py`

GUI 的全部生命周期操作（启动/停止/重启/恢复系统代理/安装与移除根证书）
都委托 `proxy_manager.ps1 -Action <action>` 非交互模式执行，与命令行菜单
走同一套备份/恢复逻辑，系统代理始终只有单一恢复来源。只读状态（进程/
端口/PID 文件身份验证/注册表/证书库）由 Python 服务层直读，不做写操作。
命令行入口（`SNI代理_一键启动.bat` / `start.bat`）原样保留：GUI 无法
启动或异常时，用它恢复环境。

## 文件说明

| 文件 | 作用 |
|------|------|
| 启动桌面版.bat | GUI 入口：优先启动 dist 便携版；无 dist 时用 Python 启动并自动安装 PySide6 |
| main.py | GUI 程序入口（`python main.py`） |
| SNI代理_一键启动.bat | 命令行入口：双击弹出菜单（自动请求管理员权限） |
| start.bat | ASCII 文件名命令行入口；中文 bat 文件名乱码时双击这个 |
| proxy_manager.ps1 | 管理逻辑：命令行菜单 + `-Action` 非交互模式（GUI 调用） |
| mitm_sni_proxy.py | 代理入口（兼容原有启动方式，实现位于 sni_proxy/） |
| sni_proxy/ | 代理核心：config / logsetup / netutil / certs / uplinks / upstream / server |
| services/ | GUI 服务层：进程、状态、证书、诊断、设置（不含 Qt） |
| gui/ | PySide6 桌面界面：主题、侧栏、工作线程、设置存储、页面与组件 |
| tests/ | 单元测试（`python -m unittest discover -s tests -v`） |
| requirements.txt | GUI 依赖（PySide6>=6.6） |
| proxy_watchdog.ps1 | 异常守护：代理进程意外退出时自动恢复系统代理 |
| mitm_certs/ | 首次启动时在本机生成设备专属 CA 和通配符证书 |
| mitm_certs/strategies.json | 每个域名的可用线路缓存（自动维护） |
| logs/proxy.log | 运行日志（自动轮转，2 MB × 3 份） |
| state/ | 系统代理备份、守护标记、守护日志 |

## 项目结构

```
main.py                  GUI 入口（python main.py）
requirements.txt         GUI 依赖（PySide6>=6.6）
mitm_sni_proxy.py        代理入口（兼容原有启动方式）
proxy_manager.ps1        管理器：命令行菜单 + -Action 非交互模式
proxy_watchdog.ps1       异常退出守护
启动桌面版.bat        GUI 入口（自动提权 + 首次自动装依赖）
SNI代理_一键启动.bat       命令行菜单入口
start.bat                ASCII 命令行入口
sni_proxy/
  config.py              常量、路径、封锁域名列表
  logsetup.py            轮转日志（时间戳 + 级别）
  netutil.py             DNS、域名/证书匹配
  certs.py               设备 CA、通配符、按需签发、旧证书迁移
  uplinks.py             多网络出口检测与绑定
  upstream.py            上游证书校验、SNI 回退、线路缓存
  server.py              CONNECT 处理与 MITM/透传转发
services/
  util.py                服务层公共工具（无 Qt 依赖）
  process_manager.py     代理进程/端口/PID 文件生命周期
  status_monitor.py      只读状态采集（进程/端口/注册表/证书库）
  cert_service.py        证书库操作封装
  diagnostics.py         出口检测、连通性、测速、环境自检
  config_manager.py      设置模式与默认值（QSettings 由 GUI 层持有）
gui/
  theme.py               玻璃拟态主题（深色/浅色）与 QSS 构建
  sidebar.py             侧边导航栏
  workers.py             后台线程桥（服务层函数 → GUI 线程）
  settings_store.py      QSettings 偏好存储 + 变更通知
  main_window.py         主窗口（侧栏 + 页面栈 + 系统托盘）
  components/
    glass_panel.py       玻璃拟态卡片面板
    title_bar.py         自绘标题栏
    log_viewer.py        日志查看组件
  pages/
    base.py              页面基类
    dashboard.py         仪表盘
    service.py           运行管理
    diagnostics.py       网络诊断
    logs.py              日志中心
    certificates.py     证书管理
    settings.py          设置中心
tests/                   单元测试（含 GUI 导入冒烟测试）
```

## 运行环境（首次运行会自动补齐）

- Windows 10 / 11
- **Python 3.8 或更高版本**：未检测到时会自动安装 Python 3.12（优先 winget，
  失败则从华为云 / python.org 下载静默安装）
  - 手动安装时务必勾选 "Add python.exe to PATH"
  - Microsoft Store 里的 python 只是占位符，不能用
- **PySide6（>= 6.6，仅 GUI 需要）**：双击 `启动桌面版.bat` 首次运行
  时自动 pip 安装；离线环境先手动 `pip install -r requirements.txt`；
  命令行模式不需要 PySide6
- **Git for Windows（提供 openssl）**：首次生成设备证书需要它；未安装时会
  自动尝试 winget 或国内镜像静默安装
  - 手动下载：https://git-scm.com/download/win
- 管理员权限：双击 bat 会自动弹出 UAC，点"是"即可
- 浏览器建议 Chrome / Edge；Firefox 使用独立证书库，不读系统根证书，
  需手动导入 `mitm_certs/ca_cert.crt`
- 安全软件（360 / 火绒 / Defender）可能拦截"安装根证书"或结束 pythonw 进程，
  请选择允许，或临时关闭后重试
- 端口 8888 不能被其他程序占用
- 必须解压后再运行，不要直接在压缩包里双击
- 自动安装需要联网；如果自动安装失败，按提示手动安装后重新运行即可

## 使用方法

### GUI（推荐）

1. 双击 `启动桌面版.bat`（自动请求管理员权限，点"是"；首次运行
   自动安装 PySide6）
2. 在「运行管理」页点启动（等价命令行菜单 [1]）：本机生成设备证书 +
   安装根证书 + 启动代理 + 设置系统代理
3. 浏览器直接访问即可
4. 不用时在「运行管理」页点停止（等价命令行菜单 [2]）：恢复启动前的
   系统代理 + 结束进程 + 删除根证书

### 命令行（备选 / 故障恢复）

1. 双击 `SNI代理_一键启动.bat`（自动请求管理员权限，点"是"）
   如果文件名显示乱码，改为双击同目录下的 `start.bat`
2. 选 [1] 启动：本机生成设备证书 + 安装根证书 + 启动代理 + 设置系统代理
3. 浏览器直接访问即可
4. 不用时选 [2] 停止：恢复启动前的系统代理 + 结束进程 + 删除根证书

其他选项：

  [3] 仅启动代理（不改系统设置，手动在浏览器配 127.0.0.1:8888）
  [4] 仅停止代理（保留证书，恢复系统代理）
  [5] 查状态 + 环境自检 + 连通性测试
  [6] 测速：网络出口检测 + 单/多网络速度对比 + 直连/代理对比（8 秒采样）
  [7] 查看最近 40 行运行日志（错误红色、警告黄色）

## 2.1.0 更新记录

- **修复「开始智能探测」导致程序直接退出**：探测线程改为由页面持有引用，
  并监听 `FuncWorker.done(result, error)`；此前把无参数的 `QThread.finished`
  当作结果信号连接，且局部 worker 在线程运行期间被回收，触发
  "QThread: Destroyed while thread is still running"。
- **修复仪表盘快捷入口跳错页面**：「网络诊断」「查看日志」现在分别跳转到
  网络诊断页与日志中心页。
- **修复运行管理页操作输出空白**：没有 `[LEVEL]` 标记的管理器输出行现在会
  显示在「全部 / INFO 及以上 / 含 DEBUG」筛选中。
- **修复全局代理模式下 PAC 路径误匹配**：只有以 `/` 开头的本地请求才会返回
  PAC 脚本，访问远端 `http://host/pac` 不再被错误拦截。
- **修复 DNS 探测异常路径的 socket 泄漏**，并补齐侧边栏「帮助」按钮的响应。
- **修复多级公共后缀识别**：`example.edu.cn`、`foo.co.uk` 等不再被截断成
  `edu.cn`、`co.uk`，避免自动学习误加过宽的分流后缀。
- **修复启动服务后出现的黑色控制台窗口**：守护进程改为 WMI `ShowWindow=0`
  启动，后台存活且不再弹出空白 PowerShell 窗口。
- **修复停止服务时 WinHTTP 权限错误**：无管理员权限恢复 WinHTTP 设置不再导致
  整个停止动作失败；浏览器代理仍按备份恢复，代理进程会正常结束。
- **版本号升级为 2.1.0**。

## 2.0.0 更新记录

- **PySide6 深色玻璃拟态桌面 GUI**：主窗口 1200×760，八个页面（仪表盘/
  运行管理/规则管理/网络诊断/网络测速/日志中心/证书管理/设置中心）+
  系统托盘；主题、玻璃强度、字体缩放可在设置中心调整。
- **proxy_manager.ps1 新增 `-Action` 非交互模式**：`start / stop / restart /
  start-proxy / stop-proxy / restore-proxy / install-ca / remove-ca /
  status / logs` 与命令行菜单语义一致，供 GUI 调用；非交互输出按 UTF-8
  编码，不带参数仍是原命令行菜单。
- **GUI 只读状态由 Python 直读**：进程/端口/PID 文件身份验证/注册表/
  证书库等只读信息由 services 层直接读取，不落盘、不改系统；全部写操作
  （生命周期/证书/系统代理）都走管理器，保持单一备份恢复来源。
- **新增单元测试**：版本与目录布局测试、GUI 导入冒烟测试（未安装
  PySide6 时自动跳过）。
- **版本与目录名升级为 2.0.0**。

## 1.1.0 安全更新

- **上游证书默认严格校验主机名**：只有上游证书覆盖原始访问域名时才接受该线路，
  证书链有效但域名不匹配的线路默认拒绝。设置 `SNI_STRICT_UPSTREAM=0` 可显式
  退回全局兼容模式。
  静态资源/CDN 后缀（`douyinstatic.com`、`douyinpic.com`、`hdslb.com` 等）默认
  例外允许 `chain` 线路，否则会出现"页面壳加载出来、内容区空白"；API 和文档
  域名仍严格校验。设置 `SNI_ASSET_COMPAT=0` 可关闭这个例外（纯严格模式）。
- **旧共享 CA 私钥销毁**：1.0.2 的 110 个旧私钥在迁移后覆盖写入并删除，只保留
  旧证书用于审计；不再把已随旧版分发的密钥当作秘密长期保存。
- **旧 CA 移除确认**：迁移后会在本机和管理员两个证书库中复查旧 CA 指纹，确认
  已从"受信任的根证书颁发机构"移除；未移除时会提示手动处理。
- **私钥文件 ACL 加固**：`ca.key`、通配符和站点私钥生成后立即重建 DACL，只允许
  当前用户、SYSTEM、Administrators 访问；不会修改 SACL/完整性标签。
- **代理存活检测更可靠**：管理器和守护进程不再只看端口是否可连接，而是检查
  监听进程的 PID、进程名和命令行；其他程序占用 8888 时会被识别为代理未运行，
  不会误判为代理存活。
- **透传域名修复**：非封锁域名改用系统 DNS + 多 IP/多出口并发连接，修复 TRAE CN
  相关域名（`www.trae.cn`、`lf-cdn.trae.ai`）以及其他正常站点走代理超时的问题。
- **域名后缀边界修复**：`notdouyin.com` 不会再被误判为 `douyin.com` 的子域。
- **协议与性能修复**：明文 HTTP POST 的请求体会完整转发；DNS 查询使用随机事务 ID
  并在公共 DNS 不可用时回退系统解析；上游 TLS 复用同一个 SSLContext；双向转发
  从 2 个线程降为 1 个；遥测 204 日志降为 debug，避免刷屏。
- **分发包精简**：不再包含 `strategies.json` 历史线路缓存；新增 ASCII 入口
  `start.bat`，避免中文文件名在部分解压工具中乱码。
- 单元测试增加到 26 个。

**严格模式说明**：个别站点首次探测时可能短暂返回 204，代理会继续探测并缓存
`host` 线路；当前网络下豆包已能通过 `host` 线路正常访问。静态资源/CDN 默认
允许 `chain` 线路以避免抖音/B站页面内容空白；如果某站点长期不可用，再设置
`SNI_STRICT_UPSTREAM=0` 退回全局兼容模式。`www.huawei.com` 的上游边缘证书
已过期，两种模式都会拒绝。

## 1.0.4 更新

- **首次运行自动补齐依赖**：未检测到 Python 时自动安装 Python 3.12（优先 winget，
  失败回退华为云 / python.org 安装包）；首次生成证书缺少 openssl 时自动安装
  Git for Windows（优先 winget，失败回退国内镜像）。
- **分发包保持洁净**：不含任何证书、私钥、`logs/`、`state/`、`.git` 或
  `__pycache__`；每台设备首次运行独立生成证书。
- 版本号同步为 1.0.4。

## 1.0.3 安全更新

- **不再随包分发 CA 私钥**：项目压缩包里没有 `ca.key`、站点证书或通配符证书。
  首次运行每台电脑各自生成一套 CA + 通配符证书，互不通用。
- **旧版共享 CA 自动轮换**：检测到 1.0.2 的共享 CA 时，会把旧证书归档到
  `mitm_certs/legacy_1.0.2/`，生成新 CA，并从系统"受信任的根证书"移除旧 CA。
- **上游证书链强制校验**：连接上游服务器时必须通过系统 CA 的证书链验证，
  自签名、过期证书一律拒绝；优先选择证书覆盖原始域名的线路。
  1.1.0 起默认只接受"证书覆盖原始域名"的 `host` 线路；设置环境变量
  `SNI_STRICT_UPSTREAM=0` 才允许"链有效但证书不覆盖原域名"的兼容线路
  （可用站点会增多，但安全性下降）。
- **系统代理备份/恢复**：启动前记录 HKCU 代理配置（ProxyEnable / ProxyServer /
  ProxyOverride / AutoConfigURL）以及 WinHTTP 的二进制配置（WinHttpSettings），
  停止或异常退出时原样恢复；不再用 `netsh winhttp reset proxy` 覆盖用户环境。
- **异常退出自动恢复**：后台守护进程每 5 秒检查代理端口，连续两次不可用即恢复
  原始系统代理；如果管理器再次打开时发现上次异常退出，也会自动恢复。
- **日志与异常处理**：所有运行信息写入 `logs/proxy.log`，带时间戳和级别，
  自动轮转；关键异常不再被静默忽略。

## 常见问题

- 提示"未检测到 Python"：程序会自动尝试安装；若失败，手动安装 3.8+ 并勾选 Add to PATH
- 提示需要 openssl / 证书初始化失败：程序会自动尝试安装 Git for Windows；若失败，手动安装后重试
- 双击 GUI 无反应 / 依赖安装失败：命令行运行 `python main.py` 查看报错；或先
  `pip install -r requirements.txt`；仍不行就用 `SNI代理_一键启动.bat` 走命令行菜单
- GUI 点了启动没动静：操作经 `proxy_manager.ps1 -Action` 提权执行，注意确认 UAC
  弹窗；未生效时去「日志中心」或 `logs/proxy.log` 查原因
- 选 [1] 后根证书安装失败：多为安全软件拦截，临时关闭安全软件后重试
- 代理启动失败：查看日志中心或菜单 [7] 日志；最常见是 8888 端口被占用
- 全部网页打不开：本版本已带守护恢复；也可重新打开 GUI 或 bat，会自动恢复上次的代理设置
- 重启电脑后失效：代理不自启 → 打开 GUI 点启动，或跑 bat 选 [1]
- 换校区/换网络后很慢：strategies.json 缓存的是原网络的线路，首次访问会重新探测
- 某个站点始终打不开：可能是该站的 CDN 证书已过期或拒绝一切外来 SNI（例如
  www.huawei.com 的部分边缘证书已过期，本版本会拒绝这类不安全线路），
  属于硬限制，本工具不会为了可用性放弃证书校验
- 豆包首次打开返回 204：代理正在探测 `host` 线路，稍等片刻或刷新即可；
  长期不可用再设置环境变量 `SNI_STRICT_UPSTREAM=0` 退回兼容模式
- 页面壳加载出来但内容区空白：多为 JS/图片 CDN 被严格模式拒绝；1.1.0 默认
  对静态资源允许 `chain` 线路。如果手动设置过 `SNI_ASSET_COMPAT=0`，改回 `1`
  或删除该环境变量后重启代理
- 新增被封锁的网站：编辑 `sni_proxy/config.py` 里的 `BLOCKED_SUFFIXES` 列表加后缀
- 限速说明：本工具不解决带宽限速（那是网关侧按账户限的）

## 技术备注

- 封锁特征：SNI 含封锁域名 → TIMEOUT；IP 段部分被封 → CDN 轮换
- 绕过策略（自动）：真实 IP/裸域 IP × 裸域 SNI/放行 SNI 池，并发探测，
  成功线路缓存到 strategies.json，重启秒连
- 线路级别：`host` = 上游证书覆盖原始域名；`chain` = 证书链有效但不覆盖原域名
- 1.1.0 起默认只用 `host` 线路；`chain` 线路仅在 `SNI_STRICT_UPSTREAM=0` 时启用
- 证书优先级：已生成的具体域名证书 → 通配符证书 → 调用 openssl 现场签发
- 纯遥测域名（zijieapi 等服务器拒绝一切外来 SNI）→ 返回 204 空响应，不影响页面
- 安全提示：`mitm_certs/` 里的私钥只属于当前电脑，**不要把自己的 mitm_certs
  目录发给别人**；每台电脑应各自运行启动生成
- GUI 架构：`gui/`（Qt 界面）依赖 `services/`（无 Qt 的服务层）依赖
  `sni_proxy/`（代理核心）；`services/` 与 `sni_proxy/` 不导入 PySide6，
  可单独测试；GUI 写操作一律经 `proxy_manager.ps1 -Action` 完成

## 开发与测试

```
pip install -r requirements.txt        # GUI 依赖（PySide6>=6.6；命令行模式不需要）
python -m unittest discover -s tests -v
```

单元测试在 1.1.0 的 26 个（覆盖域名/证书匹配、后缀边界、线路缓存兼容、
并发探测、断连分类、旧私钥销毁、私钥 ACL 加固、静态资源兼容和明文 HTTP
请求体读取）基础上，新增版本/目录布局测试与 GUI 导入冒烟测试；GUI 导入
测试在未安装 PySide6 的环境自动跳过，不阻塞核心逻辑测试。测试时可用
`SNI_PROXY_PORT=18888` 启动第二个实例，不影响正在运行的 8888。
