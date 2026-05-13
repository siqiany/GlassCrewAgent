import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from GlassCrewAgent.crew import kickoff_with_input

if __name__ == '__main__':

    user_input=""

    result = kickoff_with_input(user_input)
