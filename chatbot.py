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
st.set_page_config(page_title="금융 인사이트 AI Pro (Ver 4.1)", page_icon="📈", layout="wide")

# ==========================================
# [함수] 구글 시트 연결 및 데이터 관리
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

def check_and_update_headers(sheet):
    """전문가 추천 필수 컬럼이 없으면 자동으로 추가"""
    required_headers = ['제목', '채널명', '게시일', '영상URL', '조회수', '카테고리', '핵심주제', '핵심주장', '요약', '시사점']
    try:
        current_headers = sheet.row_values(1)
    except:
        current_headers = []
        
    if not current_headers:
        sheet.append_row(required_headers)
        return required_headers
    
    missing_cols = [col for col in required_headers if col not in current_headers]
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
        
        expected_cols = ['제목', '채널명', '게시일', '영상URL', '조회수', '카테고리', '핵심주제', '요약', '시사점']
        for col in expected_cols:
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
        
        if isinstance(json_data, dict):
            items = [json_data]
        elif isinstance(json_data, list):
            items = json_data
        else:
            return False, "JSON 형식이 올바르지 않습니다."

        rows_to_append = []
        for item in items:
            row = []
            for header in current_headers:
                row.append(str(item.get(header, "")))
            rows_to_append.append(row)
            
        sheet.append_rows(rows_to_append)
        return True, f"{len(items)}건 저장 완료! DB 헤더도 최신화되었습니다."
    except Exception as e:
        return False, f"오류 발생: {e}"

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
            1. 데이터에 '게시일'이 있다면 참고하되, 없으면 내용의 논리성에 집중하세요.
            2. 여러 자료를 종합하여 명확한 투자 포지션(매수/매도/관망)을 제안하세요.
            3. **출처 표기 필수:** 주장의 근거가 되는 자료를 인용할 때는 반드시 **"[자료 N] 제목"** 또는 **"OOO 채널에 따르면"**과 같이 출처를 명확히 밝히세요. 이때 [자료 N]의 번호는 제공된 텍스트에 적힌 번호를 그대로 사용해야 합니다.
            """
        elif mode == "critique":
            prompt = f"""
            당신은 '금융 리스크 관리자'입니다.
            현재 시점은 {today}입니다. 이 날짜는 당신이 현재에 있다는 인식의 기준일 뿐입니다.
            DB 자료에 '게시일'이 없다면 시의성을 문제 삼지 말고, 논리의 타당성을 평가하세요.
            
            아래 AI 답변을 검토하고 다음 3가지 항목으로 비평 리포트를 작성하세요.

            [사용자 질문]
            {query}
            [AI 답변]
            {context}

            [작성 양식]
            1. 🌟 **긍정적 평가 (Good Points):** - 이 답변이 가진 장점과 투자 전략으로서의 가치를 구체적으로 언급해 주세요.
               - 어떤 투자자에게 도움이 되는 조언인지 설명하세요.
               
            2. ⚖️ **비판적 검증 (Critical Review):** - 객관적인 경제 데이터(금리, 인플레이션, 환율 등)나 시장의 반대 논리를 들어 이 의견을 비판해 주세요.
               - 이 전략이 실패할 수 있는 리스크 시나리오를 제시하세요.
               
            3. 💡 **추가 인사이트 (Key Implications):** - 답변에서 다루지 않았지만 고려해야 할 추가적인 시사점을 도출해 주세요.
               - 투자자가 지금 당장 확인해야 할 지표나 행동 요령을 제안하세요.
            """

        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 오류: {e}"

# ==========================================
# [PAGE] 데이터 관리 페이지 (모바일 최적화)
# ==========================================
def show_db_management_page(df):
    st.header("⚙️ DB 데이터 관리 센터")
    st.info("모바일에서도 데이터를 쉽게 추가하고 관리하세요.")

    # 1. 수동 입력 섹션
    with st.container(border=True):
        st.subheader("📝 데이터 수동 추가")
        st.caption("ChatGPT/Gemini가 생성한 JSON을 아래에 붙여넣으세요.")
        
        json_input = st.text_area("JSON 입력", height=200, placeholder='[{"제목": "...", "게시일": "2024-01-01"}]', key="json_input_page")
        
        if st.button("💾 DB에 저장하기", key="save_btn_page", type="primary", use_container_width=True):
            if not json_input.strip():
                st.warning("내용이 비어있습니다.")
            else:
                try:
                    parsed_json = json.loads(json_input)
                    with st.spinner("구글 시트에 저장 중..."):
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

    # 2. 데이터 목록 섹션
    st.subheader(f"🗂️ 현재 DB 목록 ({len(df)}건)")
    if st.button("🔄 목록 새로고침", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    if not df.empty and '제목' in df.columns:
        cols_to_show = ['제목']
        if '게시일' in df.columns: cols_to_show.append('게시일')
        
        display_df = df[cols_to_show].copy()
        display_df.insert(0, 'No', range(1, len(display_df) + 1))
        
        # 모바일 가독성을 위해 데이터프레임 높이 조절
        st.dataframe(display_df, use_container_width=True, height=500, hide_index=True)
    else:
        st.info("데이터가 없습니다.")

# ==========================================
# [PAGE] 챗봇 페이지 (메인)
# ==========================================
def show_chatbot_page(df):
    st.header("💬 AI 금융 투자 비서")
    
    # 채팅 기록 초기화
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "안녕하세요! 투자 전략에 대해 무엇이든 물어보세요."}]

    # 채팅 출력
    for msg in st.session_state.messages:
        st.chat_message(msg["role"]).write(msg["content"])

    # 비평 버튼 (마지막 답변이 AI일 때)
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

    # 입력창
    if prompt := st.chat_input("질문 입력 (예: 비트코인 전망)"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.rerun()

    # 답변 생성 로직
    if st.session_state.messages[-1]["role"] == "user":
        user_query = st.session_state.messages[-1]["content"]
        
        search_cols = ['제목', '핵심주제', '요약', '카테고리']
        valid_cols = [col for col in search_cols if col in df.columns]
        
        context_text = ""
        if not df.empty and valid_cols:
            mask = df[valid_cols].astype(str).apply(lambda x: x.str.contains(user_query, case=False).any(), axis=1)
            filtered_df = df[mask]
            target_df = filtered_df if not filtered_df.empty else df.tail(5)
            
            for i, (idx, row) in enumerate(target_df.iterrows(), 1):
                real_db_no = idx + 1
                context_text += f"""
                [자료 {real_db_no}]
                - 제목: {row.get('제목')} (날짜: {row.get('게시일')})
                - 채널명: {row.get('채널명')}
                - 요약: {row.get('요약')}
                - 시사점: {row.get('시사점')}
                
                """
        else:
            context_text = "관련 데이터가 없습니다."

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
    # 데이터 로드 (전역 사용)
    df = load_data()

    # 화면 상단 타이틀
    st.title("📱 금융 인사이트 AI Pro")

    # [수정] 메뉴를 화면 중앙 상단에 배치 (사이드바 제거)
    # 컬럼을 사용하여 중앙 정렬 효과
    col1, col2, col3 = st.columns([1, 8, 1])
    
    with col2:
        page = st.radio(
            "메뉴 선택",
            ["💬 AI 투자 비서", "⚙️ DB 데이터 관리"],
            index=0,
            horizontal=True, # 가로로 배치하여 탭처럼 사용
            label_visibility="collapsed" # 라벨 숨김
        )
    
    st.divider()

    # 페이지 라우팅
    if page == "⚙️ DB 데이터 관리":
        show_db_management_page(df)
    else:
        show_chatbot_page(df)

if __name__ == "__main__":
    main()
