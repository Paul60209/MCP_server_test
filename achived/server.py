import json
import httpx
import os
from typing import Dict, Any, Optional
import mcp
# from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv


load_dotenv()

class WeatherServer:
    # 初始化Weather Server
    def __init__(self):
        self.mcp = FastMCP("WeatherServer")
        self.openweather_api_base = os.getenv("OPENWEATHER_API_BASE")
        self.openweather_api_key = os.getenv("OPENWEATHER_API_KEY")
        self.user_agent = os.getenv("USER_AGENT")
        
        if not self.openweather_api_base:
            raise ValueError("缺少OPENWEATHER_API_BASE，請在.env文件中設置。")
        if not self.openweather_api_key:
            raise ValueError("缺少OPENWEATHER_API_KEY，請在.env文件中設置。")
        if not self.user_agent:
            raise ValueError("缺少USER_AGENT，請在.env文件中設置。")
        
    async def fetch_weather(self, city: str) -> Dict[str, Any] | None:
        """
        從OpenWeather API取得指定城市的氣象資料
        Args:
            city (str): 城市名稱
        Returns:
            Dict[str, Any] | None: 氣象資料或None（如果API回應錯誤）
        """
        params = {
            'q': city,
            'appid': self.openweather_api_key,
            'units': 'metric',
            'lang': 'zh_cn'
        }
        headers = {"User-Agent":self.user_agent}
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(self.openweather_api_base, headers=headers, params=params)
                response.raise_for_status()
                return response.json()  # 將API回應轉換為JSON
            except httpx.HTTPStatusError as e:
                return f"OpenWeather API回應錯誤: {e}"
            except Exception as e:
                return f"其他錯誤: {e}"
            
    def format_weather(self, data: dict[str, Any] | str) -> str:
        """
        將天氣資料轉換為易讀的文字格式
        Args:
            data (dict[str, Any] | str): 氣象資料
        Returns:
            str: 易讀的文字格式
        """
        
        # 如果傳入的是str，則先轉換為dict
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except Exception as e:
                return f"無效的JSON格式: {e}"
        
        # 如果回傳的資料包含錯誤訊息，則直接返回錯誤訊息
        if "error" in data:
            return f"⚠️ {data['error']}"
        
        # 提取必要數據，並進行容錯處理
        city = data.get('name', '未知地區')
        country = data.get('sys', {}).get('country', '未知國家')
        temp = data.get("main", {}).get("temp", "N/A")
        humidity = data.get("main", {}).get("humidity", "N/A")
        wind_speed = data.get("wind", {}).get("speed", "N/A")
        # weather 可能是null list，因此用 [0] 前先提供預設字典
        weather_list = data.get("weather", [{}])
        description = weather_list[0].get("description", "未知")
        
        # 組裝易讀的文字格式
        return (
            f"🌍 {city}, {country}\n"
            f"🌡 溫度: {temp}°C\n"
            f"💧 濕度: {humidity}%\n"
            f"🌬 風速: {wind_speed} m/s\n"
            f"🌤 天氣: {description}\n"
        )
    
    @mcp.tool()
    async def query_weather(self, city: str) -> str:
        """
        輸入城市的英文名稱，回傳今天的天氣查詢結果
        Args:
            city (str): 城市名稱（英文）
        Returns:
            str: 格式化後的天氣資料
        """
        data = await self.fetch_weather(city)
        return self.format_weather(data)
    
if __name__ == "__main__":
    mcp.run(transport='studio')