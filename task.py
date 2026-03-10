import argparse
import os
import sys
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import unquote, urlsplit, urlunsplit

import requests
from requests.adapters import HTTPAdapter
from sqlalchemy import Column, DateTime, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.sql import func
from urllib3.util.retry import Retry

parser = argparse.ArgumentParser(description="操作任务数据库并下载文件")
parser.add_argument("--opt", help="操作类型: query / delete / requeue", default="query")
parser.add_argument("--con", help="数据库连接字符串", default="")
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


if not args.con:
    print("Error: --con 不能为空")
    sys.exit(1)

engine = create_engine(args.con, echo=False, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

DOWNLOAD_DIR = Path("downloads")
TIMEOUT = (20, 300)
CHUNK_SIZE = 1024 * 1024


def parse_task_url(url_value: str) -> Tuple[str, str]:
    parts = url_value.split("##", 1)
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        raise ValueError("任务链接格式错误，必须为: url##filename")
    return parts[0].strip(), parts[1].strip()


def mask_url(raw_url: str) -> str:
    try:
        parsed = urlsplit(raw_url)
        netloc = parsed.hostname or ""
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    except Exception:
        return "<invalid-url>"


def parse_auth_url(raw_url: str) -> Tuple[str, Optional[Tuple[str, str]], str]:
    parsed = urlsplit(raw_url)

    username = unquote(parsed.username) if parsed.username else None
    password = unquote(parsed.password) if parsed.password else None

    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"

    clean_url = urlunsplit((parsed.scheme, host, parsed.path, parsed.query, parsed.fragment))
    auth = (username, password) if username is not None else None
    referer = f"{parsed.scheme}://{parsed.hostname}/" if parsed.scheme and parsed.hostname else ""
    return clean_url, auth, referer


def get_retry_session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        redirect=5,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(["HEAD", "GET", "OPTIONS"]),
        raise_on_status=False,
    )

    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/132.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
        }
    )
    return session


def claim_one_task(db) -> Optional[Task]:
    try:
        query = (
            db.query(Task)
            .filter(Task.status == "draft")
            .order_by(Task.sort.asc(), Task.id.asc())
        )

        try:
            task = query.with_for_update(skip_locked=True).first()
        except Exception:
            task = query.first()

        if task is None:
            return None

        task.status = "processing"
        db.commit()
        db.refresh(task)
        return task
    except Exception as exc:
        db.rollback()
        print(f"Error querying database: {exc}")
        return None


def find_task_by_name(db, file_name: str) -> Optional[Task]:
    keyword = f"##{file_name}"
    return (
        db.query(Task)
        .filter(Task.url.like(f"%{keyword}"))
        .order_by(Task.id.desc())
        .first()
    )


def delete_task(file_name: str) -> int:
    db = SessionLocal()
    try:
        task = find_task_by_name(db, file_name)
        if task is None:
            print(f"Task {file_name} not found, skip delete.")
            return 0

        db.delete(task)
        db.commit()
        print(f"Task {file_name} deleted.")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"Error deleting task: {exc}")
        return 1
    finally:
        db.close()


def requeue_task(file_name: str) -> int:
    db = SessionLocal()
    try:
        task = find_task_by_name(db, file_name)
        if task is None:
            print(f"Task {file_name} not found, skip requeue.")
            return 0

        task.status = "draft"
        db.commit()
        print(f"Task {file_name} requeued.")
        return 0
    except Exception as exc:
        db.rollback()
        print(f"Error requeueing task: {exc}")
        return 1
    finally:
        db.close()


def cleanup_partial_file(partial_path: Path) -> None:
    try:
        if partial_path.exists():
            partial_path.unlink()
    except Exception:
        pass


def download_file(raw_url: str, file_name: str) -> Path:
    clean_url, auth, referer = parse_auth_url(raw_url)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    final_path = DOWNLOAD_DIR / file_name
    partial_path = DOWNLOAD_DIR / f"{file_name}.part"
    cleanup_partial_file(partial_path)

    session = get_retry_session()
    if referer:
        session.headers["Referer"] = referer

    print("-" * 20)
    print(f"正在下载: {file_name}")
    print(f"下载链接: {mask_url(raw_url)}")
    print("-" * 20)

    try:
        with session.get(
            clean_url,
            auth=auth,
            stream=True,
            allow_redirects=True,
            timeout=TIMEOUT,
        ) as response:
            if response.status_code >= 400:
                print(f"最终请求地址: {mask_url(response.url)}")
                raise requests.HTTPError(
                    f"下载失败，HTTP 状态码: {response.status_code}",
                    response=response,
                )

            with partial_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if chunk:
                        handle.write(chunk)

            if partial_path.stat().st_size == 0:
                raise RuntimeError("下载完成但文件大小为 0")

            os.replace(partial_path, final_path)
            print(f"下载完成: {final_path} ({final_path.stat().st_size} bytes)")
            return final_path
    except Exception:
        cleanup_partial_file(partial_path)
        raise
    finally:
        session.close()


def query_and_download() -> int:
    db = SessionLocal()
    task = None
    file_name = ""
    try:
        task = claim_one_task(db)
        if task is None:
            print("没有找到任务。")
            return 0

        download_url, file_name = parse_task_url(task.url)
        download_file(download_url, file_name)
        return 0
    except Exception as exc:
        print(f"处理任务失败: {exc}")
        if file_name:
            try:
                requeue_task(file_name)
            except Exception as requeue_exc:
                print(f"任务回滚失败: {requeue_exc}")
        elif task is not None:
            try:
                task.status = "draft"
                db.commit()
                print(f"任务 {task.id} 已回滚为 draft")
            except Exception as rollback_exc:
                db.rollback()
                print(f"任务 {task.id} 回滚失败: {rollback_exc}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    if args.opt == "query":
        sys.exit(query_and_download())
    if args.opt == "delete":
        sys.exit(delete_task(args.name))
    if args.opt == "requeue":
        sys.exit(requeue_task(args.name))

    print(f"Error: unsupported --opt value: {args.opt}")
    sys.exit(1)
