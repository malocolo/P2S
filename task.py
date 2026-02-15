import sys
import argparse
import os
import time
import requests
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

# === 浏览器仿真下载引擎 ===
def download_file(url, filename):
    print(f"[*] 启动下载: {filename}")
    print(f"[*] 目标 URL: {url}")
    
    # 模拟真实浏览器的 Headers
    # 关键点：Accept, Accept-Language, Range
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7',
        'Referer': 'https://dav.2dland.cn/',
        'Range': 'bytes=0-', # 关键：告诉服务器我是流媒体播放器/下载器
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1'
    }

    try:
        session = requests.Session()
        session.headers.update(headers)
        
        start_time = time.time()
        # 允许重定向，设置较长的超时时间
        response = session.get(url, stream=True, timeout=60, allow_redirects=True)
        
        print(f"[*] 最终 URL: {response.url}")
        print(f"[*] 状态码: {response.status_code}")
        
        response.raise_for_status()

        total_size = int(response.headers.get('content-length', 0))
        if total_size > 0:
            print(f"[*] 文件大小: {total_size / 1024 / 1024:.2f} MB")
        else:
            print(f"[*] 文件大小: 未知 (流式传输)")

        downloaded = 0
        chunk_size = 1024 * 1024 
        
        with open(filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                         percent = (downloaded / total_size) * 100
                         if downloaded % (20 * 1024 * 1024) < chunk_size:
                             print(f"--> 进度: {percent:.2f}%")
        
        print(f"[*] 下载成功！耗时: {time.time() - start_time:.2f}s")
        return True

    except Exception as e:
        print(f"[!] 下载失败: {e}")
        return False

if __name__ == "__main__":
    if args.opt == "query":
        task = find_one_and_update()
        if not task:
            print("没有找到任务。")
            quit()
            
        urlinfo = task.url.split("##")
        if len(urlinfo) >= 2:
            raw_url = urlinfo[0]
            file_name = urlinfo[1]
            
            if not os.path.exists("downloads"):
                os.makedirs("downloads")
            
            save_path = os.path.join("downloads", file_name)
            
            # 直接尝试下载，依赖 WARP 解决 IP 问题
            if not download_file(raw_url, save_path):
                sys.exit(1)
        else:
            print("URL 格式错误")
            quit()

    if args.opt == "delete":
        delete_task()
