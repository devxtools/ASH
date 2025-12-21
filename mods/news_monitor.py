# mods/news_monitor.py 修复版本

import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
import aiohttp
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from collections import defaultdict
import schedule
import time
import threading
import logging
import redis

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Redis配置
redis_client = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.stock_subscriptions: Dict[str, List[str]] = defaultdict(list)
        
    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        return client_id
        
    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        # 清理订阅
        for stock_code in list(self.stock_subscriptions.keys()):
            if client_id in self.stock_subscriptions[stock_code]:
                self.stock_subscriptions[stock_code].remove(client_id)
                
    async def send_personal_message(self, message: dict, client_id: str):
        if client_id in self.active_connections:
            websocket = self.active_connections[client_id]
            try:
                await websocket.send_json(message)
            except:
                self.disconnect(client_id)
                
    async def broadcast_to_subscribers(self, stock_code: str, message: dict):
        if stock_code in self.stock_subscriptions:
            for client_id in self.stock_subscriptions[stock_code]:
                await self.send_personal_message(message, client_id)
                
    def subscribe(self, client_id: str, stock_code: str):
        if client_id in self.active_connections:
            if stock_code not in self.stock_subscriptions:
                self.stock_subscriptions[stock_code] = []
            if client_id not in self.stock_subscriptions[stock_code]:
                self.stock_subscriptions[stock_code].append(client_id)
                
    def unsubscribe(self, client_id: str, stock_code: str):
        if stock_code in self.stock_subscriptions:
            if client_id in self.stock_subscriptions[stock_code]:
                self.stock_subscriptions[stock_code].remove(client_id)

manager = ConnectionManager()

# 数据模型
class StockRequest(BaseModel):
    stock_codes: List[str]
    stock_names: Optional[List[str]] = None

class NewsItem(BaseModel):
    title: str
    content: str
    source: str
    publish_time: str
    stock_code: str
    stock_name: str
    url: str
    crawl_time: str

# WebSocket路由 - 修复后的版本
@app.websocket("/ws/news/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """WebSocket连接处理"""
    client_id = await manager.connect(websocket, client_id)
    
    try:
        # 等待客户端发送订阅信息
        data = await websocket.receive_json()
        
        if data.get("type") == "subscribe":
            stock_codes = data.get("stock_codes", [])
            
            for stock_code in stock_codes:
                manager.subscribe(client_id, stock_code)
            
            logger.info(f"客户端 {client_id} 订阅了 {stock_codes}")
            
            # 发送确认消息
            await websocket.send_json({
                "type": "connected",
                "message": f"已订阅 {len(stock_codes)} 只股票的实时新闻",
                "stock_codes": stock_codes,
                "timestamp": datetime.now().isoformat()
            })
            
            # 保持连接
            while True:
                try:
                    # 心跳检测
                    data = await websocket.receive_json(timeout=60)
                    if data.get("type") == "ping":
                        await websocket.send_json({
                            "type": "pong",
                            "timestamp": datetime.now().isoformat()
                        })
                except WebSocketDisconnect:
                    logger.info(f"客户端 {client_id} 断开连接")
                    break
                except asyncio.TimeoutError:
                    # 发送心跳检测
                    try:
                        await websocket.send_json({
                            "type": "ping",
                            "timestamp": datetime.now().isoformat()
                        })
                    except:
                        break
                except Exception as e:
                    logger.error(f"WebSocket接收错误: {e}")
                    break
                    
    except WebSocketDisconnect:
        logger.info(f"客户端 {client_id} 断开连接")
    except Exception as e:
        logger.error(f"WebSocket处理错误: {e}")
    finally:
        # 清理客户端
        manager.disconnect(client_id)

# API端点
@app.post("/api/crawl/start")
async def start_crawling(request: StockRequest, background_tasks: BackgroundTasks):
    """开始爬取指定股票的新闻"""
    try:
        if not request.stock_codes:
            raise HTTPException(status_code=400, detail="必须提供至少一个股票代码")
        
        # 这里添加你的爬取逻辑
        background_tasks.add_task(crawl_stocks_task, request.stock_codes, request.stock_names)
        
        return JSONResponse({
            "status": "success",
            "message": f"已开始爬取{len(request.stock_codes)}只股票的新闻",
            "stock_codes": request.stock_codes,
        })
        
    except Exception as e:
        logger.error(f"启动爬取失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/crawl/single")
async def crawl_single_stock(
    stock_code: str = Query(..., description="股票代码"),
    stock_name: Optional[str] = Query(None, description="股票名称")
):
    """立即爬取单只股票的新闻"""
    try:
        # 这里调用你的爬取函数
        news_items = await mock_crawl_news(stock_code, stock_name)
        
        # 推送给订阅者
        for news in news_items:
            await manager.broadcast_to_subscribers(stock_code, {
                "type": "news",
                "data": news.dict()
            })
        
        return JSONResponse({
            "status": "success",
            "stock_code": stock_code,
            "news_count": len(news_items),
        })
        
    except Exception as e:
        logger.error(f"爬取单只股票失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/test")
async def test_api():
    """测试API"""
    return JSONResponse({
        "status": "success",
        "message": "新闻监控API运行正常",
        "websocket_clients": len(manager.active_connections),
        "timestamp": datetime.now().isoformat()
    })

# 模拟爬取函数（替换为你的实际爬取逻辑）
async def mock_crawl_news(stock_code: str, stock_name: Optional[str] = None) -> List[NewsItem]:
    """模拟爬取新闻数据"""
    stock_name = stock_name or f"股票{stock_code}"
    
    news_items = []
    sources = ["东方财富", "新浪财经", "同花顺", "雪球"]
    
    for i in range(2):  # 模拟2条新闻
        news = NewsItem(
            title=f"{stock_name}最新动态({i+1})",
            content=f"这是{stock_name}({stock_code})的最新新闻内容...",
            source=sources[i % len(sources)],
            publish_time=(datetime.now() - timedelta(minutes=i*5)).strftime("%Y-%m-%d %H:%M:%S"),
            stock_code=stock_code,
            stock_name=stock_name,
            url=f"https://example.com/news/{stock_code}/{i}",
            crawl_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        news_items.append(news)
    
    return news_items

async def crawl_stocks_task(stock_codes: List[str], stock_names: Optional[List[str]] = None):
    """后台爬取任务"""
    for i, stock_code in enumerate(stock_codes):
        stock_name = stock_names[i] if stock_names and i < len(stock_names) else None
        try:
            news_items = await mock_crawl_news(stock_code, stock_name)
            
            for news in news_items:
                await manager.broadcast_to_subscribers(stock_code, {
                    "type": "news",
                    "data": news.dict()
                })
                
                logger.info(f"推送新闻: {stock_code} - {news.title}")
                
        except Exception as e:
            logger.error(f"爬取{stock_code}失败: {e}")

# 启动函数
def start_monitor():
    """启动新闻监控"""
    logger.info("启动新闻监控服务...")
    
    # 这里可以添加定时任务
    def run_scheduler():
        schedule.every(1).minute.do(lambda: asyncio.create_task(check_news()))
        
        while True:
            schedule.run_pending()
            time.sleep(1)
    
    # 启动调度器线程
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    
    logger.info("新闻监控服务已启动")

async def check_news():
    """定时检查新闻"""
    try:
        # 获取所有已订阅的股票
        subscribed_stocks = list(manager.stock_subscriptions.keys())
        
        if subscribed_stocks:
            logger.info(f"定时检查 {len(subscribed_stocks)} 只股票的新闻")
            
            # 这里调用实际的爬取逻辑
            for stock_code in subscribed_stocks[:5]:  # 限制每次检查5只
                news_items = await mock_crawl_news(stock_code)
                
                for news in news_items:
                    await manager.broadcast_to_subscribers(stock_code, {
                        "type": "news",
                        "data": news.dict()
                    })
                    
    except Exception as e:
        logger.error(f"定时检查失败: {e}")

# 如果直接运行此文件
# if __name__ == "__main__":
#     import uvicorn
    
#     start_monitor()
    
#     uvicorn.run(
#         "news_monitor:app",
#         host="0.0.0.0",
#         port=8001,
#         reload=True
#     )