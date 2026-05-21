import os
import time
import requests
import pandas as pd
from pathlib import Path

BASE_URL = "https://graph.instagram.com/v21.0"

MEDIA_TYPE_KR = {
    "REELS": "릴스",
    "VIDEO": "영상",
    "IMAGE": "이미지",
    "CAROUSEL_ALBUM": "캐러셀",
}


def _find_dotenv() -> Path | None:
    script_dir = Path(__file__).parent
    candidates = [
        script_dir / ".env",
        script_dir / "venv" / ".env",
        Path.cwd() / ".env",
        Path.cwd() / "venv" / ".env",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def load_credentials() -> tuple[str, str]:
    """Return (access_token, instagram_user_id) from Streamlit secrets or .env."""
    try:
        import streamlit as st
        if hasattr(st, "secrets") and "ACCESS_TOKEN" in st.secrets:
            return st.secrets["ACCESS_TOKEN"], st.secrets["INSTAGRAM_USER_ID"]
    except Exception:
        pass

    env_path = _find_dotenv()
    if env_path:
        try:
            from dotenv import load_dotenv
            load_dotenv(env_path)
        except ImportError:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())

    token = os.getenv("ACCESS_TOKEN")
    user_id = os.getenv("INSTAGRAM_USER_ID")
    if not token or not user_id:
        raise EnvironmentError(
            "ACCESS_TOKEN / INSTAGRAM_USER_ID를 찾을 수 없습니다.\n"
            ".env 파일 또는 Streamlit Secrets에 설정해주세요.\n"
            "찾은 .env 경로: " + str(_find_dotenv())
        )
    return token, user_id


def _get(url: str, params: dict, timeout: int = 30) -> dict:
    resp = requests.get(url, params=params, timeout=timeout)
    body = resp.json()
    if "error" in body:
        raise RuntimeError(body["error"].get("message", str(body["error"])))
    resp.raise_for_status()
    return body


def get_all_media(token: str, user_id: str) -> list[dict]:
    """Fetch all media IDs from the account (handles pagination)."""
    media_list: list[dict] = []
    url = f"{BASE_URL}/{user_id}/media"
    params: dict = {
        "fields": "id,caption,media_type,timestamp,permalink",
        "access_token": token,
        "limit": 100,
    }

    while True:
        body = _get(url, params)
        media_list.extend(body.get("data", []))
        next_url = body.get("paging", {}).get("next")
        if not next_url:
            break
        url = next_url
        params = {}  # next URL already contains all query params

    return media_list


def _parse_insights(data: list) -> dict:
    result = {}
    for item in data:
        vals = item.get("values", [])
        result[item["name"]] = vals[0].get("value", 0) if vals else 0
    return result


def get_media_insights(token: str, media_id: str, media_type: str) -> dict:
    """Fetch insights for a single media item."""
    url = f"{BASE_URL}/{media_id}/insights"
    insights: dict = {}

    common = ["reach", "likes", "comments", "saved", "shares"]

    if media_type in ("IMAGE", "CAROUSEL_ALBUM"):
        extras = ["impressions", "profile_visits", "follows"]
    else:
        extras = []

    # Try common + extras in one request; fall back to common-only on error
    try:
        body = _get(url, {"metric": ",".join(common + extras), "access_token": token}, timeout=20)
        insights.update(_parse_insights(body.get("data", [])))
    except Exception:
        try:
            body = _get(url, {"metric": ",".join(common), "access_token": token}, timeout=20)
            insights.update(_parse_insights(body.get("data", [])))
        except Exception:
            pass

        for metric in extras:
            if metric not in insights:
                try:
                    body = _get(url, {"metric": metric, "access_token": token}, timeout=10)
                    insights.update(_parse_insights(body.get("data", [])))
                except Exception:
                    pass

    # REELS/VIDEO: try views → plays → video_views
    if media_type in ("REELS", "VIDEO"):
        for view_metric in ("views", "plays", "video_views"):
            try:
                body = _get(url, {"metric": view_metric, "access_token": token}, timeout=10)
                data = body.get("data", [])
                if data:
                    vals = data[0].get("values", [])
                    insights["views"] = vals[0].get("value", 0) if vals else 0
                    break
            except Exception:
                continue

    return insights


def fetch_insights(progress_callback=None) -> pd.DataFrame:
    """Fetch all Instagram media insights. Returns a pandas DataFrame."""
    token, user_id = load_credentials()
    media_list = get_all_media(token, user_id)
    total = len(media_list)
    records = []

    for i, media in enumerate(media_list):
        if progress_callback:
            progress_callback(i, total, media.get("id", ""))

        media_id = media["id"]
        media_type = media.get("media_type", "IMAGE")
        timestamp = media.get("timestamp", "")
        caption = (media.get("caption") or "")[:150]
        permalink = media.get("permalink", "")

        try:
            ins = get_media_insights(token, media_id, media_type)
        except Exception:
            ins = {}

        reach = int(ins.get("reach") or 0)
        likes = int(ins.get("likes") or 0)
        comments = int(ins.get("comments") or 0)
        saved = int(ins.get("saved") or 0)
        shares = int(ins.get("shares") or 0)
        views = int(ins.get("views") or 0)
        impressions = int(ins.get("impressions") or 0)
        profile_visits = int(ins.get("profile_visits") or 0)
        follows = int(ins.get("follows") or 0)

        engagement_rate = (likes + comments + saved + shares) / reach * 100 if reach else 0.0
        share_rate = shares / reach * 100 if reach else 0.0
        completion_rate = views / reach * 100 if (reach and media_type in ("REELS", "VIDEO")) else 0.0

        records.append({
            "미디어ID": media_id,
            "날짜": timestamp[:10] if len(timestamp) >= 10 else "",
            "미디어타입": MEDIA_TYPE_KR.get(media_type, media_type),
            "미디어타입_원본": media_type,
            "캡션": caption,
            "링크": permalink,
            "도달": reach,
            "좋아요": likes,
            "댓글": comments,
            "저장": saved,
            "공유": shares,
            "조회수": views,
            "노출": impressions,
            "프로필방문": profile_visits,
            "팔로우": follows,
            "참여율(%)": round(engagement_rate, 2),
            "공유율(%)": round(share_rate, 2),
            "조회완료율(%)": round(completion_rate, 2),
        })

        time.sleep(0.1)  # API rate limit 준수

    df = pd.DataFrame(records)
    if not df.empty:
        df["날짜"] = pd.to_datetime(df["날짜"], errors="coerce")
        df = df.sort_values("날짜", ascending=False).reset_index(drop=True)

    return df


if __name__ == "__main__":
    def _cb(i, total, mid):
        print(f"\r[{i+1}/{total}] {mid}", end="", flush=True)

    df = fetch_insights(progress_callback=_cb)
    print(f"\n\n총 {len(df)}개 미디어 수집 완료")
    pd.set_option("display.max_columns", None)
    print(df[["날짜", "미디어타입", "도달", "좋아요", "참여율(%)"]].head(10).to_string())
