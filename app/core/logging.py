"""
日志配置模块

使用 loguru 提供高性能、美观的日志输出。
"""

import sys

from loguru import logger


def setup_logger(
    level: str = "INFO",
    format_string: str | None = None,
    log_file: str | None = None,
) -> None:
    """配置日志系统
    
    Args:
        level: 日志级别
        format_string: 日志格式，默认使用美观的彩色格式
        log_file: 日志文件路径，None 表示只输出到控制台
    """
    # 移除默认处理器
    logger.remove()

    # 默认格式：带颜色的美观格式
    if format_string is None:
        format_string = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        )

    # 添加控制台处理器
    logger.add(
        sys.stderr,
        format=format_string,
        level=level,
        colorize=True,
        backtrace=True,
        diagnose=True,
    )

    # 可选：添加文件处理器
    if log_file:
        logger.add(
            log_file,
            format=format_string,
            level=level,
            rotation="10 MB",
            retention="7 days",
            compression="zip",
        )


def get_logger(name: str | None = None):
    """获取日志记录器
    
    Args:
        name: 日志名称，通常为模块名
        
    Returns:
        配置好的 logger 实例
    """
    if name:
        return logger.bind(name=name)
    return logger


# 自动配置默认日志
setup_logger()
