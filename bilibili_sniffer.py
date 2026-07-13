#!/usr/bin/env python3
"""
哔哩哔哩视频下载地址抓取工具
支持:
  1. API模式: 通过B站官方API获取所有清晰度的视频/音频流地址
  2. 抓包模式: 通过tcpdump/mitmproxy实时抓取HTTPS流量中的视频下载地址

用法:
  python bilibili_sniffer.py BV1xx411c7mD              # BV号
  python bilibili_sniffer.py https://bilibili.com/...   # 完整URL
  python bilibili_sniffer.py av12345678                 # AV号
  python bilibili_sniffer.py BV1xx -q 120 -c "cookie"   # 指定4K+Cookie
  python bilibili_sniffer.py --sniff                    # 抓包模式
  python bilibili_sniffer.py --list-qualities            # 查看清晰度代码
"""

import argparse
import base64
import glob
import json
import os
import platform
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import readline
from urllib.parse import urlparse, parse_qs

# ---------------------------------------------------------------------------
# 依赖检查
# ---------------------------------------------------------------------------
MISSING = []
try:
    import requests
except ImportError:
    MISSING.append('requests')
try:
    from cryptography import x509
    from cryptography.hazmat.backends import default_backend
except ImportError:
    MISSING.append('cryptography')

if MISSING:
    print(f"\033[33m[!] 缺少依赖: {', '.join(MISSING)}")
    print(f"    请运行: pip install {' '.join(MISSING)}\033[0m")
    # requests是硬依赖，cryptography仅抓包模式需要
    if 'requests' in MISSING:
        sys.exit(1)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/126.0.0.0 Safari/537.36'
    ),
    'Referer': 'https://www.bilibili.com/',
    'Origin': 'https://www.bilibili.com',
}

API_VIDEO_INFO = 'https://api.bilibili.com/x/web-interface/view'
API_PLAYURL    = 'https://api.bilibili.com/x/player/playurl'
API_SEARCH     = 'https://api.bilibili.com/x/web-interface/search/type'
API_POPULAR    = 'https://api.bilibili.com/x/web-interface/popular?pn=1&ps=50'

if platform.system() == 'Windows':
    _appdata = os.path.expandvars('%APPDATA%')
    CONFIG_FILE  = os.path.join(_appdata, 'bili_sniffer', 'config.json')
    HISTORY_FILE = os.path.join(_appdata, 'bili_sniffer', 'history')
    DEFAULT_DL_DIR = os.path.join(os.path.expanduser('~'), 'Downloads', 'bilibili_downloads')
else:
    CONFIG_FILE  = os.path.expanduser('~/.config/bili_sniffer.json')
    HISTORY_FILE = os.path.expanduser('~/.bili_sniffer_history')
    DEFAULT_DL_DIR = os.path.expanduser('~/bilibili_downloads')

VERSION = "1.1.4"
GITHUB_REPO     = "x0tuzi/bili-sniffer"
GITHUB_API      = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
GITHUB_RAW      = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main"

API_NAV_STAT    = 'https://api.bilibili.com/x/web-interface/nav/stat'
API_DAILY_CLICK = 'https://api.bilibili.com/x/report/click/now'

# 清晰度代号 -> 中文描述
QUALITY_MAP = {
    127: '8K 超高清',
    126: '杜比视界',
    125: 'HDR 真彩',
    120: '4K 超清',
    116: '1080P 60帧',
    112: '1080P 高码率',
    80:  '1080P 高清',
    74:  '720P 60帧',
    64:  '720P 高清',
    48:  '720P 高清(旧)',
    32:  '480P 清晰',
    16:  '360P 流畅',
    6:   '240P 极速',
    208: 'HDR(旧)',
}

# ---------------------------------------------------------------------------
# 会话状态 + 配置持久化
# ---------------------------------------------------------------------------

SESSION = {
    'cookie': '', 'quality': 80, 'download_dir': DEFAULT_DL_DIR,
    'last_bvid': None, 'last_info': None,
    'last_search_results': [], 'last_hot_results': [],
    'auto_delete_m4s': False,
    'download_subtitle': False,
    'download_danmaku': False,
    'download_cover': False,
    'notify': False,
    'retry_count': 2,
    'save_cookie': False,
    'auto_mux_subtitle': False,
    'auto_mux_danmaku': False,
    'download_queue': [],
    'search_page': 1,
    'search_keyword': '',
    'search_total_pages': 1,
}

CONFIG_KEYS = [
    'quality', 'download_dir', 'auto_delete_m4s',
    'download_subtitle', 'download_danmaku', 'download_cover', 'notify', 'retry_count',
    'save_cookie', 'auto_mux_subtitle', 'auto_mux_danmaku',
]

def load_config():
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                cfg = json.load(f)
            for k in CONFIG_KEYS:
                if k in cfg:
                    SESSION[k] = cfg[k]
            if cfg.get('save_cookie') and 'cookie' in cfg:
                SESSION['cookie'] = cfg['cookie']
        except Exception:
            pass

def save_config():
    cfg = {}
    for k in CONFIG_KEYS:
        cfg[k] = SESSION.get(k)
    if SESSION.get('save_cookie') and SESSION.get('cookie'):
        cfg['cookie'] = SESSION['cookie']
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)

# ---------------------------------------------------------------------------
# API 重试封装
# ---------------------------------------------------------------------------

def retry_call(func, *args, **kwargs):
    max_retries = SESSION.get('retry_count', 2)
    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            if attempt < max_retries:
                wait = 2 ** attempt
                print(yellow(f"  [!] 网络错误，{wait}s后重试({attempt+1}/{max_retries})..."))
                time.sleep(wait)
            else:
                raise
        except requests.exceptions.HTTPError:
            raise

# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def red(s):   return f"\033[31m{s}\033[0m"
def green(s): return f"\033[32m{s}\033[0m"
def yellow(s):return f"\033[33m{s}\033[0m"
def cyan(s):  return f"\033[36m{s}\033[0m"
def bold(s):  return f"\033[1m{s}\033[0m"
def dim(s):   return f"\033[90m{s}\033[0m"

def format_size(n):
    for u in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TB"

def format_duration(ms):
    s = ms // 1000
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    return f"{m:02d}:{s:02d}"

def extract_video_id(raw: str):
    """从输入字符串中提取 BV号 或 AV号"""
    bv = re.search(r'(BV[a-zA-Z0-9]{10})', raw, re.IGNORECASE)
    if bv:
        return bv.group(1)
    av = re.search(r'av(\d+)', raw, re.IGNORECASE)
    if av:
        return f"av{av.group(1)}"
    if re.match(r'^[aA][vV]\d+$', raw):
        return raw.lower()
    if re.match(r'^BV[a-zA-Z0-9]{10}$', raw, re.IGNORECASE):
        return raw
    return None

def sanitize_filename(s):
    return re.sub(r'[\\/:*?"<>|]', '_', s).strip()

def format_srt_time(seconds):
    ms = int((seconds - int(seconds)) * 1000)
    h, remainder = divmod(int(seconds), 3600)
    m, s = divmod(remainder, 60)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def _extract_csrf(cookie_str):
    for part in cookie_str.split(';'):
        part = part.strip()
        if part.startswith('bili_jct='):
            return part.split('=', 1)[1]
    return ''

def make_cookie_headers(cookie=''):
    h = HEADERS.copy()
    if cookie:
        h['Cookie'] = cookie
    h['Cookie'] = h.get('Cookie', '') + '; platform=pc'
    return h

# ---------------------------------------------------------------------------
# API 模式 (核心)
# ---------------------------------------------------------------------------

def api_get_video_info(video_id: str):
    """获取视频基本信息 (标题, 分P, 封面等)"""
    p = {}
    if video_id.startswith(('BV', 'bv')):
        p['bvid'] = video_id
    else:
        p['aid'] = video_id.lower().lstrip('av')

    resp = requests.get(API_VIDEO_INFO, params=p, headers=HEADERS, timeout=15)
    data = resp.json()
    if data['code'] != 0:
        raise RuntimeError(f"API错误: code={data['code']} msg={data.get('message','')}")
    return data['data']


def api_get_playurl(bvid: str, cid: int, cookie='', quality=127):
    """获取指定清晰度的视频流播放地址"""
    params = {
        'bvid': bvid,
        'cid': cid,
        'qn': quality,
        'type': '',
        'otype': 'json',
        'fnval': 4048,   # dash + flac + dolby + 8k
        'fnver': 0,
        'fourk': 1,
    }
    h = HEADERS.copy()
    if cookie:
        h['Cookie'] = cookie
    h['Cookie'] = h.get('Cookie', '') + '; platform=pc'

    resp = requests.get(API_PLAYURL, params=params, headers=h, timeout=15)
    data = resp.json()
    if data['code'] != 0:
        raise RuntimeError(f"播放地址API错误: code={data['code']} msg={data.get('message','')}")
    return data['data']


def api_get_subtitle(bvid: str, cid: int, cookie=''):
    """从 player/v2 获取字幕列表（playurl不返回字幕，需要单独请求）"""
    h = HEADERS.copy()
    if cookie:
        h['Cookie'] = cookie
    resp = requests.get(f'https://api.bilibili.com/x/player/v2?bvid={bvid}&cid={cid}', headers=h, timeout=15)
    data = resp.json()
    if data['code'] != 0:
        return None
    return data['data'].get('subtitle')


def api_get_danmaku(bvid: str, cid: int, cookie=''):
    """获取弹幕XML（/x/v1/dm/list.so）"""
    h = HEADERS.copy()
    if cookie:
        h['Cookie'] = cookie
    resp = requests.get(f'https://api.bilibili.com/x/v1/dm/list.so?oid={cid}', headers=h, timeout=15)
    resp.encoding = 'utf-8'
    return resp.text


def parse_playurl(play_data: dict):
    """从 playurl 返回数据中提取所有可下载URL"""
    result = {'dash': {'video': [], 'audio': []}, 'durl': [], 'subtitle': None}

    dash = play_data.get('dash')
    if dash:
        for v in dash.get('video', []):
            item = {
                'id':        v.get('id'),
                'quality':   QUALITY_MAP.get(v.get('id'), f"未知({v.get('id')})"),
                'codecs':    v.get('codecs', ''),
                'codecid':   v.get('codecid'),
                'width':     v.get('width'),
                'height':    v.get('height'),
                'frameRate': v.get('frameRate'),
                'bandwidth': v.get('bandwidth'),
                'urls':      [v.get('baseUrl', '')] + (v.get('backupUrl', []) or v.get('backup_url', [])),
            }
            item['urls'] = [u for u in item['urls'] if u]
            result['dash']['video'].append(item)

        for a in dash.get('audio', []):
            item = {
                'id':        a.get('id'),
                'codecs':    a.get('codecs', ''),
                'bandwidth': a.get('bandwidth'),
                'urls':      [a.get('baseUrl', '')] + (a.get('backupUrl', []) or a.get('backup_url', [])),
            }
            item['urls'] = [u for u in item['urls'] if u]
            result['dash']['audio'].append(item)

    durl = play_data.get('durl')
    if durl:
        for d in durl:
            result['durl'].append({
                'order':  d.get('order'),
                'length': d.get('length'),
                'size':   d.get('size'),
                'urls':   [d.get('url', '')] + (d.get('backup_url', []) or []),
            })

    subtitle = play_data.get('subtitle')
    if subtitle:
        sub_list = subtitle.get('subtitles', []) or subtitle.get('list', [])
        if sub_list:
            result['subtitle'] = sub_list

    return result


def api_search(keyword, cookie='', page=1):
    params = {'search_type': 'video', 'keyword': keyword,
              'page': page, 'order': 'totalrank'}
    h = HEADERS.copy()
    if cookie:
        h['Cookie'] = cookie
    resp = requests.get(API_SEARCH, params=params, headers=h, timeout=15)
    try:
        data = resp.json()
    except Exception:
        raise RuntimeError(f"搜索失败: 服务器返回非JSON (HTTP {resp.status_code})")
    if data.get('code') != 0:
        raise RuntimeError(f"搜索失败: {data.get('message','?')}")
    return data.get('data', {})

def api_popular(cookie=''):
    h = HEADERS.copy()
    if cookie:
        h['Cookie'] = cookie
    resp = requests.get(API_POPULAR, headers=h, timeout=15)
    try:
        data = resp.json()
    except Exception:
        raise RuntimeError(f"获取热门失败: 服务器返回非JSON (HTTP {resp.status_code})")
    if data.get('code') != 0:
        raise RuntimeError(f"获取热门失败: {data.get('message','?')}")
    return data.get('data', {})

def api_nav_stat(cookie=''):
    h = HEADERS.copy()
    if cookie:
        h['Cookie'] = cookie
    resp = requests.get(API_NAV_STAT, headers=h, timeout=15)
    try:
        data = resp.json()
    except Exception:
        raise RuntimeError(f"获取用户状态失败: HTTP {resp.status_code}")
    if data.get('code') != 0:
        raise RuntimeError(f"获取用户状态失败: {data.get('message','?')}")
    return data.get('data', {})

def api_daily_click(cookie=''):
    h = HEADERS.copy()
    if cookie:
        h['Cookie'] = cookie
    h['Referer'] = 'https://www.bilibili.com/'
    csrf = _extract_csrf(cookie)
    resp = requests.post(API_DAILY_CLICK, data={'csrf': csrf}, headers=h, timeout=15)
    try:
        return resp.json()
    except Exception:
        raise RuntimeError(f"签到请求失败: HTTP {resp.status_code}")

# ---------------------------------------------------------------------------
# 打印/展示
# ---------------------------------------------------------------------------

def print_video_info(info):
    bvid   = info.get('bvid', '?')
    title  = info.get('title', 'N/A')
    owner  = info.get('owner', {}).get('name', 'N/A')
    desc   = info.get('desc', '')
    pages  = info.get('pages', [])
    dur_ms = sum(p.get('duration', 0) for p in pages)
    print(bold(f"\n{'='*60}"))
    print(f"  {cyan('标题')}: {title}")
    print(f"  {cyan('UP主')}: {owner}")
    print(f"  {cyan('BV号')}: {bvid}")
    print(f"  {cyan('时长')}: {format_duration(dur_ms)}")
    print(f"  {cyan('分P数')}: {len(pages)}")
    if desc:
        ds = desc[:120] + ('...' if len(desc) > 120 else '')
        print(f"  {cyan('简介')}: {ds}")
    for i, p in enumerate(pages):
        part = p.get('part', f'P{i+1}')
        d = format_duration(p.get('duration', 0))
        print(f"  {cyan(f'  P{i+1}')}: {part} ({d}  CID:{p['cid']})")
    print(bold(f"{'='*60}"))

def print_stream_urls(info, cookie='', quality=127):
    bvid = info['bvid']
    pages = info.get('pages', [])
    for idx, page in enumerate(pages):
        cid  = page['cid']
        part = page.get('part', f'P{idx+1}')
        dur  = format_duration(page.get('duration', 0))
        print(f"\n{green(f'[{idx+1}/{len(pages)}] {part}')}  ({dur}  CID:{cid})")
        try:
            play = api_get_playurl(bvid, cid, cookie, quality)
        except RuntimeError as e:
            print(f"  {red('x')} {e}")
            continue
        parsed = parse_playurl(play)
        aq = play.get('accept_quality', [])
        if aq:
            print(f"  {cyan('可用清晰度')}: {', '.join(f'{q}({QUALITY_MAP.get(q,q)})' for q in aq)}")
        if parsed['dash']['video']:
            print(f"  {cyan('[DASH 视频流]')}")
            for v in parsed['dash']['video']:
                bw = f"{v['bandwidth']//1000} kbps" if v['bandwidth'] else '?'
                res = f"{v['width'] or '?'}x{v['height'] or '?'}"
                print(f"    {v['quality']:12s} | {v['codecs']:20s} | {res:10s} | {bw}")
                for i, url in enumerate(v['urls']):
                    print(f"      [{i+1}] {url}")
        if parsed['dash']['audio']:
            print(f"  {cyan('[DASH 音频流]')}")
            for a in parsed['dash']['audio']:
                bw = f"{a['bandwidth']//1000} kbps" if a['bandwidth'] else '?'
                print(f"    {a['codecs']:20s} | {bw}")
                for i, url in enumerate(a['urls']):
                    print(f"      [{i+1}] {url}")
        if parsed['durl']:
            total = sum(d.get('size', 0) or 0 for d in parsed['durl'])
            print(f"  {cyan('[FLV 分段流]')} ({len(parsed['durl'])}段, 共{format_size(total)})")
            for d in parsed['durl'][:3]:
                url = d['urls'][0] if d['urls'] else ''
                sz = format_size(d.get('size', 0) or 0)
                print(f"    段{d['order']:02d} ({sz}) => {url[:100]}...")
            if len(parsed['durl']) > 3:
                print(f"    ... 还有 {len(parsed['durl'])-3} 段")
        aq_actual = play.get('quality')
        if aq_actual != quality:
            print(f"  {yellow(f'[!] 实际获{aq_actual}({QUALITY_MAP.get(aq_actual,aq_actual)})')}")


# ---------------------------------------------------------------------------
# 下载功能
# ---------------------------------------------------------------------------

def find_downloader():
    """检测可用下载器，返回优先级列表"""
    dl = []
    if shutil.which('aria2c'): dl.append('aria2c')
    if shutil.which('wget'):   dl.append('wget')
    if shutil.which('curl'):   dl.append('curl')
    return dl

def download_file(url, out_path, referer='https://www.bilibili.com/'):
    """下载文件，自动选择最佳下载器，支持回退"""
    filename = os.path.basename(out_path)
    out_dir  = os.path.dirname(out_path) or '.'
    dl = find_downloader()

    def _run_aria2c():
        subprocess.run(['aria2c','-c','-x4','-s4','--referer',referer,
                        '-d',out_dir,'-o',filename,url], check=True)
    def _run_wget():
        subprocess.run(['wget','-c','--referer',referer,'-O',out_path,url], check=True)
    def _run_curl():
        subprocess.run(['curl','-L','-C','-','-H',f'Referer: {referer}',
                        '-H',f'User-Agent: {HEADERS["User-Agent"]}',
                        '-o',out_path,url], check=True)

    print(cyan(f"[*] 下载: {url[:80]}..."))
    runners = {'aria2c':_run_aria2c,'wget':_run_wget,'curl':_run_curl}
    for name in dl:
        try:
            runners[name]()
            print(green(f"[+] 完成: {out_path}"))
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            print(yellow(f"\n[!] {name} 失败，尝试下一方案..."))
    # fallback: python
    print(yellow("[*] 使用 Python 原生下载..."))
    try:
        return _download_python(url, out_path, referer)
    except KeyboardInterrupt:
        raise
    except Exception as e:
        print(red(f"[-] Python下载失败: {e}")); return False

def _download_python(url, out_path, referer):
    h = HEADERS.copy(); h['Referer'] = referer
    try:
        resp = requests.get(url, headers=h, stream=True, timeout=120)
        resp.raise_for_status()
        total = int(resp.headers.get('content-length', 0))
        dl = 0
        with open(out_path, 'wb') as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk); dl += len(chunk)
                if total:
                    pct = dl/total*100
                    print(f"\r  进度: {pct:.1f}% ({dl/1048576:.1f}/{total/1048576:.1f} MB)",
                          end='', flush=True)
        if total: print()
        print(green(f"[+] 完成: {out_path}"))
        return True
    except Exception as e:
        print(red(f"[-] 下载失败: {e}"))
        return False

def merge_dash(video_path, audio_path, out_path):
    if not shutil.which('ffmpeg'):
        print(yellow("[!] ffmpeg 未安装，无法合并。文件已保留:"));
        print(f"  视频: {video_path}"); print(f"  音频: {audio_path}")
        return False
    cmd = ['ffmpeg','-y','-i',video_path,'-i',audio_path,'-c','copy',out_path]
    print(cyan(f"[*] 合并: -> {out_path}"))
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        print(green(f"[+] 合并完成: {out_path}")); return True
    except subprocess.CalledProcessError as e:
        print(red(f"[-] 合并失败: {e}")); return False

def _download_subtitle(bvid, cid, play_data, out_dir, dl_name):
    subtitle = play_data.get('subtitle')
    if not subtitle:
        return
    sub_list = subtitle.get('subtitles', []) or subtitle.get('list', [])
    if not sub_list:
        return
    for i, sub in enumerate(sub_list):
        sub_url = sub.get('subtitle_url', '')
        if not sub_url:
            continue
        if sub_url.startswith('//'):
            sub_url = 'https:' + sub_url
        lang = sub.get('lan_doc', sub.get('lan', 'zh'))
        print(cyan(f"  [*] 下载字幕: {lang}"))
        try:
            resp = requests.get(sub_url, headers=HEADERS, timeout=15)
            sj = resp.json()
            if i == 0:
                srt_path = os.path.join(out_dir, f"{dl_name}.srt")
            else:
                srt_path = os.path.join(out_dir, f"{dl_name}_{lang}.srt")
            with open(srt_path, 'w', encoding='utf-8') as f:
                body = sj.get('body', [])
                for i, seg in enumerate(body, 1):
                    f.write(f"{i}\n")
                    f.write(f"{format_srt_time(seg.get('from', 0))} --> {format_srt_time(seg.get('to', 0))}\n")
                    f.write(f"{seg.get('content', '')}\n\n")
            print(green(f"  [+] 字幕: {srt_path}"))
        except Exception as e:
            print(yellow(f"  [!] 字幕下载失败: {e}"))

def _format_ass_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds - int(seconds)) * 100)
    return f'{h}:{m:02d}:{s:02d}.{cs:02d}'

def _download_danmaku(bvid, cid, out_dir, dl_name):
    print(cyan(f"  [*] 下载弹幕..."))
    try:
        xml_text = api_get_danmaku(bvid, cid, SESSION['cookie'])
    except Exception as e:
        print(yellow(f"  [!] 弹幕下载失败: {e}"))
        return
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_text)
    except Exception as e:
        print(yellow(f"  [!] 弹幕解析失败: {e}"))
        return
    d_elements = root.findall('d')
    if not d_elements:
        print(yellow("  [!] 无弹幕"))
        return
    lines = []
    lines.append('[Script Info]')
    lines.append('Title: Bilibili Danmaku')
    lines.append('ScriptType: v4.00+')
    lines.append('PlayResX: 1920')
    lines.append('PlayResY: 1080')
    lines.append('WrapStyle: 2')
    lines.append('')
    lines.append('[V4+ Styles]')
    lines.append('Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding')
    lines.append('Style: R2L,Microsoft YaHei,36,&H99FFFFFF,&H99FFFFFF,&H99000000,&H99000000,0,0,0,0,100,100,0,0,1,1.5,0,7,0,0,0,1')
    lines.append('Style: TOP,Microsoft YaHei,36,&H99FFFFFF,&H99FFFFFF,&H99000000,&H99000000,0,0,0,0,100,100,0,0,1,1.5,0,7,0,0,0,1')
    lines.append('Style: BTM,Microsoft YaHei,36,&H99FFFFFF,&H99FFFFFF,&H99000000,&H99000000,0,0,0,0,100,100,0,0,1,1.5,0,7,0,0,0,1')
    lines.append('')
    lines.append('[Events]')
    lines.append('Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text')
    for d in d_elements:
        p_attr = d.get('p', '')
        text = d.text or ''
        if not p_attr or not text:
            continue
        parts = p_attr.split(',')
        if len(parts) < 6:
            continue
        try:
            time_s = float(parts[0])
            mode = int(parts[1])
            size = int(parts[2])
            color_dec = int(parts[3])
        except (ValueError, IndexError):
            continue
        b = (color_dec >> 16) & 0xFF
        g = (color_dec >> 8) & 0xFF
        r = color_dec & 0xFF
        c = f'\\c&H{b:02X}{g:02X}{r:02X}&'
        fs = max(20, min(size + 10, 64))
        start_t = _format_ass_time(time_s)
        if mode <= 3:
            end_t = _format_ass_time(time_s + 9)
            style = 'R2L'
            body = f'{{\\move(1920,0,-{len(text)*fs},0)\\fs{fs}{c}}}{text}'
        elif mode == 4:
            end_t = _format_ass_time(time_s + 5)
            style = 'BTM'
            body = f'{{\\fs{fs}{c}}}{text}'
        elif mode == 5:
            end_t = _format_ass_time(time_s + 5)
            style = 'TOP'
            body = f'{{\\fs{fs}{c}}}{text}'
        else:
            end_t = _format_ass_time(time_s + 9)
            style = 'R2L'
            body = f'{{\\move(1920,0,-{len(text)*fs},0)\\fs{fs}{c}}}{text}'
        lines.append(f'Dialogue: 0,{start_t},{end_t},{style},,0,0,0,,{body}')
    ass_path = os.path.join(out_dir, f'{dl_name}.ass')
    with open(ass_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print(green(f'  [+] 弹幕: {ass_path} ({len(d_elements)}条)'))

def _download_cover(pic_url, out_dir, dl_name):
    if not pic_url:
        return
    if pic_url.startswith('//'):
        pic_url = 'https:' + pic_url
    ext = '.jpg'
    if '.png' in pic_url:
        ext = '.png'
    elif '.webp' in pic_url:
        ext = '.webp'
    cover_path = os.path.join(out_dir, f"{dl_name}_cover{ext}")
    print(cyan(f"  [*] 下载封面..."))
    try:
        download_file(pic_url, cover_path)
    except KeyboardInterrupt:
        raise
    except Exception as e:
        print(yellow(f"  [!] 封面下载失败: {e}"))

def _mux_subtitles(video_path, sub_path, danmaku_path):
    has_sub = sub_path and os.path.exists(sub_path)
    has_danmu = danmaku_path and os.path.exists(danmaku_path)
    if not has_sub and not has_danmu:
        return
    if not shutil.which('ffmpeg'):
        print(yellow("  [!] ffmpeg未安装，跳过合并"))
        return
    inputs = ['-i', video_path]
    maps = ['-map', '0']
    if has_sub:
        inputs.extend(['-i', sub_path])
        maps.extend(['-map', '1'])
    if has_danmu:
        inputs.extend(['-i', danmaku_path])
        maps.extend(['-map', str(len(maps))])
    if has_danmu:
        out_ext = '.mkv'
        codec_args = ['-c', 'copy']
    else:
        out_ext = '.mp4'
        codec_args = ['-c', 'copy', '-c:s', 'mov_text']
    print(cyan(f"  [*] 合并字幕/弹幕到视频..."))
    tmp_out = video_path + f'_muxing_tmp{out_ext}'
    cmd = ['ffmpeg', '-y'] + inputs + codec_args + maps + [tmp_out]
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode == 0 and os.path.exists(tmp_out) and os.path.getsize(tmp_out) > 0:
        os.remove(video_path)
        final_out = os.path.splitext(video_path)[0] + out_ext
        os.rename(tmp_out, final_out)
        if has_sub:
            os.remove(sub_path)
        if has_danmu:
            os.remove(danmaku_path)
        print(green(f"  [+] 已合并并删除源文件: {final_out}"))
    else:
        if os.path.exists(tmp_out):
            os.remove(tmp_out)
        print(yellow("  [!] 合并失败，保留原始文件"))

def _notify(title, message):
    if SESSION.get('notify') and shutil.which('notify-send'):
        subprocess.run(['notify-send', '--app-name=bili_sniffer', title, message],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

BILIVIDEO_URL_RE = re.compile(
    r'(https?://[^\s"\'\\<>]*'
    r'(?:bilivideo\.com|hdslb\.com|biliapi\.net)'
    r'[^\s"\'\\<>]*)',
    re.IGNORECASE
)


def sniff_tcpdump(interface: str, timeout: int, port: int):
    """后台运行 tcpdump，解析输出中的B站视频URL"""
    if shutil.which('tcpdump') is None:
        print(red("✗ tcpdump 未安装，请安装: sudo apt install tcpdump (或对应包管理器)"))
        return []

    cmd = [
        'tcpdump',
        '-i', interface,
        '-A',           # ASCII 输出
        '-s', '0',      # 完整包内容
        '-n',           # 不解析域名
        f'port {port}',
        '-l',           # 行缓冲
    ]

    print(yellow(f"[*] 启动 tcpdump (接口:{interface}, 端口:{port}, "
                 f"超时:{timeout}s)"))
    print(yellow("[*] 请在浏览器中打开哔哩哔哩视频页面播放视频..."))
    print(yellow("[*] 按 Ctrl+C 提前停止\n"))

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
    except PermissionError:
        print(red("✗ 需要 root 权限。请用 sudo 运行此脚本，或执行:"))
        print(red("  sudo setcap cap_net_raw=+eip $(which tcpdump)"))
        return []

    found = set()
    start = time.time()

    try:
        for line in iter(proc.stdout.readline, ''):
            if time.time() - start > timeout:
                print(yellow("\n[*] 抓包超时，停止"))
                break

            for m in BILIVIDEO_URL_RE.finditer(line):
                url = m.group(1).rstrip('\\').rstrip('"').rstrip("'")
                if url not in found:
                    found.add(url)
                    print(f"{green('[+]')} {url}")
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
        proc.wait(timeout=3)

    return list(found)


# ---------------------------------------------------------------------------
# 抓包模式 (mitmproxy) - 更精准的HTTPS抓包
# ---------------------------------------------------------------------------

def sniff_mitmproxy(timeout: int):
    """使用 mitmproxy Python API 进行HTTPS抓包"""
    try:
        from mitmproxy import options
        from mitmproxy.master import Master
        from mitmproxy import http
    except ImportError:
        print(red("✗ mitmproxy 未安装，请运行: pip install mitmproxy"))
        print(yellow("  注意: mitmproxy 需要额外安装CA证书才能解密HTTPS"))
        return []

    if shutil.which('mitmdump') is None:
        print(red("✗ mitmdump 未在PATH中找到"))
        return []

    urls = set()

    class BiliAddon:
        def response(self, flow: http.HTTPFlow):
            url = flow.request.pretty_url
            # 匹配B站视频CDN域名
            if re.search(r'bilivideo\.com|hdslb\.com', url):
                if url not in urls:
                    urls.add(url)
                    print(f"{green('[+]')} {url}")
            # 也匹配含有 .mp4 / .m4s / .flv 的响应
            ct = flow.response.headers.get('content-type', '')
            if any(ext in url for ext in ('.mp4', '.m4s', '.flv')):
                if url not in urls:
                    urls.add(url)
                    print(f"{green('[+]')} {url}")

    print(yellow("[*] 启动 mitmproxy 抓包..."))
    print(yellow(f"[*] 将在 {timeout}s 后自动停止"))
    print(yellow("[*] 请确保浏览器已配置代理 127.0.0.1:8080 并信任 mitmproxy CA证书\n"))

    # 使用 mitmdump 子进程方式更简单可靠
    cmd = [
        'mitmdump', '-q', '--ignore-hosts', '^(?!.*(bilivideo|hdslb|bilibili)).*$',
        '-s', '-',
    ]

    start = time.time()
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )

        while time.time() - start < timeout:
            try:
                proc.wait(timeout=1)
                break
            except subprocess.TimeoutExpired:
                continue

        proc.terminate()
    except Exception as e:
        print(f"mitmproxy 错误: {e}")

    return list(urls)


# ---------------------------------------------------------------------------
# 从浏览器自动提取 B站 Cookie
# ---------------------------------------------------------------------------

def _get_chrome_key_from_local_state(base_path):
    ls = os.path.join(base_path, 'Local State')
    if not os.path.isfile(ls):
        return None
    with open(ls, 'r', encoding='utf-8') as f:
        state = json.load(f)
    enc_key_b64 = state.get('os_crypt', {}).get('encrypted_key')
    if not enc_key_b64:
        return None
    return base64.b64decode(enc_key_b64)[5:]  # strip 'DPAPI' prefix


def _get_chrome_key_from_keyring():
    try:
        import gi
        gi.require_version('Secret', '1')
        from gi.repository import Secret
        schema = Secret.Schema.new('chrome_libsecret_os_crypt_password_v2',
            Secret.SchemaFlags.NONE,
            {'application': Secret.SchemaAttributeType.STRING})
        results = Secret.password_search_sync(schema, {'application': 'chrome'},
            Secret.SearchFlags.ALL | Secret.SearchFlags.UNLOCK |
            Secret.SearchFlags.LOAD_SECRETS, None)
        if results:
            secret_val = results[0].retrieve_secret_sync()
            val = secret_val.get_text()
            return base64.b64decode(val)
    except Exception:
        pass
    return None


def _decrypt_chrome_value(enc_val, key):
    if not isinstance(enc_val, bytes):
        try:
            return enc_val.decode('utf-8')
        except Exception:
            return None

    if not enc_val[:2] == b'v1':    # v10 or v11
        try:
            return enc_val.decode('utf-8')
        except Exception:
            return None

    if not key:
        return None

    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        nonce = enc_val[3:15]
        ciphertext = enc_val[15:]

        for derived in [key, key[:32]]:
            try:
                aesgcm = AESGCM(derived)
                return aesgcm.decrypt(nonce, ciphertext, None).decode('utf-8')
            except Exception:
                continue
    except Exception:
        pass
    return None


def _read_chrome_cookies(base_path):
    key = _get_chrome_key_from_local_state(base_path)
    if not key:
        key = _get_chrome_key_from_keyring()

    profiles = ['Default'] + [d for d in os.listdir(base_path)
                              if d.startswith('Profile ') or d.startswith('Profile')]

    for profile in profiles:
        for db_name in ['Network/Cookies', 'Cookies']:
            db_path = os.path.join(base_path, profile, db_name)
            if not os.path.isfile(db_path):
                continue
            try:
                shutil.copy2(db_path, '/tmp/bili_cookies.db')
                sqlite3.connect('/tmp/bili_cookies.db').close()
                conn = sqlite3.connect('/tmp/bili_cookies.db')
                cur = conn.cursor()
                cur.execute("SELECT host_key, name, encrypted_value FROM cookies WHERE host_key LIKE '%bilibili%'")
                rows = cur.fetchall()
                conn.close()

                cookies = {}
                for host, name, enc_val in rows:
                    value = _decrypt_chrome_value(enc_val, key)
                    if value:
                        cookies[name] = value

                if cookies and cookies.get('SESSDATA'):
                    return cookies
            except Exception:
                continue
    return None


def _read_firefox_cookies(base_path):
    for profile in glob.glob(os.path.join(base_path, '*.default*')):
        db = os.path.join(profile, 'cookies.sqlite')
        if not os.path.isfile(db):
            continue
        try:
            shutil.copy2(db, '/tmp/bili_ff_cookies.db')
            conn = sqlite3.connect('/tmp/bili_ff_cookies.db')
            cur = conn.cursor()
            cur.execute("SELECT host, name, value FROM moz_cookies WHERE host LIKE '%bilibili%'")
            rows = cur.fetchall()
            conn.close()
            cookies = {name: val for _, name, val in rows}
            if cookies.get('SESSDATA'):
                return cookies
        except Exception:
            continue
    return None


def _get_browser_dirs():
    system = platform.system()
    browsers = []

    if system == 'Linux':
        browsers = [
            ('Google Chrome', '~/.config/google-chrome', 'chrome'),
            ('Chromium',       '~/.config/chromium', 'chrome'),
            ('Microsoft Edge', '~/.config/microsoft-edge', 'chrome'),
            ('Brave',          '~/.config/Brave-Browser', 'chrome'),
            ('Vivaldi',        '~/.config/vivaldi', 'chrome'),
            ('Opera',          '~/.config/opera', 'chrome'),
            ('Firefox',        '~/.mozilla/firefox', 'firefox'),
        ]
        for flat_dir in glob.glob(os.path.expanduser('~/.var/app/com.*')):
            for sub in ['config/google-chrome', 'config/chromium']:
                browsers.append(('Chrome (Flatpak)', os.path.join(flat_dir, sub), 'chrome'))
    elif system == 'Darwin':
        browsers = [
            ('Google Chrome', '~/Library/Application Support/Google/Chrome', 'chrome'),
            ('Chromium',       '~/Library/Application Support/Chromium', 'chrome'),
            ('Microsoft Edge', '~/Library/Application Support/Microsoft Edge', 'chrome'),
            ('Brave',          '~/Library/Application Support/BraveSoftware/Brave-Browser', 'chrome'),
            ('Firefox',        '~/Library/Application Support/Firefox/Profiles', 'firefox'),
        ]
    elif system == 'Windows':
        browsers = [
            ('Google Chrome', '%LOCALAPPDATA%\\Google\\Chrome\\User Data', 'chrome'),
            ('Chromium',       '%LOCALAPPDATA%\\Chromium\\User Data', 'chrome'),
            ('Microsoft Edge', '%LOCALAPPDATA%\\Microsoft\\Edge\\User Data', 'chrome'),
            ('Brave',          '%LOCALAPPDATA%\\BraveSoftware\\Brave-Browser\\User Data', 'chrome'),
            ('Firefox',        '%APPDATA%\\Mozilla\\Firefox\\Profiles', 'firefox'),
        ]

    available = []
    for name, path, btype in browsers:
        expanded = os.path.expanduser(os.path.expandvars(path))
        if os.path.isdir(expanded):
            available.append((name, expanded, btype))
    return available


def _extract_from_browser(base_path, btype):
    if btype == 'chrome':
        return _read_chrome_cookies(base_path)
    elif btype == 'firefox':
        return _read_firefox_cookies(base_path)
    return None


def _extract_with_browser_cookie3(browser_name=None):
    try:
        import browser_cookie3
    except ImportError:
        return None

    browser_map = {
        'google chrome':  browser_cookie3.chrome,
        'chromium':       browser_cookie3.chromium,
        'microsoft edge': browser_cookie3.edge,
        'brave':          browser_cookie3.brave,
        'opera':          browser_cookie3.opera,
        'firefox':        browser_cookie3.firefox,
    }

    targets = [(browser_name, browser_map.get(browser_name.lower()))] if browser_name else browser_map.items()

    for name, getter in targets:
        if not getter:
            continue
        try:
            cj = getter()
            cookies = {}
            for c in cj:
                if 'bilibili' in c.domain:
                    cookies[c.name] = c.value
            if cookies.get('SESSDATA'):
                return name, cookies
        except Exception:
            continue
    return None


def _cookie_auto():
    print(cyan("[*] 正在扫描浏览器..."))

    has_bc3 = False
    try:
        import browser_cookie3
        has_bc3 = True
    except ImportError:
        pass

    system = platform.system()
    if not has_bc3:
        if system == 'Darwin':
            print(red("[-] macOS 手动提取Cookie需要 Keychain 权限，请安装 browser_cookie3"))
            print(yellow("      pip install browser_cookie3"))
            return False
        if system == 'Windows':
            print(red("[-] Windows 手动提取Cookie需要 win32crypt/DPAPI，请安装 browser_cookie3"))
            print(yellow("      pip install browser_cookie3"))
            return False

    browsers = _get_browser_dirs()

    entries = []
    for i, (name, path, btype) in enumerate(browsers):
        entries.append((i + 1, name, path, btype))

    if has_bc3:
        # also add browsers that browser_cookie3 supports but no dir found
        known = {'google chrome', 'chromium', 'microsoft edge', 'brave', 'opera', 'firefox'}
        found_names = {e[1].lower() for e in entries}
        for extra_name in known - found_names:
            entries.append((len(entries) + 1, extra_name.title(), '', ''))

    if not entries:
        print(red("[-] 未检测到可用浏览器"))
        print(yellow("    pip install browser_cookie3  (推荐，跨平台自动解密)"))
        print(yellow("    或手动设置: cookie SESSDATA=xxx; bili_jct=xxx"))
        return False

    print(bold(f"\n  可用浏览器:"))
    for num, name, _path, _btype in entries:
        method = "browser_cookie3" if has_bc3 else "手动提取"
        print(f"    [{cyan(str(num))}] {name}  ({method})")
    print(f"    [{cyan('A')}] 尝试全部")
    if has_bc3:
        print(f"\n  {yellow('⚠ 手动提取仅 Linux Chrome/Firefox 可用，推荐安装 browser_cookie3')}")
    else:
        print(f"\n  {yellow('⚠ 手动提取: Linux Chrome <v130 + Firefox 可行。Chrome 130+ 需 keyring 已解锁。')}")
    print()

    try:
        choice = input(f"  选择浏览器 [1-{len(entries)}/A] (回车取消): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not choice:
        return False

    if choice.upper() == 'A':
        chosen = entries
    else:
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(entries):
                chosen = [entries[idx]]
            else:
                print(red("无效选择"))
                return False
        except ValueError:
            print(red("无效选择"))
            return False

    result = None
    for _num, name, path, btype in chosen:
        if has_bc3:
            r = _extract_with_browser_cookie3(name)
            if r:
                result = r
                break

        if not has_bc3 and btype:
            cookies = _extract_from_browser(path, btype)
            if cookies:
                result = (name, cookies)
                break

    if not result:
        print(red(f"[-] 未能从所选浏览器提取Cookie"))
        if system == 'Linux':
            print(yellow("    提示: 登录B站后将浏览器完全关闭再试，或 pip install browser_cookie3"))
        else:
            print(yellow("    提示: pip install browser_cookie3 (支持所有平台自动解密)"))
        return False

    name, cookies = result
    pairs = []
    for k in ['SESSDATA', 'bili_jct', 'DedeUserID', 'DedeUserID__ckMd5', 'buvid3', 'buvid4', 'sid']:
        if k in cookies:
            pairs.append(f'{k}={cookies[k]}')
    cookie_str = '; '.join(pairs)
    SESSION['cookie'] = cookie_str
    print(green(f"[+] 已从 {name} 提取Cookie ({len(pairs)}键)"))
    if 'SESSDATA' in cookies:
        print(f"    SESSDATA: {cookies['SESSDATA'][:20]}...")
    save_config()
    return True


def _check_tools():
    missing = []
    sysname = platform.system()
    if sysname == 'Windows':
        ffmpeg_hint = 'winget install ffmpeg  (或 https://ffmpeg.org/download.html)'
        aria2_hint = 'winget install aria2'
    elif sysname == 'Darwin':
        ffmpeg_hint = 'brew install ffmpeg'
        aria2_hint = 'brew install aria2'
    else:
        ffmpeg_hint = 'sudo apt install ffmpeg'
        aria2_hint = 'sudo apt install aria2'
    if not shutil.which('ffmpeg'):
        missing.append(('ffmpeg', '合并视频/音视频/字幕/弹幕', ffmpeg_hint))
    if not shutil.which('aria2c'):
        if not shutil.which('wget') and not shutil.which('curl'):
            missing.append(('aria2c', '多线程/断点续传下载', aria2_hint))
    return missing

def _check_python_deps():
    if getattr(sys, 'frozen', False):
        return
    missing = []
    try:
        import browser_cookie3
    except ImportError:
        missing.append(('browser_cookie3', '跨浏览器自动提取Cookie', 'pip install browser_cookie3'))
    try:
        import cryptography
    except ImportError:
        missing.append(('cryptography', '抓包模式HTTPS解密', 'pip install cryptography'))
    if not missing:
        return
    print(bold(f"\n  ══ 可选Python库 ══"))
    for name, desc, _ in missing:
        print(yellow(f"  ✗ {name} — {desc}"))
    try:
        ans = input(f"\n  是否自动安装？[Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print(); return
    if ans in ('', 'y', 'yes'):
        for name, desc, hint in missing:
            print(cyan(f"  [*] pip install {name}"))
            subprocess.run([sys.executable, '-m', 'pip', 'install', name],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        lines = [f'  {hint}' for _, _, hint in missing]
        print(dim('\n'.join(lines)))

def _first_run_wizard():
    if SESSION.get('cookie'):
        return
    is_new = not os.path.isfile(CONFIG_FILE)
    if not is_new:
        return
    _check_python_deps()
    print(bold(f"\n  ══ 首次运行配置 ══"))
    try:
        ans = input(f"  是否自动从浏览器提取B站Cookie？[Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        print(yellow("  可稍后通过 settings [2] 或 cookie auto 命令设置"))
        return
    if ans in ('', 'y', 'yes'):
        _cookie_auto()
    else:
        print(yellow("  可稍后通过 settings [2] 或 cookie auto 命令设置"))
        try:
            import browser_cookie3
        except ImportError:
            print(yellow("  建议 pip install browser_cookie3 实现跨平台自动提取"))
    missing = _check_tools()
    if missing:
        print(bold(f"\n  ══ 缺失工具检查 ══"))
        for name, desc, hint in missing:
            print(red(f"  ✗ {name} — {desc}"))
        print(dim(f"  修复: {'; '.join(h[2] for h in missing)}"))


# ---------------------------------------------------------------------------
# 交互模式会话
# ---------------------------------------------------------------------------

def _resolve_bvid(s):
    """解析用户输入: BV号 / URL / #N (搜索结果序号)"""
    if s.startswith('#'):
        try:
            n = int(s[1:]) - 1
            pool = SESSION['last_search_results'] or SESSION['last_hot_results']
            if 0 <= n < len(pool):
                return pool[n]['bvid']
            print(red(f"无效序号: #{n+1}")); return None
        except ValueError: pass
    return extract_video_id(s)

def _i_search(args):
    if not args: print(yellow("用法: search <关键词>")); return
    kw = ' '.join(args)
    SESSION['search_keyword'] = kw
    print(cyan(f"[*] 搜索: {kw}"))
    try: data = api_search(kw, SESSION['cookie'])
    except RuntimeError as e: print(red(f"[-] {e}")); return
    SESSION['search_page'] = 1
    SESSION['search_total_pages'] = data.get('numPages', 1) if 'numPages' in data else 1
    results = data.get('result') or []
    if not results: print(yellow("[!] 无结果")); return
    SESSION['last_search_results'] = []
    print(bold(f"\n{'='*60}"))
    pg_info = f"  第 {SESSION['search_page']}/{SESSION['search_total_pages']} 页" if SESSION['search_total_pages'] > 1 else ""
    print(f"  搜索: {kw}  共 {data.get('numResults',len(results))} 个结果{pg_info}")
    print(bold(f"{'='*60}"))
    for i, r in enumerate(results[:20]):
        title = r.get('title','').replace('<em class="keyword">','').replace('</em>','')
        SESSION['last_search_results'].append({'bvid':r['bvid'],'title':title,'author':r.get('author','?')})
        print(f"  {green(f'#{i+1:2d}')} [{cyan(r['bvid'])}] {title}")
        print(f"        UP:{r.get('author','?')} | 播放:{r.get('play',0)} | 时长:{r.get('duration','?')}")

def _i_hot(args):
    print(cyan("[*] 获取热门视频..."))
    try: data = api_popular(SESSION['cookie'])
    except RuntimeError as e: print(red(f"[-] {e}")); return
    results = data.get('list') or []
    SESSION['last_hot_results'] = []
    print(bold(f"\n{'='*60}"))
    print(f"  哔哩哔哩热门 (Top {len(results)})")
    print(bold(f"{'='*60}"))
    for i, r in enumerate(results):
        stat = r.get('stat',{})
        SESSION['last_hot_results'].append({'bvid':r['bvid'],'title':r.get('title',''),'author':r.get('owner',{}).get('name','?')})
        print(f"  {green(f'#{i+1:2d}')} [{cyan(r['bvid'])}] {r.get('title','')}")
        print(f"        UP:{r.get('owner',{}).get('name','?')} | 播放:{stat.get('view',0)} | 弹幕:{stat.get('danmaku',0)}")

def _i_info(args):
    if not args:
        if SESSION['last_bvid']: args = [SESSION['last_bvid']]
        else: print(yellow("用法: info <BV号|URL|#N>")); return
    bvid = _resolve_bvid(args[0])
    if not bvid: return
    print(cyan(f"[*] 获取: {bvid}"))
    try: info = api_get_video_info(bvid)
    except RuntimeError as e: print(red(f"[-] {e}")); return
    SESSION['last_bvid'] = bvid; SESSION['last_info'] = info
    print_video_info(info)
    print_stream_urls(info, SESSION['cookie'], SESSION['quality'])

def _i_url(args):
    if not args:
        if SESSION['last_bvid']: args = [SESSION['last_bvid']]
        else: print(yellow("用法: url <BV号|#N>")); return
    bvid = _resolve_bvid(args[0])
    if not bvid: return
    try: info = api_get_video_info(bvid)
    except RuntimeError as e: print(red(f"[-] {e}")); return
    SESSION['last_bvid'] = bvid; SESSION['last_info'] = info
    for page in info.get('pages', []):
        try: play = api_get_playurl(bvid, page['cid'], SESSION['cookie'], SESSION['quality'])
        except RuntimeError: continue
        parsed = parse_playurl(play)
        for v in parsed['dash']['video']:
            for url in v['urls']: print(url)
        for a in parsed['dash']['audio']:
            for url in a['urls']: print(url)
        for d in parsed['durl']:
            for url in d['urls']: print(url)

def _download_single_page(bvid, info, page, sq, format_choice):
    """下载单个分P，返回成功与否"""
    cid = page['cid']; pn = page['page']; part = page.get('part', f'P{pn}')
    title = sanitize_filename(info.get('title', bvid))
    total_pages = len(info.get('pages', []))
    print(f"\n{cyan(f'[P{pn}/{total_pages}]')} {part}")
    try: play = api_get_playurl(bvid, cid, SESSION['cookie'], sq)
    except RuntimeError as e: print(red(f"  [-] {e}")); return False
    parsed = parse_playurl(play)
    os.makedirs(SESSION['download_dir'], exist_ok=True)
    dd = SESSION['download_dir']
    has_dash = bool(parsed['dash']['video']); has_flv = bool(parsed['durl'])
    dl_name = f"{title}_{sq}_{bvid}_P{pn}"
    use_flv = (format_choice == 'flv') or (has_flv and not has_dash)
    if format_choice != 'flv' and format_choice != 'dash':
        use_flv = not has_dash
    if use_flv:
        if not has_flv: print(red("  [-] 无FLV流")); return False
        print(yellow(f"  [*] FLV {len(parsed['durl'])}段"))
        for d in parsed['durl']:
            url = d['urls'][0] if d['urls'] else ''
            if not url: continue
            seg_name = f"{dl_name}_{d['order']:02d}.flv"
            try: download_file(url, os.path.join(dd, seg_name))
            except KeyboardInterrupt: print(yellow("\n  [!] 已中断")); raise
    else:
        if not has_dash: print(red("  [-] 无DASH流")); return False
        video_ok = False; audio_ok = False
        video_path = audio_path = ""
        if parsed['dash']['video']:
            v = parsed['dash']['video'][0]
            url = v['urls'][0] if v['urls'] else ''
            if url:
                video_path = os.path.join(dd, f"{dl_name}_video.m4s")
                try: video_ok = download_file(url, video_path)
                except KeyboardInterrupt: print(yellow("\n  [!] 已中断")); raise
        if parsed['dash']['audio']:
            a = parsed['dash']['audio'][0]
            url = a['urls'][0] if a['urls'] else ''
            if url:
                audio_path = os.path.join(dd, f"{dl_name}_audio.m4s")
                try: audio_ok = download_file(url, audio_path)
                except KeyboardInterrupt: print(yellow("\n  [!] 已中断")); raise
        merged_ok = False
        final_video = None
        if video_ok and audio_ok and shutil.which('ffmpeg'):
            merged = os.path.join(dd, f"{dl_name}_merged.mp4")
            merged_ok = merge_dash(video_path, audio_path, merged)
            if merged_ok:
                final_video = os.path.join(dd, f"{dl_name}.mp4")
                os.rename(merged, final_video)
                if SESSION.get('auto_delete_m4s'):
                    for fp in (video_path, audio_path):
                        try:
                            os.remove(fp)
                        except OSError:
                            pass
                    print(cyan("  [*] 已自动删除m4s源文件"))
        if SESSION.get('download_subtitle'):
            sub_data = api_get_subtitle(bvid, cid, SESSION['cookie'])
            if sub_data:
                play['subtitle'] = sub_data
            _download_subtitle(bvid, cid, play, dd, dl_name)
        if SESSION.get('download_cover'):
            _download_cover(info.get('pic', ''), dd, dl_name)
        if SESSION.get('download_danmaku'):
            _download_danmaku(bvid, cid, dd, dl_name)
        if merged_ok and final_video and (SESSION.get('auto_mux_subtitle') or SESSION.get('auto_mux_danmaku')):
            sub_path = os.path.join(dd, f"{dl_name}.srt") if SESSION.get('auto_mux_subtitle') else None
            danmaku_path = os.path.join(dd, f"{dl_name}.ass") if SESSION.get('auto_mux_danmaku') else None
            _mux_subtitles(final_video, sub_path, danmaku_path)
    return True

def _i_download(args):
    if not args: print(yellow("用法: download <BV号|#N> [all|P页码|P开始-P结束]")); return
    bvid = _resolve_bvid(args[0])
    if not bvid: return
    print(cyan(f"[*] 获取: {bvid}"))
    try: info = api_get_video_info(bvid)
    except RuntimeError as e: print(red(f"[-] {e}")); return
    SESSION['last_bvid'] = bvid; SESSION['last_info'] = info
    pages = info.get('pages', []); bvid = info['bvid']
    if not pages: print(red("[-] 无分P")); return
    total = len(pages); title = sanitize_filename(info.get('title', bvid))
    print(f"  {title}  ({green(str(total))}P)\n")
    for p in pages:
        pg_num = p['page']
        print(f"  {green(f'[P{pg_num}]')}  {p.get('part', '无标题')}")
    selection = args[1] if len(args) > 1 else ''
    pn_start = pn_end = None
    if selection:
        selection_lower = selection.lower()
        if selection_lower == 'all':
            pn_start, pn_end = 1, total
        else:
            range_m = re.match(r'[pP]?(\d+)\s*-\s*(\d+)', selection)
            single_m = re.match(r'[pP]?(\d+)', selection)
            if range_m:
                pn_start, pn_end = int(range_m.group(1)), int(range_m.group(2))
            elif single_m:
                pn_start = pn_end = int(single_m.group(1))
    else:
        print(f"\n  {cyan('下载选项')}:")
        print(f"  {green('[1]')} 下载全部 ({total}P)")
        print(f"  {green('[2]')} 指定单P")
        print(f"  {green('[3]')} 指定范围 (如 2-5)")
        try:
            choice = input(f"\n  选 [1-3] (回车=1): ").strip()
            if not choice: choice = '1'
            if choice == '1':
                pn_start, pn_end = 1, total
            elif choice == '2':
                sp = input(f"  输入P页码 (1-{total}): ").strip()
                m = re.match(r'(\d+)', sp)
                if m: pn_start = pn_end = int(m.group(1))
            elif choice == '3':
                sr = input(f"  输入范围 (如 2-5, 回车=1-{total}): ").strip()
                if not sr: pn_start, pn_end = 1, total
                else:
                    range_m = re.match(r'(\d+)\s*-\s*(\d+)', sr)
                    if range_m: pn_start, pn_end = int(range_m.group(1)), int(range_m.group(2))
        except (EOFError, KeyboardInterrupt): return
    if pn_start is None or pn_start < 1 or pn_end > total or pn_end < pn_start:
        print(red(f"[-] 页码范围无效(共{total}P): {selection}")); return
    # 获取清晰度
    page0 = pages[pn_start-1]; cid0 = page0['cid']
    try: play0 = api_get_playurl(bvid, cid0, SESSION['cookie'], SESSION['quality'])
    except RuntimeError as e: print(red(f"[-] {e}")); return
    aq = play0.get('accept_quality', [])
    if not aq: print(red("[-] 无可用清晰度")); return
    print(f"\n  {cyan('可用清晰度')}:")
    for i, q in enumerate(aq):
        label = QUALITY_MAP.get(q, str(q))
        mk = ' <默认>' if q == SESSION['quality'] else ''
        print(f"  {green(f'[{i+1}]')} {q:4d} {label}{mk}")
    try:
        c = input(f"\n  选清晰度 [1-{len(aq)}] (回车={aq[0]}): ").strip()
        if c:
            try:
                v = int(c)
            except ValueError:
                print(red("无效")); return
            if v in aq:
                sq = v
            elif 1 <= v <= len(aq):
                sq = aq[v-1]
            else:
                print(red("无效")); return
        else:
            sq = aq[0]
    except (ValueError, EOFError, KeyboardInterrupt): return
    print(f"  已选: {sq} {QUALITY_MAP.get(sq,str(sq))}")
    # 选格式
    play_test = api_get_playurl(bvid, pages[pn_start-1]['cid'], SESSION['cookie'], sq)
    parsed_test = parse_playurl(play_test)
    has_dash = bool(parsed_test['dash']['video'])
    has_flv = bool(parsed_test['durl'])
    format_choice = 'dash'
    if has_dash and has_flv:
        try:
            fc = input(f"  格式: [1]DASH [2]FLV (回车=DASH): ").strip()
            format_choice = 'flv' if fc == '2' else 'dash'
        except (EOFError, KeyboardInterrupt): return
    elif has_flv: format_choice = 'flv'
    # 批量下载
    print(f"\n{cyan(f'[*] 下载: P{pn_start}~P{pn_end} (共{pn_end-pn_start+1}P)')}")
    ok = fail = 0
    try:
        for i in range(pn_start - 1, pn_end):
            page = pages[i]
            if _download_single_page(bvid, info, page, sq, format_choice):
                ok += 1
            else:
                fail += 1
    except KeyboardInterrupt:
        print(yellow("\n[!] 用户中断"))
    print(f"\n{green(f'[+] 完成: {ok}成功')}", end='')
    if fail: print(red(f'  {fail}失败'), end='')
    print()
    _notify(f'下载: {info.get("title", bvid)}', f'{ok}成功 {fail}失败')

def _i_settings(args):
    has_ffmpeg = bool(shutil.which('ffmpeg'))
    while True:
        q = SESSION['quality']; c = SESSION['cookie']; d = SESSION['download_dir']
        a = SESSION['auto_delete_m4s']; sub = SESSION['download_subtitle']
        dm = SESSION['download_danmaku']; cov = SESSION['download_cover']; nt = SESSION['notify']
        rt = SESSION['retry_count']; sc = SESSION['save_cookie']
        ams = SESSION['auto_mux_subtitle']; amd = SESSION['auto_mux_danmaku']
        print(bold(f"\n{'─'*40}"))
        print(bold(f"  设置"))
        print(bold(f"{'─'*40}"))
        print(f"  [1] 默认清晰度:   {cyan(str(q))} {QUALITY_MAP.get(q, '')}")
        c_disp = c[:40] + '...' if len(c) > 40 else (c if c else '未设置')
        print(f"  [2] Cookie:        {cyan(f'{c_disp}' + ('  (输入 auto 自动提取)' if not c else ''))}")
        print(f"  [3] 下载目录:      {cyan(d)}")
        if has_ffmpeg:
            print(f"  [4] 合并后删m4s:   {cyan('是' if a else '否')}")
        else:
            print(f"  [4] 合并后删m4s:   {dim('否(需ffmpeg合并)')}")
        if has_ffmpeg:
            print(f"  [5] 下载字幕:      {cyan('是' if sub else '否')} (自动合并: {cyan('是' if ams else '否')})")
            print(f"  [6] 下载弹幕:      {cyan('是' if dm else '否')} (自动合并: {cyan('是' if amd else '否')})")
        else:
            print(f"  [5] 下载字幕:      {cyan('是' if sub else '否')} (自动合并: {dim('否(需ffmpeg)')})")
            print(f"  [6] 下载弹幕:      {cyan('是' if dm else '否')} (自动合并: {dim('否(需ffmpeg)')})")
        print(f"  [7] 下载封面:      {cyan('是' if cov else '否')}")
        print(f"  [8] 完成通知:      {cyan('是' if nt else '否')}")
        print(f"  [9] 重试次数:      {cyan(str(rt))}")
        print(f"  [10] 保存Cookie:   {cyan('是' if sc else '否')}")
        print(f"  [u] 检查更新       (当前 v{VERSION})")
        print(f"{'─'*40}")
        try:
            ch = input(f"  修改 [1-10/u] (回车返回): ").strip()
        except (EOFError, KeyboardInterrupt):
            print(); break
        if not ch:
            save_config(); break
        if ch == '1':
            print(f"  {cyan('清晰度代码:')}")
            for code, name in sorted(QUALITY_MAP.items(), reverse=True):
                mk = ' <当前>' if code == q else ''
                print(f"    {code:>4}  {name}{mk}")
            v = input(f"  新代码 (回车不变): ").strip()
            if v:
                try:
                    nq = int(v)
                    if nq in QUALITY_MAP:
                        SESSION['quality'] = nq
                        print(green(f"  => {nq} {QUALITY_MAP[nq]}"))
                    else:
                        print(red("  无效"))
                except ValueError:
                    print(red("  无效"))
        elif ch == '2':
            print(f"  当前: {c[:60] + '...' if len(c) > 60 else (c or '未设置')}")
            v = input(f"  新Cookie (auto=自动提取, 回车不变): ").strip()
            if v.lower() == 'auto':
                _cookie_auto()
            elif v:
                SESSION['cookie'] = v
                print(green("  已更新"))
        elif ch == '3':
            v = input(f"  新路径 (回车不变): ").strip()
            if v:
                nd = os.path.expanduser(v)
                os.makedirs(nd, exist_ok=True)
                SESSION['download_dir'] = nd
                print(green(f"  => {nd}"))
        elif ch == '4':
            if not has_ffmpeg:
                print(yellow(f"  [!] ffmpeg未安装，DASH合并及m4s删除均不可用"))
                print(dim(f"  安装: sudo apt install ffmpeg"))
                continue
            SESSION['auto_delete_m4s'] = not a
            print(green(f"  => {'是' if not a else '否'}"))
            save_config()
        elif ch == '5':
            _settings_sub('字幕', 'download_subtitle', 'auto_mux_subtitle')
        elif ch == '6':
            _settings_sub('弹幕', 'download_danmaku', 'auto_mux_danmaku')
        elif ch == '7':
            SESSION['download_cover'] = not cov
            print(green(f"  => {'是' if not cov else '否'}"))
        elif ch == '8':
            SESSION['notify'] = not nt
            print(green(f"  => {'是' if not nt else '否'}"))
        elif ch == '9':
            v = input(f"  重试次数 (回车不变): ").strip()
            if v:
                try:
                    n = int(v)
                    if n >= 0:
                        SESSION['retry_count'] = n
                        print(green(f"  => {n}"))
                    else:
                        print(red("  必须 >= 0"))
                except ValueError:
                    print(red("  无效数字"))
        elif ch == '10':
            SESSION['save_cookie'] = not sc
            print(green(f"  => {'是' if not sc else '否'}"))
            save_config()
        elif ch.lower() == 'u':
            _do_update()

def _settings_sub(label, dl_key, mux_key):
    has_ffmpeg = bool(shutil.which('ffmpeg'))
    while True:
        dl = SESSION[dl_key]
        mux = SESSION[mux_key]
        print(bold(f"\n  ── {label}设置 ──"))
        print(f"  [1] 下载开关:       {cyan('是' if dl else '否')}")
        if has_ffmpeg:
            print(f"  [2] 自动合并并删除: {cyan('是' if mux else '否')}")
        else:
            print(f"  [2] 自动合并并删除: {dim('否(需ffmpeg, 已关闭)')}")
        print(f"  [3] 返回")
        try:
            ch = input(f"  选 [1-3]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print(); break
        if ch == '1':
            SESSION[dl_key] = not dl
            print(green(f"  => {'是' if not dl else '否'}"))
            save_config()
        elif ch == '2':
            if not has_ffmpeg:
                print(yellow(f"  [!] ffmpeg未安装，无法启用自动合并"))
                print(dim(f"  安装: sudo apt install ffmpeg"))
                continue
            SESSION[mux_key] = not mux
            print(green(f"  => {'是' if not mux else '否'}"))
            save_config()
        elif ch == '3' or ch == '':
            save_config(); break

GH_MIRRORS = ['', 'https://ghproxy.com/']

def _gh_request(url, **kwargs):
    for mirror in GH_MIRRORS:
        u = mirror + url if mirror else url
        try:
            return requests.get(u, **kwargs)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if mirror:
                raise
            continue
    raise requests.exceptions.ConnectionError(f'无法访问 GitHub: {url}')

def _check_update():
    try:
        r = _gh_request(GITHUB_API, headers=HEADERS, timeout=10)
        r.raise_for_status()
        data = r.json()
        latest = data['tag_name'].lstrip('v')
        assets = {}
        for a in data.get('assets', []):
            assets[a['name']] = a['browser_download_url']
        def _ver(s):
            try: return tuple(int(x) for x in s.split('.'))
            except: return (0,)
        if _ver(latest) > _ver(VERSION):
            return True, latest, assets
        return False, latest, assets
    except Exception as e:
        return None, str(e), {}

def _do_update(args=None):
    print(bold(f"\n{'─'*40}"))
    print(bold(f"  检查更新..."))
    has_upd, latest, assets = _check_update()
    if has_upd is None:
        print(red(f"  [!] 检查失败: {latest}"))
        return
    if not has_upd:
        print(green(f"  已是最新版本 v{VERSION}"))
        return

    print(cyan(f"  发现新版本 v{latest} (当前 v{VERSION})"))
    try:
        ans = input(f"  是否更新? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print(); return
    if ans not in ('', 'y', 'yes'):
        return

    frozen = getattr(sys, 'frozen', False)
    if frozen:
        src = sys.executable
        uname = platform.system()
        if uname == 'Windows':
            asset_name = 'bili-sniffer-windows.exe'
        elif uname == 'Darwin':
            asset_name = 'bili-sniffer-macos'
        else:
            asset_name = 'bili-sniffer-linux'
        dl_url = assets.get(asset_name)
        if not dl_url:
            print(red(f"  [!] 未找到 {asset_name}"))
            return
        print(cyan(f"  [*] 当前程序: {src}"))
    else:
        src = os.path.abspath(__file__)
        dl_url = f"{GITHUB_RAW}/bilibili_sniffer.py"
        print(cyan(f"  [*] 当前脚本: {src}"))

    print(cyan(f"  下载地址: {dl_url}"))
    print(cyan(f"  [*] 正在连接..."), end='', flush=True)
    try:
        r = _gh_request(dl_url, headers=HEADERS, timeout=(10, 120), stream=True)
        print(f"\r  {cyan('[→] 连接成功，下载中...')}     ", flush=True)
        r.raise_for_status()
        total = int(r.headers.get('content-length', 0))
        new_data = b''
        chunk_size = 8192
        last_pct = -1
        for chunk in r.iter_content(chunk_size=chunk_size):
            new_data += chunk
            if total:
                pct = len(new_data) * 100 // total
                if pct != last_pct:
                    bar_len = 30
                    filled = bar_len * pct // 100
                    bar = '█' * filled + '░' * (bar_len - filled)
                    print(f'\r  {cyan(f"[↓]")} [{bar}] {pct}%  {len(new_data)/1024/1024:.1f}/{total/1024/1024:.1f} MB', end='', flush=True)
                    last_pct = pct
        status = 'done!' if not total else ''
        print(f'\r  {cyan("[↓]")} 下载完成 {len(new_data)/1024/1024:.1f} MB {status}'.strip())
    except requests.exceptions.ConnectionError as e:
        print(f'\r  {red("[!] 连接失败: 无法访问 GitHub")}         ')
        print(dim(f'  {e}'))
        return
    except requests.exceptions.Timeout as e:
        print(f'\r  {red("[!] 连接超时")}         ')
        print(dim(f'  {e}'))
        return
    except requests.exceptions.SSLError as e:
        print(f'\r  {red("[!] SSL 错误")}         ')
        print(dim(f'  {e}'))
        return
    except requests.exceptions.HTTPError as e:
        print(f'\r  {red(f"[!] HTTP 错误: {r.status_code}")}         ')
        return
    except Exception as e:
        print(f'\r  {red(f"[!] 下载失败: {e}")}         ')
        return

    tmp = src + ".new"
    try:
        with open(tmp, 'wb') as f:
            f.write(new_data)
        if not frozen:
            os.chmod(tmp, os.stat(src).st_mode)
        else:
            os.chmod(tmp, 0o755)
        os.replace(tmp, src)
        print(green(f"  [+] 更新完成 v{latest} — 重新启动后生效"))
    except (PermissionError, OSError):
        print(yellow(f"  [!] 权限不足，无法直接替换 {src}"))
        print(dim(f"  文件已下载到 {tmp}"))
        if platform.system() != 'Windows':
            print(yellow(f"  [*] 尝试用 sudo 替换..."))
            try:
                subprocess.run(['sudo', 'mv', tmp, src], check=True)
                subprocess.run(['sudo', 'chmod', '755' if frozen else str(oct(os.stat(src).st_mode)[-3:]), src], check=True)
                print(green(f"  [+] 更新完成 v{latest} — 重新启动后生效"))
            except Exception as e2:
                print(red(f"  [!] sudo 也失败了: {e2}"))
                print(yellow(f"  请手动执行: sudo mv {tmp} {src}"))
        else:
            print(yellow(f"  请以管理员身份重新运行，或手动替换: {tmp} -> {src}"))

def _i_next(args):
    if SESSION['search_total_pages'] <= 1:
        print(yellow("无可翻页，请先 search"))
        return
    np = SESSION['search_page'] + 1
    if np > SESSION['search_total_pages']:
        print(yellow(f"已是最后一页 ({SESSION['search_total_pages']}/{SESSION['search_total_pages']})"))
        return
    SESSION['search_page'] = np
    print(cyan(f"[*] 翻到第 {np} 页"))
    try:
        data = api_search(SESSION['search_keyword'], SESSION['cookie'], page=np)
        SESSION['search_total_pages'] = data.get('numPages', 1) if 'numPages' in data else SESSION['search_total_pages']
        results = data.get('result') or []
        SESSION['last_search_results'] = []
        print(bold(f"\n{'='*60}"))
        print(f"  搜索: {SESSION['search_keyword']}  第 {np}/{SESSION['search_total_pages']} 页")
        print(bold(f"{'='*60}"))
        for i, r in enumerate(results[:20]):
            title = r.get('title','').replace('<em class="keyword">','').replace('</em>','')
            SESSION['last_search_results'].append({'bvid':r['bvid'],'title':title,'author':r.get('author','?')})
            print(f"  {green(f'#{i+1:2d}')} [{cyan(r['bvid'])}] {title}")
            print(f"        UP:{r.get('author','?')} | 播放:{r.get('play',0)} | 时长:{r.get('duration','?')}")
    except RuntimeError as e:
        print(red(f"[-] {e}")); SESSION['search_page'] -= 1

def _i_prev(args):
    if SESSION['search_page'] <= 1:
        print(yellow("已是第一页"))
        return
    SESSION['search_page'] -= 1
    print(cyan(f"[*] 翻到第 {SESSION['search_page']} 页"))
    try:
        data = api_search(SESSION['search_keyword'], SESSION['cookie'], page=SESSION['search_page'])
        SESSION['search_total_pages'] = data.get('numPages', 1) if 'numPages' in data else SESSION['search_total_pages']
        results = data.get('result') or []
        SESSION['last_search_results'] = []
        print(bold(f"\n{'='*60}"))
        print(f"  搜索: {SESSION['search_keyword']}  第 {SESSION['search_page']}/{SESSION['search_total_pages']} 页")
        print(bold(f"{'='*60}"))
        for i, r in enumerate(results[:20]):
            title = r.get('title','').replace('<em class="keyword">','').replace('</em>','')
            SESSION['last_search_results'].append({'bvid':r['bvid'],'title':title,'author':r.get('author','?')})
            print(f"  {green(f'#{i+1:2d}')} [{cyan(r['bvid'])}] {title}")
            print(f"        UP:{r.get('author','?')} | 播放:{r.get('play',0)} | 时长:{r.get('duration','?')}")
    except RuntimeError as e:
        print(red(f"[-] {e}")); SESSION['search_page'] += 1

def _i_qlist(args):
    q = SESSION['download_queue']
    if not q:
        print(yellow("下载队列为空"))
        return
    print(bold(f"\n  下载队列 ({len(q)}项):"))
    for i, (bvid, info, fmt) in enumerate(q):
        title = sanitize_filename(info.get('title', bvid))
        print(f"  [{cyan(str(i+1))}] {title}  ({bvid})  fmt={fmt}")

def _i_qrun(args):
    q = SESSION['download_queue']
    if not q:
        print(yellow("下载队列为空"))
        return
    print(cyan(f"[*] 开始执行下载队列 ({len(q)}项)"))
    for idx, (bvid, info, fmt) in enumerate(q):
        print(cyan(f"\n[队列 {idx+1}/{len(q)}]"))
        pages = info.get('pages', [])
        if not pages:
            print(yellow(f"  [!] {bvid} 无分P，跳过"))
            continue
        sq = info.get('quality', SESSION['quality'])
        for page in pages:
            try:
                _download_single_page(bvid, info, page, sq, fmt)
            except KeyboardInterrupt:
                print(yellow("\n[!] 用户中断"))
                return
    SESSION['download_queue'].clear()
    _notify('bili_sniffer', '下载队列完成')
    print(green("\n[+] 队列完成"))

def _i_qadd(args):
    bvid = _resolve_bvid(args[0]) if args else None
    if not bvid: print(yellow("用法: qadd <BV|#N>")); return
    try:
        info = api_get_video_info(bvid)
    except RuntimeError as e:
        print(red(f"[-] {e}")); return
    SESSION['download_queue'].append((bvid, info, 'dash'))
    title = sanitize_filename(info.get('title', bvid))
    print(green(f"[+] 已加入队列: {title}"))

def _i_qclear(args):
    SESSION['download_queue'].clear()
    print(green("[+] 队列已清空"))

def _i_daily(args):
    if not SESSION['cookie']:
        print(yellow("请先设置Cookie"))
        return
    print(cyan("[*] 每日签到..."))
    try:
        result = api_daily_click(SESSION['cookie'])
        if result.get('code') == 0:
            print(green("[+] 签到成功"))
        else:
            print(yellow(f"[!] {result.get('message', '签到失败')}"))
    except RuntimeError as e:
        print(red(f"[-] {e}"))

def _i_help(args):
    d = SESSION['download_dir']
    print(bold(f"\n  ══ B站视频下载器 ══"))
    print(f"""  {cyan('search <关键词>')}    搜索视频
  {cyan('next / n')}         下一页搜索结果
  {cyan('prev / p')}         上一页搜索结果
  {cyan('hot')}              热门视频
  {cyan('info <BV|URL|#N>')}  视频详情 + 流地址
  {cyan('download <BV|#N>')}  选择分P/清晰度下载
  {cyan('url <BV|#N>')}       仅输出下载URL
  {cyan('daily')}            每日签到 (需Cookie)
  {cyan('last')}              上次查询的视频
  {cyan('qlist')}             查看下载队列
  {cyan('qadd <BV|#N>')}      加入下载队列
  {cyan('qrun')}              执行下载队列
  {cyan('qclear')}            清空下载队列
  {cyan('settings')}          统一设置
  {cyan('update')}            检查更新
  {cyan('help')}              本帮助
  {cyan('exit / q')}          退出

  下载目录: {d}""")

def interactive_shell():
    """交互式 REPL 主循环"""
    # 设置 readline 历史 + Tab补全
    if readline:
        try: readline.read_history_file(HISTORY_FILE)
        except FileNotFoundError: pass
        readline.set_history_length(1000)
        _cmds = ['search','hot','info','download','url','last','settings','set',
                 'quality','cookie','dir','help','exit','quit',
                 'next','prev','daily','qlist','qadd','qrun','qclear','update']
        def _complete(text, state):
            for m in [c for c in _cmds if c.startswith(text)]:
                if state == 0:
                    return m
                state -= 1
        readline.parse_and_bind('tab: complete')
        readline.set_completer(_complete)

    _i_help([])
    while True:
        try:
            raw = input(f"\n{green('bili')}> ").strip()
        except (EOFError, KeyboardInterrupt):
            print(); break
        if not raw: continue
        if readline:
            readline.write_history_file(HISTORY_FILE)
        parts = raw.split()
        cmd = parts[0].lower(); args = parts[1:]

        if cmd in ('exit','quit','q'): break
        elif cmd == 'search':   _i_search(args)
        elif cmd == 'next' or cmd == 'n':    _i_next(args)
        elif cmd == 'prev' or cmd == 'p':    _i_prev(args)
        elif cmd == 'hot':      _i_hot(args)
        elif cmd == 'info':     _i_info(args)
        elif cmd == 'download': _i_download(args)
        elif cmd == 'url':      _i_url(args)
        elif cmd == 'settings' or cmd == 'set':
            _i_settings(args)
        elif cmd == 'daily':    _i_daily(args)
        elif cmd == 'qlist':    _i_qlist(args)
        elif cmd == 'qadd':     _i_qadd(args)
        elif cmd == 'qrun':     _i_qrun(args)
        elif cmd == 'qclear':   _i_qclear(args)
        elif cmd == 'last':
            if SESSION['last_bvid']:
                _i_info([SESSION['last_bvid']])
            else: print(yellow("还没有查询过视频"))
        elif cmd == 'quality':
            if args:
                try:
                    q = int(args[0])
                    if q in QUALITY_MAP:
                        SESSION['quality'] = q
                        print(green(f"默认清晰度: {q} {QUALITY_MAP[q]}"))
                    else: print(yellow(f"未知清晰度代码: {q}"))
                except ValueError: print(red("无效数字"))
            else: print(f"当前: {SESSION['quality']} {QUALITY_MAP.get(SESSION['quality'],'')}")
        elif cmd == 'cookie':
            if not args:
                if SESSION['cookie']:
                    print(f"Cookie: {SESSION['cookie'][:80]}...")
                else:
                    print(yellow("未设置Cookie，用 settings 或 cookie auto 从浏览器提取"))
            elif args[0].lower() == 'auto':
                _cookie_auto()
            else:
                SESSION['cookie'] = ' '.join(args); print(green("Cookie已设置"))
        elif cmd == 'dir':
            if args:
                d = os.path.expanduser(args[0])
                os.makedirs(d, exist_ok=True)
                SESSION['download_dir'] = d; print(green(f"下载目录: {d}"))
            else: print(f"当前: {SESSION['download_dir']}")
        elif cmd == 'update': _do_update(args)
        elif cmd == 'help': _i_help(args)
        else: print(yellow(f"未知命令: {cmd} (输入 help 查看帮助)"))

    if readline:
        try: readline.write_history_file(HISTORY_FILE)
        except: pass
    print(green("再见!"))

def main():
    load_config()

    if '--download' in sys.argv or '-d' in sys.argv:
        bv_idx = -1
        for i, a in enumerate(sys.argv[1:], 1):
            if a in ('--download', '-d'):
                continue
            if a.startswith('--') or a.startswith('-'):
                continue
            bv_idx = i
            break
        bvid = _resolve_bvid(sys.argv[bv_idx]) if bv_idx > 0 else None
        if not bvid:
            print(red("用法: bilibili_sniffer --download <BV|URL>"))
            return
        try:
            info = api_get_video_info(bvid)
        except RuntimeError as e:
            print(red(f"[-] {e}")); return
        pages = info.get('pages', [])
        if not pages:
            print(red("[-] 无分P")); return
        sq = info.get('quality', SESSION['quality'])
        fmt = 'dash'
        for page in pages:
            _download_single_page(bvid, info, page, sq, fmt)
        ok = len([p for p in pages if True])
        total = len(pages)
        _notify('bili_sniffer', f'下载完成: {info.get("title", bvid)}')
        print(green(f"\n[+] 完成 ({total}P)"))
        return

    if len(sys.argv) == 1:
        _first_run_wizard()
        interactive_shell()
        return

    parser = argparse.ArgumentParser(
        description='哔哩哔哩视频下载地址抓取工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
\033[36m清晰度代码参考:\033[0m
  {cyan('127')}  8K 超高清      {cyan('120')}  4K 超清
  {cyan('116')}  1080P 60帧     {cyan('112')}  1080P 高码率
  {cyan('80 ')}  1080P 高清     {cyan('74 ')}  720P 60帧
  {cyan('64 ')}  720P 高清      {cyan('32 ')}  480P 清晰
        """
    )
    parser.add_argument('input', nargs='?', help='视频BV号/AV号或完整URL')
    parser.add_argument('-q', '--quality', type=int, default=80, help='清晰度代码 (默认:80)')
    parser.add_argument('-c', '--cookie', default='', help='Cookie字符串')
    parser.add_argument('-o', '--output', default='', help='输出JSON文件路径')
    parser.add_argument('--format', choices=['all','dash','durl','audio'], default='all',
                        help='输出格式')
    parser.add_argument('--list-qualities', action='store_true', help='列出清晰度代码')
    sg = parser.add_argument_group('抓包模式')
    sg.add_argument('--sniff', action='store_true', help='启用网络抓包模式')
    sg.add_argument('--sniff-mode', choices=['tcpdump','mitmproxy'], default='tcpdump')
    sg.add_argument('-i', '--interface', default='any', help='网络接口')
    sg.add_argument('-p', '--port', type=int, default=443, help='端口')
    sg.add_argument('-t', '--timeout', type=int, default=60, help='抓包超时秒数')
    args = parser.parse_args()

    if args.list_qualities:
        print(bold("\n哔哩哔哩清晰度代码:\n"))
        for code, name in sorted(QUALITY_MAP.items(), reverse=True):
            print(f"  {code:>4}  =>  {name}")
        return

    if args.sniff:
        if args.sniff_mode == 'tcpdump':
            urls = sniff_tcpdump(args.interface, args.timeout, args.port)
        else:
            urls = sniff_mitmproxy(args.timeout)
        if urls:
            print(bold(f"\n{'='*60}"))
            print(f"  共发现 {len(urls)} 个视频下载地址:")
            print(bold(f"{'='*60}"))
            for u in sorted(urls): print(f"  {u}")
            if args.output:
                with open(args.output, 'w') as f:
                    json.dump(sorted(urls), f, ensure_ascii=False, indent=2)
                print(f"\n{green('已保存到: ' + args.output)}")
        else:
            print(red("\n未捕获到B站视频地址"))
        return

    if not args.input:
        parser.print_help()
        return

    video_id = extract_video_id(args.input)
    if not video_id:
        print(red(f"无法识别视频ID: {args.input}"))
        return

    print(green(f"[*] 识别视频ID: {video_id}"))
    try:
        info = api_get_video_info(video_id)
        print_video_info(info)
        print_stream_urls(info, args.cookie, args.quality)
        if args.output:
            pages = info.get('pages', [])
            all_data = {}
            for page in pages:
                try:
                    play = api_get_playurl(info['bvid'], page['cid'], args.cookie, args.quality)
                    all_data[page.get('part', f"P{page.get('page',0)}")] = parse_playurl(play)
                except RuntimeError: continue
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(all_data, f, ensure_ascii=False, indent=2)
            print(f"\n{green('结果已保存到: ' + args.output)}")
    except RuntimeError as e:
        print(red(f"\n{e}"))
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(red(f"\n网络请求失败: {e}"))
        sys.exit(1)


if __name__ == '__main__':
    main()
