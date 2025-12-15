# app.py (更新版)
from flask import Flask, request, jsonify
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from Ashare import get_price
import requests
import threading
import time
import warnings
from functools import lru_cache

warnings.filterwarnings('ignore')

app = Flask(__name__)

# ==================== 全局配置 ====================
ALL_STOCKS = []  # 全局存储所有股票列表
LAST_UPDATE_TIME = None
UPDATE_INTERVAL = 24 * 3600  # 24小时更新一次（秒）

# ==================== 股票数据管理 ====================

def fetch_all_stocks():
    """
    从API获取所有股票列表
    注意：这是一个示例URL，实际使用时需要确认正确的API
    """
    global ALL_STOCKS, LAST_UPDATE_TIME
    
    try:
        print("🔄 开始更新股票列表...")
        
        # 这里使用示例API，实际请使用正确的API地址
        # url = "https://api.biyingapi.com/hslt/list/biyinglicence"
        
        # 由于示例API可能无法访问，这里使用模拟数据
        # 实际使用时请取消注释上面的URL
        
        # 模拟数据 - 实际请替换为真实API调用
        stocks_data = []
        
        # 上证A股示例
        for i in range(600000, 601000):
            if i % 100 == 0:  # 每隔100个取一个，减少数量
                stocks_data.append({
                    'symbol': f'sh{i:06d}',
                    'name': f'测试股票{i:06d}',
                    'code': f'{i:06d}',
                    'exchange': 'SH'
                })
        
        # 深证A股示例
        for i in range(0, 1000):
            if i % 10 == 0:
                stocks_data.append({
                    'symbol': f'sz{300000 + i:06d}',
                    'name': f'创业板股票{300000 + i:06d}',
                    'code': f'{300000 + i:06d}',
                    'exchange': 'SZ'
                })
        
        for i in range(0, 1000):
            if i % 10 == 0:
                stocks_data.append({
                    'symbol': f'sz{000000 + i:06d}',
                    'name': f'深证股票{000000 + i:06d}',
                    'code': f'{000000 + i:06d}',
                    'exchange': 'SZ'
                })
        
        # 过滤ST股票（模拟过滤）
        filtered_stocks = []
        for stock in stocks_data:
            # 过滤ST/*ST股票（根据股票名称或代码判断）
            stock_name = stock.get('name', '')
            stock_code = stock.get('code', '')
            
            # 判断是否为ST股票
            is_st = False
            if 'ST' in stock_name.upper():
                is_st = True
            elif stock_code.startswith('60') and 'ST' in stock_name.upper():
                is_st = True
            elif stock_code.startswith('00') and 'ST' in stock_name.upper():
                is_st = True
            elif stock_code.startswith('30') and 'ST' in stock_name.upper():
                is_st = True
            
            if not is_st:
                # 添加更多信息
                stock.update({
                    'market': '主板' if stock_code.startswith('60') or stock_code.startswith('00') else '创业板' if stock_code.startswith('30') else '未知',
                    'full_code': stock['symbol'],
                    'display_name': f"{stock['symbol']} {stock['name']}"
                })
                filtered_stocks.append(stock)
        
        ALL_STOCKS = filtered_stocks
        LAST_UPDATE_TIME = datetime.now()
        
        print(f"✅ 股票列表更新完成！共 {len(ALL_STOCKS)} 只股票")
        print(f"📅 最后更新时间: {LAST_UPDATE_TIME}")
        
        return True
        
    except Exception as e:
        print(f"❌ 获取股票列表失败: {e}")
        
        # 返回一些基础股票作为后备
        fallback_stocks = [
            {'symbol': 'sh000001', 'name': '上证指数', 'code': '000001', 'exchange': 'SH', 'market': '指数', 'full_code': 'sh000001', 'display_name': 'sh000001 上证指数'},
            {'symbol': 'sz399001', 'name': '深证成指', 'code': '399001', 'exchange': 'SZ', 'market': '指数', 'full_code': 'sz399001', 'display_name': 'sz399001 深证成指'},
            {'symbol': 'sh600519', 'name': '贵州茅台', 'code': '600519', 'exchange': 'SH', 'market': '主板', 'full_code': 'sh600519', 'display_name': 'sh600519 贵州茅台'},
            {'symbol': 'sz000858', 'name': '五粮液', 'code': '000858', 'exchange': 'SZ', 'market': '主板', 'full_code': 'sz000858', 'display_name': 'sz000858 五粮液'},
            {'symbol': 'sz000333', 'name': '美的集团', 'code': '000333', 'exchange': 'SZ', 'market': '主板', 'full_code': 'sz000333', 'display_name': 'sz000333 美的集团'},
            {'symbol': 'sh601318', 'name': '中国平安', 'code': '601318', 'exchange': 'SH', 'market': '主板', 'full_code': 'sh601318', 'display_name': 'sh601318 中国平安'},
            {'symbol': 'sz002415', 'name': '海康威视', 'code': '002415', 'exchange': 'SZ', 'market': '中小板', 'full_code': 'sz002415', 'display_name': 'sz002415 海康威视'},
            {'symbol': 'sh600036', 'name': '招商银行', 'code': '600036', 'exchange': 'SH', 'market': '主板', 'full_code': 'sh600036', 'display_name': 'sh600036 招商银行'},
            {'symbol': 'sz300750', 'name': '宁德时代', 'code': '300750', 'exchange': 'SZ', 'market': '创业板', 'full_code': 'sz300750', 'display_name': 'sz300750 宁德时代'},
            {'symbol': 'sh601888', 'name': '中国中免', 'code': '601888', 'exchange': 'SH', 'market': '主板', 'full_code': 'sh601888', 'display_name': 'sh601888 中国中免'},
        ]
        ALL_STOCKS = fallback_stocks
        LAST_UPDATE_TIME = datetime.now()
        
        return False

def auto_update_stocks():
    """后台自动更新股票列表"""
    while True:
        try:
            now = datetime.now()
            
            # 检查是否需要更新（每24小时）
            if LAST_UPDATE_TIME is None or (now - LAST_UPDATE_TIME).total_seconds() >= UPDATE_INTERVAL:
                fetch_all_stocks()
            else:
                next_update = LAST_UPDATE_TIME + timedelta(seconds=UPDATE_INTERVAL)
                print(f"⏰ 下次更新: {next_update}")
            
            # 休眠1小时检查一次
            time.sleep(3600)
            
        except Exception as e:
            print(f"自动更新出错: {e}")
            time.sleep(300)  # 出错后休眠5分钟

def get_stocks_list():
    """获取股票列表（带缓存和更新检查）"""
    global ALL_STOCKS, LAST_UPDATE_TIME
    
    # 如果列表为空或需要更新
    if not ALL_STOCKS or (LAST_UPDATE_TIME and 
                         (datetime.now() - LAST_UPDATE_TIME).total_seconds() >= UPDATE_INTERVAL):
        print("🔄 股票列表需要更新...")
        fetch_all_stocks()
    
    return ALL_STOCKS

# ==================== 股票分析类 ====================
class StockAnalyzer:
    """简化的股票分析器"""
    
    def __init__(self, stock_code, days=120):
        self.code = stock_code
        self.days = days
        self.df = self._get_data()
    
    def _get_data(self):
        """获取股票数据"""
        try:
            df = get_price(self.code, frequency='1d', count=self.days)
            if not df.empty:
                df['returns'] = df['close'].pct_change()
            return df
        except:
            return pd.DataFrame()
    
    def calculate_indicators(self):
        """计算技术指标"""
        if self.df.empty or len(self.df) < 30:
            return False
        
        df = self.df.copy()
        
        # 移动平均线
        df['MA5'] = df['close'].rolling(5).mean()
        df['MA10'] = df['close'].rolling(10).mean()
        df['MA20'] = df['close'].rolling(20).mean()
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # MACD
        exp1 = df['close'].ewm(span=12, adjust=False).mean()
        exp2 = df['close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = exp1 - exp2
        df['MACD_signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        
        # KD指标
        low_14 = df['low'].rolling(14).min()
        high_14 = df['high'].rolling(14).max()
        df['%K'] = 100 * ((df['close'] - low_14) / (high_14 - low_14))
        df['%D'] = df['%K'].rolling(3).mean()
        
        # 布林带位置
        df['BB_middle'] = df['close'].rolling(20).mean()
        bb_std = df['close'].rolling(20).std()
        df['BB_upper'] = df['BB_middle'] + (bb_std * 2)
        df['BB_lower'] = df['BB_middle'] - (bb_std * 2)
        df['BB_position'] = (df['close'] - df['BB_lower']) / (df['BB_upper'] - df['BB_lower'])
        
        self.df = df
        return True
    
    def analyze(self):
        """综合分析"""
        if self.df.empty or len(self.df) < 30:
            return self._empty_result()
        
        latest = self.df.iloc[-1]
        prev = self.df.iloc[-2]
        
        # 分析信号
        signals = self._analyze_signals(latest, prev)
        confidence = self._calculate_confidence(signals)
        
        # 生成结果
        result = self._generate_result(latest, prev, signals, confidence)
        return result
    
    def _analyze_signals(self, latest, prev):
        """分析技术信号"""
        signals = {
            'trend': {'reasons': [], 'score': 0},
            'momentum': {'reasons': [], 'score': 0},
            'volume': {'reasons': [], 'score': 0},
            'oscillators': {'reasons': [], 'score': 0},
            'patterns': {'patterns': [], 'score': 0}
        }
        
        # 趋势分析
        if latest['close'] > latest['MA20']:
            signals['trend']['reasons'].append("价格站上20日线")
            signals['trend']['score'] += 15
        
        if latest['MA5'] > latest['MA10'] > latest['MA20']:
            signals['trend']['reasons'].append("均线多头排列")
            signals['trend']['score'] += 10
        
        # 动量分析
        if 30 < latest['RSI'] < 70:
            signals['momentum']['reasons'].append("RSI处于健康区间")
            signals['momentum']['score'] += 10
        elif latest['RSI'] < 30:
            signals['momentum']['reasons'].append("RSI超卖")
            signals['momentum']['score'] += 20
        
        if latest['MACD'] > latest['MACD_signal']:
            signals['momentum']['reasons'].append("MACD金叉")
            signals['momentum']['score'] += 15
        
        # 摆动指标
        if latest['%K'] < 20:
            signals['oscillators']['reasons'].append("K值超卖")
            signals['oscillators']['score'] += 15
        
        if latest['BB_position'] < 0.3:
            signals['oscillators']['reasons'].append("接近布林带下轨")
            signals['oscillators']['score'] += 10
        
        return signals
    
    def _calculate_confidence(self, signals):
        """计算信心分数"""
        total_score = 0
        max_score = 100
        
        for category in signals.values():
            if 'score' in category:
                total_score += min(category['score'], 30)
        
        return min(total_score, 100)
    
    def _generate_result(self, latest, prev, signals, confidence):
        """生成分析结果"""
        price_change = ((latest['close'] - prev['close']) / prev['close'] * 100)
        
        # 收集关键理由
        key_reasons = []
        for category in signals.values():
            if 'reasons' in category:
                key_reasons.extend(category['reasons'])
        
        # 确定信号和操作
        if confidence >= 75:
            signal = "强烈买入"
            action = "BUY"
            position = "中等仓位(30-50%)"
        elif confidence >= 60:
            signal = "买入"
            action = "BUY"
            position = "轻仓位(20-30%)"
        elif confidence >= 45:
            signal = "关注"
            action = "HOLD"
            position = "观望"
        else:
            signal = "回避"
            action = "SELL"
            position = "不建议"
        
        # 计算风险指标
        risk_metrics = self._calculate_risk_metrics()
        
        return {
            'stock_code': self.code,
            'timestamp': datetime.now().isoformat(),
            'current_price': round(latest['close'], 2),
            'price_change': round(price_change, 2),
            'volume': int(latest['volume']),
            'indicators': {
                'MA5': round(latest['MA5'], 2),
                'MA10': round(latest['MA10'], 2),
                'MA20': round(latest['MA20'], 2),
                'RSI': round(latest['RSI'], 2),
                'MACD': round(latest['MACD'], 4),
                'KD_K': round(latest['%K'], 2),
                'KD_D': round(latest['%D'], 2),
                'BB_position': round(latest['BB_position'], 3)
            },
            'analysis': {
                'confidence_score': round(confidence, 1),
                'signal': signal,
                'action': action,
                'position_suggestion': position,
                'key_reasons': key_reasons[:5],
                'detailed_signals': signals
            },
            'risk_metrics': risk_metrics,
            'success': True
        }
    
    def _calculate_risk_metrics(self):
        """计算风险指标"""
        if len(self.df) < 20:
            return {}
        
        returns = self.df['returns'].dropna()
        
        # 波动率
        volatility = returns.std() * np.sqrt(252) * 100
        
        # 夏普比率
        sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
        
        # 最大回撤
        cumulative = (1 + returns).cumprod()
        running_max = cumulative.expanding().max()
        drawdown = (cumulative - running_max) / running_max
        max_dd = drawdown.min() * 100
        
        risk_level = '高' if volatility > 40 else '中' if volatility > 20 else '低'
        
        return {
            'volatility': round(volatility, 2),
            'sharpe_ratio': round(sharpe, 3),
            'max_drawdown': round(abs(max_dd), 2),
            'risk_level': risk_level
        }
    
    def _empty_result(self):
        """空结果"""
        return {
            'stock_code': self.code,
            'error': '数据不足或获取失败',
            'timestamp': datetime.now().isoformat(),
            'success': False
        }

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
        'version': '2.0',
        'endpoints': {
            '/': '本页面',
            '/api/analyze?code=股票代码': '分析单只股票',
            '/api/stocks': '获取所有股票列表',
            '/api/stocks/search?q=关键词': '搜索股票',
            '/api/stocks/update': '手动更新股票列表',
            '/api/health': '健康检查'
        },
        'status': '运行中',
        'stocks_count': len(ALL_STOCKS),
        'last_update': LAST_UPDATE_TIME.isoformat() if LAST_UPDATE_TIME else None
    })

@app.route('/api/stocks', methods=['GET'])
def get_stocks():
    """
    获取所有股票列表
    支持分页和搜索
    """
    try:
        # 获取分页参数
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 100))
        search = request.args.get('search', '').strip().upper()
        
        # 获取股票列表
        stocks = get_stocks_list()
        
        # 搜索过滤
        if search:
            filtered = []
            for stock in stocks:
                if (search in stock.get('symbol', '').upper() or 
                    search in stock.get('name', '').upper() or
                    search in stock.get('code', '').upper()):
                    filtered.append(stock)
            stocks = filtered
        
        # 分页
        total = len(stocks)
        start = (page - 1) * per_page
        end = start + per_page
        paged_stocks = stocks[start:end]
        
        return jsonify({
            'success': True,
            'data': paged_stocks,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'total_pages': (total + per_page - 1) // per_page
            },
            'summary': {
                'total_stocks': total,
                'search_term': search if search else None,
                'last_update': LAST_UPDATE_TIME.isoformat() if LAST_UPDATE_TIME else None
            }
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/stocks/search', methods=['GET'])
def search_stocks():
    """搜索股票"""
    query = request.args.get('q', '').strip()
    
    if not query:
        return jsonify({
            'success': False,
            'error': '请输入搜索关键词'
        }), 400
    
    stocks = get_stocks_list()
    results = []
    
    for stock in stocks:
        symbol = stock.get('symbol', '').upper()
        name = stock.get('name', '').upper()
        code = stock.get('code', '').upper()
        
        if (query.upper() in symbol or 
            query.upper() in name or 
            code.startswith(query)):
            results.append(stock)
    
    return jsonify({
        'success': True,
        'query': query,
        'count': len(results),
        'results': results[:50]  # 限制最多返回50个
    })

@app.route('/api/stocks/update', methods=['POST'])
def update_stocks():
    """手动更新股票列表"""
    try:
        success = fetch_all_stocks()
        
        if success:
            return jsonify({
                'success': True,
                'message': f'股票列表更新成功，共 {len(ALL_STOCKS)} 只股票',
                'last_update': LAST_UPDATE_TIME.isoformat() if LAST_UPDATE_TIME else None
            })
        else:
            return jsonify({
                'success': False,
                'message': '股票列表更新失败，使用后备数据',
                'stocks_count': len(ALL_STOCKS)
            })
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/analyze', methods=['GET'])
def analyze_stock():
    """分析单只股票"""
    stock_code = request.args.get('code', '').strip()
    period = request.args.get('period', '120')
    
    if not stock_code:
        return jsonify({
            'success': False,
            'error': '请提供股票代码参数: code=sh600519'
        }), 400
    
    try:
        period_days = int(period)
        if period_days < 30 or period_days > 500:
            return jsonify({
                'success': False,
                'error': '分析周期需在30-500天之间'
            }), 400
        
        analyzer = StockAnalyzer(stock_code, period_days)
        
        if analyzer.df.empty:
            return jsonify({
                'success': False,
                'error': f'无法获取股票 {stock_code} 的数据'
            }), 404
        
        if not analyzer.calculate_indicators():
            return jsonify({
                'success': False,
                'error': '数据不足，无法计算技术指标'
            }), 400
        
        result = analyzer.analyze()
        return jsonify(result)
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'分析过程中出错: {str(e)}'
        }), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """健康检查"""
    return jsonify({
        'status': 'healthy',
        'service': 'Stock Analysis API',
        'version': '2.0',
        'timestamp': datetime.now().isoformat(),
        'stocks_count': len(ALL_STOCKS),
        'last_update': LAST_UPDATE_TIME.isoformat() if LAST_UPDATE_TIME else None,
        'uptime': '0'  # 可以添加uptime计算
    })

# ==================== 启动应用 ====================

if __name__ == '__main__':
    print("🚀 股票分析API服务启动中...")
    
    # 初始加载股票列表
    print("📋 正在加载股票列表...")
    fetch_all_stocks()
    
    # 启动后台更新线程
    update_thread = threading.Thread(target=auto_update_stocks, daemon=True)
    update_thread.start()
    
    print("✅ 股票列表加载完成！")
    print("\n📊 可用端点:")
    print("  GET  /                 - API文档")
    print("  GET  /api/stocks       - 获取所有股票列表（支持分页和搜索）")
    print("  GET  /api/stocks/search?q=关键词 - 搜索股票")
    print("  POST /api/stocks/update - 手动更新股票列表")
    print("  GET  /api/analyze      - 分析单只股票")
    print("  GET  /api/health       - 健康检查")
    
    print("\n🔗 示例请求:")
    print("  http://localhost:5000/api/stocks")
    print("  http://localhost:5000/api/stocks?page=2&per_page=50")
    print("  http://localhost:5000/api/stocks/search?q=茅台")
    print("  http://localhost:5000/api/analyze?code=sh600519")
    
    print(f"\n📈 当前股票数量: {len(ALL_STOCKS)} 只")
    
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)