import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from GlassCrewAgent.crew import kickoff_with_input

if __name__ == '__main__':

    user_input="下列Nb₂O₅ B₂O₃ La₂O₃ ZnO体系高折射率重镧火石玻璃组成的质量百分比(wt%)分别为：B2O3：12.2，La2O3：47.5，TiO2：6.6，ZrO2：5.5， SiO2：7.1，WO3：1.2，Y2O3：11，Nb2O5：6.2，ZnO：2.7。 其对应的折射率为1.911，阿贝数为35.3，膨胀系数为66*10-7/K, 硬度Hk为7070 MPa，弹性模量E为126 GPa。在此玻璃组分基础上，从Nb₂O₅ B₂O₃ La₂O₃ ZnO体系高折射率玻璃各组分对玻璃性能影响和玻璃结构解读分析，提出如何优化玻璃组成，实现同时降低膨胀系数（预期达到55*10-7/K）、提高玻璃的硬度Hk，降低弹性模量E小于120GPa的玻璃性能设计目标。"

    result = kickoff_with_input(user_input)
