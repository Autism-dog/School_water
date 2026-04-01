# 🌸💧 校园热水控制系统 / School Water Control 💧🌸

> kawaii water control — 少女风格校园蓝牙热水控制器（洗澡用）

基于 [celesWuff/waterctl](https://github.com/celesWuff/waterctl) 2.x 协议，使用 Python 重写，支持：

| 平台 | 技术栈 |
|------|--------|
| 🌐 **Web** | FastAPI + Docker + nginx + acme.sh HTTPS |
| 🤖 **Android** | Kivy + pyjnius 原生 BLE |
| 🪟 **Windows** | PyQt6 + bleak (WinRT) 原生 BLE |

---

## 📂 项目结构

```
School_water/
├── core/                   # 共享协议核心库
│   ├── algorithms.py       # CRC-16/ChangGong, CRC-16/CGAEAF
│   ├── payloads.py         # 静态协议帧 + UUID 常量
│   ├── solvers.py          # 动态帧构建（B2 / AE→AF）
│   └── bluetooth.py        # 异步 BLE 状态机（bleak）
├── web/                    # Web 平台
│   ├── app.py              # FastAPI 应用
│   ├── templates/
│   │   └── index.html      # 🌸 粉色少女风前端（Web Bluetooth API）
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── nginx.conf          # HTTPS 反向代理
│   ├── ssl_renew.sh        # acme.sh 证书申请 & 热重载
│   └── entrypoint.sh
├── android/                # Android APK
│   ├── main.py             # Kivy UI + pyjnius BLE
│   └── buildozer.spec
├── windows/                # Windows EXE
│   ├── main.py             # PyQt6 UI + bleak BLE
│   └── main.spec           # PyInstaller 打包配置
└── .github/workflows/
    ├── windows.yml         # 自动编译 Windows EXE
    ├── android.yml         # 自动编译 Android APK
    └── release.yml         # 打 tag 自动发布 Release
```

---

## ⚙️ deputy.wasm（新固件密钥派生）

新版固件在握手时会发送 `0xAE` 密钥挑战包，需要运行 `deputy.wasm` 派生响应密钥。

1. 从原项目获取：
   ```
   https://github.com/celesWuff/waterctl/blob/2.x/src/deputy.wasm
   ```
2. 将文件放置到：
   - **Python 后端**（Windows/core）：`core/deputy.wasm`
   - **Web 前端**：`web/static/deputy.wasm`（浏览器直接加载）
3. 安装 wasmtime：`pip install wasmtime`

老固件（`0xB0`/`0xB1` 响应）无需此文件即可正常使用。

---

## 🌐 Web 部署（Docker）

### 快速启动

```bash
cd web/
# 先申请证书（在 80 端口 standalone 验证）
DOMAIN=your.domain.com DOMAIN_ALT=www.your.domain.com ./ssl_renew.sh

# 启动服务
DOMAIN=your.domain.com docker compose up -d
```

### 证书自动续期

acme.sh 安装后会自动添加 cron 任务（每天检查，到期前 30 天自动续期）。  
续期后 `ssl_renew.sh` 会自动向 nginx 发送 reload 信号，**无需中断服务**。

手动续期：
```bash
DOMAIN=your.domain.com ./web/ssl_renew.sh
```

> acme.sh 命令参考：
> ```bash
> acme.sh --issue --server letsencrypt --standalone -d $DOMAIN --certificate-profile shortlived
> acme.sh --install-cert -d $DOMAIN --key-file "/root/Water/ssl/privkey.key" \
>         --fullchain-file "/root/Water/ssl/fullchain.pem"
> ```

---

## 🤖 Android APK

### 本地构建

```bash
cd android/
# 将 core/ 目录复制进来
cp -r ../core ./core
pip install buildozer cython
buildozer android debug
# APK 在 bin/ 目录
```

### GitHub Actions 自动构建

推送 tag 即可触发自动构建并发布 Release：

```bash
git tag v1.0.0
git push origin v1.0.0
```

---

## 🪟 Windows EXE

### 本地构建

```bash
cd windows/
pip install -r requirements.txt
pyinstaller main.spec
# EXE 在 dist/ 目录
```

**要求**：Windows 10 1903+（WinRT Bluetooth API）

---

## 🧪 核心库使用（Python）

```python
import asyncio
from core.bluetooth import WaterController, Stage

async def main():
    ctrl = WaterController()
    ctrl.on_stage_change = lambda s: print("阶段:", s)
    ctrl.on_error = lambda msg, fatal: print("错误:", msg)

    devices = await ctrl.scan_all()
    # 选择目标设备 ...
    await ctrl.connect(devices[0])

    input("按 Enter 结束用水...")
    await ctrl.end()

asyncio.run(main())
```

---

## 🌸 UI 设计

前端（Web / Android / Windows）均采用 **粉色少女可爱风格**：

- 主色调：樱花粉 `#E75480` / `#F48FB1`
- 背景：浅粉渐变
- 动效：浮落樱花花瓣（Web）
- 圆角卡片 + 玻璃拟态效果

---

## 📜 协议参考

| 帧类型 | 方向 | 说明 |
|--------|------|------|
| `B0`/`B1` | ← RXD | 开启序言 OK（旧固件） |
| `AE` | ← RXD | 密钥挑战（新固件） |
| `AF` | → TXD | 密钥响应 |
| `B2` | ↔ | 会话开启 epilogue |
| `B3` | ← RXD | 结束序言 OK |
| `B4` | → TXD | 结束 epilogue |
| `AA`/`B5`/`B8` | ← RXD | 遥测，忽略 |
| `BA` | ← RXD | 用户信息上传请求（伪 ACK） |
| `BC` | ← RXD | 离线炸弹修复 |
| `C8` | ← RXD | 拒绝（报错） |

---

## 🙏 致谢

- [celesWuff/waterctl](https://github.com/celesWuff/waterctl) — 原始协议逆向与实现