import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import google.generativeai as genai
import json

# ==========================================
# [설정] 페이지 기본 설정
# ==========================================
st.set_page_config(page_title="나만의 금융 AI 비서", page_icon="💰", layout="wide")

# ==========================================
# [함수] 구글 시트 데이터 가져오기
# ==========================================
@st.cache_data(ttl=600) # 10분마다 갱신
def load_data():
    try:
        # Streamlit Secrets에서 키 가져오기
        json_creds = json.loads(st.secrets["GCP_CREDENTIALS_JSON"])
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(json_creds, scope)
        client = gspread.authorize(creds)
        
        # ★ 저장해둔 시트 이름 정확히 입력
        sheet = client.open("Youtube_Test_Local").sheet1
        data = sheet.get_all_records()
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return pd.DataFrame()

# ==========================================
# [함수] Gemini 답변 생성
# ==========================================
def ask_gemini(query, context):
    try:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        prompt = f"""
        너는 금융 투자 전문가야. 아래 제공된 [유튜브 분석 데이터]를 기반으로 사용자의 질문에 답변해.
        
        [지침]
        1. 반드시 제공된 데이터에 있는 내용으로만 답변할 것.
        2. 근거(Evidence)와 수치를 포함해서 논리적으로 설명할 것.
        3. 관련된 영상의 제목과 채널명을 출처로 밝힐 것.
        4. 데이터에 없는 내용은 "데이터에 없는 내용입니다"라고 말할 것.

        [유튜브 분석 데이터]
        {context}

        [사용자 질문]
        {query}
        """
        
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"에러 발생: {e}"

# ==========================================
# [UI] 화면 구성
# ==========================================
st.title("💰 유튜브 금융 인사이트 챗봇")

# 1. 데이터 로드
df = load_data()

if df.empty:
    st.warning("데이터가 없거나 불러오지 못했습니다.")
else:
    # 2. 사이드바 (데이터 미리보기)
    with st.sidebar:
        st.header(f"📚 분석된 영상: {len(df)}개")
        st.dataframe(df[['채널명', '제목', '업로드일']].sort_values(by='업로드일', ascending=False), use_container_width=True)
        if st.button("데이터 새로고침"):
            st.cache_data.clear()
            st.rerun()

    # 3. 채팅 인터페이스
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "안녕하세요! 무엇이 궁금하신가요? (예: 최근 엔비디아 전망은?)"}]

    for msg in st.session_state.messages:
        st.chat_message(msg["role"]).write(msg["content"])

    if prompt := st.chat_input("질문을 입력하세요..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.chat_message("user").write(prompt)

        # 간단한 검색 로직 (질문과 관련된 행만 추려서 AI에게 전달)
        # 키워드가 포함된 행을 찾음 (제목, 핵심주제, 요약, 핵심주장 등에서 검색)
        search_columns = ['제목', '핵심주제', '핵심주장', '요약', '태그']
        mask = df[search_columns].apply(lambda x: x.astype(str).str.contains(prompt, case=False).any(), axis=1)
        filtered_df = df[mask]
        
        # 검색 결과가 없으면 전체 데이터 중 최신 5개만 참고 (토큰 절약)
        if filtered_df.empty:
            context_df = df.tail(5)
            search_msg = "관련된 키워드를 찾지 못해 최신 영상들을 참고하여 답변합니다."
        else:
            context_df = filtered_df.head(5) # 관련도 높은 5개만
            search_msg = f"'{prompt}'와 관련된 영상 {len(filtered_df)}개를 찾았습니다."

        # AI에게 보낼 데이터 텍스트로 변환
        context_text = ""
        for idx, row in context_df.iterrows():
            context_text += f"""
            - 영상제목: {row['제목']} (채널: {row['채널명']})
            - 핵심주장: {row['핵심주장']}
            - 근거: {row['근거']}
            - 시사점: {row['시사점']}
            --------------------------------
            """

        with st.chat_message("assistant"):
            st.caption(search_msg)
            with st.spinner("분석 중..."):
                response = ask_gemini(prompt, context_text)
                st.write(response)
                st.session_state.messages.append({"role": "assistant", "content": response})
