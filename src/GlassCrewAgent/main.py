import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from GlassCrewAgent.crew import kickoff_with_input

if __name__ == '__main__':

    user_input="满足下关键指标的计算光纤材料成分和工艺是什么：1. 光传输波段覆盖C+L波段；2. 色散系数≥200 ps/（nm·km）；3. 模场半径≤5 μm；4. 弯曲半径≤5 mm；5. 损耗≤ 0.5 dB/km；6. 本征拉曼增益系数≥ 2.0 ×10 ^(-12) m/W."

    result = kickoff_with_input(user_input)
