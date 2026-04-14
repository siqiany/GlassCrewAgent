#!/usr/bin/env python3
"""
GlassCrewAgent Web UI - Flask backend
提供大模型问答界面，实时显示智能体运行进程
"""

import os
import sys
import json
import threading
import uuid
from flask import Flask, render_template, request, jsonify, Response
from flask_cors import CORS

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.GlassCrewAgent.crew import handle_user_goal, get_crew_instance

app = Flask(__name__)
CORS(app)

# 存储活跃的任务
active_tasks = {}


def run_crew_task(task_id, user_input):
    """
    在后台线程中运行 crew 任务，并通过 SSE 发送实时更新
    """
    task_info = active_tasks.get(task_id)
    if not task_info:
        return
    
    task_info['status'] = 'running'
    
    try:
        # 获取 crew 实例
        crew = get_crew_instance()
        
        # 启动任务 - 虽然CrewAI的kickoff不直接支持回调，我们会在完成后返回结果
        result = crew.kickoff(inputs={'user_input': user_input})
        
        # 任务完成
        task_info['status'] = 'completed'
        task_info['result'] = result.raw if hasattr(result, 'raw') else str(result)
        
        # 保存最终结果到本地 Markdown 文件
        try:
            # 导入datetime
            from datetime import datetime
            # 确保输出目录存在
            os.makedirs('output', exist_ok=True)
            # 使用时间戳生成唯一文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file_path = os.path.join('output', f"final_glass_report_{timestamp}.md")
            # 同时也保存一个固定名称的文件用于最新结果
            fixed_output_path = os.path.join('output', "final_glass_report.md")
            
            # 写入带时间戳的文件
            with open(output_file_path, 'w', encoding='utf-8') as f:
                f.write(task_info['result'])
                f.write("\n\n---\n")
                f.write(f"Generated on: {datetime.now().isoformat()}\n")
                f.write(f"User Query: {user_input}\n")
            
            # 更新固定名称的最新结果文件
            with open(fixed_output_path, 'w', encoding='utf-8') as f:
                f.write(task_info['result'])
                f.write("\n\n---\n")
                f.write(f"Generated on: {datetime.now().isoformat()}\n")
                f.write(f"User Query: {user_input}\n")
            
            task_info['output_file'] = output_file_path
            task_info['latest_output_file'] = fixed_output_path
            print(f"\n✅ Final report saved to:")
            print(f"   - {output_file_path}")
            print(f"   - {fixed_output_path} (latest version)\n")
        except Exception as e:
            print(f"\n⚠️  Warning: Failed to save final report to file: {e}\n")
            task_info['output_file'] = None
            task_info['latest_output_file'] = None
        
        # 发送完成事件
        event = {
            'type': 'complete',
            'result': task_info['result'],
            'output_file': task_info.get('output_file', None),
            'latest_output_file': task_info.get('latest_output_file', None),
            'timestamp': str(uuid.uuid4())[:8]
        }
        task_info['stream_queue'].put(json.dumps(event))
        
    except Exception as e:
        task_info['status'] = 'error'
        task_info['error'] = str(e)
        
        event = {
            'type': 'error',
            'error': str(e),
            'timestamp': str(uuid.uuid4())[:8]
        }
        task_info['stream_queue'].put(json.dumps(event))
    
    # 发送结束标记
    task_info['stream_queue'].put(json.dumps({'type': 'end'}))


@app.route('/')
def index():
    """主页"""
    return render_template('index.html')


@app.route('/api/ask', methods=['POST'])
def ask():
    """
    接收用户问题，启动智能体任务
    返回 task_id 用于后续获取实时更新
    """
    data = request.get_json()
    user_input = data.get('question', '')
    
    if not user_input:
        return jsonify({'error': '问题不能为空'}), 400
    
    # 生成任务 ID
    task_id = str(uuid.uuid4())[:8]
    
    # 创建任务信息
    active_tasks[task_id] = {
        'question': user_input,
        'status': 'pending',
        'result': None,
        'error': None,
        'events': [],
        'stream_queue': __import__('queue').Queue()
    }
    
    # 在后台线程中启动任务
    thread = threading.Thread(target=run_crew_task, args=(task_id, user_input))
    thread.daemon = True
    thread.start()
    
    return jsonify({'task_id': task_id})


@app.route('/api/stream/<task_id>')
def stream(task_id):
    """
    SSE 实时流式返回任务进度
    """
    task_info = active_tasks.get(task_id)
    if not task_info:
        return Response('data: {"error": "任务不存在"}\n\n', 
                       mimetype='text/event-stream')
    
    def generate():
        queue = task_info['stream_queue']
        while True:
            try:
                message = queue.get(timeout=30)
                yield f"data: {message}\n\n"
                
                if message == json.dumps({'type': 'end'}):
                    break
            except Exception:
                break
    
    return Response(generate(), mimetype='text/event-stream')


@app.route('/api/status/<task_id>')
def get_status(task_id):
    """
    获取任务状态和结果
    """
    task_info = active_tasks.get(task_id)
    if not task_info:
        return jsonify({'error': '任务不存在'}), 404
    
    return jsonify({
        'status': task_info['status'],
        'result': task_info.get('result'),
        'error': task_info.get('error'),
        'events': task_info.get('events', [])
    })


@app.route('/api/tasks')
def list_tasks():
    """列出所有任务"""
    tasks = []
    for task_id, info in active_tasks.items():
        tasks.append({
            'task_id': task_id,
            'question': info.get('question', '')[:100],
            'status': info.get('status'),
            'timestamp': task_id
        })
    return jsonify({'tasks': tasks})


if __name__ == '__main__':
    # 确保输出目录存在
    os.makedirs('output', exist_ok=True)
    
    print("=" * 50)
    print("GlassCrewAgent Web UI 启动中...")
    print("访问地址: http://localhost:5000")
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)