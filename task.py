import sys
import argparse
import os
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import func

parser = argparse.ArgumentParser(description="操作数据库")
parser.add_argument("--opt", help="操作", default="query")
parser.add_argument("--con", help="数据库链接地址", default="")
parser.add_argument("--name", help="文件名称", default="")

args = parser.parse_args()

# 创建数据库引擎
engine = create_engine(
    args.con,
    echo=False,
)

# 创建会话工厂
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# === 核心修改：实例化一个全局 db 会话，后续所有操作都用这个 ===
db = SessionLocal()
Base = declarative_base()


class Task(Base):
    __tablename__ = "task"
    id = Column(Integer, unique=True, primary_key=True)
    status = Column(String, index=True)
    sort = Column(Integer)
    date_created = Column(DateTime(timezone=True), server_default=func.now())
    url = Column(String)


def find_one_and_update():
    # === 修正：直接使用全局 db，不要再创建新的 session ===
    try:
        task = db.query(Task).filter(Task.status == "draft").first()
        if task:
            task.status = "published"
            db.commit()
            db.refresh(task)
            return task
        return None
    except Exception as e:
        print(f"Error querying database: {e}")
        return None


def delete_task():
    # === 修正：直接使用全局 db ===
    try:
        keyword = "##" + args.name
        # 注意：这里可能需要根据实际情况调整 query 逻辑
        # 如果你的 url 格式是 "链接##文件名"，且你要根据文件名删除
        task = db.query(Task).filter(Task.url.like(f"%{keyword}")).first()
        if task is not None:
            db.delete(task)
            db.commit()
            print(f"Task {args.name} deleted.")
        else:
            print(f"Task {args.name} not found for deletion.")
    except Exception as e:
        print(f"Error deleting task: {e}")


if __name__ == "__main__":
    if args.opt == "query":
        task = find_one_and_update()
        
        # 如果没有任务，正常退出，不要报错
        if task is None:
            print("没有找到 'draft' 状态的任务。")
            quit()
            
        urlinfo = task.url.split("##")
        
        # === 再次确认：根据你之前的报错日志，[0]是链接，[1]是文件名 ===
        # 如果之前报错 Unrecognized URI ... .mp4，说明 [0] 必须是 http 链接
        if len(urlinfo) >= 2:
            download_url = urlinfo[0]
            file_name = urlinfo[1]
        else:
            print(f"Error: URL format incorrect: {task.url}")
            quit()

        # 构建命令：确保包含重试逻辑
        cmd = (
            f'aria2c --conf-path=aria2.conf '
            f'--seed-time=0 '
            f'--dir=downloads '
            f'--out="{file_name}" '
            f'--console-log-level=notice '
            f'"{download_url}"'
        )

        print("-" * 20)
        print(f"正在下载: {file_name}")
        print(f"下载链接: {download_url}")
        print(f"执行命令: {cmd}")
        print("-" * 20)

        # 执行下载
        exit_code = os.system(cmd)
        
        # 下载失败处理
        if exit_code != 0:
            print(f"错误: 下载失败，退出码 {exit_code}")
            sys.exit(1)
            
        quit()

    if args.opt == "delete":
        delete_task()
