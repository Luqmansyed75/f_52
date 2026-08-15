import os
from operator import itemgetter

from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from langchain_groq import ChatGroq
from pydantic import BaseModel
from sqlalchemy import text

from db.database import AsyncSessionLocal

load_dotenv()


class MeetingSummary(BaseModel):
    summary: str
    insights: list[str]


# --- Runnable 1: Prompt ---
prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a meeting analyst. From the transcript produce a concise summary "
               "and a list of key insights: decisions made, important dates, and notable events."),
    ("human", "{transcript}"),
])


# --- Runnable 2: Groq LLM with structured output ---
llm = ChatGroq(model="llama-3.3-70b-versatile", api_key=os.getenv("GROQ_API_KEY"))
structured_llm = llm.with_structured_output(MeetingSummary)


# --- Runnable 3: Store into meetings table ---
async def store_summary(data: dict) -> MeetingSummary:
    result: MeetingSummary = data["result"]
    meeting_id: str = data["meeting_id"]
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("UPDATE meetings SET summary = :summary, insights = :insights WHERE meeting_id = :id"),
            {"summary": result.summary, "insights": result.insights, "id": str(meeting_id)},
        )
        await session.commit()
    return result


# --- Chain ---
chain = (
    {"result": prompt | structured_llm, "meeting_id": itemgetter("meeting_id")}
    | RunnableLambda(store_summary)
)
