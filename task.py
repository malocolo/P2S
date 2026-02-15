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

# === Python 原生下载器 ===
def python_download(url, filename, user_agent, referer):
    print(f"[*] 启动 Python 下载引擎...")
    
    headers = {
        'User-Agent': user_agent,
        'Referer': referer
    }
    
    session = requests.Session()
    session.headers.update(headers)
    
    try:
        # 1. 发起请求 (stream=True 是关键)
        start_time = time.time()
        response = session.get(url, stream=True, timeout=60, allow_redirects=True)
        response.raise_for_status() # 检查 403/404 等错误
        
        # 获取文件大小
        total_size = int(response.headers.get('content-length', 0))
        
        # 2. 写入文件
        downloaded_size = 0
        chunk_size = 1024 * 1024 # 1MB 一块
        
        print(f"[*] 开始下载: {filename}")
        if total_size > 0:
            print(f"[*] 文件大小: {total_size / 1024 / 1024:.2f} MB")
        else:
            print(f"[*] 文件大小: 未知 (流式传输)")

        with open(filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded_size += len(chunk)
                    
                    # 简单的进度打印
                    if total_size > 0:
                        percent = (downloaded_size / total_size) * 100
                        # 每下载 10MB 打印一次日志，避免刷屏太快
                        if downloaded_size % (10 * 1024 * 1024) < chunk_size:
                             print(f"--> 进度: {percent:.2f}% ({downloaded_size / 1024 / 1024:.2f} MB)")
                    else:
                        # 如果没有总大小，就只打印已下载量
                        if downloaded_size % (10 * 1024 * 1024) < chunk_size:
                            print(f"--> 已下载: {downloaded_size / 1024 / 1024:.2f} MB")
                            
        end_time = time.time()
        print(f"[*] 下载完成！耗时: {end_time - start_time:.2f} 秒")
        return True

    except Exception as e:
        print(f"[!] 下载发生错误: {e}")
        return False

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

        # 定义伪装头
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        
        # 切换到下载目录
        if not os.path.exists("downloads"):
            os.makedirs("downloads")
        
        # 拼接完整的文件路径
        save_path = os.path.join("downloads", file_name)

        # === 直接使用 Python 下载 ===
        success = python_download(raw_url, save_path, ua, raw_url)
        
        if not success:
            # 下载失败，退出码 1
            sys.exit(1)
            
        quit()

    if args.opt == "delete":
        delete_task()
