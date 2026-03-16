"""
Session清理定时任务
定期清理过期的session目录
"""
import asyncio
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from workflow.sandbox_manager import get_path_manager

logger = logging.getLogger(__name__)


class SessionCleanupScheduler:
    """Session清理调度器"""

    def __init__(self, retention_days: int = 7):
        """
        初始化调度器

        Args:
            retention_days: 保留天数,超过此天数的session将被清理
        """
        self.retention_days = retention_days
        self.scheduler = AsyncIOScheduler()
        self.path_manager = get_path_manager()

    async def cleanup_task(self):
        """清理任务"""
        logger.info("Starting session cleanup task...")

        try:
            cleaned_count = self.path_manager.cleanup_old_sessions(
                days=self.retention_days
            )

            logger.info(
                f"Session cleanup completed. "
                f"Cleaned {cleaned_count} sessions older than {self.retention_days} days."
            )

            # 记录当前session统计
            sessions = self.path_manager.list_sessions()
            total_size_mb = sum(s["size_mb"] for s in sessions)

            logger.info(
                f"Current sessions: {len(sessions)}, "
                f"Total size: {total_size_mb:.2f} MB"
            )

        except Exception as e:
            logger.error(f"Session cleanup failed: {e}", exc_info=True)

    def start(self, cron_expression: str = "0 2 * * *"):
        """
        启动调度器

        Args:
            cron_expression: Cron表达式,默认每天凌晨2点执行
                            格式: 分 时 日 月 周
                            示例:
                            - "0 2 * * *": 每天凌晨2点
                            - "0 */6 * * *": 每6小时
                            - "0 0 * * 0": 每周日凌晨
        """
        self.scheduler.add_job(
            self.cleanup_task,
            trigger=CronTrigger.from_crontab(cron_expression),
            id="session_cleanup",
            name="Session Cleanup Task",
            replace_existing=True
        )

        self.scheduler.start()
        logger.info(
            f"Session cleanup scheduler started. "
            f"Cron: {cron_expression}, Retention: {self.retention_days} days"
        )

    def stop(self):
        """停止调度器"""
        self.scheduler.shutdown()
        logger.info("Session cleanup scheduler stopped.")

    async def run_now(self):
        """立即执行一次清理"""
        await self.cleanup_task()


# 全局调度器实例
_scheduler = None


def get_cleanup_scheduler(retention_days: int = 7) -> SessionCleanupScheduler:
    """
    获取全局清理调度器

    Args:
        retention_days: 保留天数

    Returns:
        SessionCleanupScheduler实例
    """
    global _scheduler
    if _scheduler is None:
        _scheduler = SessionCleanupScheduler(retention_days=retention_days)
    return _scheduler


def start_cleanup_scheduler(
    retention_days: int = 7,
    cron_expression: str = "0 2 * * *"
):
    """
    启动清理调度器(便捷函数)

    Args:
        retention_days: 保留天数
        cron_expression: Cron表达式
    """
    scheduler = get_cleanup_scheduler(retention_days)
    scheduler.start(cron_expression)


async def cleanup_sessions_now(retention_days: int = 7):
    """
    立即执行清理(便捷函数)

    Args:
        retention_days: 保留天数
    """
    scheduler = get_cleanup_scheduler(retention_days)
    await scheduler.run_now()


# 使用示例
if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # 启动调度器(每天凌晨2点清理7天前的session)
    start_cleanup_scheduler(retention_days=7, cron_expression="0 2 * * *")

    # 或者立即执行一次清理
    # asyncio.run(cleanup_sessions_now(retention_days=7))

    # 保持程序运行
    try:
        asyncio.get_event_loop().run_forever()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
