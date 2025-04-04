import os
import asyncio
import subprocess
import time
import signal
import httpx
import threading
import chainlit as cl
from chainlit.element import Element
from chainlit.sync import run_sync
from langchain.agents import AgentExecutor, create_react_agent
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.memory import ConversationBufferMemory
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_core.prompts import PromptTemplate
from langchain.agents.output_parsers import ReActJsonSingleInputOutputParser

# 加載環境變量
load_dotenv()

# MCP 伺服器配置
SERVER_CONFIGS = {
    "weather": {
        "path": os.path.join("MCP_Servers", "weather_server.py"),
        "port": 8001,
        "transport": "sse"
    },
    "sql_query": {
        "path": os.path.join("MCP_Servers", "sql_query_server.py"),
        "port": 8002,
        "transport": "sse"
    },
    "ppt_translator": {
        "path": os.path.join("MCP_Servers", "ppt_translator_server.py"),
        "port": 8003,
        "transport": "sse"
    }
}

# 配置 OpenAI 模型
OPENAI_MODEL = os.getenv("MODEL", "gpt-4o-mini")

async def check_server_health(url, retries=5, delay=2):
    """
    檢查伺服器健康狀態
    
    Args:
        url: 伺服器 URL
        retries: 重試次數
        delay: 每次重試之間的延遲（秒）
        
    Returns:
        bool: 伺服器是否健康
    """
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=5.0)
                # 只要伺服器返回任何響應，就認為是健康的
                print(f"健康檢查響應: {url} - 狀態碼: {response.status_code}")
                return True  # 如果能夠得到響應，就認為伺服器是健康的
        except Exception as e:
            print(f"健康檢查失敗 (嘗試 {attempt+1}/{retries}): {e}")
        
        if attempt < retries - 1:  # 如果不是最後一次嘗試
            await asyncio.sleep(delay)  # 等待一段時間再重試
    
    return False

async def create_mcp_client_with_retry(client_config, max_retries=3):
    """
    嘗試創建 MCP 客戶端，如果失敗則重試
    
    Args:
        client_config: MCP 客戶端配置
        max_retries: 最大重試次數
        
    Returns:
        tuple: (客戶端, 工具列表) 或 (None, None)
    """
    for attempt in range(max_retries):
        try:
            # 不使用timeout參數
            mcp_client = MultiServerMCPClient(client_config)
            await mcp_client.__aenter__()
            
            # 嘗試獲取工具列表，驗證連接成功
            try:
                tools = mcp_client.get_tools()
                if not tools:
                    print("警告: 工具列表為空")
                    tools = []
                return mcp_client, tools
            except Exception as tool_error:
                print(f"獲取工具列表失敗: {tool_error}")
                # 嘗試優雅退出
                try:
                    await mcp_client.__aexit__(None, None, None)
                except Exception as exit_error:
                    print(f"客戶端退出錯誤: {exit_error}")
                raise tool_error
                
        except Exception as e:
            print(f"創建 MCP 客戶端失敗 (嘗試 {attempt+1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                # 如果不是最後一次嘗試，等待一段時間再重試
                await asyncio.sleep(3)
    
    return None, None

# 添加將服務器配置保存到文件的函數
def save_server_config():
    """將伺服器配置保存到文件"""
    config_file = "server_config.txt"
    with open(config_file, "w") as f:
        for name, config in SERVER_CONFIGS.items():
            f.write(f"{name}:{config['port']}:{config['transport']}\n")
    print(f"伺服器配置已保存到 {config_file}")

# 從文件加載服務器配置
def load_server_config():
    """從文件加載伺服器配置"""
    config_file = "server_config.txt"
    if not os.path.exists(config_file):
        print(f"找不到配置文件 {config_file}，使用默認配置")
        return False
    
    try:
        with open(config_file, "r") as f:
            lines = f.readlines()
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            parts = line.split(":")
            if len(parts) != 3:
                print(f"無效的配置行: {line}")
                continue
            
            name, port, transport = parts
            if name in SERVER_CONFIGS:
                SERVER_CONFIGS[name]["port"] = int(port)
                SERVER_CONFIGS[name]["transport"] = transport
        
        print("已從配置文件加載伺服器配置")
        return True
    except Exception as e:
        print(f"加載配置文件時出錯: {e}")
        return False

@cl.on_chat_start
async def on_chat_start():
    """聊天開始時的初始化程序"""
    
    # 顯示初始化消息
    init_message = cl.Message(content="正在連接到 MCP 伺服器...")
    await init_message.send()
    
    # 加載伺服器配置
    load_server_config()
    
    # 創建 MCP 客戶端配置
    client_config = {}
    
    for name, config in SERVER_CONFIGS.items():
        if config["transport"] == "sse":
            client_config[name] = {
                "url": f"http://localhost:{config['port']}/sse",
                "transport": "sse"
            }
        else:
            client_config[name] = {
                "command": "python",
                "args": [config["path"], "--port", str(config["port"])],
                "transport": "stdio"
            }
    
    # 初始化 MCP 客戶端（帶重試）
    try:
        connecting_message = cl.Message(content="正在連接到 MCP 伺服器...")
        await connecting_message.send()
        mcp_client, tools = await create_mcp_client_with_retry(client_config)
        
        if not mcp_client or not tools:
            error_message = cl.Message(content="連接 MCP 伺服器失敗。請確保 MCP 伺服器已運行 (使用 run_server.py)。")
            await error_message.send()
            return
        
        # 將客戶端保存到會話
        cl.user_session.set("mcp_client", mcp_client)
        
        # 顯示已連接的伺服器
        servers_info = "\n".join([f"- {name} (端口: {config['port']})" for name, config in SERVER_CONFIGS.items()])
        connected_message = cl.Message(content=f"已連接到以下 MCP 伺服器:\n{servers_info}")
        await connected_message.send()
        
        # 初始化對話記憶
        memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
        
        # 初始化 OpenAI 模型
        llm = ChatOpenAI(model=OPENAI_MODEL, temperature=0.5, streaming=True)
        
        # 獲取工具名稱列表
        tool_names = [tool.name for tool in tools]
        
        # 創建代理模板
        template = """Answer the following questions as best you can. You have access to the following tools:

{tools}

Use the following tools: {tool_names}

IMPORTANT: When using a tool, you MUST provide the input in JSON format with the exact required parameters.

Example for Weather Tool: {{"city": "Taipei"}}
Example for SQL Query Tool: {{"query": "SELECT * FROM sales LIMIT 5"}}

Think step-by-step, and be sure to format your tool inputs correctly.

Question: {input}
{agent_scratchpad}"""

        # 創建提示模板
        prompt = PromptTemplate.from_template(template)
        
        # 創建代理
        agent = create_react_agent(
            llm=llm, 
            tools=tools, 
            prompt=prompt
        )
        
        # 創建代理執行器
        agent_executor = AgentExecutor.from_agent_and_tools(
            agent=agent,
            tools=tools,
            memory=memory,
            verbose=True,
            handle_parsing_errors=True,
            max_iterations=3,
            return_intermediate_steps=True  # 返回中間步驟以便調試
        )
        
        # 存儲到用戶會話
        cl.user_session.set("agent_executor", agent_executor)
        
        # 發送歡迎消息
        welcome_message = cl.Message(content="您好！我是基於 MCP 的智能助手。請問有什麼我可以幫您的？")
        await welcome_message.send()
    
    except Exception as e:
        error_message = cl.Message(content=f"初始化 MCP 客戶端時出錯: {str(e)}")
        await error_message.send()
        import traceback
        traceback.print_exc()  # 在伺服器端打印完整錯誤信息

@cl.on_message
async def on_message(message: cl.Message):
    """處理用戶消息"""
    # 獲取代理執行器
    agent_executor = cl.user_session.get("agent_executor")
    
    # 在終端打印用戶訊息
    print(f"\n[用戶] {message.content}\n")
    
    if agent_executor is None:
        error_message = cl.Message(content="抱歉，MCP 客戶端尚未初始化，請重新開始對話。")
        await error_message.send()
        return
    
    # 創建響應消息
    response = cl.Message(content="思考中...")
    await response.send()
    
    try:
        # 打印調試信息
        print("正在執行代理...")
        print(f"輸入: {message.content}")
        
        # 直接執行代理並捕獲輸出
        result = await agent_executor.ainvoke(
            {"input": message.content}
        )
        
        # 打印中間步驟結果，用於調試
        print("\n--- 代理執行步驟 ---")
        if "intermediate_steps" in result:
            for i, step in enumerate(result["intermediate_steps"]):
                action = step[0]
                observation = step[1]
                print(f"步驟 {i+1}:")
                print(f"  動作: {action.tool} - 輸入: {action.tool_input}")
                print(f"  觀察: {observation}")
        print("-------------------\n")
        
        # 獲取最終輸出
        output = result.get("output", "沒有回應")
        
        # 在終端顯示 AI 回應
        print(f"\n[AI 回應]\n{output}\n")
        
        # 更新消息內容
        response.content = output
        await response.update()
        
        # 處理可能的元素（如圖像等）
        if "elements" in result:
            for element_data in result["elements"]:
                element = Element(**element_data)
                await response.elements.append(element)
    
    except Exception as e:
        print(f"處理請求時出錯: {str(e)}")
        import traceback
        traceback.print_exc()  # 在伺服器端打印完整錯誤信息
        
        # 更新消息內容
        response.content = f"處理您的請求時發生錯誤: {str(e)}"
        await response.update()

@cl.on_chat_end
async def on_chat_end():
    """聊天結束時的清理程序"""
    # 獲取 MCP 客戶端
    mcp_client = cl.user_session.get("mcp_client")
    if mcp_client:
        try:
            print("正在關閉 MCP 客戶端...")
            await mcp_client.__aexit__(None, None, None)
            print("MCP 客戶端已關閉")
        except Exception as e:
            print(f"關閉 MCP 客戶端時出錯: {str(e)}")
            import traceback
            traceback.print_exc()
    
    print("客戶端已關閉，MCP 伺服器仍在運行")

if __name__ == "__main__":
    try:
        # 直接從命令行運行時的入口
        cl.run()
    except KeyboardInterrupt:
        print("接收到鍵盤中斷，正在關閉客戶端...")
    finally:
        # 修改這裡，不要在結束時停止伺服器
        print("客戶端已關閉，MCP 伺服器仍在運行") 