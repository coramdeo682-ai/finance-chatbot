import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import google.generativeai as genai
import json

# ==========================================
# [설정] 페이지 기본 설정
# ==========================================
st.set_page_config(page_title="금융 인사이트 AI", page_icon="📈", layout="wide")

# ==========================================
# [함수] 구글 시트 데이터 가져오기 (전처리 강화)
# ==========================================
@st.cache_data(ttl=600)
def load_data():
    try:
        # Secrets에서 키 가져오기 (TOML 방식)
        json_creds = dict(st.secrets["gcp_service_account"])
        
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(json_creds, scope)
        client = gspread.authorize(creds)
        
        # 시트 이름 확인
        sheet = client.open("Youtube_Test_Local").sheet1
        data = sheet.get_all_records()
        
        df = pd.DataFrame(data)
        
        # [중요] 데이터 전처리: 빈 값 채우기 & 컬럼명 공백 제거
        df = df.fillna("") # 빈칸을 빈 문자열로 채움
        df.columns = df.columns.str.strip() # 컬럼 이름의 앞뒤 공백 제거 ('채널명 ' -> '채널명')
        
        return df
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return pd.DataFrame()

# ==========================================
# [함수] Gemini에게 질문하기 (프롬프트 강화)
# ==========================================
def ask_gemini(query, context):
    try:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        # [프롬프트 업그레이드]: 페르소나 부여 및 답변 스타일 지정
        prompt = f"""
        당신은 월스트리트 출신의 유능한 '금융 투자 분석가'입니다. 
        사용자의 질문에 대해 아래 제공된 [분석 리포트 데이터]만을 근거로 통찰력 있는 답변을 제공하세요.

        [분석 리포트 데이터]
        {context}

        [사용자 질문]
        {query}

        [답변 가이드라인]
        1. **두괄식 결론:** 질문에 대한 핵심 답변을 먼저 제시하세요.
        2. **근거 중심:** "데이터에 따르면~" 같은 모호한 말 대신, 구체적인 수치(%, 금액)와 유튜버의 주장을 인용하세요.
        3. **구조화:** 줄글로만 쓰지 말고, 불렛 포인트(-), 강조(**굵게**)를 사용하여 가독성을 높이세요.
        4. **출처 명시:** 어떤 채널의 어떤 영상에서 나온 내용인지 꼭 밝히세요.
        5. 정보가 없으면 솔직하게 "제공된 데이터에는 해당 내용이 없습니다"라고 답하세요.
        """
        
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 분석 중 오류가 발생했습니다: {e}"

# ==========================================
# [UI] 화면 구성
# ==========================================
st.title("📈 나만의 금융 투자 AI 비서")
st.caption("🚀 수집된 유튜브 데이터를 심층 분석하여 답변합니다.")

# 1. 데이터 로드
df = load_data()

if df.empty:
    st.warning("데이터가 없습니다. 로컬 봇이 데이터를 수집했는지 확인해주세요.")
else:
    # 2. 사이드바 (데이터 현황)
    with st.sidebar:
        st.header(f"🗂️ 수집된 영상: {len(df)}개")
        
        # 사이드바 표출용 데이터 정리
        if '채널명' in df.columns and '제목' in df.columns:
            # 최신순 정렬 (수집일시 기준 내림차순)
            display_df = df[['채널명', '제목']].copy()
            st.dataframe(display_df, use_container_width=True, hide_index=True)
        else:
            st.error("데이터에 '채널명' 또는 '제목' 컬럼이 보이지 않습니다. 구글 시트 헤더를 확인하세요.")

        if st.button("🔄 데이터 새로고침"):
            st.cache_data.clear()
            st.rerun()

    # 3. 채팅창 인터페이스
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "안녕하세요! 투자에 대해 무엇이든 물어보세요. 데이터에 기반해 팩트만 전달해 드립니다."}]

    for msg in st.session_state.messages:
        st.chat_message(msg["role"]).write(msg["content"])

    if prompt := st.chat_input("질문을 입력하세요... (예: 엔비디아 전망은 어때?)"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.chat_message("user").write(prompt)

        # 4. 스마트 검색 로직 (키워드 매칭)
        # 검색할 컬럼들 (시트 헤더와 일치해야 함)
        search_cols = ['제목', '핵심주제', '핵심주장', '근거', '요약', '태그']
        
        # 실제 존재하는 컬럼만 필터링
        valid_cols = [col for col in search_cols if col in df.columns]
        
        if valid_cols:
            # 키워드 검색
            mask = df[valid_cols].astype(str).apply(lambda x: x.str.contains(prompt, case=False).any(), axis=1)
            filtered_df = df[mask]
        else:
            filtered_df = pd.DataFrame()

        # 검색 결과 처리
        if filtered_df.empty:
            # 관련 데이터가 없으면 최신 데이터 3개를 참고
            context_df = df.tail(3)
            info_msg = "💡 질문과 정확히 일치하는 키워드가 없어, **최신 영상 3개**를 바탕으로 답변합니다."
        else:
            # 관련 데이터가 있으면 최대 5개까지 참고
            context_df = filtered_df.tail(5)
            info_msg = f"🔍 **{len(filtered_df)}개**의 관련 영상을 찾아 분석했습니다."

        # AI에게 보낼 문맥(Context) 구성
        context_text = ""
        for idx, row in context_df.iterrows():
            # 안전하게 데이터 가져오기 (.get 사용)
            title = row.get('제목', '제목 없음')
            channel = row.get('채널명', '채널 미상')
            main_topic = row.get('핵심주제', '')
            arguments = row.get('핵심주장', '')
            evidence = row.get('근거', '')
            implication = row.get('시사점', '')
            
            context_text += f"""
            --- [참고 자료 {idx+1}] ---
            * 출처: {channel} - "{title}"
            * 핵심 주제: {main_topic}
            * 주요 주장: {arguments}
            * 핵심 근거(수치): {evidence}
            * 투자 시사점: {implication}
            -------------------------
            """

        # 답변 생성 및 출력
        with st.chat_message("assistant"):
            st.info(info_msg)
            with st.spinner("데이터 분석 중..."):
                response = ask_gemini(prompt, context_text)
                st.write(response)
                st.session_state.messages.append({"role": "assistant", "content": response})
