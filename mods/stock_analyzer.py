# stock_analyzer.py
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from Ashare.Ashare import get_price, get_price_min_tx
import warnings
import re
from typing import Dict, List, Optional, Any

warnings.filterwarnings('ignore')

class StockAnalyzer:
    """
    股票分析核心类
    包含所有分析逻辑，可以在任何地方调用
    """
    
    def __init__(self, stock_code: str, period_days: int = 120):
        """
        初始化分析器
        
        Args:
            stock_code: 股票代码 (如 'sh600519')
            period_days: 分析的历史数据天数
        """
        self.stock_code = stock_code
        self.period_days = period_days
        self.df = None
        self.df_min = None
        self._fetch_data()
    
    def _fetch_data(self) -> None:
        """获取基础数据"""
        try:
            self.df = get_price(self.stock_code, frequency='1d', count=self.period_days)
            if not self.df.empty:
                self.df['returns'] = self.df['close'].pct_change()
        except Exception as e:
            print(f"获取数据失败 {self.stock_code}: {e}")
            self.df = pd.DataFrame()
    
    def calculate_indicators(self) -> bool:
        """计算技术指标"""
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
        
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        # 布林带
        df['BB_middle'] = df['close'].rolling(20).mean()
        bb_std = df['close'].rolling(20).std()
        df['BB_upper'] = df['BB_middle'] + (bb_std * 2)
        df['BB_lower'] = df['BB_middle'] - (bb_std * 2)
        df['BB_position'] = (df['close'] - df['BB_lower']) / (df['BB_upper'] - df['BB_lower'])
        
        # KD指标
        low_14 = df['low'].rolling(14).min()
        high_14 = df['high'].rolling(14).max()
        df['%K'] = 100 * ((df['close'] - low_14) / (high_14 - low_14))
        df['%D'] = df['%K'].rolling(3).mean()
        
        # 成交量
        df['volume_ma5'] = df['volume'].rolling(5).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma5']
        
        self.df = df
        return True
    
    def analyze(self) -> Dict[str, Any]:
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
    
    def _analyze_signals(self, latest: pd.Series, prev: pd.Series) -> Dict[str, Any]:
        """分析技术信号"""
        signals = {
            'trend': {'reasons': [], 'score': 0},
            'momentum': {'reasons': [], 'score': 0},
            'volume': {'reasons': [], 'score': 0},
            'oscillators': {'reasons': [], 'score': 0},
            'patterns': {'patterns': [], 'score': 0}
        }
        
        # 趋势分析
        if latest['close'] > latest.get('MA20', 0):
            signals['trend']['reasons'].append("价格站上20日线")
            signals['trend']['score'] += 15
        
        if latest.get('MA5', 0) > latest.get('MA10', 0) > latest.get('MA20', 0):
            signals['trend']['reasons'].append("均线多头排列")
            signals['trend']['score'] += 10
        
        # 动量分析
        rsi = latest.get('RSI', 50)
        if 30 < rsi < 70:
            signals['momentum']['reasons'].append("RSI处于健康区间")
            signals['momentum']['score'] += 10
        elif rsi < 30:
            signals['momentum']['reasons'].append("RSI超卖")
            signals['momentum']['score'] += 20
        
        macd = latest.get('MACD', 0)
        macd_signal = latest.get('MACD_signal', 0)
        prev_macd = prev.get('MACD', 0)
        prev_signal = prev.get('MACD_signal', 0)
        
        if macd > macd_signal and prev_macd <= prev_signal:
            signals['momentum']['reasons'].append("MACD金叉")
            signals['momentum']['score'] += 15
        
        # 摆动指标
        k_value = latest.get('%K', 50)
        if k_value < 20:
            signals['oscillators']['reasons'].append("K值超卖")
            signals['oscillators']['score'] += 15
        
        bb_position = latest.get('BB_position', 0.5)
        if bb_position < 0.3:
            signals['oscillators']['reasons'].append("接近布林带下轨")
            signals['oscillators']['score'] += 10
        
        # 成交量
        volume_ratio = latest.get('volume_ratio', 1)
        if volume_ratio > 1.5:
            signals['volume']['reasons'].append("成交量放大")
            signals['volume']['score'] += 15
        
        if latest['close'] > prev['close'] and latest['volume'] > prev['volume']:
            signals['volume']['reasons'].append("量价齐升")
            signals['volume']['score'] += 10
        
        return signals
    
    def _calculate_confidence(self, signals: Dict[str, Any]) -> float:
        """计算信心分数"""
        total_score = 0
        max_score = 100
        
        for category in signals.values():
            if 'score' in category:
                total_score += min(category['score'], 30)
        
        return min(total_score, 100)
    
    def _generate_result(self, latest: pd.Series, prev: pd.Series, 
                        signals: Dict[str, Any], confidence: float) -> Dict[str, Any]:
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
            'stock_code': self.stock_code,
            'timestamp': datetime.now().isoformat(),
            'current_price': round(latest['close'], 2),
            'price_change': round(price_change, 2),
            'volume': int(latest['volume']),
            'indicators': {
                'MA5': round(latest.get('MA5', 0), 2),
                'MA10': round(latest.get('MA10', 0), 2),
                'MA20': round(latest.get('MA20', 0), 2),
                'RSI': round(latest.get('RSI', 50), 2),
                'MACD': round(latest.get('MACD', 0), 4),
                'KD_K': round(latest.get('%K', 50), 2),
                'KD_D': round(latest.get('%D', 50), 2),
                'BB_position': round(latest.get('BB_position', 0.5), 3)
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
    
    def _calculate_risk_metrics(self) -> Dict[str, Any]:
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
    
    def _empty_result(self) -> Dict[str, Any]:
        """空结果"""
        return {
            'stock_code': self.stock_code,
            'error': '数据不足或获取失败',
            'timestamp': datetime.now().isoformat(),
            'success': False
        }
    
    def get_realtime_data(self, minutes: int = 60, frequency: str = '1min') -> Dict[str, Any]:
        """
        获取实时数据
        
        Args:
            minutes: 获取多少分钟的数据
            frequency: 频率 (1min, 5min, 15min, 30min, 60min)
        
        Returns:
            实时数据字典
        """
        try:
            df_min = get_price_min_tx(
                code=self.stock_code,
                frequency=frequency,
                count=minutes
            )
            
            if df_min.empty:
                return {'error': '无法获取实时数据'}
            
            data_delay = (datetime.now() - df_min.index[-1].replace(tzinfo=None)).total_seconds()
            
            # 转换为列表格式
            kline_data = []
            for idx, row in df_min.iterrows():
                kline_data.append({
                    'timestamp': idx.strftime('%Y-%m-%d %H:%M:%S'),
                    'time_str': idx.strftime('%H:%M'),
                    'open': round(row['open'], 2),
                    'close': round(row['close'], 2),
                    'high': round(row['high'], 2),
                    'low': round(row['low'], 2),
                    'volume': int(row['volume']),
                    'change': round(row['close'] - row['open'], 2),
                    'change_percent': round((row['close'] - row['open']) / row['open'] * 100, 2) if row['open'] > 0 else 0
                })
            
            return {
                'frequency': frequency,
                'data_count': len(kline_data),
                'data_delay_seconds': round(data_delay, 1),
                'latest_time': kline_data[-1]['timestamp'] if kline_data else None,
                'kline_data': kline_data,
                'summary': self._calculate_realtime_summary(kline_data)
            }
            
        except Exception as e:
            return {'error': str(e)}
    
    def _calculate_realtime_summary(self, kline_data: List[Dict]) -> Dict[str, Any]:
        """计算实时数据摘要"""
        if not kline_data:
            return {}
        
        closes = [bar['close'] for bar in kline_data]
        volumes = [bar['volume'] for bar in kline_data]
        latest = kline_data[-1]
        
        summary = {
            'latest_price': latest['close'],
            'latest_change': latest['change'],
            'latest_change_percent': latest['change_percent'],
            'latest_volume': latest['volume'],
            'high': max(closes) if closes else 0,
            'low': min(closes) if closes else 0,
            'avg_price': round(sum(closes) / len(closes), 2) if closes else 0,
            'total_volume': sum(volumes),
            'avg_volume': round(sum(volumes) / len(volumes), 2) if volumes else 0
        }
        
        # 判断短期趋势
        if len(closes) >= 3:
            if closes[-1] > closes[-2] > closes[-3]:
                summary['short_trend'] = '上涨'
            elif closes[-1] < closes[-2] < closes[-3]:
                summary['short_trend'] = '下跌'
            else:
                summary['short_trend'] = '震荡'
        
        return summary
    
    def analyze_realtime(self, minutes: int = 30) -> Dict[str, Any]:
        """
        实时分析
        
        Args:
            minutes: 分析多少分钟的实时数据
        
        Returns:
            实时分析结果
        """
        # 获取实时数据
        realtime_data = self.get_realtime_data(minutes=minutes, frequency='5min')
        
        if 'error' in realtime_data:
            return {'error': realtime_data['error']}
        
        # 获取日线分析
        day_analysis = self.analyze()
        
        # 结合实时和日线分析
        combined_analysis = {
            'stock_code': self.stock_code,
            'timestamp': datetime.now().isoformat(),
            'realtime_data': realtime_data,
            'day_analysis': day_analysis if day_analysis.get('success') else None,
            'signals': self._generate_realtime_signals(realtime_data, day_analysis)
        }
        
        return combined_analysis
    
    def _generate_realtime_signals(self, realtime_data: Dict, day_analysis: Dict) -> Dict[str, Any]:
        """生成实时交易信号"""
        signals = {
            'buy_signals': [],
            'sell_signals': [],
            'warning_signals': [],
            'overall_signal': 'HOLD'
        }
        
        if 'error' in realtime_data or not realtime_data.get('kline_data'):
            return signals
        
        kline_data = realtime_data['kline_data']
        
        if len(kline_data) < 3:
            return signals
        
        latest = kline_data[-1]
        prev = kline_data[-2]
        
        # 简单的实时信号
        if latest['volume'] > prev['volume'] * 1.5 and latest['change_percent'] > 0:
            signals['buy_signals'].append("放量上涨")
        
        if latest['volume'] > prev['volume'] * 1.5 and latest['change_percent'] < 0:
            signals['sell_signals'].append("放量下跌")
        
        # 日线信号的影响
        if day_analysis.get('success'):
            day_action = day_analysis['analysis'].get('action', 'HOLD')
            if day_action == 'BUY' and len(signals['buy_signals']) > 0:
                signals['overall_signal'] = 'BUY'
            elif day_action == 'SELL' and len(signals['sell_signals']) > 0:
                signals['overall_signal'] = 'SELL'
        
        return signals


# ==================== 批量分析工具 ====================

class BatchStockAnalyzer:
    """批量股票分析器"""
    
    def __init__(self, stock_list: List[str], period_days: int = 120):
        """
        初始化批量分析器
        
        Args:
            stock_list: 股票代码列表
            period_days: 分析周期
        """
        self.stock_list = stock_list
        self.period_days = period_days
        self.results = []
    
    def analyze_all(self, min_confidence: float = 80.0) -> List[Dict[str, Any]]:
        """
        分析所有股票
        
        Args:
            min_confidence: 最小信心分数
        
        Returns:
            分析结果列表
        """
        print(f"🔍 开始批量分析 {len(self.stock_list)} 只股票...")
        
        high_confidence_results = []
        
        for i, stock_code in enumerate(self.stock_list, 1):
            # 显示进度
            if i % 10 == 0:
                print(f"  进度: {i}/{len(self.stock_list)}")
            
            try:
                analyzer = StockAnalyzer(stock_code, self.period_days)
                
                if analyzer.df.empty or len(analyzer.df) < 30:
                    continue
                
                if not analyzer.calculate_indicators():
                    continue
                
                result = analyzer.analyze()
                
                if result.get('success') and result['analysis']['confidence_score'] >= min_confidence:
                    high_confidence_results.append(result)
                    
            except Exception as e:
                print(f"分析 {stock_code} 失败: {e}")
                continue
        
        # 按信心分数排序
        high_confidence_results.sort(key=lambda x: x['analysis']['confidence_score'], reverse=True)
        self.results = high_confidence_results
        
        print(f"✅ 分析完成！找到 {len(high_confidence_results)} 只信心分数≥{min_confidence}的股票")
        
        return high_confidence_results
    
    def get_top_stocks(self, top_n: int = 10) -> List[Dict[str, Any]]:
        """
        获取前N名股票
        
        Args:
            top_n: 返回前几名
        
        Returns:
            前N名股票列表
        """
        if not self.results:
            self.analyze_all()
        
        return self.results[:top_n]
    
    def analyze_with_realtime(self, stock_codes: List[str] = None, 
                            realtime_minutes: int = 30) -> List[Dict[str, Any]]:
        """
        结合实时数据分析
        
        Args:
            stock_codes: 股票代码列表（默认使用全部）
            realtime_minutes: 实时数据分钟数
        
        Returns:
            结合实时数据的分析结果
        """
        if stock_codes is None:
            stock_codes = self.stock_list
        
        combined_results = []
        
        for stock_code in stock_codes[:50]:  # 限制数量
            try:
                analyzer = StockAnalyzer(stock_code, self.period_days)
                
                # 实时分析
                realtime_result = analyzer.analyze_realtime(minutes=realtime_minutes)
                
                # 日线分析
                if analyzer.df.empty or len(analyzer.df) < 30:
                    continue
                
                if not analyzer.calculate_indicators():
                    continue
                
                day_result = analyzer.analyze()
                
                if day_result.get('success'):
                    combined_result = {
                        'stock_code': stock_code,
                        'realtime_analysis': realtime_result,
                        'day_analysis': day_result,
                        'combined_confidence': self._calculate_combined_confidence(realtime_result, day_result)
                    }
                    combined_results.append(combined_result)
                    
            except Exception as e:
                print(f"实时分析 {stock_code} 失败: {e}")
                continue
        
        return combined_results
    
    def _calculate_combined_confidence(self, realtime_result: Dict, day_result: Dict) -> float:
        """计算综合信心分数"""
        day_confidence = day_result.get('analysis', {}).get('confidence_score', 0)
        
        # 实时数据加分（如果有积极信号）
        realtime_signals = realtime_result.get('signals', {})
        realtime_bonus = len(realtime_signals.get('buy_signals', [])) * 5
        realtime_bonus -= len(realtime_signals.get('sell_signals', [])) * 3
        
        combined = day_confidence + realtime_bonus
        return max(0, min(combined, 100))


# ==================== 工具函数 ====================

def get_2min_data(stock_code: str, total_minutes: int = 60) -> Dict[str, Any]:
    """
    获取2分钟数据（通过1分钟数据计算）
    
    Args:
        stock_code: 股票代码
        total_minutes: 总分钟数
    
    Returns:
        2分钟数据
    """
    try:
        # 获取1分钟数据
        need_1min_count = total_minutes * 2 + 10
        df_1min = get_price_min_tx(
            code=stock_code,
            frequency='1min',
            count=need_1min_count
        )
        
        if df_1min.empty:
            return {'error': '无法获取1分钟数据', 'data': []}
        
        # 聚合成2分钟数据
        two_min_data = []
        df_sorted = df_1min.sort_index()
        
        for i in range(0, len(df_sorted) - 1, 2):
            if i + 1 >= len(df_sorted):
                break
            
            bar1 = df_sorted.iloc[i]
            bar2 = df_sorted.iloc[i + 1]
            
            two_min_bar = {
                'timestamp': bar2.name.strftime('%Y-%m-%d %H:%M:%S'),
                'time_str': bar2.name.strftime('%H:%M'),
                'open': round(float(bar1['open']), 2),
                'close': round(float(bar2['close']), 2),
                'high': round(max(float(bar1['high']), float(bar2['high'])), 2),
                'low': round(min(float(bar1['low']), float(bar2['low'])), 2),
                'volume': int(bar1['volume'] + bar2['volume'])
            }
            
            two_min_data.append(two_min_bar)
        
        # 只保留最新的数据
        recent_data = two_min_data[-min(len(two_min_data), total_minutes // 2):]
        
        return {
            'frequency': '2min',
            'data_count': len(recent_data),
            'time_period_minutes': len(recent_data) * 2,
            'data_delay_seconds': round((datetime.now() - df_sorted.index[-1].replace(tzinfo=None)).total_seconds(), 1),
            'kline_data': recent_data
        }
        
    except Exception as e:
        return {'error': str(e), 'data': []}

def analyze_stock_simple(stock_code: str, period_days: int = 120) -> Dict[str, Any]:
    """
    简单股票分析（单函数版本）
    
    Args:
        stock_code: 股票代码
        period_days: 分析周期
    
    Returns:
        分析结果
    """
    analyzer = StockAnalyzer(stock_code, period_days)
    
    if analyzer.df.empty or len(analyzer.df) < 30:
        return analyzer._empty_result()
    
    if not analyzer.calculate_indicators():
        return analyzer._empty_result()
    
    return analyzer.analyze()

def batch_analyze_stocks(stock_list: List[str], min_confidence: float = 80.0) -> List[Dict[str, Any]]:
    """
    批量分析股票（单函数版本）
    
    Args:
        stock_list: 股票代码列表
        min_confidence: 最小信心分数
    
    Returns:
        分析结果列表
    """
    batch_analyzer = BatchStockAnalyzer(stock_list)
    return batch_analyzer.analyze_all(min_confidence)