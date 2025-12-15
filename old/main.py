from flask import Flask, jsonify, request
from Ashare import get_price,get_price_day_tx,requests
from StockAnalysis import analyze_stock 
import re

app = Flask(__name__)

# 替换成你的必盈 licence
BIYING_LICENCE = "biyinglicence"

# 全局变量存储所有股票
ALL_STOCKS = []

def load_all_stocks():
    global ALL_STOCKS
    try:
        ak_url = f"https://api.biyingapi.com/hslt/list/{BIYING_LICENCE}"
        resp = requests.get(ak_url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        # 使用正则过滤掉名称中包含 ST 或 *ST 的股票
        pattern = re.compile(r"\*?ST", re.IGNORECASE)

        ALL_STOCKS = []
        for stock in data:
            if pattern.search(stock["mc"]):
                continue  # 跳过 ST/*ST
            code = stock["jys"] + stock["dm"]  # 原始 code，例如 SZ000001.SZ
            # 去掉 .后缀并转小写
            code = code.split('.')[0].lower()
            ALL_STOCKS.append({
                "code": code,
                "name": stock["mc"],
            })

        print(f"已加载 {len(ALL_STOCKS)} 支股票")
    except Exception as e:
        print("加载股票列表失败:", str(e))
        ALL_STOCKS = []


# ------------------------
# 返回全市场股票列表
# ------------------------
@app.route("/api/stocks", methods=["GET"])
def get_all_stocks():
    global ALL_STOCKS
    if not ALL_STOCKS:
        return jsonify({"success": False, "error": "股票列表为空，请先加载"}), 500
    return jsonify({"success": True, "data": ALL_STOCKS})

#股票详情
fields = [
    'date', 'open', 'high', 'low', 'close', 'volume', 'amount',
    'pct_change', 'change', 'pct_change_close',
    'ma5', 'ma10', 'ma20', 
    'vol_change', 'amount_change',
    'limit_up', 'limit_diff', 'near_limit',
    'continuous_limit',
    # 新增指标
    'rsi14', 'macd', 'macd_signal', 'macd_hist',
    'boll_upper', 'boll_middle', 'boll_lower', 'boll_width',
    'atr14',
    'turnover_rate', 'float_market_cap',
    'prev1_pct_change', 'prev2_pct_change', 'prev3_pct_change',
    'prev_vol_ratio', 'sector_strength',
    'price_std5', 'price_std10', 'max_drawdown5', 'max_drawdown10'
]
@app.route("/api/stock_detail", methods=["GET"])
def get_stock_detail():
    """
    获取指定股票的实时详情数据（日线或分钟线）
    请求参数：
      code: 股票代码，例如 sh600673
      frequency: 数据周期，默认 '1d'
      count: 获取条数，默认 5
    返回：
      JSON，包含所有字段
    """
    try:
        # 获取请求参数
        code = request.args.get("code")
        frequency = request.args.get("frequency", "1d")
        count = int(request.args.get("count", 60))

        if not code:
            return jsonify({"success": False, "error": "请提供股票代码参数 code"}), 400

        # 获取股票行情
        df = get_price(code, frequency=frequency, count=count, fields=fields)

        # 将 DataFrame 转为 JSON（按行）
        data = df.to_dict(orient="records")

        return jsonify({
            "success": True,
            "code": code,
            "frequency": frequency,
            "count": count,
            "data": data
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

# 股票分析
@app.route("/api/stock_analysis", methods=["GET"])
def stock_analysis():
    """
    分析指定单只股票，返回技术指标、连板信息、高胜率信号和历史胜率
    请求参数：
        code: 股票代码，例如 sh600673
        count: 可选，获取日线条数，默认 60
    返回：
        JSON 格式：
        {
            "success": True,
            "data": [...],       # 股票指标历史记录
            "backtest": {...}    # 历史连板/胜率统计
        }
    """
    code = request.args.get("code")
    count = int(request.args.get("count", 60))

    if not code:
        return jsonify({"success": False, "error": "请提供股票代码参数 code"}), 400

    code = code.strip().lower()
    all_data = []
    backtest_data = {}

    # 获取股票数据
    df = get_price(code, frequency='1d', count=count, fields=fields)
    # 分析股票
    df, summary = analyze_stock(df)
    data = df.to_dict(orient="records")

    return jsonify({"success": True, "data": data, "backtest": backtest_data})


if __name__ == "__main__":
    # load_all_stocks()
    app.run(host="0.0.0.0", port=8888, debug=True)
