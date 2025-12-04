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
# [함수] 구글 시트 데이터 가져오기
# ==========================================
@st.cache_data(ttl=600)
def load_data():
    try:
        # Secrets에서 키 가져오기
        json_creds = dict(st.secrets["gcp_service_account"])
        
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds = ServiceAccountCredentials.from_json_keyfile_dict(json_creds, scope)
        client = gspread.authorize(creds)
        
        # 시트 이름 확인
        sheet = client.open("Youtube_Test_Local").sheet1
        data = sheet.get_all_records()
        
        df = pd.DataFrame(data)
        
        # 전처리: 빈 값 채우기
        df = df.fillna("")
        
        return df
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        return pd.DataFrame()

# ==========================================
# [함수] Gemini에게 질문하기 (품질 개선)
# ==========================================
def ask_gemini(query, context):
    try:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        # [품질 개선 포인트]
        # AI에게 페르소나를 더 강력하게 부여하고, 답변 스타일을 구체적으로 지시합니다.
        prompt = f"""
        당신은 수석 금융 투자 전략가입니다. 
        사용자의 질문에 대해 아래 제공된 [분석 리포트 데이터]를 종합적으로 검토하여 깊이 있는 인사이트를 제공하세요.

        [분석 리포트 데이터]
        {context}

        [사용자 질문]
        {query}

        [답변 가이드라인]
        1. **심층 분석:** 단순 나열식이 아니라, 여러 영상의 내용을 종합하여 논리적인 결론을 도출하세요.
        2. **근거 제시:** "데이터에 따르면" 같은 모호한 표현 대신, **"A채널의 [영상제목]에서는 ~라고 분석했습니다"**와 같이 출처와 수치(%, 금액)를 명확히 인용하세요.
        3. **구조화:** 가독성을 위해 불렛 포인트, **굵은 글씨**, 단락 구분을 적절히 사용하세요.
        4. **투자 조언:** 데이터에 기반한 실질적인 투자 시사점(Action Plan)을 마지막에 요약해 주세요.
        5. 데이터에 없는 내용은 솔직하게 모른다고 답하세요.
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
    # 2. 사이드바 (요청사항 반영: 제목 및 순번 표시)
    with st.sidebar:
        st.header(f"🗂️ 수집된 영상: {len(df)}개")
        
        # [수정됨] 제목과 함께 앞에 '순번'을 붙여서 표시
        if '제목' in df.columns:
            # 제목 컬럼만 가져오기
            display_df = df[['제목']].copy()
            
            # [수정 포인트] 맨 앞에 '순번' 컬럼 삽입 (1부터 시작)
            display_df.insert(0, '순번', range(1, len(display_df) + 1))
            
            # hide_index=True로 설정하여 기본 인덱스는 숨기고 우리가 만든 '순번'을 보여줍니다.
            st.dataframe(display_df, use_container_width=True, hide_index=True)
        else:
            st.error("'제목' 컬럼을 찾을 수 없습니다.")

        if st.button("🔄 데이터 새로고침"):
            st.cache_data.clear()
            st.rerun()

    # 3. 채팅창 인터페이스
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "안녕하세요! 투자에 대해 무엇이든 물어보세요. 데이터에 기반해 심층 분석해 드립니다."}]

    for msg in st.session_state.messages:
        st.chat_message(msg["role"]).write(msg["content"])

    if prompt := st.chat_input("질문을 입력하세요... (예: 최근 환율 전망은?)"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.chat_message("user").write(prompt)

        # 4. 스마트 검색 로직
        # 검색 범위를 '요약'과 '전체 내용'까지 확장하여 정확도 높임
        search_cols = ['제목', '핵심주제', '핵심주장', '근거', '요약', '태그', '시사점']
        valid_cols = [col for col in search_cols if col in df.columns]
        
        if valid_cols:
            # 키워드 검색
            mask = df[valid_cols].astype(str).apply(lambda x: x.str.contains(prompt, case=False).any(), axis=1)
            filtered_df = df[mask]
        else:
            filtered_df = pd.DataFrame()

        if filtered_df.empty:
            context_df = df.tail(3)
            info_msg = "💡 질문과 정확히 일치하는 키워드가 없어, **최신 영상 3개**를 바탕으로 답변합니다."
        else:
            context_df = filtered_df.tail(5) # 관련도 높은 최신 5개
            info_msg = f"🔍 **{len(filtered_df)}개**의 관련 영상을 찾아 분석했습니다."

        # [품질 개선 포인트] AI에게 보내는 데이터 양을 대폭 늘림
        context_text = ""
        for idx, row in context_df.iterrows():
            # 안전하게 데이터 가져오기
            title = row.get('제목', '')
            channel = row.get('채널명', '')
            main_topic = row.get('핵심주제', '')
            summary = row.get('요약', '') # 상세 요약 추가
            arguments = row.get('핵심주장', '')
            evidence = row.get('근거', '')
            implication = row.get('시사점', '')
            
            context_text += f"""
            --- [참고 자료 {idx+1}] ---
            * 출처: {channel} - "{title}"
            * 핵심 주제: {main_topic}
            * 상세 요약: {summary}  <-- (추가됨)
            * 주요 주장: {arguments}
            * 핵심 근거(수치): {evidence}
            * 투자 시사점: {implication}
            -------------------------
            """

        with st.chat_message("assistant"):
            st.info(info_msg)
            with st.spinner("심층 분석 중..."):
                response = ask_gemini(prompt, context_text)
                st.write(response)
                st.session_state.messages.append({"role": "assistant", "content": response})
