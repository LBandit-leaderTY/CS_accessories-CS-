#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CS2饰品价格监控工具 - 三重指标监控版本
监控指标：价格、在售数量、求购数量
基于SteamDT开放平台API (https://open.steamdt.com)
"""

import urllib.request
import urllib.parse
import urllib.error
import re
import time
import random
import json
import os
import gzip
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

# ==================== 配置区域 ====================

# SteamDT API KEY（必填）
STEAMDT_API_KEY = ''

# 饰品配置
ITEMS_TO_MONITOR = [
   {
        'name': 'M4A1-S | Guardian (Factory New)',
        'market_hash_name': 'M4A1-S | Guardian (Factory New)',
        'url': 'https://steamdt.com/cs2/M4A1-S%20%7C%20Guardian%20(Factory%20New)',
        'platform': 'YOUPIN'  # UU平台
    } 
]

# 监控设置
CHECK_INTERVAL = 10 * 60  # 10分钟（秒）

# 三重阈值配置
THRESHOLDS = {
    'price': 0.01,        # 价格波动阈值（1%）
    'sell_count': 0.03,   # 在售数量波动阈值（3%）
    'bidding_count': 0.03 # 求购数量波动阈值（3%）
}

# ==================== 飞书机器人配置 ====================
FEISHU_WEBHOOK = ''  # ← 替换为你的Webhook地址
FEISHU_SECRET = ''  # 签名密钥，用于安全校验

# 数据持久化文件
PRICE_HISTORY_FILE = 'his_price_Guardian.json'
API_STATS_FILE = 'api_Guardian.json'

# ==================== 数据模型 ====================

@dataclass
class MarketData:
    """市场数据模型"""
    price: float = 0.0           # 当前售价
    sell_count: int = 0          # 在售数量
    bidding_count: int = 0       # 求购数量
    bidding_price: float = 0.0   # 求购价（备用）
    platform: str = ''           # 平台名称
    update_time: int = 0         # 更新时间戳

    def is_valid(self) -> bool:
        """检查数据是否有效"""
        return self.price > 0 and (self.sell_count > 0 or self.bidding_count > 0)


@dataclass
class DataChange:
    """数据变动模型"""
    has_change: bool = False
    price_change_pct: float = 0.0
    sell_count_change_pct: float = 0.0
    bidding_count_change_pct: float = 0.0
    price_direction: str = ''
    sell_count_direction: str = ''
    bidding_count_direction: str = ''


# ==================== 飞书机器人通知类 ====================

import base64
import hashlib
import hmac

class FeishuNotifier:
    """飞书群机器人推送封装"""
    
    def __init__(self, webhook_url: str, secret: str = None):
        self.webhook = webhook_url
        self.secret = secret
        self.enabled = bool(webhook_url and 'hook/' in webhook_url)
    
    def _gen_sign(self, timestamp: int) -> str:
        """生成签名（如开启了安全校验）"""
        if not self.secret:
            return None
        
        string_to_sign = f"{timestamp}\n{self.secret}"
        hmac_code = hmac.new(
            self.secret.encode('utf-8'),
            string_to_sign.encode('utf-8'),
            digestmod=hashlib.sha256
        ).digest()
        sign = base64.b64encode(hmac_code).decode('utf-8')
        return sign
    
    def send_text(self, text: str) -> bool:
        """发送纯文本"""
        if not self.enabled:
            print('[Feishu] 未启用或配置无效')
            return False
        
        timestamp = int(time.time())
        sign = self._gen_sign(timestamp)
        
        data = {
            "timestamp": timestamp,
            "sign": sign,
            "msg_type": "text",
            "content": {
                "text": text
            }
        }
        # 清理None值
        data = {k: v for k, v in data.items() if v is not None}
        
        return self._post(data)
    
    def send_markdown(self, title: str, content: str) -> bool:
        """
        发送Markdown格式（推荐，支持标题、加粗、颜色）
        """
        if not self.enabled:
            return False
        
        timestamp = int(time.time())
        sign = self._gen_sign(timestamp)
        
        data = {
            "timestamp": timestamp,
            "sign": sign,
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": title
                    },
                    "template": "red"  # 颜色：blue、green、orange、red、grey
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": content
                        }
                    }
                ]
            }
        }
        if not sign:
            del data['sign']
            del data['timestamp']
        
        return self._post(data)
    
    def _post(self, data: dict) -> bool:
        """底层POST请求"""
        try:
            resp = requests.post(
                self.webhook,
                json=data,
                timeout=10,
                headers={'Content-Type': 'application/json'}
            )
            result = resp.json()
            
            if result.get('code') == 0:
                print('✅ 飞书推送成功')
                return True
            else:
                print(f'❌ 飞书API错误: {result.get("msg")}')
                return False
                
        except Exception as e:
            print(f'❌ 飞书推送异常: {e}')
            return False


# ==================== SteamDT API 客户端 ====================

class SteamDTAPIClient:
    """SteamDT开放平台API客户端"""

    BASE_URL = 'https://open.steamdt.com'

    ENDPOINTS = {
        'price_single': '/open/cs2/v1/price/single',
        'price_batch': '/open/cs2/v1/price/batch',
    }

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.stats = self._load_stats()

    def _load_stats(self) -> Dict:
        if os.path.exists(API_STATS_FILE):
            try:
                with open(API_STATS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {'calls': [], 'errors': []}

    def _save_stats(self):
        with open(API_STATS_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.stats, f, ensure_ascii=False, indent=2)

    def clean_old_api_calls(self):
        """清理两天前的API调用记录"""
        cutoff_time = datetime.now() - timedelta(days=2)
        cutoff_str = cutoff_time.isoformat()
        
        original_count = len(self.stats.get('calls', []))
        self.stats['calls'] = [
            call for call in self.stats.get('calls', [])
            if call.get('time', '') > cutoff_str
        ]
        cleaned_count = original_count - len(self.stats['calls'])
        
        if cleaned_count > 0:
            self._save_stats()
            print(f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] 清理了 {cleaned_count} 条两天前的API调用记录')

    def _make_request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """发起API请求"""
        if not self.api_key:
            return None

        url = f'{self.BASE_URL}{endpoint}'
        if params:
            query_string = urllib.parse.urlencode(params)
            url = f'{url}?{query_string}'

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip, deflate',
            'User-Agent': 'SteamDT-PriceTracker/2.0',
        }

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                content = response.read()
                if response.info().get('Content-Encoding') == 'gzip':
                    content = gzip.decompress(content)

                result = json.loads(content.decode('utf-8'))

                self.stats['calls'].append({
                    'time': datetime.now().isoformat(),
                    'endpoint': endpoint,
                    'success': result.get('success', False)
                })
                self._save_stats()

                if result.get('success'):
                    return result.get('data')
                else:
                    error_msg = result.get('errorMsg', 'Unknown error')
                    print(f'[API] 请求失败: {error_msg}')
                    return None

        except Exception as e:
            print(f'[API] 请求异常: {e}')
            return None

    def get_market_data(self, market_hash_name: str, platform: str = None) -> Optional[MarketData]:
        """
        获取完整市场数据（价格+数量）
        """
        params = {'marketHashName': market_hash_name}
        if platform:
            params['platform'] = platform

        data = self._make_request(self.ENDPOINTS['price_single'], params)

        if data and isinstance(data, list) and len(data) > 0:
            target_data = None
            if platform:
                for item in data:
                    if item.get('platform') == platform:
                        target_data = item
                        break

            if not target_data:
                target_data = data[0]

            return MarketData(
                price=float(target_data.get('sellPrice', 0)),
                sell_count=int(target_data.get('sellCount', 0)),
                bidding_count=int(target_data.get('biddingCount', 0)),
                bidding_price=float(target_data.get('biddingPrice', 0)),
                platform=target_data.get('platform', ''),
                update_time=int(target_data.get('updateTime', 0))
            )
        return None


# ==================== 价格监控核心类 ====================

class PriceTracker:
    """三重指标价格监控主类"""

    def __init__(self):
        self.api_client = SteamDTAPIClient(STEAMDT_API_KEY)
        self.history = self._load_history()
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15',
        ]
        # 初始化飞书通知器
        self.feishu = FeishuNotifier(FEISHU_WEBHOOK, FEISHU_SECRET)

    def _load_history(self) -> Dict:
        """加载历史数据"""
        if os.path.exists(PRICE_HISTORY_FILE):
            try:
                with open(PRICE_HISTORY_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def _save_history(self):
        """保存历史数据"""
        with open(PRICE_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.history, f, ensure_ascii=False, indent=2)

    def clean_old_history(self):
        """清理两天前的历史数据记录"""
        cutoff_time = datetime.now() - timedelta(days=2)
        cutoff_str = cutoff_time.strftime('%Y-%m-%d %H:%M:%S')
        
        cleaned_count = 0
        for item_name, item_data in self.history.items():
            original_count = len(item_data.get('records', []))
            item_data['records'] = [
                record for record in item_data.get('records', [])
                if record.get('time', '') > cutoff_str
            ]
            cleaned_count += original_count - len(item_data['records'])
        
        if cleaned_count > 0:
            self._save_history()
            print(f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] 清理了 {cleaned_count} 条两天前的历史数据')

    def get_market_data_from_web(self, item: Dict) -> Optional[MarketData]:
        """网页爬取备用方案"""
        url = item.get('url')
        if not url:
            return None

        try:
            headers = {
                'User-Agent': random.choice(self.user_agents),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
            }

            time.sleep(random.uniform(1, 2))

            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as response:
                content = response.read()
                if response.info().get('Content-Encoding') == 'gzip':
                    html = gzip.decompress(content).decode('utf-8', errors='ignore')
                else:
                    html = content.decode('utf-8', errors='ignore')

            price = 0.0
            price_patterns = [
                r'[全息|Holo].*?￥(\\d+\\.?\\d*)',
                r'"currentPrice":\s*(\d+\.?\d*)',
                r'￥(\d+\.\d{2})',
            ]
            for pattern in price_patterns:
                matches = re.findall(pattern, html, re.IGNORECASE | re.DOTALL)
                if matches:
                    try:
                        price = float(matches[0])
                        if 0.01 < price < 100000:
                            break
                    except:
                        pass

            return MarketData(price=price, sell_count=0, bidding_count=0)

        except Exception as e:
            print(f'[Web] 获取失败: {e}')
            return None

    def get_market_data(self, item: Dict) -> Optional[MarketData]:
        """获取市场数据（优先API）"""
        market_hash_name = item.get('market_hash_name')
        platform = item.get('platform')

        if market_hash_name:
            data = self.api_client.get_market_data(market_hash_name, platform)
            if data and data.is_valid():
                return data

        print('[Info] API获取失败，回退到网页爬取（注意：网页模式无法获取在售/求购数量）')
        return self.get_market_data_from_web(item)

    def calculate_change(self, current: MarketData, previous: MarketData) -> DataChange:
        """计算数据变动"""
        change = DataChange()

        if not previous or previous.price == 0:
            return change

        if previous.price > 0:
            change.price_change_pct = abs(current.price - previous.price) / previous.price
            change.price_direction = '上涨📈' if current.price > previous.price else '下跌📉'

        if previous.sell_count > 0:
            change.sell_count_change_pct = abs(current.sell_count - previous.sell_count) / previous.sell_count
            change.sell_count_direction = '增加📈' if current.sell_count > previous.sell_count else '减少📉'
        elif current.sell_count > 0:
            change.sell_count_change_pct = 1.0
            change.sell_count_direction = '新增📈'

        if previous.bidding_count > 0:
            change.bidding_count_change_pct = abs(current.bidding_count - previous.bidding_count) / previous.bidding_count
            change.bidding_count_direction = '增加📈' if current.bidding_count > previous.bidding_count else '减少📉'
        elif current.bidding_count > 0:
            change.bidding_count_change_pct = 1.0
            change.bidding_count_direction = '新增📈'

        price_trigger = change.price_change_pct >= THRESHOLDS['price']
        sell_trigger = change.sell_count_change_pct >= THRESHOLDS['sell_count']
        bidding_trigger = change.bidding_count_change_pct >= THRESHOLDS['bidding_count']

        change.has_change = price_trigger or sell_trigger or bidding_trigger

        return change

    def format_feishu_message(self, item: Dict, current: MarketData, 
                              previous: MarketData, change: DataChange) -> Tuple[str, str]:
        """格式化飞书通知消息"""

        # 构建变动摘要
        changes = []
        if change.price_change_pct >= THRESHOLDS['price']:
            icon = "🔴" if "上涨" in change.price_direction else "🟢"
            changes.append(f"{icon}价格{change.price_direction.replace('📈','').replace('📉','')} **{change.price_change_pct*100:.2f}%**")
        
        if change.sell_count_change_pct >= THRESHOLDS['sell_count']:
            icon = "📈" if "增加" in change.sell_count_direction else "📉"
            changes.append(f"{icon}在售{change.sell_count_direction.replace('📈','').replace('📉','')} **{change.sell_count_change_pct*100:.2f}%**")
        
        if change.bidding_count_change_pct >= THRESHOLDS['bidding_count']:
            icon = "📈" if "增加" in change.bidding_count_direction else "📉"
            changes.append(f"{icon}求购{change.bidding_count_direction.replace('📈','').replace('📉','')} **{change.bidding_count_change_pct*100:.2f}%**")
        
        change_summary = " | ".join(changes)
        title = f"🎮 {item['name'][:50]}"

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 构建Markdown内容
        lines = [
            f"**{change_summary}**",
            "",
            f"💰 **当前价格：** ¥{current.price:.2f}",
        ]
        
        if previous.price > 0:
            lines.append(f"上次：¥{previous.price:.2f}")
        
        lines.extend([
            "",
            f"📦 **在售：** {current.sell_count} 件",
            f"🛒 **求购：** {current.bidding_count} 件",
        ])
        
        if current.bidding_price > 0:
            lines.append(f"💵 **求购价：** ¥{current.bidding_price:.2f}")
        
        lines.extend([
            "",
            f"🏪 平台：{current.platform or '未知'}",
            f"⏰ 时间：{now}",
            f"🔗 [查看详情]({item.get('url', 'https://steamdt.com')})"
        ])

        content = "\n".join(lines)
        return title, content

    def send_notification(self, title: str, content: str) -> bool:
        """发送飞书通知"""
        return self.feishu.send_markdown(title, content)

    def check_and_notify(self, item: Dict, current: MarketData):
        """检查变动并发送通知"""
        item_name = item['name']
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 初始化历史记录
        if item_name not in self.history:
            self.history[item_name] = {
                'records': [],
                'last_data': None
            }

        # 获取上次数据
        last_data_dict = self.history[item_name].get('last_data')
        previous = MarketData(**last_data_dict) if last_data_dict else MarketData()

        # 记录当前数据
        self.history[item_name]['records'].append({
            'time': now,
            'data': asdict(current)
        })

        # 只保留最近100条记录
        self.history[item_name]['records'] = self.history[item_name]['records'][-100:]

        # 计算变动
        change = self.calculate_change(current, previous)

        # 打印当前状态
        print(f'[{now}] {item_name}')
        print(f'  价格: ¥{current.price:.2f} (上次: {"¥" + f"{previous.price:.2f}" if previous.price > 0 else "N/A"})')
        print(f'  在售: {current.sell_count}件 (上次: {previous.sell_count if previous.sell_count > 0 else "N/A"})')
        print(f'  求购: {current.bidding_count}件 (上次: {previous.bidding_count if previous.bidding_count > 0 else "N/A"})')

        # 如果有变动，发送飞书通知
        if change.has_change:
            title, content = self.format_feishu_message(item, current, previous, change)
            success = self.send_notification(title, content)
            if success:
                print(f'  🚨 触发预警，已发送飞书通知')
            else:
                print(f'  ⚠️ 触发预警，但飞书通知发送失败')
        else:
            print(f'  ✅ 数据稳定，未触发阈值')

        # 更新历史数据
        self.history[item_name]['last_data'] = asdict(current)
        self._save_history()

    def run(self):
        """主运行循环"""
        print('=' * 70)
        print('CS2饰品三重指标监控工具（飞书版）')
        print('=' * 70)
        print(f'API配置: {"✅ 已配置" if STEAMDT_API_KEY else "❌ 未配置"}')
        print(f'飞书配置: {"✅ 已配置" if self.feishu.enabled else "❌ 未配置"}')
        print(f'监控饰品: {len(ITEMS_TO_MONITOR)} 个')
        print(f'监控间隔: {CHECK_INTERVAL // 60} 分钟')
        print('-' * 70)
        print('阈值设置:')
        print(f'  价格波动: ≥{THRESHOLDS["price"]*100:.0f}%')
        print(f'  在售数量: ≥{THRESHOLDS["sell_count"]*100:.0f}%')
        print(f'  求购数量: ≥{THRESHOLDS["bidding_count"]*100:.0f}%')
        print('=' * 70)

        # 首次运行
        print('\n>>> 初始化检查...')
        for item in ITEMS_TO_MONITOR:
            try:
                data = self.get_market_data(item)
                if data and data.is_valid():
                    self.check_and_notify(item, data)
                else:
                    print(f'⚠️ 无法获取 {item["name"]} 的有效数据')
                time.sleep(2)
            except Exception as e:
                print(f'❌ 检查 {item["name"]} 时出错: {e}')

        print('\n>>> 进入监控循环...')

        # 监控循环
        while True:
            time.sleep(CHECK_INTERVAL)
            print(f'\n[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] 开始新一轮检查...')
            
            # 每天执行一次清理（检查当前时间是否为0点）
            now = datetime.now()
            if now.hour == 0 and now.minute < 10:
                self.clean_old_history()
                self.api_client.clean_old_api_calls()

            for item in ITEMS_TO_MONITOR:
                try:
                    data = self.get_market_data(item)
                    if data and data.is_valid():
                        self.check_and_notify(item, data)
                    else:
                        print(f'⚠️ 无法获取 {item["name"]} 的有效数据')
                    time.sleep(2)
                except Exception as e:
                    print(f'❌ 检查 {item["name"]} 时出错: {e}')


def test_api():
    """测试API连接"""
    print('测试SteamDT API连接...')
    client = SteamDTAPIClient(STEAMDT_API_KEY)

    test_items = [
        'AK-47 | Redline (Field-Tested)',
        'Sticker | Natus Vincere (Holo) | Stockholm 2021'
    ]

    for item in test_items:
        print(f'\n测试查询: {item}')
        result = client.get_market_data(item)
        if result:
            print(f'✅ 成功！')
            print(f'  价格: ¥{result.price}')
            print(f'  在售: {result.sell_count}')
            print(f'  求购: {result.bidding_count}')
            print(f'  平台: {result.platform}')
        else:
            print(f'❌ 失败')


def test_feishu():
    """测试飞书机器人"""
    print('测试飞书机器人连接...')
    notifier = FeishuNotifier(FEISHU_WEBHOOK, FEISHU_SECRET)
    success = notifier.send_markdown(
        title="🎮 CS2监控测试",
        content="**测试消息**\n飞书机器人配置成功！\n⏰ 时间：" + datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )
    if success:
        print('✅ 飞书测试消息发送成功，请检查群聊')
    else:
        print('❌ 飞书测试消息发送失败，请检查Webhook地址')


def main():
    import sys

    if len(sys.argv) > 1:
        if sys.argv[1] == '--test':
            test_api()
            return
        elif sys.argv[1] == '--test-feishu':
            test_feishu()
            return

    tracker = PriceTracker()
    try:
        tracker.run()
    except KeyboardInterrupt:
        print('\n\n用户中断，程序退出')
    except Exception as e:
        print(f'\n程序异常: {e}')
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()