import json
import httpx
import os
import dotenv
from typing import Any
from mcp.server.fastmcp import FastMCP

dotenv.load_dotenv()

# 初始化 MCP 服务器
mcp = FastMCP("WeatherServer")

# OpenWeather API 配置
OPENWEATHER_API_BASE = os.getenv("OPENWEATHER_API_BASE")
API_KEY = os.getenv("OPENWEATHER_API_KEY") 
USER_AGENT = os.getenv("USER_AGENT")

async def fetch_weather(city: str) -> dict[str, Any] | None:
    """
    透過 OpenWeather API 獲取當天天氣資訊。
    :param city: 城市名稱（需使用英文，如 Taipei）
    :return: 天氣資訊dict；如果出現error則返回error訊息
    """
    params = {
        "q": city,
        "appid": API_KEY,
        "units": "metric",
        "lang": "zh_cn"
    }
    headers = {"User-Agent": USER_AGENT}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(OPENWEATHER_API_BASE, params=params, headers=headers, timeout=30.0)
            response.raise_for_status()
            return response.json()  # 返回dict
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP 錯誤: {e.response.status_code}"}
        except Exception as e:
            return {"error": f"發生錯誤: {str(e)}"}

def format_weather(data: dict[str, Any] | str) -> str:
    """
    將天氣資訊轉為易讀文本。
    :param data: 天氣數據(dict or json str)
    :return: 提取後的易讀天氣資訊
    """
    # 如果input為str，先轉為dict
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception as e:
            return f"無法解析天氣數據: {e}"

    # 如果發現data內包含error，直接返回完整錯誤訊息
    if "error" in data:
        return f"⚠️ {data['error']}"

    # 提取資料，並進行容錯性處理
    city = data.get("name", "未知城市")
    country = data.get("sys", {}).get("country", "未知國家")
    temp = data.get("main", {}).get("temp", "N/A")
    humidity = data.get("main", {}).get("humidity", "N/A")
    wind_speed = data.get("wind", {}).get("speed", "N/A")
    # weather 可能null list，因此用 [0] 來提供default dict
    weather_list = data.get("weather", [{}])
    description = weather_list[0].get("description", "未知")

    return (
        f"🌍 {city}, {country}\n"
        f"🌡 溫度: {temp}°C\n"
        f"💧 濕度: {humidity}%\n"
        f"🌬 風速: {wind_speed} m/s\n"
        f"🌤 天氣: {description}\n"
    )

@mcp.tool()
async def query_weather(city: str) -> str:
    """
    輸入指定城市的英文名稱，系統會返回今天天氣查詢結果。
    :param city: 城市名稱（需使用英文）
    :return: 格式化後的天氣資訊
    """
    data = await fetch_weather(city)
    return format_weather(data)

if __name__ == "__main__":
    # 使用標準I/O的方式來啟動MCP Server
    mcp.run(transport='stdio')