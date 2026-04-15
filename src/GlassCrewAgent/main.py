import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from GlassCrewAgent.crew import kickoff_with_input

if __name__ == '__main__':

    user_input="设计用于导引头的红外光窗材料（成分、工艺、结构，具体性质指标暂时没有），涉及光电探测、满足超音速气动加热与抗冲击力学等要求、以适应导引头光电探测，目前红外（尤其中红外）光窗材料是导引头光电探测难点。"

    result = kickoff_with_input(user_input)
