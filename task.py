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
    # 匹配 bafy 开头的 CID v1 或 Qm 开头的 CID v0
    match = re.search(r'(bafy[a-zA-Z0-9]{40,}|Qm[a-zA-Z0-9]{44})', url)
    if match:
        return match.group(1)
    return None

# === 核心下载引擎 ===
def download_engine(url, filename, user_agent):
    print(f"[*] 正在尝试下载: {filename}")
    
    # 解析域名作为 Referer，而不是完整的 URL，这能规避部分防盗链
    parsed_uri = urlparse(url)
    domain = '{uri.scheme}://{uri.netloc}/'.format(uri=parsed_uri)
    
    headers = {
        'User-Agent': user_agent,
        'Referer': domain, # 修正 Referer
        'Origin': domain
    }
    
    # 策略列表
    strategies = [
        {"name": "原始链接 (直连)", "url": url},
    ]
    
    # 尝试提取 CID 添加备选策略
    cid = extract_ipfs_cid(url)
    if cid:
        print(f"[*] 检测到 IPFS CID: {cid}")
        # 这里的 filename 需要 URL 编码吗？通常 requests 会处理
        strategies.append({"name": "Cloudflare 公共网关 (穿墙)", "url": f"https://cloudflare-ipfs.com/ipfs/{cid}/{filename}"})
        strategies.append({"name": "IPFS.io 官方网关", "url": f"https://ipfs.io/ipfs/{cid}/{filename}"})
        strategies.append({"name": "4EVERLAND 网关", "url": f"https://4everland.io/ipfs/{cid}/{filename}"})
    
    session = requests.Session()
    session.headers.update(headers)
    
    for strategy in strategies:
        print(f"--- 正在尝试策略: {strategy['name']} ---")
        print(f"    URL: {strategy['url']}")
        
        try:
            # 1. 尝试连接 (stream=True)
            start_time = time.time()
            response = session.get(strategy['url'], stream=True, timeout=20, allow_redirects=True)
            
            # 检查状态码
            if response.status_code == 403:
                print(f"[!] 403 Forbidden - 服务器拒绝了请求 (可能是 IP 黑名单)")
                response.close()
                continue # 尝试下一个策略
                
            if response.status_code == 404:
                print(f"[!] 404 Not Found - 文件不存在")
                response.close()
                continue
                
            response.raise_for_status() # 其他错误抛出异常
            
            # 2. 开始写入
            total_size = int(response.headers.get('content-length', 0))
            if total_size > 0:
                print(f"[*] 连接成功! 文件大小: {total_size / 1024 / 1024:.2f} MB")
            else:
                print(f"[*] 连接成功! (流式传输，未知大小)")

            downloaded_size = 0
            chunk_size = 1024 * 1024 
            
            with open(filename, 'wb') as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        
                        # 进度条
                        if total_size > 0:
                            percent = (downloaded_size / total_size) * 100
                            if downloaded_size % (20 * 1024 * 1024) < chunk_size: # 每20MB打印一次
                                 print(f"--> 进度: {percent:.2f}%")
            
            end_time = time.time()
            print(f"[*] 下载成功！策略 [{strategy['name']}] 有效。耗时: {end_time - start_time:.2f} 秒")
            return True # 只要有一个成功，就直接返回
            
        except Exception as e:
            print(f"[!] 策略 [{strategy['name']}] 失败: {e}")
            
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
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
        
        if not os.path.exists("downloads"):
            os.makedirs("downloads")
        
        save_path = os.path.join("downloads", file_name)

        # 启动下载引擎
        success = download_engine(raw_url, save_path, ua)
        
        if not success:
            print("[X] 所有下载策略均失败。")
            sys.exit(1)
            
        quit()

    if args.opt == "delete":
        delete_task()
