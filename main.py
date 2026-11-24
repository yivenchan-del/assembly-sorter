import os
import sys
import logging
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from assembly_sorter_project.config import CONFIG, STATIC_DIR_PATH
from assembly_sorter_project.api.routes import router

# 🌟 修复 1：在无控制台(--noconsole)打包模式下，防止 sys.stdout/stderr 为 None 导致崩溃
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

app = FastAPI(title="装配排版", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态资源
if os.path.exists(STATIC_DIR_PATH):
    app.mount("/static", StaticFiles(directory=STATIC_DIR_PATH), name="static")
else:
    logging.warning(f"⚠️ 未找到 static 静态目录: {STATIC_DIR_PATH}")

app.include_router(router)

if __name__ == "__main__":
    app_cfg = CONFIG.get("app", {})
    
    # 🌟 修复 2：禁用 uvicorn 的默认彩色控制台日志配置 (log_config=None)
    # 所有业务与请求日志会继续通过你在 config.py 中配置的 RotatingFileHandler 正常写入 app.log 文件
    uvicorn.run(
        app, 
        host=app_cfg.get("host", "127.0.0.1"), 
        port=app_cfg.get("port", 8088),
        reload=False,
        log_config=None  # 关键点：禁用 uvicorn 默认的 isatty 日志格式化器
    )
    