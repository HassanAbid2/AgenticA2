"""BriefBot service."""
import sys
from langgraph.graph import StateGraph
from langchain_core.prompts import ChatPromptTemplate
SYSTEM_PROMPT = open('prompt.md').read()
from pinecone import Pinecone
from openai import OpenAI


def main():
    pass
