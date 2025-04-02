import asyncio
import os
import json
from typing import Dict, Any, Optional
from contextlib import AsyncExitStack

from openai import OpenAI
from dotenv import load_dotenv

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# 載入環境變量
load_dotenv()

class MCPClient:
    def __init__(self):
        """初始化 MCP 用戶端"""
        self.exit_stack = AsyncExitStack()
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.model = os.getenv("MODEL")
        
        if not self.openai_api_key:
            raise ValueError("缺少OPENAI_API_KEY，請在.env文件中設置。")
        if not self.model:
            raise ValueError("缺少MODEL，請在.env文件中設置。")
        
        self.client = OpenAI(api_key=self.openai_api_key)
        self.session : Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        
    async def connect_to_server(self, server_script_path: str):
        """
        連接至遠端 MCP Server，並列出可用工具
        Args:
            server_script_path (str): MCP Server 腳本路徑
        """
        is_python = server_script_path.endswith('.py')
        is_js = server_script_path.endswith('.js')
        if not (is_python or is_js):
            raise ValueError("不支援的檔案類型，請使用 .py 或 .js 文件。")
        
        command = 'python' if is_python else 'node'
        server_params = StdioServerParameters(
            command = command,
            args = [server_script_path],
            env = None
        )

        # 啟動MCP Server並建立連線
        stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
        self.stdio, self.write = stdio_transport
        self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))

        await self.session.initialize()
        
        # 列出MCP Server上可用工具
        response = await self.session.list_tools()
        tools = response.tools
        print("\n已連線到MCP Server，可用工具包含：", [tool.name for tool in tools])
        

    async def process_query(self, query: str) -> str:
        """調用OpenAI API處理用戶聊天請求，並且調用可使用的MCP工具(Function Calling)"""
        messages = [
            {
                "role": "system",
                "content": """你是一個智慧助理，且你有許多不同的工具可以給你使用。
                你需依據使用者問題與工具提示判斷你是否要使用工具。
                如果不需要調用工具，則直接使用繁體中文簡短回答用戶的問題。
                如果需要調用工具，則在調用必要工具後，整理你所獲得的資訊後並使用繁體中文簡短回答用戶提供的問題。
                注意：query_weather 工具需要一個 city 參數，例如：{"city": "Taipei"}"""
            },
            {"role": "user", "content": query}
        ]
        response = await self.session.list_tools()
        
        available_tools = [
            {
            'type': 'function',
            'function': {
                'name': tool.name,
                'description': tool.description,
                'input_schema': tool.inputSchema
            }
        } for tool in response.tools]
        # print(available_tools)
        
        response = self.client.chat.completions.create(
            model = self.model,
            messages = messages,
            tools = available_tools,
        )
        
        # try:
        #     # 調用OpenAI API
        #     response = await asyncio.get_event_loop().run_in_executor(
        #         None,
        #         lambda: self.client.chat.completions.create(
        #             model = self.model,
        #             messages = messages,
        #         )
        #     )
        #     return response.choices[0].message.content
        # except Exception as e:
        #     return f"⚠️調用API時發生錯誤：{str(e)}"
        
        # 處理OpenAI API的回應
        content = response.choices[0]
        if content.finish_reason == 'tool_calls':
            # 解析工具調用回應
            tool_call = content.message.tool_calls[0]
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments)

            # 使用工具
            result = await self.session.call_tool(tool_name, tool_args)
            print(f"\n\n[Calling tool {tool_name} with args {tool_args}]\n\n")
            
            # 將模型返回的工具調用數據與執行完結果全部存入messages當中
            messages.append(content.message.model_dump())
            messages.append({
                'role': 'tool',
                'content': result.content[0].text,
                'tool_call_id': tool_call.id,
            })    
        
            # 將上面附加資訊後的messages傳遞給OpenAI API，產出最終結果
            response = self.client.chat.completions.create(
                model = self.model,
                messages = messages,
            )
            return response.choices[0].message.content
        
        return content.message.content
    
    async def chat_loop(self):
        """交互式聊天循環"""
        print("\nMCP Chatbot已經成功啟動！如要退出，請輸入 'quit'")

        while True:
            try:
                query = input("\nUser: ").strip()
                if query.lower() == 'quit':
                    break
                
                response = await self.process_query(query)
                print(f"\n🤖 OpenAI：{response}")
                
            except Exception as e:
                print(f"\n⚠️ 發生錯誤: {str(e)}")

    async def cleanup(self):
        """清理資源"""
        await self.exit_stack.aclose()

async def main():
    if len(sys.argv) < 2:
        print("Usage: python client.py <path_to_server_script>")
        sys.exit(1)
        
    client = MCPClient()
    try:
        await client.connect_to_server(sys.argv[1])
        await client.chat_loop()
    finally:
        await client.cleanup()

if __name__ == "__main__":
    import sys
    asyncio.run(main())
    
    
