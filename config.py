

import json
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

# ==================== 1. 动态判断运行环境与基础路径 ====================
if getattr(sys, 'frozen', False):
    # 如果是 PyInstaller 打包后的环境
    # EXE 所在的文件夹路径（用于放置可编辑的 config.json, logs, saved_images 等外部修改文件）
    EXE_DIR = os.path.dirname(sys.executable)
    # PyInstaller 解压静态资源的临时目录路径
    BUNDLE_DIR = getattr(sys, '_MEIPASS', EXE_DIR)
else:
    # 正常 Python 开发环境
    EXE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
    BUNDLE_DIR = EXE_DIR

# 配置文件与输出数据放置在 EXE 所在目录下（方便用户随时修改 config.json 或查看图片/日志）
CONFIG_FILE = os.path.join(EXE_DIR, "config.json")
LOG_DIR = os.path.join(EXE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# 静态资源优先在 EXE 同级目录查找；如果同级目录没有，则退回使用 PyInstaller 打包内部的静态文件
def resolve_resource_path(relative_path: str) -> str:
    external_path = os.path.join(EXE_DIR, relative_path)
    if os.path.exists(external_path):
        return external_path
    return os.path.join(BUNDLE_DIR, relative_path)

INDEX_HTML_PATH = resolve_resource_path("index.html")
STATIC_DIR_PATH = resolve_resource_path("static")

# ==================== 2. 日志配置 ====================
LOG_FILE = os.path.join(LOG_DIR, "app.log")
LOG_FORMAT = "%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"

file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8"
)
stream_handler = logging.StreamHandler(sys.stdout)

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[file_handler, stream_handler]
)

# ==================== 3. 配置文件加载 ====================
DEFAULT_CONFIG = {
    "serial": {
        "enabled": False,
        "port": "COM3",
        "baud_rate": 9600,
        "timeout": 1
    },
    "app": {
        "host": "127.0.0.1",
        "port": 8088,
        "api_base_url": "https://mps.casetify.com/api/printing_batch",
        "ship_api_base_url":"https://mps.casetify.com/api/shipping_task",
        "assembly_task_api":"https://mps.casetify.com/api/assembly_task",
        "API_HISTORY_URL"  :"https://mps.casetify.com/api/printing_task",
        "image_dir": "saved_images"
    },
    "hardware": {
        "available_boards": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
    }
}

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"⚠️ 读取 {CONFIG_FILE} 异常，使用默认配置: {e}")
            return DEFAULT_CONFIG
    else:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        logging.info(f"📝 已在程序同级目录自动生成默认配置文件: {CONFIG_FILE}")
        return DEFAULT_CONFIG

CONFIG = load_config()
IMAGE_DIR = os.path.join(EXE_DIR, CONFIG["app"]["image_dir"])
API_BASE_URL = CONFIG["app"]["api_base_url"]
SHIP_API_BASE_URL = CONFIG["app"]["ship_api_base_url"]
ASSEMBLY_TASK_URL = CONFIG["app"]["assembly_task_api"]
AVAILABLE_BOARDS = CONFIG["hardware"]["available_boards"]
API_HISTORY_URL = CONFIG["app"]["API_HISTORY_URL"]
SERIAL_CFG = CONFIG.get("serial", {})
APP_CFG = CONFIG.get("app", {})
BASE_DIR = EXE_DIR
os.makedirs(IMAGE_DIR, exist_ok=True)