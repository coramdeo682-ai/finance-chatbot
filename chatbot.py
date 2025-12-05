import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import google.generativeai as genai
import json
import datetime

# ==========================================
# [설정] 페이지 기본 설정
# ==========================================
st.set_page_config(page_title="금융 인사이트 AI Pro (Ver 4.3)", page_icon="📈", layout="wide")

# ==========================================
# [함수] 구글 시트 연결
# ==========================================
def get_sheet_client():
    if "gcp_service_account" not in st.secrets:
        st.error("Secrets 설정(gcp_service_account)이 누락되었습니다.")
        return None
    json_creds = dict(st.secrets["gcp_service_account"])
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(json_creds, scope)
    client = gspread.authorize(creds)
    return client

# [중요] DB 스키마 정의 (수집 봇과 동일하게 맞춤)
REQUIRED_HEADERS = [
    'video_id', 'url', 'title', 'channel_name', 'published_at', 
    'view_count', 'category', 'main_topic', 'key_arguments', 
    'evidence', 'implications', 'validity_check', 'sentiment', 
    'tags', 'full_summary'
]

def check_and_update_headers(sheet):
    try:
        current_headers = sheet.row_values(1)
    except:
        current_headers = []
    
    if not current_headers:
        sheet.append_row(REQUIRED_HEADERS)
        return REQUIRED_HEADERS
    
    missing_cols = [col for col in REQUIRED_HEADERS if col not in current_headers]
    if missing_cols:
        if len(current_headers) + len(missing_cols) > sheet.col_count:
            sheet.resize(cols=len(current_headers) + len(missing_cols) + 5)
        start_col_idx = len(current_headers) + 1
        for i, col_name in enumerate(missing_cols):
            sheet.update_cell(1, start_col_idx + i, col_name)
        return current_headers + missing_cols
    return current_headers

@st.cache_data(ttl=600)
def load_data():
    client = get_sheet_client()
    if not client: return pd.DataFrame()
    try:
        sheet = client.open("Youtube_Test_Local").sheet1
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        
        # 필수 컬럼이 없으면 빈 값으로 채움
        for col in REQUIRED_HEADERS:
            if col not in df.columns:
                df[col] = "" 
        df = df.fillna("")
        return df
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return pd.DataFrame()

def append_data_to_sheet(json_data):
    client = get_sheet_client()
    if not client: return False, "구글 시트 연결 실패"
    try:
        sheet = client.open("Youtube_Test_Local").sheet1
        current_headers = check_and_update_headers(sheet)
        
        if isinstance(json_data, dict): items = [json_data]
        elif isinstance(json_data, list): items = json_data
        else: return False, "JSON 형식이 아닙니다."

        rows_to_append = []
        for item in items:
            row = []
            for header in current_headers:
                # 리스트 형태 데이터는 문자열로 변환
                val = item.get(header, "")
                if isinstance(val, list):
                    val = "\n".join(val)
                row.append(str(val))
            rows_to_append.append(row)
            
        sheet.append_rows(rows_to_append)
        return True, f"{len(items)}건 저장 완료!"
    except Exception as e:
        return False, f"오류: {e}"

# ==========================================
# [함수] Gemini API
# ==========================================
def ask_gemini(query, context, mode="analysis"):
    try:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
        model = genai.GenerativeModel('gemini-2.5-flash')
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        
        if mode == "analysis":
            prompt = f"""
            당신은 수석 금융 투자 전략가입니다.
            아래 [분석 데이터]를 기반으로 질문에 답하세요.
            [분석 데이터]
            {context}
            [질문]
            {query}
            [지침]
            1. 'published_at'(게시일)이 있다면 참고하되, 없으면 내용의 논리성에 집중하세요.
            2. 'evidence'(근거)와 'implications'(시사점)을 적극 활용하여 깊이 있는 분석을 제공하세요.
            3. **출처 표기 필수:** 주장의 근거가 되는 자료를 인용할 때는 반드시 **"[자료 N] 제목"**과 같이 출처를 명확히 밝히세요.
            """
        elif mode == "critique":
            prompt = f"""
            당신은 '금융 리스크 관리자'입니다.
            현재 시점은 {today}입니다. 이 날짜는 당신이 현재에 있다는 인식의 기준일 뿐입니다.
            DB 자료에 'published_at'이 없다면 시의성을 문제 삼지 말고, 논리의 타당성을 평가하세요.
            
            아래 AI 답변을 검토하고 다음 3가지 항목으로 비평 리포트를 작성하세요.

            [사용자 질문]
            {query}
            [AI 답변]
            {context}

            [작성 양식]
            1. 🌟 **긍정적 평가 (Good Points):** - 이 답변이 가진 장점과 가치를 언급하세요.
            2. ⚖️ **비판적 검증 (Critical Review):** - 객관적인 경제 데이터나 반대 논리를 들어 비판하세요.
            3. 💡 **추가 인사이트 (Key Implications):** - 답변에서 다루지 않은 추가 시사점을 도출하세요.
            """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 오류: {e}"

# ==========================================
# [PAGE] 데이터 관리 페이지
# ==========================================
def show_db_management_page(df):
    st.header("⚙️ DB 데이터 관리 센터")
    st.info("외부 AI(ChatGPT, Gemini 등)를 이용해 영상을 분석하고 JSON으로 변환하여 저장하세요.")

    with st.container(border=True):
        st.subheader("📝 데이터 수동 추가")
        st.markdown("##### 👇 아래 프롬프트를 복사하여 ChatGPT에게 보내세요")
        
        # [수정됨] 사용자님이 제공한 최종 프롬프트 적용
        prompt_text = """
당신은 수석 금융 데이터 분석가입니다.
제공된 영상(또는 텍스트)의 내용을 심층 분석하여 아래의 JSON 포맷으로 출력해 주세요.

[분석 지침]
1. 다른 말(서론, 추임새)은 절대 하지 말고 **오직 JSON 코드 블록**만 출력하세요.
2. 'key_arguments'와 'evidence'는 짝을 이루어 구체적으로 작성하세요.
3. 수치(%, 금액, 날짜)가 있다면 반드시 포함하세요.
4. 투자자 관점에서 실질적인 도움이 되는 정보를 추출하세요.

[JSON 포맷]
{
  "video_id": "영상ID (URL에서 추출, 모르면 공란)",
  "url": "영상 전체 URL",
  "title": "영상 제목",
  "channel_name": "채널명",
  "published_at": "YYYY-MM-DD (게시일 필수)",
  "category": "주식/부동산/코인/거시경제 중 택1 (필수)",
  "main_topic": "영상을 관통하는 핵심 주제 (1문장)",
  "key_arguments": ["핵심 주장 1", "핵심 주장 2", "핵심 주장 3", "핵심 주장 4"],
  "evidence": ["주장 1에 대한 근거", "주장 2에 대한 근거", "주장 3에 대한 근거", "주장 4에 대한 근거"],
  "implications": "투자자를 위한 시사점 및 구체적인 액션 플랜",
  "validity_check": "논리적 타당성 및 비판적 검토",
  "sentiment": "긍정/부정/중립",
  "tags": "키워드1, 키워드2, 키워드3, 키워드4",
  "full_summary": "전체 내용 상세 요약 (서론-본론-결론)"
}
        """
        st.code(prompt_text, language="text")
        
        json_input = st.text_area("JSON 입력", height=200, placeholder='[{"title": "...", "published_at": "2024-01-01"}]')
        
        if st.button("💾 DB에 저장하기", key="save_btn_page", type="primary", use_container_width=True):
            if not json_input.strip():
                st.warning("내용이 비어있습니다.")
            else:
                try:
                    parsed_json = json.loads(json_input)
                    with st.spinner("저장 중..."):
                        success, msg = append_data_to_sheet(parsed_json)
                        if success:
                            st.success(msg)
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(msg)
                except json.JSONDecodeError:
                    st.error("잘못된 JSON 형식입니다.")

    st.divider()

    st.subheader(f"🗂️ 현재 DB 목록 ({len(df)}건)")
    if st.button("🔄 목록 새로고침", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    if not df.empty and 'title' in df.columns:
        # 보여줄 컬럼 선택
        cols_to_show = ['title', 'published_at', 'category']
        valid_cols = [c for c in cols_to_show if c in df.columns]
        
        display_df = df[valid_cols].copy()
        display_df.insert(0, 'No', range(1, len(display_df) + 1))
        st.dataframe(display_df, use_container_width=True, height=500, hide_index=True)
    else:
        st.info("데이터가 없습니다.")

# ==========================================
# [PAGE] 챗봇 페이지
# ==========================================
def show_chatbot_page(df):
    st.header("💬 AI 금융 투자 비서")
    
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "안녕하세요! 투자 전략에 대해 무엇이든 물어보세요."}]

    for msg in st.session_state.messages:
        st.chat_message(msg["role"]).write(msg["content"])

    if st.session_state.messages and st.session_state.messages[-1]["role"] == "assistant":
        if len(st.session_state.messages) > 1:
            st.markdown("---")
            with st.container(border=True):
                col1, col2 = st.columns([0.6, 0.4])
                with col1:
                    st.write("##### 🧐 답변 검증")
                    st.caption("AI 리스크 관리자의 비평을 들어보세요.")
                with col2:
                    if st.button("🚩 비평 보기", key="critique_btn_main", type="secondary", use_container_width=True):
                        last_msg = st.session_state.messages[-1]["content"]
                        last_query = st.session_state.messages[-2]["content"]
                        with st.spinner("3단계 검증 중..."):
                            critique = ask_gemini(last_query, last_msg, mode="critique")
                            st.session_state.messages.append({"role": "assistant", "content": f"📝 **[전문가 비평 리포트]**\n\n{critique}"})
                            st.rerun()

    if prompt := st.chat_input("질문 입력 (예: 비트코인 전망)"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.rerun()

    if st.session_state.messages[-1]["role"] == "user":
        user_query = st.session_state.messages[-1]["content"]
        
        # 검색 대상 컬럼 확장
        search_target = ['title', 'main_topic', 'full_summary', 'category', 'tags']
        valid_cols = [col for col in search_target if col in df.columns]
        
        context_text = ""
        if not df.empty and valid_cols:
            mask = df[valid_cols].astype(str).apply(lambda x: x.str.contains(user_query, case=False).any(), axis=1)
            filtered_df = df[mask]
            target_df = filtered_df if not filtered_df.empty else df.tail(5)
            
            for i, (idx, row) in enumerate(target_df.iterrows(), 1):
                real_db_no = idx + 1
                # [중요] 챗봇에게 풍부한 정보를 제공하도록 포맷 변경
                context_text += f"""
                [자료 {real_db_no}]
                - 제목: {row.get('title')} (날짜: {row.get('published_at')})
                - 채널: {row.get('channel_name')}
                - 핵심주제: {row.get('main_topic')}
                - 요약: {row.get('full_summary')}
                - 근거(Evidence): {row.get('evidence')}
                - 시사점(Implications): {row.get('implications')}
                - 타당성검토: {row.get('validity_check')}
                
                """
        else:
            context_text = "관련 데이터가 없습니다."

        with st.chat_message("assistant"):
            with st.spinner("심층 분석 중..."):
                response = ask_gemini(user_query, context_text, mode="analysis")
                st.write(response)
                st.session_state.messages.append({"role": "assistant", "content": response})
                st.rerun()

# ==========================================
# [Main] 메인 실행 함수
# ==========================================
def main():
    df = load_data()
    st.title("📱 금융 인사이트 AI Pro")

    col1, col2, col3 = st.columns([1, 8, 1])
    with col2:
        page = st.radio("메뉴 선택", ["💬 AI 투자 비서", "⚙️ DB 데이터 관리"], index=0, horizontal=True, label_visibility="collapsed")
    
    st.divider()

    if page == "⚙️ DB 데이터 관리":
        show_db_management_page(df)
    else:
        show_chatbot_page(df)

if __name__ == "__main__":
    main()
