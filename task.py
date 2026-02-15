import sys
import argparse
import os
import requests  # 必须引入这个库
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

# === 核心：用 Python 跑完重定向流程 ===
def get_real_download_info(initial_url):
    print(f"[*] Python正在介入：模拟浏览器解析重定向链...")
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    
    try:
        # 使用 Session 对象，它会自动保持 Cookie
        session = requests.Session()
        session.headers.update({'User-Agent': ua})
        
        # head 请求只拿头部，不下载内容，速度快
        # allow_redirects=True 会自动跟踪跳转直到终点
        resp = session.get(initial_url, allow_redirects=True, stream=True, timeout=30)
        
        final_url = resp.url
        
        # 提取最终有效的 Cookie
        cookies_dict = session.cookies.get_dict()
        cookie_str = "; ".join([f"{k}={v}" for k, v in cookies_dict.items()])
        
        print(f"[*] 解析完成！")
        print(f"[*] 最终直链: {final_url}")
        print(f"[*] 捕获Cookie: {cookie_str[:50]}...") # 只打印前50个字符示意
        
        resp.close()
        return final_url, cookie_str, ua
        
    except Exception as e:
        print(f"[!] 解析失败: {e}")
        # 如果解析失败，死马当活马医，返回原链接
        return initial_url, "", ua

if __name__ == "__main__":
    if args.opt == "query":
        task = find_one_and_update()
        
        if task is None:
            print("没有找到任务。")
            quit()
            
        urlinfo = task.url.split("##")
        if len(urlinfo) >= 2:
            raw_url = urlinfo[0]
            file_name = urlinfo[1]
        else:
            print(f"Error: URL format incorrect")
            quit()

        # 1. 解决 cookie 文件报错，先创建一个空的
        cookie_file = "aria2_cookies.txt"
        with open(cookie_file, 'w') as f:
            f.write("")

        # 2. 调用 Python 解析函数
        final_url, cookie_header, ua = get_real_download_info(raw_url)

        # 3. 构造 Aria2 命令
        # 使用 --header 直接注入 Cookie，这是最稳的方式
        cmd = (
            f'aria2c --conf-path=aria2.conf '
            f'--dir=downloads '
            f'--out="{file_name}" '
            f'--user-agent="{ua}" '
            f'--referer="{raw_url}" '  # 原始地址做 referer
            f'--console-log-level=notice '
        )
        
        # 如果有 Cookie，拼接到 header 里
        if cookie_header:
            cmd += f' --header="Cookie: {cookie_header}"'
            
        # 最后加上下载地址
        cmd += f' "{final_url}"'

        print("-" * 20)
        print(f"开始下载: {file_name}")
        print("-" * 20)

        exit_code = os.system(cmd)
        
        if exit_code != 0:
            sys.exit(1)
            
        quit()

    if args.opt == "delete":
        delete_task()
