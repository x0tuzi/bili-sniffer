# bili-sniffer

B站视频下载器 — API 获取全清晰度流地址、批量下载、弹幕/字幕提取。

---

## 📦 安装

### 需要先装好

- **Python 3.8+** （方式二和方式三需要）
- **ffmpeg** （可选，想合并字幕/弹幕到视频才需要）

---

### 🪟 Windows — 选一种方式

<details open>
<summary><b>方式一：一键安装脚本（推荐）</b></summary>

右键下载 [setup.bat](https://raw.githubusercontent.com/x0tuzi/bili-sniffer/main/setup.bat)，双击运行。

脚本会自动：
1. 检测 Python，没有就弹出 python.org 下载页
2. 安装 requests 等依赖
3. 下载 bilibili_sniffer.py
4. 在桌面生成快捷启动图标

> ⚠️ 如提示找不到 Python：去 python.org 下载安装包，**必须勾选 "Add Python to PATH"**，装完后再跑一次脚本。

</details>

<details>
<summary><b>方式二：预编译 .exe（不需要 Python）</b></summary>

去 [Releases](https://github.com/x0tuzi/bili-sniffer/releases) 下载 `bili-sniffer-windows.exe`，双击即用。

</details>

<details>
<summary><b>方式三：手动建虚拟环境</b></summary>

打开终端（PowerShell 或 cmd），复制粘贴：

```powershell
python -m venv "%USERPROFILE%\bili-sniffer"
"%USERPROFILE%\bili-sniffer\Scripts\python" -m pip install requests browser_cookie3 cryptography
curl -o "%USERPROFILE%\bili-sniffer\bilibili_sniffer.py" https://raw.githubusercontent.com/x0tuzi/bili-sniffer/main/bilibili_sniffer.py
```

每次使用：

```powershell
"%USERPROFILE%\bili-sniffer\Scripts\python" "%USERPROFILE%\bili-sniffer\bilibili_sniffer.py"
```

</details>

---

### 🐧 Linux — 一键安装

```bash
curl -fsSL https://raw.githubusercontent.com/x0tuzi/bili-sniffer/main/install.sh | bash
```

三条选项：单文件脚本 / Python 虚拟环境 / 预编译二进制。装完终端输入 `bili-sniffer`。

---

### 🍎 macOS — 三步安装

打开终端，复制粘贴：

```bash
python3 -m venv ~/bili-sniffer
~/bili-sniffer/bin/pip install requests browser_cookie3 cryptography
curl -o ~/bili-sniffer/bilibili_sniffer.py https://raw.githubusercontent.com/x0tuzi/bili-sniffer/main/bilibili_sniffer.py
```

每次使用：

```bash
~/bili-sniffer/bin/python ~/bili-sniffer/bilibili_sniffer.py
```

---

### 🐍 我用 git / 直接跑 .py

```bash
git clone https://github.com/x0tuzi/bili-sniffer.git
cd bili-sniffer
pip install -r requirements.txt
python bilibili_sniffer.py
```

---

## 🚀 用法

```bash
bili-sniffer                 # 交互模式（推荐）
bili-sniffer BV1xx411c7mD    # 命令行查看流地址
bili-sniffer --download BV1  # 命令行直接下载
bili-sniffer --sniff         # 抓包模式
```

### 交互命令

| 命令 | 说明 |
|---|---|
| `search 关键词` | 搜索视频 |
| `hot` | 热门视频 |
| `info BV号` | 视频详情 + 流地址 |
| `download BV号` | 选择分P/清晰度下载 |
| `url BV号` | 仅输出下载地址（喂给其他下载器） |
| `daily` | 每日签到（需Cookie） |
| `qadd BV号` | 加入下载队列 |
| `qrun` / `qlist` / `qclear` | 队列管理 |
| `settings` | 统一设置（字幕/弹幕自动合并等） |
| `cookie auto` | 自动从浏览器提取 Cookie |

---

## 🔧 可选依赖

首次运行时会自动检测缺失的工具，并给出安装提示。

| 工具 | 用途 | 怎么装 |
|---|---|---|
| **ffmpeg** | 合并音视频、字幕/弹幕到视频 | `apt install ffmpeg` / `brew install ffmpeg` |
| **aria2c** | 多线程下载加速 | `apt install aria2` |
| browser_cookie3 | 自动提取浏览器 Cookie | pip install browser_cookie3 |

---

## 📦 自己打包成二进制

```bash
pip install pyinstaller
pyinstaller --onefile --name bili-sniffer bilibili_sniffer.py
```

---

## License

MIT
