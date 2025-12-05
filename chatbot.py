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
st.set_page_config(page_title="금융 인사이트 AI Pro (Ver 4.6)", page_icon="📈", layout="wide")

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

# DB 스키마 (14개 컬럼)
REQUIRED_HEADERS = [
    'video_id', 'url', 'title', 'channel_name', 'published_at', 
    'category', 'main_topic', 'key_arguments', 'evidence', 
    'implications', 'validity_check', 'sentiment', 'tags', 'full_summary'
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
                val = item.get(header, "")
                if isinstance(val, list): val = "\n".join(val)
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
            1. 'published_at'을 참고하되 내용은 'evidence'와 'implications' 위주로 분석하세요.
            2. 반드시 **"[자료 N] 제목"** 형태로 출처를 밝히세요.
            """
        elif mode == "critique":
            prompt = f"""
            당신은 '금융 리스크 관리자'입니다. (현재: {today})
            아래 제공된 [상세 원본 데이터]를 꼼꼼히 검토하여, AI의 답변을 비평하세요.
            특히 원본 데이터의 'evidence'(근거)와 'validity_check'(타당성 검토) 내용을 적극 활용하세요.

            [사용자 질문]
            {query}
            
            [AI 답변]
            {context['ai_answer']}
            
            [상세 원본 데이터 (참고용)]
            {context['raw_data']}

            [작성 양식]
            1. 🌟 **긍정적 평가:** 답변의 장점.
            2. ⚖️ **비판적 검증:** 원본 데이터의 '근거'와 비교했을 때 과장되거나 누락된 리스크 지적.
            3. 💡 **추가 인사이트:** 놓친 시사점 보완.
            """
        
        if mode == "critique":
            final_prompt = prompt 
        else:
            final_prompt = prompt

        response = model.generate_content(final_prompt)
        return response.text
    except Exception as e:
        return f"AI 오류: {e}"

# ==========================================
# [PAGE] 데이터 관리 페이지
# ==========================================
def show_db_management_page(df):
    st.header("⚙️ DB 데이터 관리 센터")
    st.info("외부 AI를 이용해 영상을 분석하고 JSON으로 저장하세요.")

    with st.container(border=True):
        st.subheader("📝 데이터 수동 추가")
        st.markdown("##### 👇 아래 프롬프트를 복사하여 ChatGPT에게 보내세요")
        prompt_text = """
당신은 수석 금융 데이터 분석가입니다.
위의 유튜브 링크의 해당 영상의 내용을 심층 분석해서 아래의 JSON 포맷으로 출력해 줘.

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
  "key_arguments": [
    "핵심 주장 1",
    "핵심 주장 2",
    "핵심 주장 3",
    "핵심 주장 4"
  ],
  "evidence": [
    "주장 1에 대한 근거(수치/팩트)",
    "주장 2에 대한 근거",
    "주장 3에 대한 근거",
    "주장 4에 대한 근거"
  ],
  "implications": "투자자를 위한 시사점 및 구체적인 액션 플랜",
  "validity_check": "논리적 타당성 및 비판적 검토",
  "sentiment": "긍정/부정/중립",
  "tags": "키워드1, 키워드2, 키워드3, 키워드4",
  "full_summary": "전체 내용 상세 요약 (서론-본론-결론)"
}
        """
        st.code(prompt_text, language="text")
        json_input = st.text_area("JSON 입력", height=150)
        if st.button("💾 DB에 저장하기", type="primary", use_container_width=True):
            if json_input.strip():
                try:
                    parsed_json = json.loads(json_input)
                    with st.spinner("저장 중..."):
                        success, msg = append_data_to_sheet(parsed_json)
                        if success: st.success(msg); st.cache_data.clear(); st.rerun()
                        else: st.error(msg)
                except: st.error("JSON 형식 오류")

    st.divider()
    st.subheader(f"🗂️ 현재 DB 목록 ({len(df)}건)")
    if st.button("🔄 새로고침", use_container_width=True): st.cache_data.clear(); st.rerun()

    if not df.empty and 'title' in df.columns:
        # [수정 1] 핵심주제 포함
        cols_to_show = ['title', 'main_topic', 'published_at', 'category']
        valid_cols = [c for c in cols_to_show if c in df.columns]
        
        display_df = df[valid_cols].copy()
        display_df.insert(0, 'No', range(1, len(display_df) + 1))
        
        # [수정 2] HTML 테이블 스타일링 (줄바꿈 및 너비 조정)
        st.markdown("""
        <style>
        .styled-table { width: 100%; border-collapse: collapse; font-size: 14px; }
        .styled-table th { background-color: #f0f2f6; border: 1px solid #e0e0e0; padding: 10px; text-align: center; }
        .styled-table td { border: 1px solid #e0e0e0; padding: 10px; vertical-align: top; }
        
        /* 컬럼별 너비 지정 (비율로 조정) */
        .styled-table td:nth-child(1) { width: 5%; text-align: center; font-weight: bold; } /* No */
        .styled-table td:nth-child(2) { width: 30%; word-break: keep-all; } /* 제목 (줄바꿈 허용) */
        .styled-table td:nth-child(3) { width: 45%; word-break: keep-all; } /* 핵심주제 (줄바꿈 허용) */
        .styled-table td:nth-child(4) { width: 10%; text-align: center; white-space: nowrap; } /* 게시일 (한줄) */
        .styled-table td:nth-child(5) { width: 10%; text-align: center; white-space: nowrap; } /* 분류 (한줄) */
        </style>
        """, unsafe_allow_html=True)

        # 데이터프레임을 HTML로 변환하여 출력
        html = display_df.to_html(index=False, classes='styled-table', escape=True)
        st.markdown(html, unsafe_allow_html=True)
        
    else:
        st.info("데이터가 없습니다.")

# ==========================================
# [PAGE] 챗봇 페이지
# ==========================================
def show_chatbot_page(df):
    st.header("💬 AI 금융 투자 비서")
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "안녕하세요! 투자 전략에 대해 물어보세요."}]

    for msg in st.session_state.messages:
        st.chat_message(msg["role"]).write(msg["content"])

    if st.session_state.messages and st.session_state.messages[-1]["role"] == "assistant":
        if len(st.session_state.messages) > 1:
            st.markdown("---")
            with st.container(border=True):
                col1, col2 = st.columns([0.6, 0.4])
                with col1:
                    st.write("##### 🧐 답변 검증")
                    st.caption("AI 리스크 관리자가 심층 분석 데이터를 기반으로 비평합니다.")
                with col2:
                    if st.button("🚩 비평 보기", key="critique_btn", type="secondary", use_container_width=True):
                        last_msg = st.session_state.messages[-1]["content"]
                        last_query = st.session_state.messages[-2]["content"]
                        raw_context = st.session_state.get("last_raw_context", "원본 데이터 없음")
                        
                        critique_payload = {
                            "ai_answer": last_msg,
                            "raw_data": raw_context
                        }
                        
                        with st.spinner("심층 검증 중..."):
                            critique = ask_gemini(last_query, critique_payload, mode="critique")
                            st.session_state.messages.append({"role": "assistant", "content": f"📝 **[전문가 비평 리포트]**\n\n{critique}"})
                            st.rerun()

    if prompt := st.chat_input("질문 입력 (예: 반도체 전망)"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.rerun()

    if st.session_state.messages[-1]["role"] == "user":
        user_query = st.session_state.messages[-1]["content"]
        
        search_target = ['title', 'main_topic', 'full_summary', 'category', 'tags']
        valid_cols = [col for col in search_target if col in df.columns]
        
        context_text = ""
        full_raw_data = "" 
        
        if not df.empty and valid_cols:
            mask = df[valid_cols].astype(str).apply(lambda x: x.str.contains(user_query, case=False).any(), axis=1)
            filtered_df = df[mask]
            target_df = filtered_df if not filtered_df.empty else df.tail(5)
            
            for i, (idx, row) in enumerate(target_df.iterrows(), 1):
                real_db_no = idx + 1
                
                context_text += f"""
                [자료 {real_db_no}]
                - 제목: {row.get('title')} (날짜: {row.get('published_at')})
                - 요약: {row.get('full_summary')}
                - 근거: {row.get('evidence')}
                """
                
                full_raw_data += f"""
                === [자료 {real_db_no} 상세] ===
                제목: {row.get('title')}
                채널: {row.get('channel_name')}
                날짜: {row.get('published_at')}
                주제: {row.get('main_topic')}
                주장: {row.get('key_arguments')}
                근거: {row.get('evidence')}
                시사점: {row.get('implications')}
                타당성: {row.get('validity_check')}
                =============================
                """
                
            st.session_state["last_raw_context"] = full_raw_data
            
        else:
            context_text = "관련 데이터가 없습니다."
            st.session_state["last_raw_context"] = "관련 데이터 없음"

        with st.chat_message("assistant"):
            with st.spinner("분석 중..."):
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
        page = st.radio("메뉴", ["💬 AI 투자 비서", "⚙️ DB 데이터 관리"], index=0, horizontal=True, label_visibility="collapsed")
    st.divider()
    if page == "⚙️ DB 데이터 관리": show_db_management_page(df)
    else: show_chatbot_page(df)

if __name__ == "__main__":
    main()
