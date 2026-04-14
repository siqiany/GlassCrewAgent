import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.GlassCrewAgent.tools.generalCommon import download_papers_from_arxiv_single


result = download_papers_from_arxiv_single.func("optical glass")
print(result)
