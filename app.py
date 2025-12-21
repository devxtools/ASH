# app.py (精简版)
from flask import Flask, request, jsonify
from datetime import datetime
import threading
import time
import os
import json
import pandas as pd
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger


# 导入独立的分析模块
from mods.stock_analyzer import (
    StockAnalyzer,
    BatchStockAnalyzer,
    analyze_stock_simple,
    batch_analyze_stocks,
    get_2min_data
)


app = Flask(__name__)

# ==================== 全局变量 ====================
ALL_STOCKS = []  # 股票列表
ANALYSIS_RESULTS = []  # 分析结果
TOP_STOCKS = []  # 前10名股票
DATA_DIR = 'data'

# ==================== API路由 ====================

@app.after_request
def after_request(response):
    """允许跨域"""
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

@app.route('/')
def index():
    """主页"""
    return jsonify({
        'service': '股票分析API',
        'version': '4.0',
        'modules': 'stock_analyzer.py 独立分析模块',
        'endpoints': {
            '/': '本页面',
            '/api/analyze': '分析单只股票',
            '/api/stock/detail': '股票详情（2分钟数据）',
            '/api/analysis/batch': '批量分析',
            '/api/analysis/top': '获取前10名',
            '/api/stocks': '获取股票列表',
            '/api/health': '健康检查'
        }
    })

@app.route('/api/analyze', methods=['GET'])
def analyze_stock_api():
    """分析单只股票"""
    stock_code = request.args.get('code', '').strip()
    
    if not stock_code:
        return jsonify({'success': False, 'error': '需要股票代码'}), 400
    
    # 使用独立模块的分析函数
    result = analyze_stock_simple(stock_code)
    return jsonify(result)

@app.route('/api/stock/detail', methods=['GET'])
def get_stock_detail_api():
    """获取股票详情（2分钟数据）"""
    stock_code = request.args.get('code', '').strip()
    minutes = int(request.args.get('minutes', '60'))
    
    if not stock_code:
        return jsonify({'success': False, 'error': '需要股票代码'}), 400
    
    try:
        # 1. 获取2分钟数据
        two_min_data = get_2min_data(stock_code, minutes)
        
        # 2. 获取日线分析
        analyzer = StockAnalyzer(stock_code)
        if analyzer.df.empty:
            return jsonify({'success': False, 'error': '无法获取股票数据'}), 404
        
        analyzer.calculate_indicators()
        day_result = analyzer.analyze()
        
        # 3. 获取实时分析
        realtime_result = analyzer.analyze_realtime(minutes=30)
        
        # 4. 整合结果
        result = {
            'success': True,
            'stock_code': stock_code,
            'timestamp': datetime.now().isoformat(),
            'two_minute_data': two_min_data,
            'day_analysis': day_result,
            'realtime_analysis': realtime_result
        }
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/analysis/batch', methods=['POST'])
def batch_analyze_api():
    """批量分析股票"""
    try:
        data = request.get_json()
        
        if not data or 'stocks' not in data:
            # 使用全局股票列表
            if not ALL_STOCKS:
                return jsonify({'success': False, 'error': '股票列表为空'}), 400
            
            stock_list = [s['symbol'] for s in ALL_STOCKS[:100]]  # 限制数量
        else:
            stock_list = data['stocks']
        
        min_confidence = data.get('min_confidence', 80.0)
        
        # 使用独立模块的批量分析函数
        results = batch_analyze_stocks(stock_list, min_confidence)
        
        return jsonify({
            'success': True,
            'count': len(results),
            'results': results[:10],  # 只返回前10名
            'top_stocks': results[:10]
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/analysis/top', methods=['GET'])
def get_top_stocks_api():
    """获取前10名股票"""
    return jsonify({
        'success': True,
        'top_stocks': TOP_STOCKS,
        'last_update': datetime.now().isoformat(),
        'count': len(TOP_STOCKS)
    })

# ==================== 定时任务 ====================

def daily_analysis_task():
    """每日分析任务"""
    global TOP_STOCKS, ANALYSIS_RESULTS
    
    if not ALL_STOCKS:
        print("⚠️ 股票列表为空，跳过分析")
        return
    
    print(f"🚀 开始每日分析任务，股票数量: {len(ALL_STOCKS)}")
    
    # 使用独立模块进行批量分析
    batch_analyzer = BatchStockAnalyzer(
        stock_list=[s['symbol'] for s in ALL_STOCKS[:200]],  # 限制数量
        period_days=120
    )
    
    results = batch_analyzer.analyze_all(min_confidence=80.0)
    TOP_STOCKS = batch_analyzer.get_top_stocks(top_n=10)
    ANALYSIS_RESULTS = results
    
    # 保存结果
    save_analysis_results()
    
    print(f"✅ 分析完成，找到 {len(results)} 只高信心股票")

def save_analysis_results():
    """保存分析结果"""
    try:
        if not os.path.exists(DATA_DIR):
            os.makedirs(DATA_DIR)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = os.path.join(DATA_DIR, f'top_stocks_{timestamp}.json')
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'top_stocks': TOP_STOCKS,
                'total_analyzed': len(ANALYSIS_RESULTS)
            }, f, ensure_ascii=False, indent=2)
        
        print(f"💾 结果已保存: {filename}")
        
    except Exception as e:
        print(f"❌ 保存结果失败: {e}")

def schedule_daily_analysis():
    """设置定时分析"""
    scheduler = BackgroundScheduler()
    
    # 周一到周五，下午13:30执行
    scheduler.add_job(
        func=daily_analysis_task,
        trigger=CronTrigger(
            day_of_week='mon-fri',
            hour=13,
            minute=30,
            timezone='Asia/Shanghai'
        ),
        id='daily_analysis',
        name='每日股票分析'
    )
    
    scheduler.start()
    print("⏰ 定时分析任务已设置: 周一到周五 13:30")
    return scheduler

# ==================== 启动应用 ====================

if __name__ == '__main__':
    print("🚀 股票分析API服务启动中...")
    print("📦 使用独立分析模块: stock_analyzer.py")
    
    # 初始化数据目录
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    
    # 启动定时任务
    scheduler = schedule_daily_analysis()
    
    print("\n📊 API端点:")
    print("  GET  /api/analyze?code=股票代码     - 分析单只股票")
    print("  GET  /api/stock/detail?code=股票代码 - 股票详情（2分钟数据）")
    print("  POST /api/analysis/batch            - 批量分析")
    print("  GET  /api/analysis/top              - 获取前10名")
    
    print("\n💡 独立模块使用示例:")
    print("  from stock_analyzer import StockAnalyzer")
    print("  analyzer = StockAnalyzer('sh600519')")
    print("  result = analyzer.analyze()")
    print(f"\n📈 当前股票数量: {len(ALL_STOCKS)} 只")
    
    app.run(host='0.0.0.0', port=8988, debug=True, use_reloader=False)