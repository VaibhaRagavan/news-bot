import streamlit as st
import main

st.title("News Bot")
st.caption("Regional & global news, verified")
query=st.text_input("Ask about any news topics")
openai_api_key=st.secrets("OPENAI_API_KEY")
langsmith_api_key=st.secrets("LANGSMITH_API_KEY")
mcp_url=st.secrets("MCP_URL")
if st.button("Search"):
    with st.spinner("Fetching news..."):
        result=main.graph(query)
        st.markdown(result)
