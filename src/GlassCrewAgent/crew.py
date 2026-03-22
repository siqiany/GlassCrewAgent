from crewai import Agent, Task, Crew, Process
from crewai.project import CrewBase, agent, crew, task
from crewai.agents.agent_builder.base_agent import BaseAgent
from typing import List

class GlassResearchCrew():
    """GlassResearch crew"""

    agents:List[BaseAgent]
    tasks:List[Task]

    @agent
    def searcher(self) -> Agent:
        return(
            
        )
