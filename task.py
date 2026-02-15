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

# === 提取 IPFS CID ===
def extract_ipfs_cid(url):
    # 匹配 bafy... (v1) 或 Qm... (v0)
    match = re.search(r'(bafy[a-zA-Z0-9]{40,}|Qm[a-zA-Z0-9]{44})', url)
    if match:
        return match.group(1)
    return None

# === 单次下载尝试函数 ===
def try_download_url(session, url, filename, description):
    print(f"--- 尝试策略: {description} ---")
    print(f"    URL: {url}")
    try:
        start_time = time.time()
        # 允许重定向，这样如果原始链接跳转，我们能拿到最终 URL
        response = session.get(url, stream=True, timeout=20, allow_redirects=True)
        
        # === 核心修改：即使 403，也检查 URL 是否泄露了 CID ===
        final_url = response.url
        
        if response.status_code == 403:
            print(f"[!] 403 Forbidden - {final_url}")
            # 返回失败，但把最终 URL 带出去，供提取 CID
            return False, final_url
            
        if response.status_code == 404:
            print(f"[!] 404 Not Found")
            return False, final_url
            
        response.raise_for_status()

        # 开始下载
        total_size = int(response.headers.get('content-length', 0))
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
        return False, url # 返回尝试过的 URL

# === 主引擎 ===
def download_engine(initial_url, filename, user_agent):
    print(f"[*] 启动下载任务: {filename}")
    
    # 基础 headers
    parsed = urlparse(initial_url)
    domain = f"{parsed.scheme}://{parsed.netloc}/"
    
    session = requests.Session()
    session.headers.update({
        'User-Agent': user_agent,
        'Referer': domain,
    })

    # 1. 首先尝试原始链接
    success, last_url = try_download_url(session, initial_url, filename, "原始链接")
    if success:
        return True

    # 2. 如果失败，检查最后一次的 URL 是否包含 CID
    print(f"[*] 检查跳转后的链接是否包含 CID: {last_url}")
    cid = extract_ipfs_cid(last_url)
    
    if not cid:
        # 如果原始链接里本身就有 CID，但没跳转就失败了
        cid = extract_ipfs_cid(initial_url)

    if cid:
        print(f"[*] 捕获到 IPFS CID: {cid}，启动穿墙模式...")
        
        # 公共网关列表 (优先 Cloudflare)
        gateways = [
            ("Cloudflare", f"https://cloudflare-ipfs.com/ipfs/{cid}/{filename}"),
            ("IPFS.io", f"https://ipfs.io/ipfs/{cid}/{filename}"),
            ("4EVERLAND", f"https://4everland.io/ipfs/{cid}/{filename}"),
            ("Dweb", f"https://dweb.link/ipfs/{cid}/{filename}")
        ]
        
        for name, gw_url in gateways:
            # 清除 Referer，因为公共网关不需要原来的 Referer
            session.headers.pop('Referer', None)
            success, _ = try_download_url(session, gw_url, filename, f"公共网关 [{name}]")
            if success:
                return True
    else:
        print("[!] 未能提取到 CID，无法使用公共网关。")

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
            
            # 确保下载目录存在
            if not os.path.exists("downloads"):
                os.makedirs("downloads")
            
            save_path = os.path.join("downloads", file_name)
            
            # 伪装 UA
            ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
            
            if not download_engine(raw_url, save_path, ua):
                print("[X] 最终失败。")
                sys.exit(1)
        else:
            print("URL 格式错误")
            quit()

    if args.opt == "delete":
        delete_task()
