from src.GlassCrewAgent.tools.qdrant_search_tool import search_papers_in_qdrant
import sys
import os

answer=search_papers_in_qdrant.func("Polymer-based  structures")

print(answer)