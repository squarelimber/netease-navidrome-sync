"""入口：调度器 + 状态页服务。"""

import argparse
import logging
import threading

import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import config as config_mod
from .db import DB
from .jobs import Jobs
from .netease.qrlogin import LoginHandler
from .util import setup_logging
from .web import create_app

log = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="netease-navidrome-sync")
    parser.add_argument("--run-now", action="store_true", help="立即执行一次每日任务后退出")
    args = parser.parse_args()

    cfg = config_mod.load()
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    (cfg.data_dir / "logs").mkdir(parents=True, exist_ok=True)
    setup_logging(cfg.data_dir / "logs" / "sync.log")

    db = DB(cfg.data_dir / "sync.db")
    jobs = Jobs(cfg, db)

    if args.run_now:
        stats = jobs.daily_run()
        log.info("运行结果: %s", stats)
        return

    scheduler = BackgroundScheduler()
    parts = cfg.cron.split()
    if len(parts) == 5:
        trigger = CronTrigger(minute=parts[0], hour=parts[1], day=parts[2],
                              month=parts[3], day_of_week=parts[4])
    else:
        log.warning("cron 表达式无效 '%s'，使用默认 04:30", cfg.cron)
        trigger = CronTrigger(hour=4, minute=30)
    scheduler.add_job(jobs.daily_run, trigger, id="daily_sync", replace_existing=True)
    scheduler.start()
    log.info("调度器已启动: cron='%s'", cfg.cron)

    if cfg.run_on_startup:
        threading.Thread(target=jobs.daily_run, daemon=True, name="startup-run").start()

    app = create_app(cfg, db, jobs, scheduler)
    app.state.qr_handler = LoginHandler(on_success=jobs.set_cookie)
    uvicorn.run(app, host=cfg.web_host, port=cfg.web_port, log_level="warning")


if __name__ == "__main__":
    main()
