import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, date, timedelta

from fetch_insights import fetch_insights
from save_to_excel import save_to_excel, get_excel_bytes

# ── 페이지 설정 ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="아이헤이트먼데이 인사이트 대시보드",
    page_icon="📊",
    layout="wide",
)

st.markdown("""
<style>
.section-title {
    font-size: 1.05rem; font-weight: 700; color: #1a1a2e;
    padding: 6px 0 4px; border-bottom: 2px solid #e9ecef; margin: 20px 0 12px;
}
.reel-card {
    background: #ffffff; border: 1px solid #dee2e6; border-radius: 10px;
    padding: 14px 16px; margin: 6px 0;
    box-shadow: 0 1px 4px rgba(0,0,0,.06);
}
.reel-rank { font-size: 1.3rem; font-weight: 800; color: #6c63ff; }
.kpi-row { margin-bottom: 8px; }
</style>
""", unsafe_allow_html=True)

# ── Session state ────────────────────────────────────────────────────────────
if "df" not in st.session_state:
    st.session_state.df = None
if "last_updated" not in st.session_state:
    st.session_state.last_updated = None


# ── 데이터 로드 ──────────────────────────────────────────────────────────────
def load_data() -> pd.DataFrame | None:
    progress_bar = st.progress(0, "인스타그램 미디어 목록 수집 중...")

    def on_progress(i: int, total: int, mid: str):
        pct = (i + 1) / max(total, 1)
        progress_bar.progress(pct, f"[{i+1}/{total}] 미디어 분석 중... ({mid})")

    try:
        df = fetch_insights(progress_callback=on_progress)
        st.session_state.df = df
        st.session_state.last_updated = datetime.now()
        return df
    except Exception as exc:
        st.error(f"데이터 로드 실패: {exc}")
        return None
    finally:
        progress_bar.empty()


# ── 헤더 ─────────────────────────────────────────────────────────────────────
col_title, col_btn = st.columns([5, 1])
with col_title:
    st.title("📊 아이헤이트먼데이 인사이트 대시보드")
    if st.session_state.last_updated:
        st.caption(f"마지막 업데이트: {st.session_state.last_updated.strftime('%Y-%m-%d %H:%M:%S')}")
with col_btn:
    st.write("")
    if st.button("🔄 새로고침", use_container_width=True):
        st.session_state.df = None
        st.rerun()

# ── 초기 로드 ────────────────────────────────────────────────────────────────
if st.session_state.df is None:
    df_raw = load_data()
else:
    df_raw = st.session_state.df

if df_raw is None or df_raw.empty:
    st.warning("데이터를 불러올 수 없습니다. .env 파일의 ACCESS_TOKEN / INSTAGRAM_USER_ID를 확인해주세요.")
    st.stop()

# ── 기간 필터 (사이드바) ─────────────────────────────────────────────────────
st.sidebar.header("📅 기간 필터")
valid_dates = df_raw["날짜"].dropna()
if valid_dates.empty:
    min_date = date.today() - timedelta(days=90)
    max_date = date.today()
else:
    min_date = valid_dates.min().date()
    max_date = valid_dates.max().date()

date_range = st.sidebar.date_input(
    "날짜 범위",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date,
)
if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date, end_date = min_date, max_date

date_mask = (
    df_raw["날짜"].notna()
    & (df_raw["날짜"].dt.date >= start_date)
    & (df_raw["날짜"].dt.date <= end_date)
)
df_filtered = df_raw[date_mask].copy()

st.sidebar.markdown("---")
st.sidebar.metric("기간 내 게시물", len(df_filtered))

# ── 공통 렌더링 함수 ─────────────────────────────────────────────────────────

def _section(title: str):
    st.markdown(f'<div class="section-title">{title}</div>', unsafe_allow_html=True)


def _kpi_row(df: pd.DataFrame):
    _section("📈 전체 합계")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("👁 도달", f"{df['도달'].sum():,}")
    c2.metric("❤️ 좋아요", f"{df['좋아요'].sum():,}")
    c3.metric("💬 댓글", f"{df['댓글'].sum():,}")
    c4.metric("🔖 저장", f"{df['저장'].sum():,}")
    c5.metric("↗️ 공유", f"{df['공유'].sum():,}")

    c6, c7, c8, c9, _ = st.columns(5)
    c6.metric("▶️ 조회수", f"{df['조회수'].sum():,}")
    c7.metric("📢 노출", f"{df['노출'].sum():,}")
    c8.metric("👤 프로필방문", f"{df['프로필방문'].sum():,}")
    c9.metric("➕ 팔로우", f"{df['팔로우'].sum():,}")


def _avg_row(df: pd.DataFrame):
    _section("🎯 평균 성과율")
    rv_sub = df[df["미디어타입_원본"].isin(["REELS", "VIDEO"])]
    completion = rv_sub["조회완료율(%)"].mean() if not rv_sub.empty else 0.0

    c1, c2, c3 = st.columns(3)
    c1.metric("💚 평균 참여율", f"{df['참여율(%)'].mean():.2f}%")
    c2.metric("🔁 평균 공유율", f"{df['공유율(%)'].mean():.2f}%")
    c3.metric("🎬 평균 조회완료율 (릴스·영상)", f"{completion:.2f}%")


def _type_compare_chart(df: pd.DataFrame, tab_key: str):
    if df["미디어타입"].nunique() < 2:
        return
    _section("📊 콘텐츠 타입별 평균 지표 비교")
    grp = (
        df.groupby("미디어타입")[["도달", "좋아요", "댓글", "저장", "공유", "조회수"]]
        .mean()
        .reset_index()
    )
    melted = grp.melt(id_vars="미디어타입", var_name="지표", value_name="평균값")
    fig = px.bar(
        melted, x="지표", y="평균값", color="미디어타입", barmode="group",
        color_discrete_sequence=px.colors.qualitative.Set2,
        height=360,
    )
    fig.update_layout(margin=dict(t=20, b=20), legend_title="콘텐츠 타입")
    st.plotly_chart(fig, use_container_width=True, key=f"type_compare_{tab_key}")


def _top5_cards(df: pd.DataFrame):
    rv = df[df["미디어타입_원본"].isin(["REELS", "VIDEO"])]
    if rv.empty:
        return

    _section("🏆 릴스·영상 Top 5")
    col_v, col_e = st.columns(2)

    def _card(row, rank: int):
        date_str = row["날짜"].strftime("%Y.%m.%d") if pd.notna(row["날짜"]) else "-"
        cap = (row["캡션"][:38] + "…") if len(row["캡션"]) > 38 else (row["캡션"] or "(캡션 없음)")
        return f"""
        <div class="reel-card">
          <span class="reel-rank">#{rank}</span>
          <span style="font-size:.8rem;color:#6c757d;">{date_str}</span><br>
          <span style="font-weight:600;">{cap}</span><br>
          <span>▶️ 조회수: <b>{row["조회수"]:,}</b> &nbsp; 💚 참여율: <b>{row["참여율(%)"]:.2f}%</b></span><br>
          <a href="{row["링크"]}" target="_blank" style="font-size:.85rem;">🔗 게시물 보기</a>
        </div>"""

    with col_v:
        st.markdown("**▶️ 조회수 상위 5**")
        for rank, (_, row) in enumerate(rv.nlargest(5, "조회수").iterrows(), 1):
            st.markdown(_card(row, rank), unsafe_allow_html=True)

    with col_e:
        st.markdown("**💚 참여율 상위 5**")
        for rank, (_, row) in enumerate(rv.nlargest(5, "참여율(%)").iterrows(), 1):
            st.markdown(_card(row, rank), unsafe_allow_html=True)


def _reels_bar_chart(df: pd.DataFrame, tab_key: str):
    rv = df[df["미디어타입_원본"].isin(["REELS", "VIDEO"])]
    if rv.empty:
        return

    _section("📊 릴스·영상 지표 비교 (조회수 상위 10)")
    top = rv.nlargest(10, "조회수").copy()
    top["게시물"] = top.apply(
        lambda r: (r["날짜"].strftime("%m/%d") if pd.notna(r["날짜"]) else "?")
                  + " " + (r["캡션"][:12] + "…" if len(r["캡션"]) > 12 else r["캡션"] or "-"),
        axis=1,
    )

    selected = st.multiselect(
        "비교할 지표",
        ["도달", "조회수", "좋아요", "댓글", "저장", "공유"],
        default=["도달", "조회수", "좋아요"],
        key=f"metric_sel_{tab_key}",
    )
    if not selected:
        return

    fig = go.Figure()
    colors = px.colors.qualitative.Plotly
    for idx, metric in enumerate(selected):
        fig.add_trace(go.Bar(
            name=metric,
            x=top["게시물"],
            y=top[metric],
            marker_color=colors[idx % len(colors)],
        ))
    fig.update_layout(
        barmode="group", height=420,
        xaxis_tickangle=-30,
        margin=dict(t=10, b=80),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    st.plotly_chart(fig, use_container_width=True, key=f"reels_bar_{tab_key}")


def _trend_chart(df: pd.DataFrame, tab_key: str):
    _section("📅 날짜별 도달 · 참여 추이")
    trend_df = df.copy()
    trend_df["참여"] = trend_df[["좋아요", "댓글", "저장", "공유"]].sum(axis=1)
    trend_df["날짜_d"] = trend_df["날짜"].dt.date
    trend = trend_df.groupby("날짜_d").agg(
        도달합계=("도달", "sum"),
        참여합계=("참여", "sum"),
    ).reset_index()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=trend["날짜_d"], y=trend["도달합계"],
        name="도달", mode="lines+markers",
        line=dict(color="#007bff", width=2),
    ))
    fig.add_trace(go.Scatter(
        x=trend["날짜_d"], y=trend["참여합계"],
        name="참여 (좋아요+댓글+저장+공유)", mode="lines+markers",
        line=dict(color="#28a745", width=2),
        yaxis="y2",
    ))
    fig.update_layout(
        height=380,
        yaxis=dict(title="도달", showgrid=True),
        yaxis2=dict(title="참여", overlaying="y", side="right", showgrid=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=10, b=20),
    )
    st.plotly_chart(fig, use_container_width=True, key=f"trend_{tab_key}")


def _raw_data(df: pd.DataFrame):
    with st.expander("📋 원본 데이터 보기"):
        disp = [c for c in df.columns if c != "미디어타입_원본"]
        st.dataframe(df[disp], use_container_width=True, height=400)


def render_tab(tab_df: pd.DataFrame, tab_key: str):
    if tab_df.empty:
        st.info("해당 기간 / 타입에 데이터가 없습니다.")
        return

    _kpi_row(tab_df)
    _avg_row(tab_df)
    _type_compare_chart(tab_df, tab_key)
    _top5_cards(tab_df)
    _reels_bar_chart(tab_df, tab_key)
    _trend_chart(tab_df, tab_key)
    _raw_data(tab_df)


# ── 콘텐츠 타입 탭 ──────────────────────────────────────────────────────────
tab_all, tab_rv, tab_feed = st.tabs(["전체", "릴스·영상", "피드 이미지·캐러셀"])

with tab_all:
    render_tab(df_filtered, "all")

with tab_rv:
    df_rv = df_filtered[df_filtered["미디어타입_원본"].isin(["REELS", "VIDEO"])]
    render_tab(df_rv, "rv")

with tab_feed:
    df_feed = df_filtered[df_filtered["미디어타입_원본"].isin(["IMAGE", "CAROUSEL_ALBUM"])]
    render_tab(df_feed, "feed")


# ── 엑셀 저장 ────────────────────────────────────────────────────────────────
st.markdown("---")
_section("💾 데이터 내보내기")
col_save, col_dl = st.columns(2)

with col_save:
    if st.button("📁 로컬 파일로 저장", use_container_width=True):
        try:
            path = save_to_excel(df_filtered)
            st.success(f"저장 완료: {path}")
        except Exception as exc:
            st.error(f"저장 실패: {exc}")

with col_dl:
    today_str = datetime.now().strftime("%Y%m%d")
    excel_bytes = get_excel_bytes(df_filtered)
    st.download_button(
        label="⬇️ 엑셀 다운로드",
        data=excel_bytes,
        file_name=f"{today_str}_아이헤이트먼데이인사이트.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
