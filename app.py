import streamlit as st
import main

st.title("News Bot")
st.caption("Regional & global news, verified")
query=st.text_input("Ask about any news topics")

if st.button("Search"):
    with st.spinner("Fetching news..."):
        result=main.graph(query)
        st.markdown(result)
