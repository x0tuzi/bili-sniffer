# bili-sniffer

B站视频下载器 — API 获取全清晰度流地址、批量下载、弹幕/字幕提取。

---

## 📦 安装

### 需要先装好

- **Python 3.8+** （必需）
- **pip** （通常和 Python 一起装好了）
- **ffmpeg** （可选，想合并字幕/弹幕到视频才需要）

> ⚠️ 不知道怎么装 Python？去 https://python.org 下载安装包，安装时**勾选 "Add Python to PATH"**。

---

### 🐧 Linux 用户 — 一键安装

一条命令，选你喜欢的安装方式：

```bash
curl -fsSL https://raw.githubusercontent.com/x0tuzi/bili-sniffer/main/install.sh | bash
```

会弹出三个选项：
1. **单文件脚本**（推荐）— 下载 `.py` + 安装依赖
2. **Python 虚拟环境** — 独立环境，不碰系统 Python
3. **预编译二进制** — 单文件，连 Python 都不需要

装完后终端输入 `bili-sniffer` 即可启动。

---

### 🪟 Windows 用户 — 三步安装

**第一步：打开终端**（PowerShell 或 cmd）

**第二步：创建虚拟环境并安装**

```powershell
python -m venv "%USERPROFILE%\bili-sniffer"
"%USERPROFILE%\bili-sniffer\Scripts\python" -m pip install requests browser_cookie3 cryptography
```

**第三步：下载脚本**

```powershell
curl -o "%USERPROFILE%\bili-sniffer\bilibili_sniffer.py" https://raw.githubusercontent.com/x0tuzi/bili-sniffer/main/bilibili_sniffer.py
```

每次使用前，先激活虚拟环境再运行：

```powershell
"%USERPROFILE%\bili-sniffer\Scripts\python" "%USERPROFILE%\bili-sniffer\bilibili_sniffer.py"
```

> 💡 觉得路径太长？在 PowerShell 里先跑一次下面这行，之后就能用 `bili-sniffer` 命令了：
> ```powershell
> echo 'python "%USERPROFILE%\bili-sniffer\bilibili_sniffer.py" %*' > "%USERPROFILE%\.local\bin\bili-sniffer.bat"
> ```

---

### 🍎 macOS 用户 — 三步安装

**第一步：打开终端**（在 启动台 → 其他 → 终端）

**第二步：创建虚拟环境并安装**

```bash
python3 -m venv ~/bili-sniffer
~/bili-sniffer/bin/pip install requests browser_cookie3 cryptography
```

**第三步：下载脚本**

```bash
curl -o ~/bili-sniffer/bilibili_sniffer.py https://raw.githubusercontent.com/x0tuzi/bili-sniffer/main/bilibili_sniffer.py
```

每次使用：

```bash
~/bili-sniffer/bin/python ~/bili-sniffer/bilibili_sniffer.py
```

> 💡 嫌路径太长？把下面这行加到 `~/.zshrc` 里，然后就能用 `bili-sniffer` 了：
> ```bash
> alias bili-sniffer='~/bili-sniffer/bin/python ~/bili-sniffer/bilibili_sniffer.py'
> ```

---

### 🐍 进阶：只用 .py 文件跑

适合已经会 Python 的用户，不依赖虚拟环境：

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
# 在 dist/ 里找到 bili-sniffer
```

---

## License

MIT
