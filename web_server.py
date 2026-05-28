from mcp.server.fastmcp import FastMCP
from langchain_tavily import TavilySearch
import feedparser
import os
from dotenv import load_dotenv
import requests
from datetime import datetime,timedelta
import uvicorn
load_dotenv()

web=FastMCP("web",stateless_http=True)

##RTE news 
@web.tool()
def get_news(query:str)->str:
    """ Use this tool to get news from RSS feeds.
    For regional queries use region name e.g. 'india news', 'ireland news'
    For sport queries include 'sport' e.g. 'sport news'"""

    rss_feeds={
    "rte": "https://www.rte.ie/feeds/rss/?index=/news",
    "bbc": "https://feeds.bbci.co.uk/news/rss.xml",
    "guardian": "https://www.theguardian.com/world/rss",
    "aljazeera": "https://www.aljazeera.com/xml/rss/all.xml",
    "irish_times": "https://www.irishtimes.com/cmlink/news-1.1319192",
    "breaking_news": "https://feeds.breakingnews.ie/bntopstories",
    "thehindu":"https://thehindu.com/feeder/default/rss",
    "scmp":"https://www.scmp.com/rss/91/feed",
    "sky_sport":"https://www.skysports.com/rss/12040",
    "rte_sport": "https://www.rte.ie/feeds/rss/?index=/sport",
    "bbc_sport": "https://feeds.bbci.co.uk/sport/rss.xml",
    }
    regional_feed={
        "india":["thehindu"],
        "uk":["bbc"],
        "usa":["guardian"],
        "uae":["aljazeera"],
        "china":["scmp"],
        "ireland":["irish_times","rte","breaking_news"]
    }
   
    sport_news={"bbc_sport","rte_sport","sky_sport"}
    genric_queries={"latest","news","latest news","recent news","genral","all","today","headlines","news update"}
    is_genric= query.lower().strip()in genric_queries
    is_sport="sport" in query.lower()

    results=[]
    detected_feed=[]
    for key,val in regional_feed.items():
        if key.lower()in query.lower():
            detected_feed=val
            break
    for name,url in rss_feeds.items():
        if is_sport and name not in sport_news:
            continue #skip other news for sport news
        if not is_sport and name in sport_news:
            continue #skip sport news for non-sport queries
        if detected_feed and name not in detected_feed:
            continue #skip other regions news
        feed=feedparser.parse(url)
        for entry in feed.entries[:5]:
            results.append({
                "title":entry.title,
                "summary":entry.get("summary", "No summary avaiable"),
                "link":entry.link
            })  
    #fallback to get top news after all feeds searched and empty.
    if not results:
        for name,url in rss_feeds.items():
            feed=feedparser.parse(url)
            for entry in feed.entries[:2]:
                results.append({
                "title":entry.title,
                "summary":entry.get("summary", "No summary avaiable"),
                "link":entry.link
            })
    return  str(results[:10])

    
## Tavily search
@web.tool()
def tavily_search(query:str)->str:
    """Use this when you need to search from the internet about the user query"""
    search=TavilySearch(max_results=5)
    result=search.run(query)
    return str(result)

## News API for older news
@web.tool()
def get_old_news(query:str ,days_ago:int)->str:
    """Use this to fetch the older news from newsapi"""
    api_key=os.getenv("NEWS_API_KEY")
    if not api_key:
        raise ValueError("NEWS_API_KEY not found in environment variables")
    params={
        "q": query,
        "sortBy":"publishedAt",
        "pageSize":10,
        "apiKey":api_key,
        "language":"en",
        "from":(datetime.now()-timedelta(days=days_ago)).strftime("%Y-%m-%d"),    
    }
    data=requests.get("https://newsapi.org/v2/everything",params=params)
    news=data.json()
    if news.get("status")!= "ok" or not news.get("articles"):
        return "No articles found for this query"
    results=[]
    for new in news["articles"][:5]:
        results.append({
            "title":new["title"],
            "summary":new["description"],
            "link":new["url"]
        })
    return str(results)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app = web.streamable_http_app()
    uvicorn.run(app, host="0.0.0.0", port=port)
    
    
   
    

