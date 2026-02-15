import sys
import argparse
import os
import time
import requests
import re
from urllib.parse import urlparse
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

def extract_ipfs_cid(url):
    # 匹配 bafy... (v1) 或 Qm... (v0)
    match = re.search(r'(bafy[a-zA-Z0-9]{40,}|Qm[a-zA-Z0-9]{44})', url)
    if match:
        return match.group(1)
    return None

def try_download_url(session, url, filename, description):
    print(f"--- 尝试策略: {description} ---")
    print(f"    URL: {url}")
    try:
        start_time = time.time()
        # 增加 connect timeout, 减少 read timeout
        response = session.get(url, stream=True, timeout=(10, 30), allow_redirects=True)
        
        final_url = response.url
        
        # 捕获 403 但返回 URL 供提取 CID
        if response.status_code == 403:
            print(f"[!] 403 Forbidden (IP限制) - {final_url}")
            return False, final_url
            
        if response.status_code == 404 or response.status_code == 502:
            print(f"[!] {response.status_code} - 文件未找到或网关错误")
            return False, final_url
            
        response.raise_for_status()

        total_size = int(response.headers.get('content-length', 0))
        
        # 检查内容类型，避免下载到 HTML 错误页
        content_type = response.headers.get('Content-Type', '').lower()
        if 'text/html' in content_type and total_size < 100000:
             print("[!] 警告: 返回的是 HTML 页面，可能是错误提示，跳过。")
             return False, final_url

        if total_size > 0:
            print(f"[*] 连接成功! 大小: {total_size / 1024 / 1024:.2f} MB")
        else:
            print(f"[*] 连接成功! (流式)")

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
        return True, final_url
        
    except Exception as e:
        print(f"[!] 错误: {e}")
        return False, url

def download_engine(initial_url, filename, user_agent):
    print(f"[*] 启动下载任务: {filename}")
    
    # 提取纯文件名 (用于 IPFS 路径)
    # 之前错误的原因是把 downloads/xx.mp4 拼进去了
    clean_filename = os.path.basename(filename) 
    
    parsed = urlparse(initial_url)
    domain = f"{parsed.scheme}://{parsed.netloc}/"
    
    session = requests.Session()
    session.headers.update({
        'User-Agent': user_agent,
        'Referer': domain,
    })

    # 1. 尝试原始链接
    success, last_url = try_download_url(session, initial_url, filename, "原始链接")
    if success:
        return True

    # 2. 穿墙模式
    print(f"[*] 检查链接是否包含 CID: {last_url}")
    cid = extract_ipfs_cid(last_url)
    if not cid:
        cid = extract_ipfs_cid(initial_url)

    if cid:
        print(f"[*] 捕获到 IPFS CID: {cid}，启动公共网关轮询...")
        session.headers.pop('Referer', None) # 公共网关不需要 Referer
        
        # 不同的路径组合
        # 组合1: ipfs/<cid>/<filename> (针对文件夹 CID)
        # 组合2: ipfs/<cid> (针对文件 CID)
        paths_to_try = [
            clean_filename, # 优先尝试带文件名
            ""              # 其次尝试纯 CID
        ]
        
        # 优质公共网关列表
        base_gateways = [
            "https://gateway.pinata.cloud/ipfs",
            "https://ipfs.io/ipfs",
            "https://dweb.link/ipfs",
            "https://4everland.io/ipfs",
            "https://w3s.link/ipfs"
        ]
        
        for path_suffix in paths_to_try:
            for base_gw in base_gateways:
                # 拼接 URL
                if path_suffix:
                    gw_url = f"{base_gw}/{cid}/{path_suffix}"
                    desc = f"网关[{base_gw}] + 文件名"
                else:
                    gw_url = f"{base_gw}/{cid}"
                    desc = f"网关[{base_gw}] + 纯CID"
                
                success, _ = try_download_url(session, gw_url, filename, desc)
                if success:
                    return True
    else:
        print("[!] 未能提取到 CID。")

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
            
            # 使用更通用的 UA
            ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            
            if not download_engine(raw_url, save_path, ua):
                print("[X] 最终失败。")
                sys.exit(1)
        else:
            print("URL 格式错误")
            quit()

    if args.opt == "delete":
        delete_task()
