# stock_api.py
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from Ashare.Ashare import get_price, requests, get_price_min_tx
import warnings
import json
import threading
import time
from collections import deque
import re
import os

warnings.filterwarnings('ignore')

app = Flask(__name__)
CORS(app)  # 允许跨域请求


# ==================== 全局配置 ====================
ALL_STOCKS = []  # 全局存储所有股票列表
LAST_UPDATE_TIME = None
UPDATE_INTERVAL = 24 * 3600  # 24小时更新一次（秒）

# 分析结果存储
ANALYSIS_RESULTS = []  # 存储所有股票分析结果
TOP_STOCKS = []  # 存储成功率最高的10支股票
LAST_ANALYSIS_TIME = None
ANALYSIS_IN_PROGRESS = False  # 防止重复分析

# 创建数据目录
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)
# ==================== 股票数据管理 ====================

def fetch_all_stocks():
    """
    从API获取所有股票列表
    注意：这是一个示例URL，实际使用时需要确认正确的API
    """
    global ALL_STOCKS, LAST_UPDATE_TIME
    
    try:
        print("🔄 开始更新股票列表...")
        
        stock_url = "https://api.biyingapi.com/hslt/list/biyinglicence"
        resp = requests.get(stock_url, timeout=10)
        resp.raise_for_status()
        stocks_data = resp.json()
        # 使用正则过滤掉名称中包含 ST 或 *ST 的股票
        pattern = re.compile(r"\*?ST", re.IGNORECASE)
        filtered_stocks = []
        for stock in stocks_data:
            if pattern.search(stock["mc"]):
                continue  # 跳过 ST/*ST
            code = stock["jys"] + stock["dm"]  # 原始 code，例如 SZ000001.SZ
            # 去掉 .后缀并转小写
            code = code.split('.')[0].lower()
            filtered_stocks.append({
                "code": code,
                "name": stock["mc"],
            })
        
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
    print("🔄 股票列表需要更新...")
    # 如果列表为空或需要更新
    if not ALL_STOCKS or (LAST_UPDATE_TIME and 
                         (datetime.now() - LAST_UPDATE_TIME).total_seconds() >= UPDATE_INTERVAL):
        print("🔄 股票列表需要更新...")
        fetch_all_stocks()
    
    return ALL_STOCKS


# 缓存系统（减少重复计算）
class CacheManager:
    def __init__(self, ttl=300):  # 默认5分钟缓存
        self.cache = {}
        self.ttl = ttl
        self.lock = threading.Lock()
    
    def get(self, key):
        with self.lock:
            if key in self.cache:
                data, timestamp = self.cache[key]
                if time.time() - timestamp < self.ttl:
                    return data
                else:
                    del self.cache[key]
        return None
    
    def set(self, key, value):
        with self.lock:
            self.cache[key] = (value, time.time())

cache = CacheManager()

class StockSignalAnalyzer:
    """股票信号分析器（优化版）"""
    
    def __init__(self, stock_code, period_days=120):
        self.stock_code = stock_code
        self.period_days = period_days
        self.df = None
        self.signals = {}
        self.confidence_score = 0
        self._fetch_data()
    
    def _fetch_data(self):
        """获取股票数据"""
        cache_key = f"data_{self.stock_code}_{self.period_days}"
        cached_data = cache.get(cache_key)
        
        if cached_data is not None:
            self.df = cached_data
            return
        
        try:
            self.df = get_price(
                self.stock_code,
                frequency='1d',
                count=self.period_days
            )
            
            if not self.df.empty:
                # 计算基本指标
                self.df['returns'] = self.df['close'].pct_change()
                self.df['log_returns'] = np.log(self.df['close'] / self.df['close'].shift(1))
                cache.set(cache_key, self.df)
                
        except Exception as e:
            print(f"数据获取失败 {self.stock_code}: {e}")
            self.df = pd.DataFrame()
    
    def calculate_all_indicators(self):
        """计算所有技术指标"""
        if self.df.empty or len(self.df) < 30:
            return False
        
        df = self.df.copy()
        
        # 移动平均线
        for window in [5, 10, 20, 30, 60]:
            df[f'MA{window}'] = df['close'].rolling(window=window).mean()
        
        # MACD
        exp1 = df['close'].ewm(span=12, adjust=False).mean()
        exp2 = df['close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = exp1 - exp2
        df['MACD_signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        df['MACD_hist'] = df['MACD'] - df['MACD_signal']
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # 布林带
        df['BB_middle'] = df['close'].rolling(window=20).mean()
        bb_std = df['close'].rolling(window=20).std()
        df['BB_upper'] = df['BB_middle'] + (bb_std * 2)
        df['BB_lower'] = df['BB_middle'] - (bb_std * 2)
        df['BB_position'] = (df['close'] - df['BB_lower']) / (df['BB_upper'] - df['BB_lower'])
        
        # 成交量
        df['volume_ma5'] = df['volume'].rolling(window=5).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma5']
        
        # KD指标
        low_14 = df['low'].rolling(window=14).min()
        high_14 = df['high'].rolling(window=14).max()
        df['%K'] = 100 * ((df['close'] - low_14) / (high_14 - low_14))
        df['%D'] = df['%K'].rolling(window=3).mean()
        
        self.df = df
        return True
    
    def analyze(self):
        """综合分析"""
        if self.df.empty or len(self.df) < 30:
            return self._empty_result()
        
        self._analyze_signals()
        self._calculate_confidence()
        
        return self._generate_result()
    
    def _analyze_signals(self):
        """分析技术信号"""
        latest = self.df.iloc[-1]
        prev = self.df.iloc[-2]
        
        self.signals = {
            'trend': self._analyze_trend(latest, prev),
            'momentum': self._analyze_momentum(latest, prev),
            'volume': self._analyze_volume(latest, prev),
            'oscillators': self._analyze_oscillators(latest),
            'patterns': self._check_patterns()
        }
    
    def _analyze_trend(self, latest, prev):
        """趋势分析"""
        trend_score = 0
        reasons = []
        
        # 均线系统
        if latest['MA5'] > latest['MA10'] > latest['MA20']:
            trend_score += 25
            reasons.append("均线多头排列")
        
        if latest['close'] > latest['MA20']:
            trend_score += 15
            reasons.append("价格站上20日线")
        
        # 趋势强度
        ma_slope = (latest['MA5'] - self.df['MA5'].iloc[-6]) / self.df['MA5'].iloc[-6] * 100
        if ma_slope > 1:
            trend_score += 10
            reasons.append(f"短期均线上涨{ma_slope:.1f}%")
        
        return {'score': trend_score, 'reasons': reasons}
    
    def _analyze_momentum(self, latest, prev):
        """动量分析"""
        momentum_score = 0
        reasons = []
        
        # RSI
        if 30 < latest['RSI'] < 70:
            momentum_score += 10
            reasons.append("RSI处于健康区间")
        elif latest['RSI'] < 30:
            momentum_score += 20
            reasons.append("RSI超卖，反弹机会")
        
        # MACD
        if latest['MACD'] > latest['MACD_signal'] and prev['MACD'] <= prev['MACD_signal']:
            momentum_score += 25
            reasons.append("MACD金叉形成")
        elif latest['MACD'] > 0:
            momentum_score += 15
            reasons.append("MACD在零轴上方")
        
        return {'score': momentum_score, 'reasons': reasons}
    
    def _analyze_volume(self, latest, prev):
        """成交量分析"""
        volume_score = 0
        reasons = []
        
        if latest['volume_ratio'] > 1.5:
            volume_score += 20
            reasons.append("成交量放大")
        
        if latest['close'] > prev['close'] and latest['volume'] > prev['volume']:
            volume_score += 15
            reasons.append("量价齐升")
        
        if latest['volume'] > latest['volume_ma5']:
            volume_score += 10
            reasons.append("成交量高于5日均量")
        
        return {'score': volume_score, 'reasons': reasons}
    
    def _analyze_oscillators(self, latest):
        """摆动指标分析"""
        oscillator_score = 0
        reasons = []
        
        # KD指标
        if latest['%K'] < 20:
            oscillator_score += 15
            reasons.append("K值超卖")
        elif latest['%K'] > latest['%D']:
            oscillator_score += 10
            reasons.append("KD金叉状态")
        
        # 布林带位置
        if latest['BB_position'] < 0.3:
            oscillator_score += 10
            reasons.append("接近布林带下轨")
        elif latest['BB_position'] > 0.7:
            oscillator_score += 5
            reasons.append("接近布林带上轨")
        
        return {'score': oscillator_score, 'reasons': reasons}
    
    def _check_patterns(self):
        """检查价格形态"""
        patterns = []
        
        # 检查最近5天的形态
        recent = self.df.tail(5)
        
        # 锤子线
        if self._is_hammer(recent.iloc[-1]):
            patterns.append("锤子线形态")
        
        # 早晨之星
        if len(recent) >= 3 and self._is_morning_star(recent.iloc[-3], recent.iloc[-2], recent.iloc[-1]):
            patterns.append("早晨之星")
        
        return {'patterns': patterns, 'score': len(patterns) * 10}
    
    def _is_hammer(self, candle):
        """判断是否为锤子线"""
        body_size = abs(candle['close'] - candle['open'])
        lower_shadow = min(candle['close'], candle['open']) - candle['low']
        upper_shadow = candle['high'] - max(candle['close'], candle['open'])
        
        return lower_shadow > body_size * 2 and upper_shadow < body_size * 0.5
    
    def _is_morning_star(self, day1, day2, day3):
        """判断是否为早晨之星"""
        # 第一天是阴线
        day1_bearish = day1['close'] < day1['open']
        # 第二天跳空低开
        gap_down = day2['open'] < day1['close']
        # 第三天是阳线且收盘价超过第一天中点
        day3_bullish = day3['close'] > day3['open']
        recovery = day3['close'] > (day1['open'] + day1['close']) / 2
        
        return day1_bearish and gap_down and day3_bullish and recovery
    
    def _calculate_confidence(self):
        """计算综合信心分数"""
        total_score = 0
        max_possible = 100
        
        for category in self.signals.values():
            if 'score' in category:
                total_score += min(category['score'], 30)  # 每项最多30分
        
        # 添加形态分数
        if 'patterns' in self.signals:
            total_score += self.signals['patterns']['score']
        
        self.confidence_score = min(total_score, 100)
    
    def _generate_result(self):
        """生成分析结果"""
        latest = self.df.iloc[-1]
        prev = self.df.iloc[-2]
        
        price_change = ((latest['close'] - prev['close']) / prev['close'] * 100)
        
        # 收集所有理由
        all_reasons = []
        for category in self.signals.values():
            if 'reasons' in category:
                all_reasons.extend(category['reasons'])
        
        # 添加形态理由
        if 'patterns' in self.signals and self.signals['patterns']['patterns']:
            all_reasons.extend(self.signals['patterns']['patterns'])
        
        # 生成交易信号
        if self.confidence_score >= 75:
            signal = "强烈买入"
            action = "BUY"
            position = "中等仓位(30-50%)"
        elif self.confidence_score >= 60:
            signal = "买入"
            action = "BUY"
            position = "轻仓位(20-30%)"
        elif self.confidence_score >= 45:
            signal = "关注"
            action = "HOLD"
            position = "观望"
        else:
            signal = "回避"
            action = "SELL"
            position = "不建议"
        
        return {
            'stock_code': self.stock_code,
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
                'confidence_score': round(self.confidence_score, 1),
                'signal': signal,
                'action': action,
                'position_suggestion': position,
                'key_reasons': all_reasons[:5],  # 最多5个理由
                'detailed_signals': self.signals
            },
            'risk_metrics': self._calculate_risk_metrics()
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
        
        return {
            'volatility': round(volatility, 2),
            'sharpe_ratio': round(sharpe, 3),
            'max_drawdown': round(abs(max_dd), 2),
            'risk_level': '高' if volatility > 40 else '中' if volatility > 20 else '低'
        }
    
    def _empty_result(self):
        """空结果"""
        return {
            'stock_code': self.stock_code,
            'error': '数据不足或获取失败',
            'timestamp': datetime.now().isoformat()
        }

# ==================== API路由 ====================


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
        
        analyzer = StockSignalAnalyzer(stock_code, period_days)
        
        if analyzer.df.empty:
            return jsonify({
                'success': False,
                'error': f'无法获取股票 {stock_code} 的数据'
            }), 404
        
        if not analyzer.calculate_all_indicators():
            return jsonify({
                'success': False,
                'error': '数据不足，无法计算技术指标'
            }), 400
        
        result = analyzer.analyze()
        result['success'] = True
        
        return jsonify(result)
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'分析过程中出错: {str(e)}'
        }), 500

@app.route('/api/batch_analyze', methods=['POST'])
def batch_analyze():
    """批量分析多只股票"""
    try:
        data = request.get_json()
        if not data or 'stocks' not in data:
            return jsonify({
                'success': False,
                'error': '请提供stocks数组参数'
            }), 400
        
        stocks = data['stocks']
        period = data.get('period', 120)
        
        if not isinstance(stocks, list) or len(stocks) == 0:
            return jsonify({
                'success': False,
                'error': 'stocks必须是非空数组'
            }), 400
        
        if len(stocks) > 20:
            return jsonify({
                'success': False,
                'error': '单次最多分析20只股票'
            }), 400
        
        results = []
        for stock_code in stocks:
            analyzer = StockSignalAnalyzer(stock_code, period)
            if not analyzer.df.empty:
                analyzer.calculate_all_indicators()
                result = analyzer.analyze()
                if 'error' not in result:
                    results.append(result)
        
        # 按信心分数排序
        results.sort(key=lambda x: x['analysis']['confidence_score'], reverse=True)
        
        return jsonify({
            'success': True,
            'count': len(results),
            'stocks_analyzed': len(results),
            'results': results,
            'top_recommendations': results[:5] if results else []
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'批量分析出错: {str(e)}'
        }), 500

@app.route('/api/market_overview', methods=['GET'])
def market_overview():
    """市场概览 - 分析主要指数"""
    indices = [
        {'code': 'sh000001', 'name': '上证指数'},
        {'code': 'sz399001', 'name': '深证成指'},
        {'code': 'sz399006', 'name': '创业板指'},
        {'code': 'sh000016', 'name': '上证50'},
        {'code': 'sz399005', 'name': '中小板指'}
    ]
    
    results = []
    for idx in indices:
        try:
            analyzer = StockSignalAnalyzer(idx['code'], 60)
            if not analyzer.df.empty:
                analyzer.calculate_all_indicators()
                result = analyzer.analyze()
                
                if 'error' not in result:
                    results.append({
                        'name': idx['name'],
                        'code': idx['code'],
                        'price': result['current_price'],
                        'change': result['price_change'],
                        'signal': result['analysis']['signal'],
                        'confidence': result['analysis']['confidence_score']
                    })
        except:
            continue
    
    market_sentiment = 'bullish' if len([r for r in results if r['signal'] in ['买入', '强烈买入']]) > len(results)/2 else 'bearish'
    
    return jsonify({
        'success': True,
        'timestamp': datetime.now().isoformat(),
        'market_sentiment': market_sentiment,
        'indices': results,
        'summary': {
            'total_analyzed': len(results),
            'buy_signals': len([r for r in results if r['signal'] in ['买入', '强烈买入']]),
            'hold_signals': len([r for r in results if r['signal'] == '关注']),
            'sell_signals': len([r for r in results if r['signal'] == '回避'])
        }
    })

@app.route('/api/historical/<code>', methods=['GET'])
def historical_data(code):
    """获取历史数据"""
    days = request.args.get('days', '30')
    
    try:
        days = int(days)
        df = get_price(code, frequency='1d', count=days)
        
        if df.empty:
            return jsonify({
                'success': False,
                'error': '无法获取历史数据'
            }), 404
        
        # 转换为列表格式
        data = []
        for idx, row in df.iterrows():
            data.append({
                'date': idx.strftime('%Y-%m-%d'),
                'open': round(row['open'], 2),
                'close': round(row['close'], 2),
                'high': round(row['high'], 2),
                'low': round(row['low'], 2),
                'volume': int(row['volume'])
            })
        
        return jsonify({
            'success': True,
            'stock_code': code,
            'period_days': days,
            'data': data
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/health', methods=['GET'])
def health_check():
    """健康检查"""
    return jsonify({
        'status': 'healthy',
        'service': 'Stock Analysis API',
        'version': '1.0.0',
        'timestamp': datetime.now().isoformat(),
        'cache_size': len(cache.cache)
    })

@app.route('/api/supported_codes', methods=['GET'])
def supported_codes():
    """支持的股票代码格式"""
    return jsonify({
        'success': True,
        'formats': [
            'sh000001 - 上证指数',
            'sz399001 - 深证成指',
            'sh600519 - 贵州茅台',
            'sz000858 - 五粮液',
            '000001.XSHG - 上证指数(聚宽格式)',
            '399001.XSHE - 深证成指(聚宽格式)'
        ],
        'note': '支持通达信(sh/sz前缀)、聚宽(.XSHG/.XSHE后缀)格式'
    })

# ==================== 错误处理 ====================

@app.errorhandler(404)
def not_found(error):
    return jsonify({
        'success': False,
        'error': 'API端点不存在'
    }), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({
        'success': False,
        'error': '服务器内部错误'
    }), 500

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

    print("📊 可用端点:")
    print("  GET  /                 - API文档")
    print("  GET  /api/analyze      - 分析单只股票")
    print("  POST /api/batch_analyze - 批量分析")
    print("  GET  /api/market_overview - 市场概览")
    print("  GET  /api/historical/<code> - 历史数据")
    print("  GET  /api/health       - 健康检查")
    print("\n🔗 示例请求:")
    print("  http://localhost:8899/api/analyze?code=sh600519")
    print("  http://localhost:8899/api/analyze?code=sh600519&period=90")
    print(f"\n📈 当前股票数量: {len(ALL_STOCKS)} 只")
    app.run(host='0.0.0.0', port=8899, debug=True)