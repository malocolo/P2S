import argparse
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, unquote

import requests
from sqlalchemy import Column, DateTime, Integer, String, asc, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.sql import func

parser = argparse.ArgumentParser(description="操作数据库与下载任务")
parser.add_argument("--opt", help="操作", default="query")
parser.add_argument("--con", help="数据库链接地址", default="")
parser.add_argument("--name", help="文件名称", default="")
args = parser.parse_args()

Base = declarative_base()


class Task(Base):
    __tablename__ = "task"
    id = Column(Integer, unique=True, primary_key=True)
    status = Column(String, index=True)
    sort = Column(Integer)
    date_created = Column(DateTime(timezone=True), server_default=func.now())
    url = Column(String)


def log(msg: str):
    print(msg, flush=True)


if not args.con:
    log("Error: missing --con database connection string")
    sys.exit(1)

engine = create_engine(args.con, echo=False, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db = SessionLocal()


def human_size(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    n = float(size)
    for unit in units:
        if n < 1024 or unit == units[-1]:
            return f"{n:.2f}{unit}"
        n /= 1024
    return f"{size}B"


def parse_url_with_auth(raw_url: str):
    parsed = urlsplit(raw_url)
    username = unquote(parsed.username) if parsed.username else None
    password = unquote(parsed.password) if parsed.password else None

    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"

    clean_url = urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))
    auth = (username, password) if username is not None else None
    referer = f"{parsed.scheme}://{parsed.hostname}/" if parsed.scheme and parsed.hostname else None
    return clean_url, auth, referer


def get_next_task():
    try:
        task = (
            db.query(Task)
            .filter(Task.status == "draft")
            .order_by(asc(Task.sort).nullslast(), asc(Task.id))
            .first()
        )
        if task:
            task.status = "published"
            db.commit()
            db.refresh(task)
        return task
    except Exception as e:
        db.rollback()
        log(f"Error querying database: {e}")
        return None


def set_task_status_by_filename(filename: str, status: str):
    try:
        keyword = "##" + filename
        task = db.query(Task).filter(Task.url.like(f"%{keyword}")).first()
        if task is None:
            log(f"Task for file not found: {filename}")
            return False
        task.status = status
        db.commit()
        log(f"Task {filename} set to {status}.")
        return True
    except Exception as e:
        db.rollback()
        log(f"Error updating task status: {e}")
        return False


def delete_task(filename: str):
    try:
        keyword = "##" + filename
        task = db.query(Task).filter(Task.url.like(f"%{keyword}")).first()
        if task is not None:
            db.delete(task)
            db.commit()
            log(f"Task {filename} deleted.")
            return True
        log(f"Task {filename} not found for delete.")
        return False
    except Exception as e:
        db.rollback()
        log(f"Error deleting task: {e}")
        return False


def download_file(download_url: str, file_name: str):
    clean_url, auth, referer = parse_url_with_auth(download_url)
    downloads_dir = Path("downloads")
    downloads_dir.mkdir(parents=True, exist_ok=True)
    temp_path = downloads_dir / f"{file_name}.part"
    final_path = downloads_dir / file_name

    if temp_path.exists():
        temp_path.unlink()
    if final_path.exists():
        final_path.unlink()

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36",
        "Accept": "*/*",
        "Connection": "keep-alive",
    }
    if referer:
        headers["Referer"] = referer

    session = requests.Session()
    session.headers.update(headers)

    log("--------------------")
    log(f"正在下载: {file_name}")
    log(f"原始地址: {clean_url}")
    log("开始请求下载链接...")
    log("--------------------")

    try:
        with session.get(
            clean_url,
            auth=auth,
            stream=True,
            allow_redirects=True,
            timeout=(20, 300),
        ) as resp:
            log(f"最终状态码: {resp.status_code}")
            if resp.history:
                for idx, item in enumerate(resp.history, 1):
                    log(f"跳转 {idx}: {item.status_code} -> {item.headers.get('Location', '')[:200]}")
                log(f"最终地址: {resp.url[:300]}")

            resp.raise_for_status()

            total = int(resp.headers.get("Content-Length", "0") or 0)
            if total > 0:
                log(f"文件大小: {human_size(total)}")
            else:
                log("文件大小: 未知")

            downloaded = 0
            last_log_time = 0.0
            last_logged_bytes = 0
            start = time.time()

            with open(temp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    f.write(chunk)
                    downloaded += len(chunk)

                    now = time.time()
                    should_log = False
                    if now - last_log_time >= 2:
                        should_log = True
                    elif downloaded - last_logged_bytes >= 20 * 1024 * 1024:
                        should_log = True

                    if should_log:
                        elapsed = max(now - start, 0.001)
                        speed = downloaded / elapsed
                        if total > 0:
                            pct = downloaded * 100 / total
                            log(
                                f"下载进度: {pct:.2f}% | 已下载 {human_size(downloaded)} / {human_size(total)} | 速度 {human_size(int(speed))}/s"
                            )
                        else:
                            log(
                                f"已下载 {human_size(downloaded)} | 速度 {human_size(int(speed))}/s"
                            )
                        last_log_time = now
                        last_logged_bytes = downloaded

            temp_path.rename(final_path)
            log(f"下载完成: {final_path} ({human_size(downloaded)})")
            return True

    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else "unknown"
        log(f"HTTP 错误: {status}")
        if e.response is not None:
            log(f"响应头: {dict(e.response.headers)}")
        return False
    except requests.RequestException as e:
        log(f"请求失败: {e}")
        return False
    except Exception as e:
        log(f"下载异常: {e}")
        return False
    finally:
        session.close()
        if temp_path.exists() and not final_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass


if __name__ == "__main__":
    if args.opt == "query":
        task = get_next_task()
        if task is None:
            log("没有找到任务。")
            sys.exit(0)

        urlinfo = task.url.split("##", 1)
        if len(urlinfo) != 2:
            log("Error: URL format incorrect, expected 'url##filename'")
            task.status = "draft"
            db.commit()
            sys.exit(1)

        download_url, file_name = urlinfo[0].strip(), urlinfo[1].strip()
        ok = download_file(download_url, file_name)
        if not ok:
            task.status = "draft"
            db.commit()
            log("下载失败，任务已恢复为 draft。")
            sys.exit(1)
        sys.exit(0)

    elif args.opt == "delete":
        sys.exit(0 if delete_task(args.name) else 1)

    elif args.opt == "requeue":
        sys.exit(0 if set_task_status_by_filename(args.name, "draft") else 1)

    else:
        log(f"Unknown opt: {args.opt}")
        sys.exit(1)
