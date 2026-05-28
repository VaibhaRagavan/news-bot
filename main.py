import os
import httpx
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.graph import StateGraph, START, END
from typing_extensions import Dict,TypedDict
from langchain.agents import create_agent
import streamlit as st
import asyncio

load_dotenv()
os.environ["LANGSMITH_API_KEY"] = st.secrets["LANGSMITH_API_KEY"]
os.environ["OPENAI_API_KEY"] = st.secrets["OPENAI_API_KEY"]
os.environ["LANGSMITH_TRACING"] = "true"
os.environ["LANGSMITH_PROJECT"] = "Basic_Agentic_AI"
os.environ["LANGSMITH_ENDPOINT"] = "https://eu.api.smith.langchain.com"

##Getting the tools from MCP server
async def get_tools():
    client = MultiServerMCPClient(
        {
            "web": {
                "url": st.secrets.get("MCP_URL" , "http://127.0.0.1:8000/mcp"),
                "transport": "streamable_http",
               
            }
        }
    )
    tool = await client.get_tools()
    return tool


tools = None
llm = ChatOpenAI(model="gpt-4o-mini")
async def get_tools_lazy():
    global tools
    if tools is None:
        tools = await get_tools()
    return tools

## Build the supervisor state
class SupervisorState(TypedDict):
    "State for the multi-agent system"

    next_agent: str
    research_data: str
    analysis: str
    final_report: str
    task_complete: bool
    current_task: str
    supervisor_instruction: str
    research_attempts: int

##Create Supervisor agent
async def supervisor_agent(state: SupervisorState) -> Dict:
   """Supervisor agent uses open-ai llm to decide the next process"""
   task=state.get("current_task", "")
   supervisor_agent_prompt=f"""You are a supervisor managing a news pipeline.
You must decide the next step based on what has been completed.
Research Attempts So Far: {state.get("research_attempts", 0)}
Current Task: {task}
Research Done: {"YES" if state.get("research_data") else "NO"}
Factcheck Done: {"YES" if state.get("analysis") else "NO"}
Report Done: {"YES" if state.get("final_report") else "NO"}
Rules:
- Check if the task has multiple questions — handle each separately
- If any question has no result AND research_attempts < 1 → return 'research'
- If any question has no result AND research_attempts >= 1 → accept and move on
- If all questions answered OR max retries hit → return 'factcheck'
- If Factcheck done but no report → return 'writer'
- If Report done → return 'done'
IMPORTANT:
- Return ONLY one word: research, factcheck, writer, done
- Never loop more than 2 times on same failed query
"""

   result = await llm.ainvoke([SystemMessage(content=supervisor_agent_prompt),
         HumanMessage(content="what is the next step?"
   )])
   decision_text=result.content.strip().lower().split()[0]   
   print(decision_text)
    ##lets determine next agent
   if "done" in decision_text:
        next_agent="end"
        supervisor_msg=" All tasks complete! Great work team."
   elif "research" in decision_text:
        next_agent="research"
        supervisor_msg="Starting research phase..."
   elif "factcheck" in decision_text:
        next_agent="factcheck"
        supervisor_msg="Factcheck agent, please verify the news and provide factual information."
   elif "writer" in decision_text:
        next_agent="writer"
        supervisor_msg="Writer agent, please compile the final report based on the research and fact-checking."
   else:
       next_agent="end"
       supervisor_msg="Ending the process."
   return{
        "messages":[AIMessage(content=supervisor_msg, name="supervisor")],
        "next_agent":next_agent,
        "current_task":task,
    }
       
   
    
    
##Create Research agent
async def research_agent(state: SupervisorState):
    """Research agent to gather news from the sources"""
    task = state["current_task"]
    research_prompt=SystemMessage(f"""
    News Resarch agent , your only job to get news related to query.
    TOOL SELECTION RULES:
- Query mentions "today", "latest", "current", "now" → use get_news
- Query mentions "yesterday" → use get_old_news(query, days_ago=1)
- Query mentions "last X days" → use get_old_news(query, days_ago=X)
- Query mentions "last week" → use get_old_news(query, days_ago=7)
- Query mentions "last month" → use get_old_news(query, days_ago=30)                             
FEED SELECTION RULES
- Ireland: rte, irish_times, breaking_news
- Europe/UK: bbc
- Americas: guardian  
- Middle East: aljazeera
- Asia/China: scmp
- India: thehindu
- Sport: bbc_sport, rte_sport, sky_sport
 STRICT RULES:
1. Do NOT think or analyse — just fetch using the tools
2. Do NOT label news from one region as another region
3. If one source fails, try another 
4. If no results found → return NO_RESULTS_FOUND
5. Do NOT use get_old_news for current/today queries
6. Do NOT use get_news for past queries

OUTPUT FORMAT (for each article):
- Title:
- Summary:
- Source:
- Link:
- Date (if available):                                
""")
    tool= await get_tools_lazy()
    agent_runnable = create_agent(
        model=llm, tools=tool, system_prompt=research_prompt.content
    )
    result = await agent_runnable.ainvoke(
        {"messages": [HumanMessage(content=f"Gather research for{task}")]}
    )
    data = result["messages"][-1].content
    agent_message = f"Research agent has gathered the news: {data[:100]}..."
    return {
        "messages": [AIMessage(content=agent_message)],
        "research_data": data,
        "next_agent": "supervisor",
        "research_attempts":state.get("research_attempts", 0)+1
    }


##Create Factcheck agent
async def factcheck_agent(state: SupervisorState):
    """Factcheck agent is to verify the news from the reasearch agent"""
    task = state["current_task"]
    data = state.get("research_data", "")
    factcheck_prompt = SystemMessage(f"""
    Factcheck agent. ONLY verify the news provided to you.
- Use tavily_search to cross-check each article title/claim
- Do NOT search for new articles
- Do NOT replace missing research data
- If research_data is empty or failed → respond with RESEARCH_FAILED
- Flag each item VERIFIED or NOT VERIFIED
- Note contradictions between sources.""")
    tool= await get_tools_lazy()
    factcheck_agent_runnable = create_agent(
        model=llm, tools=tool, system_prompt=factcheck_prompt.content
    )
    result = await factcheck_agent_runnable.ainvoke(
        {"messages": [HumanMessage(content=f"Verify the research findings{data}")]}
    )

    analysis = result["messages"][-1].content

    agent_message = f"Factcheck agent verifies the news data and the response is {analysis}"
    return {
        "messages": [AIMessage(content=agent_message)],
        "analysis": analysis,
        "next_agent": "supervisor",
    }


##Create Writer agent
"""Write agent to create the structed result using data from research agent anf factcheck agent"""


async def writer_agent(state: SupervisorState):
    """Write agent to create the structed result using data from research agent anf factcheck agent"""
    instruction = state.get("supervisor_instruction", "")
    research_data = state.get("research_data", "")
    analysis = state.get("analysis", "")
    task = state["current_task"]
    if "NO_RESULTS_FOUND" in state.get("research_data", ""):
        final_report = "I can only help with news related queries"
        agent_message = "Writer agent could not compile a report due to no research data."
    else:
        writer_prompt = f"""
 Writer agent, your job is to create a structured report based on the research and fact-checking.
User Query:{task}
Analysis:{analysis}
Supervisor Instruction:{instruction} 
Research Data:{research_data}

Rules:
- If instruction says VERIFIED → present news confidently with sources
- If instruction says NOT VERIFIED → clearly label each item as  Unverified
  and note the reader should cross-check before sharing

Instruction:
1. If the query is not related to news then respond with 'I can only help with news related queries'
2. The report should be in a structured format
3. The report should be clear and concise
4. The report should be in a professional tone
5. The report does not ot exceed 2000 tokens.
OUTPUT:
The final report should be in a structured format with the following sections: 
- News in order 
- For each news item include the summary , link for the newspage ,source , factcheckcstatus, any contrediciton.

"""     
        writer_llm=ChatOpenAI(model=llm, max_tokens=2000)
        writer_response = await writer_llm.ainvoke([HumanMessage(content=writer_prompt)])
        final_report = writer_response.content
        agent_message = (
            f"Writer agent has compiled the final report: {final_report[:2000]}..."
        )
    
    return {
        "messages": [AIMessage(content=agent_message)],
        "final_report": final_report,
        "next_agent": "supervisor",
        "task_complete": True,
    }


##create the graph
def graph(query):
    async def main():
        """Main function to run the multi-agent system"""
        workflow = StateGraph(SupervisorState)
        workflow.add_node("supervisor", supervisor_agent)
        workflow.add_node("research", research_agent)
        workflow.add_node("factcheck", factcheck_agent)
        workflow.add_node("writer", writer_agent)

        workflow.add_edge(START, "supervisor")
        workflow.add_edge("research", "supervisor")
        workflow.add_edge("factcheck", "supervisor")
        workflow.add_edge("writer", "supervisor")
        def router(state: SupervisorState):
            return state["next_agent"] if state["next_agent"] != "end" else END

        workflow.add_conditional_edges(
                "supervisor",
                router,
                {"research": "research", "factcheck": "factcheck", "writer": "writer", END: END},)
        graph = workflow.compile()  
        return await graph.ainvoke({"messages":[HumanMessage(content=query)],
                       "current_task": query,
                       "research_attempts": 0})
    response = asyncio.run(main())
    return response["final_report"]

         
