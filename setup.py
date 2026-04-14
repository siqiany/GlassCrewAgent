from setuptools import setup, find_packages

setup(
    name="GlassCrewAgent",          # 项目名，可自定义，不能有空格
    version="0.0.1",         # 自动发现所有带 __init__.py 的包
    python_requires=">=3.12",           # 根据你的环境调整
    package_dir={"": "src"},
    packages=find_packages(where="src"),
)