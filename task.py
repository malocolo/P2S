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
from sqlalchemy.orm import declarative_base  # 更新了导入方式以消除警告
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.sql import func

parser = argparse.ArgumentParser(description="操作数据库")
parser.add_argument("--opt", help="操作", default="query")
parser.add_argument("--con", help="数据库链接地址", default="")
parser.add_argument("--name", help="文件名称", default="")

args = parser.parse_args()

engine = create_engine(
    args.con,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
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
    with Session(engine) as session:
        task = db.query(Task).filter(Task.status == "draft").first()
        if task:
            task.status = "published"
            session.commit()
            session.refresh(task)
        return task


def delete_task():
    with Session(engine) as session:
        keyword = "##" + args.name
        task = db.query(Task).filter(Task.url.like(f"%{keyword}")).first()
        if task is not None:
            session.delete(task)
            session.commit()


if __name__ == "__main__":
    if args.opt == "query":
        task = find_one_and_update()
        if task is None:
            print("没有找到相关记录")
            quit()
            
        urlinfo = task.url.split("##")
        
        # === 核心修正：根据日志，[0]是链接，[1]是文件名 ===
        download_url = urlinfo[0]
        file_name = urlinfo[1]
        # ===============================================

        # 构建命令：确保包含重试逻辑
        # 注意：--conf-path=aria2.conf 确保读取了 retry-on-403=true
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
        
        # 如果下载失败(非0)，不仅要退出，最好抛出错误让 GitHub Action 停止
        if exit_code != 0:
            print(f"错误: 下载失败，退出码 {exit_code}")
            sys.exit(1)
            
        quit()

    if args.opt == "delete":
        delete_task()
