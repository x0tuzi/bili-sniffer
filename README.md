# bili-sniffer

B站视频下载器 — 支持 API 获取全清晰度流地址、批量下载、弹幕/字幕提取。

## 安装

### Linux / macOS

```bash
curl -fsSL https://raw.githubusercontent.com/anomalyco/bili-sniffer/main/install.sh | bash
```

安装器提供三种方式:
- **单文件脚本** — 下载 `.py` + pip 安装依赖 (推荐)
- **Python 虚拟环境** — 独立 venv，含完整库，不污染系统 Python
- **预编译二进制** — PyInstaller 单文件，无需 Python

### Windows

```powershell
Invoke-WebRequest -Uri https://raw.githubusercontent.com/anomalyco/bili-sniffer/main/install.bat -OutFile install.bat; .\install.bat
```

### 手动

```bash
git clone https://github.com/anomalyco/bili-sniffer.git
cd bili-sniffer
pip install -r requirements.txt
python bilibili_sniffer.py
```

## 用法

```bash
bili-sniffer              # 交互模式 (推荐)
bili-sniffer BV1xx411c7mD # 命令行查看流地址
bili-sniffer --download BV1xx  # 命令行直接下载
bili-sniffer --sniff      # 抓包模式
```

### 交互命令

| 命令 | 说明 |
|---|---|
| `search <关键词>` | 搜索视频 |
| `hot` | 热门视频 |
| `info <BV\|URL\|#N>` | 视频详情 + 流地址 |
| `download <BV\|#N>` | 选择分P/清晰度下载 |
| `url <BV\|#N>` | 仅输出下载 URL |
| `daily` | 每日签到 (需Cookie) |
| `qadd <BV\|#N>` | 加入下载队列 |
| `qrun` / `qlist` / `qclear` | 队列管理 |
| `settings` | 统一设置 |
| `cookie auto` | 自动从浏览器提取 Cookie |

## 依赖

| 工具 | 用途 | 安装 |
|---|---|---|
| **ffmpeg** | 合并音视频 / 字幕 / 弹幕 | `sudo apt install ffmpeg` / `brew install ffmpeg` |
| **aria2c** | 多线程下载 (可选，提升速度) | `sudo apt install aria2` |
| requests | HTTP 请求 (必需) | pip |
| browser_cookie3 | 自动提取浏览器 Cookie (可选) | pip |

首次运行时会自动检测缺失工具并给出安装提示。

## 从源码构建二进制

```bash
pip install pyinstaller
pyinstaller --onefile --name bili-sniffer bilibili_sniffer.py
# 输出: dist/bili-sniffer
```

## License

MIT
