#!/usr/bin/env bash
set -euo pipefail

BOLD="\033[1m"; CYAN="\033[36m"; GREEN="\033[32m"; YELLOW="\033[33m"; RED="\033[31m"; RESET="\033[0m"

echo -e "${BOLD}══ bili-sniffer 安装器 ══${RESET}"
echo ""
echo -e "  1) ${CYAN}单文件脚本${RESET}      — 下载 bilibili_sniffer.py + requirements.txt (推荐)"
echo -e "  2) ${CYAN}Python 虚拟环境${RESET}  — venv + pip install, 含完整依赖"
echo -e "  3) ${CYAN}预编译二进制${RESET}    — PyInstaller 单文件 (Linux x86_64)"
echo ""

read -p "  选择 [1-3] (回车=1): " choice
choice="${choice:-1}"

INSTALL_DIR="${HOME}/.local/bin"
mkdir -p "${INSTALL_DIR}"

GITHUB_RAW="https://raw.githubusercontent.com/x0tuzi/bili-sniffer/main"
GITHUB_RELEASE="https://github.com/x0tuzi/bili-sniffer/releases/latest/download"

case "$choice" in
  1)
    echo -e "\n${CYAN}[*] 安装单文件脚本...${RESET}"
    curl -fsSLo "${INSTALL_DIR}/bilibili_sniffer.py" "${GITHUB_RAW}/bilibili_sniffer.py"
    chmod +x "${INSTALL_DIR}/bilibili_sniffer.py"
    pip install -r <(curl -fsSL "${GITHUB_RAW}/requirements.txt") --quiet 2>/dev/null || \
      echo -e "${YELLOW}[!] pip 安装依赖失败，请手动: pip install requests browser_cookie3${RESET}"
    WRAPPER="${INSTALL_DIR}/bili-sniffer"
    cat > "${WRAPPER}" << 'WRAPPER'
#!/usr/bin/env bash
exec python3 "${HOME}/.local/bin/bilibili_sniffer.py" "$@"
WRAPPER
    chmod +x "${WRAPPER}"
    echo -e "${GREEN}[+] 完成! 运行: bili-sniffer${RESET}"
    ;;

  2)
    VENV_DIR="${HOME}/.local/share/bili-sniffer-venv"
    echo -e "\n${CYAN}[*] 创建虚拟环境: ${VENV_DIR}${RESET}"
    python3 -m venv "${VENV_DIR}"
    "${VENV_DIR}/bin/pip" install --quiet requests browser_cookie3 cryptography 2>/dev/null
    curl -fsSLo "${VENV_DIR}/bin/bilibili_sniffer.py" "${GITHUB_RAW}/bilibili_sniffer.py"
    chmod +x "${VENV_DIR}/bin/bilibili_sniffer.py"
    WRAPPER="${INSTALL_DIR}/bili-sniffer"
    cat > "${WRAPPER}" << WRAPPER
#!/usr/bin/env bash
exec "${VENV_DIR}/bin/python3" "${VENV_DIR}/bin/bilibili_sniffer.py" "\$@"
WRAPPER
    chmod +x "${WRAPPER}"
    echo -e "${GREEN}[+] 完成! 运行: bili-sniffer${RESET}"
    echo -e "  卸载: rm -rf ${VENV_DIR} ${WRAPPER}"
    ;;

  3)
    echo -e "\n${CYAN}[*] 下载预编译二进制...${RESET}"
    BIN="${INSTALL_DIR}/bili-sniffer"
    curl -fsSLo "${BIN}" "${GITHUB_RELEASE}/bili-sniffer-linux"
    chmod +x "${BIN}"
    echo -e "${GREEN}[+] 完成! 运行: bili-sniffer${RESET}"
    ;;

  *)
    echo -e "${RED}[!] 无效选择${RESET}"; exit 1
    ;;
esac

echo -e "\n${YELLOW}[!] 请确保 ${INSTALL_DIR} 在 PATH 中，否则请自行添加。${RESET}"
