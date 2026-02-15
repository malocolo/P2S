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

# 全局 db 会话
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
        else:
            print(f"Task {args.name} not found for deletion.")
    except Exception as e:
        print(f"Error deleting task: {e}")


if __name__ == "__main__":
    if args.opt == "query":
        task = find_one_and_update()
        
        if task is None:
            print("没有找到 'draft' 状态的任务。")
            quit()
            
        urlinfo = task.url.split("##")
        
        # 确保格式正确：[0]是链接，[1]是文件名
        if len(urlinfo) >= 2:
            download_url = urlinfo[0]
            file_name = urlinfo[1]
        else:
            print(f"Error: URL format incorrect: {task.url}")
            quit()

        # === 关键修改 ===
        # 1. 创建一个临时的 cookies 文件路径
        cookie_file = "aria2_cookies.txt"
        
        # 2. 构造 User-Agent (模拟 Chrome)
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"

        # 构建命令
        # --header="Cookie: ..." : 如果你能获取到浏览器里的 Cookie，可以在这里加上
        # --save-cookies / --load-cookies : 解决无限重定向的核心
        # --referer : 解决防盗链
        cmd = (
            f'aria2c --conf-path=aria2.conf '
            f'--seed-time=0 '
            f'--dir=downloads '
            f'--out="{file_name}" '
            f'--console-log-level=notice '
            f'--user-agent="{ua}" '
            f'--referer="{download_url}" '
            f'--save-cookies="{cookie_file}" '
            f'--load-cookies="{cookie_file}" '
            f'"{download_url}"'
        )

        print("-" * 20)
        print(f"正在下载: {file_name}")
        print(f"下载链接: {download_url}")
        print(f"Referer: {download_url}")
        print("-" * 20)

        # 执行下载
        exit_code = os.system(cmd)
        
        # 清理 cookie 文件 (可选)
        if os.path.exists(cookie_file):
            try:
                os.remove(cookie_file)
            except:
                pass

        # 下载失败处理
        if exit_code != 0:
            print(f"错误: 下载失败，退出码 {exit_code}")
            sys.exit(1)
            
        quit()

    if args.opt == "delete":
        delete_task()
