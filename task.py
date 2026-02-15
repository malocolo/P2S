import sys
import argparse
import os
from sqlalchemy import (
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

engine = create_engine(args.con, echo=False)
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
    try:
        keyword = "##" + args.name
        task = db.query(Task).filter(Task.url.like(f"%{keyword}")).first()
        if task is not None:
            db.delete(task)
            db.commit()
            print(f"Task {args.name} deleted.")
    except Exception as e:
        print(f"Error deleting task: {e}")

if __name__ == "__main__":
    if args.opt == "query":
        task = find_one_and_update()
        
        if task is None:
            print("没有找到任务。")
            quit()
            
        urlinfo = task.url.split("##")
        if len(urlinfo) >= 2:
            download_url = urlinfo[0]
            file_name = urlinfo[1]
        else:
            print(f"Error: URL format incorrect")
            quit()

        # 创建 Cookie 文件
        cookie_file = "aria2_cookies.txt"
        with open(cookie_file, 'w') as f:
            f.write("")

        # 构建命令
        # -s 1 -x 1: 强制单线程，防止多线程竞争导致验证失败
        # --save/load-cookies: 处理重定向会话
        cmd = (
            f'aria2c --conf-path=aria2.conf '
            f'--dir=downloads '
            f'--out="{file_name}" '
            f'--referer="{download_url}" ' 
            f'--save-cookies="{cookie_file}" '
            f'--load-cookies="{cookie_file}" '
            f'-s 1 -x 1 ' 
            f'--console-log-level=notice '
            f'"{download_url}"'
        )

        print("-" * 20)
        print(f"正在下载: {file_name}")
        print(f"下载链接: {download_url}")
        print("-" * 20)

        exit_code = os.system(cmd)
        
        if exit_code != 0:
            print(f"下载失败，退出码: {exit_code}")
            sys.exit(1)
            
        quit()

    if args.opt == "delete":
        delete_task()
