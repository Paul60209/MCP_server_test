# 首先修復 python-pptx 在 Python 3.10+ 中的相容性問題
import sys
import collections
if not hasattr(collections, 'Container'):
    import collections.abc
    collections.Container = collections.abc.Container
    collections.Mapping = collections.abc.Mapping
    collections.MutableMapping = collections.abc.MutableMapping
    collections.Sequence = collections.abc.Sequence
    collections.Set = collections.abc.Set

# 現在引入所需模組
import asyncio
import tempfile
import os
import time
import dotenv
import base64
import pathlib
import argparse

# 引入 MCP 相關模組
from mcp.server.fastmcp import FastMCP, Image

# 最後再引入 python-pptx 相關模組
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.enum.dml import MSO_THEME_COLOR_INDEX, MSO_COLOR_TYPE
from pptx.dml.color import RGBColor
from pptx.util import Pt

# 載入環境變數
dotenv.load_dotenv()

# 定義輸出路徑
OUTPUT_PATH = 'output'

# 創建 MCP 伺服器
mcp = FastMCP("PPTTranslatorServer")

# 解析命令行參數
parser = argparse.ArgumentParser(description='PPT翻譯MCP服務器')
parser.add_argument('--port', type=int, default=8001, help='服務器監聽端口 (默認: 8001)')
args = parser.parse_args()

# 設置環境變數，讓 FastMCP 使用指定的端口
os.environ["MCP_SSE_PORT"] = str(args.port)

def get_text_frame_properties(text_frame):
    """獲取文本框的所有格式屬性"""
    properties = {
        'margin_left': text_frame.margin_left,
        'margin_right': text_frame.margin_right,
        'margin_top': text_frame.margin_top,
        'margin_bottom': text_frame.margin_bottom,
        'vertical_anchor': text_frame.vertical_anchor,
        'word_wrap': text_frame.word_wrap,
        'auto_size': text_frame.auto_size,
    }
    return properties

def get_paragraph_properties(paragraph):
    """獲取段落的所有格式屬性"""
    properties = {
        'alignment': paragraph.alignment,
        'level': paragraph.level,
        'line_spacing': paragraph.line_spacing,
        'space_before': paragraph.space_before,
        'space_after': paragraph.space_after,
    }
    return properties

def get_color_properties(color):
    """獲取顏色屬性"""
    if not color:
        return None
        
    properties = {
        'type': color.type if hasattr(color, 'type') else None,
        'rgb': color.rgb if hasattr(color, 'rgb') else None,
        'theme_color': color.theme_color if hasattr(color, 'theme_color') else None,
        'brightness': color.brightness if hasattr(color, 'brightness') else None,
    }
    return properties

def get_run_properties(run):
    """獲取文本運行的所有格式屬性"""
    font = run.font
    properties = {
        'size': font.size,
        'name': font.name,
        'bold': font.bold,
        'italic': font.italic,
        'underline': font.underline,
        'color': get_color_properties(font.color),
        'fill': get_color_properties(font.fill.fore_color) if hasattr(font, 'fill') else None,
    }
    return properties

def apply_color_properties(color_obj, properties):
    """應用顏色屬性"""
    if not properties or not color_obj:
        return
        
    try:
        # 如果有 RGB 值，直接設置 RGB 顏色
        if properties['rgb']:
            if isinstance(properties['rgb'], (tuple, list)) and len(properties['rgb']) == 3:
                color_obj.rgb = RGBColor(*properties['rgb'])
            else:
                color_obj.rgb = properties['rgb']
        # 如果有主題顏色，設置主題顏色
        elif properties['theme_color'] and properties['theme_color'] != MSO_THEME_COLOR_INDEX.NOT_THEME_COLOR:
            color_obj.theme_color = properties['theme_color']
            if properties['brightness'] is not None:
                color_obj.brightness = properties['brightness']
    except Exception as e:
        print(f"設置顏色時發生錯誤: {str(e)}")
        pass  # 如果設置失敗，保持原有顏色

def apply_text_frame_properties(text_frame, properties):
    """應用文本框格式屬性"""
    text_frame.margin_left = properties['margin_left']
    text_frame.margin_right = properties['margin_right']
    text_frame.margin_top = properties['margin_top']
    text_frame.margin_bottom = properties['margin_bottom']
    text_frame.vertical_anchor = properties['vertical_anchor']
    text_frame.word_wrap = properties['word_wrap']
    text_frame.auto_size = properties['auto_size']

def apply_paragraph_properties(paragraph, properties):
    """應用段落格式屬性"""
    paragraph.alignment = properties['alignment']
    paragraph.level = properties['level']
    paragraph.line_spacing = properties['line_spacing']
    paragraph.space_before = properties['space_before']
    paragraph.space_after = properties['space_after']

def apply_run_properties(run, properties):
    """應用文本運行格式屬性"""
    font = run.font
    if properties['size']:
        font.size = properties['size']
    if properties['name']:
        font.name = properties['name']
    if properties['bold'] is not None:
        font.bold = properties['bold']
    if properties['italic'] is not None:
        font.italic = properties['italic']
    if properties['underline'] is not None:
        font.underline = properties['underline']
    
    # 應用顏色
    if properties['color']:
        apply_color_properties(font.color, properties['color'])
    if properties['fill'] and hasattr(font, 'fill'):
        apply_color_properties(font.fill.fore_color, properties['fill'])

async def translate_text(text: str, olang: str, tlang: str, ctx=None) -> str:
    """使用 MCP 的 sampling 功能翻譯文本。

    Args:
        text (str): 要翻譯的文本
        olang (str): 原始語言代碼
        tlang (str): 目標語言代碼
        ctx: MCP 上下文對象

    Returns:
        str: 翻譯後的文本
    """
    if not text.strip():
        return text

    print(f"\n正在翻譯文本:")
    print(f"原文 ({olang}): {text}")
    
    if ctx:
        # 向用戶報告進度
        await ctx.info(f"正在翻譯：{text[:30]}{'...' if len(text) > 30 else ''}")
    
    # 創建翻譯提示
    system_prompt = f"""You are a professional translator. Translate the following text from {olang} to {tlang}.
    Rules:
    1. Keep all formatting symbols (like bullet points, numbers) unchanged
    2. Keep all special characters unchanged
    3. Keep all whitespace and line breaks
    4. Only translate the actual text content
    5. Maintain the same tone and style
    6. Do not add any explanations or notes
    7. Keep all numbers and dates unchanged
    8. Keep all proper nouns unchanged unless they have standard translations
    """
    
    # MCP 內容格式
    messages = [
        {
            "role": "system",
            "content": system_prompt
        },
        {
            "role": "user",
            "content": text
        }
    ]
    
    try:
        # 使用 MCP sampling 功能請求 LLM 翻譯 (如果有上下文)
        if ctx and hasattr(ctx, 'sampling'):
            result = await ctx.sampling.create_message(
                messages=messages,
                system_prompt=system_prompt,
                temperature=0.1,
                max_tokens=1024
            )
            translated_text = result.content.get("text", "")
        else:
            # 假設沒有 MCP 上下文，使用簡單副本
            # 在實際應用中，這裡可能需要使用其他方式翻譯
            translated_text = f"[翻譯 {olang} → {tlang}] {text}"
        
        print(f"譯文 ({tlang}): {translated_text}\n")
        return translated_text
        
    except Exception as e:
        print(f"翻譯失敗: {str(e)}")
        if ctx:
            await ctx.info(f"翻譯失敗: {str(e)}")
        # 返回原文以確保不會丟失內容
        return text

async def translate_group_shape(shape, olang: str, tlang: str, ctx=None) -> None:
    """翻譯群組中的所有形狀。

    Args:
        shape: PowerPoint 群組形狀對象
        olang (str): 原始語言代碼
        tlang (str): 目標語言代碼
        ctx: MCP 上下文對象
    """
    try:
        if not hasattr(shape, 'shapes'):
            return
            
        # 遍歷群組中的所有形狀
        for child_shape in shape.shapes:
            if child_shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                # 遞歸處理嵌套群組
                await translate_group_shape(child_shape, olang, tlang, ctx)
            else:
                # 翻譯單個形狀
                await translate_shape(child_shape, olang, tlang, ctx)
    except Exception as e:
        print(f"翻譯群組形狀時發生錯誤: {str(e)}")
        if ctx:
            await ctx.info(f"翻譯群組形狀時發生錯誤: {str(e)}")
        raise

async def translate_shape(shape, olang: str, tlang: str, ctx=None) -> None:
    """翻譯 PowerPoint 中的形狀。

    Args:
        shape: PowerPoint 形狀對象
        olang (str): 原始語言代碼
        tlang (str): 目標語言代碼
        ctx: MCP 上下文對象
    """
    try:
        # 處理群組形狀
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            await translate_group_shape(shape, olang, tlang, ctx)
            return
            
        # 檢查形狀是否包含文本框
        if not hasattr(shape, "text_frame"):
            return
            
        text_frame = shape.text_frame
        if not text_frame.text.strip():
            return
            
        # 保存文本框格式
        text_frame_props = get_text_frame_properties(text_frame)
        
        # 遍歷所有段落
        for paragraph in text_frame.paragraphs:
            # 保存段落格式
            para_props = get_paragraph_properties(paragraph)
            
            # 遍歷所有文本運行
            runs_data = []
            for run in paragraph.runs:
                # 保存運行格式和文本
                run_props = get_run_properties(run)
                original_text = run.text
                if original_text.strip():
                    translated_text = await translate_text(original_text, olang, tlang, ctx)
                    runs_data.append((translated_text, run_props))
                else:
                    runs_data.append((original_text, run_props))
            
            # 清除原有內容
            for _ in range(len(paragraph.runs)):
                paragraph._p.remove(paragraph.runs[0]._r)
            
            # 添加翻譯後的文本並應用格式
            for text, props in runs_data:
                run = paragraph.add_run()
                run.text = text
                apply_run_properties(run, props)
            
            # 恢復段落格式
            apply_paragraph_properties(paragraph, para_props)
        
        # 恢復文本框格式
        apply_text_frame_properties(text_frame, text_frame_props)
        
    except Exception as e:
        print(f"翻譯形狀時發生錯誤: {str(e)}")
        if ctx:
            await ctx.info(f"翻譯形狀時發生錯誤: {str(e)}")
        raise

async def translate_ppt_file(file_path: str, olang: str, tlang: str, ctx=None) -> str:
    """翻譯 PowerPoint 文件。

    Args:
        file_path (str): PowerPoint 文件路徑
        olang (str): 原始語言代碼
        tlang (str): 目標語言代碼
        ctx: MCP 上下文對象

    Returns:
        str: 翻譯後的文件路徑
    """
    try:
        # 1. 建立輸出目錄
        os.makedirs(OUTPUT_PATH, exist_ok=True)
        
        # 2. 準備輸出文件路徑
        file_name = os.path.basename(file_path)
        name, ext = os.path.splitext(file_name)
        output_file = f'translated_{name}{ext}'
        output_path = os.path.join(OUTPUT_PATH, output_file)
        
        # 3. 載入 PowerPoint
        print("\nStarting PowerPoint translation...")
        print(f"Source language: {olang}")
        print(f"Target language: {tlang}")
        if ctx:
            await ctx.info(f"開始翻譯...\n從 {olang} 到 {tlang}")
        
        presentation = Presentation(file_path)
        total_slides = len(presentation.slides)
        
        # 4. 翻譯每個投影片
        for index, slide in enumerate(presentation.slides, 1):
            progress_msg = f"正在翻譯投影片 {index}/{total_slides}..."
            print(f"\n{progress_msg}")
            if ctx:
                await ctx.info(progress_msg)
                # 報告進度 (0-100%)
                await ctx.report_progress(index - 1, total_slides)
                
            for shape in slide.shapes:
                await translate_shape(shape, olang, tlang, ctx)
        
        # 5. 儲存翻譯後的文件
        print("\nSaving translated file...")
        if ctx:
            await ctx.info("翻譯完成，生成文件中...")
            await ctx.report_progress(total_slides, total_slides)  # 100% 完成
            
        presentation.save(output_path)
        
        # 6. 返回路徑
        return output_path
        
    except Exception as e:
        error_msg = f"翻譯過程中發生錯誤: {str(e)}"
        print(f"\n{error_msg}")
        if ctx:
            await ctx.info(error_msg)
        raise

@mcp.tool()
async def translate_ppt(olang: str, tlang: str, file_content: str = None) -> str:
    """
    翻譯 PowerPoint 檔案從一種語言到另一種語言。
    
    :param olang: 來源語言代碼，例如 'zh-TW'（中文）、'en'（英文）、'ja'（日文）
    :param tlang: 目標語言代碼，例如 'zh-TW'（中文）、'en'（英文）、'ja'（日文）
    :param file_content: 以 base64 編碼的 PowerPoint 檔案內容
    :return: 翻譯完成的訊息及檔案路徑
    """
    # 獲取 MCP 上下文 (內部自動傳遞，不需要用戶提供)
    ctx = mcp.get_current_request_context()
    
    try:
        print(f"\n開始 PowerPoint 翻譯工具...")
        print(f"來源語言: {olang}")
        print(f"目標語言: {tlang}")
        
        # 檢查必要參數
        if not file_content:
            return "錯誤：需要提供 PowerPoint 檔案的 base64 編碼內容。請上傳檔案並提供內容。"
            
        # 檢查是否為檔案路徑而非 base64 內容
        if file_content.startswith("/") or file_content.startswith("C:") or file_content.startswith("\\"):
            return "錯誤：file_content 參數應該是 base64 編碼的檔案內容，而不是檔案路徑。請將檔案內容編碼為 base64 字串。"
        
        # 建立臨時檔案來存儲上傳的內容
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pptx') as temp_file:
            # 解碼 base64 內容
            try:
                decoded_content = base64.b64decode(file_content)
                temp_file.write(decoded_content)
                temp_file_path = temp_file.name
                print(f"檔案已暫存於: {temp_file_path}")
            except Exception as e:
                return f"解碼檔案內容時發生錯誤: {str(e)}。請確認 file_content 是有效的 base64 編碼字串。"
        
        # 執行翻譯
        print("開始翻譯...")
        output_path = await translate_ppt_file(temp_file_path, olang, tlang, ctx)
        print(f"翻譯結果: {output_path}")
        
        # 讀取翻譯後的檔案，轉為 base64
        with open(output_path, 'rb') as f:
            translated_content = base64.b64encode(f.read()).decode('utf-8')
        
        # 清理臨時檔案
        if os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        
        # 成功的回覆
        return f"翻譯完成！檔案已儲存在: {output_path} 並已編碼為 base64。檔案內容長度: {len(translated_content)} 字元。"
        
    except Exception as e:
        print(f"翻譯工具執行錯誤: {str(e)}")
        return f"翻譯過程中發生錯誤: {str(e)}"

@mcp.resource("translator://instructions")
async def get_instructions() -> str:
    """獲取 PPT 翻譯器的使用說明。"""
    return """
# PowerPoint 翻譯工具使用說明

這個工具可以將 PowerPoint 文件從一種語言翻譯成另一種語言，同時保留原始格式。

## 支援的語言

- 中文（zh-TW）
- 英文（en）
- 日文（ja）
- 其他語言代碼也可嘗試

## 使用方法

1. 將 PowerPoint 檔案（.ppt 或 .pptx）轉為 base64 編碼
2. 調用 `translate_ppt` 工具，提供以下參數：
   - olang: 原始語言代碼
   - tlang: 目標語言代碼
   - file_content: 檔案的 base64 編碼內容

## 翻譯過程

1. 工具會解析 PowerPoint 檔案中的所有文本
2. 逐一翻譯每個文本元素，保留原始格式
3. 生成新的 PowerPoint 檔案，將結果回傳

## 注意事項

- 翻譯大型檔案可能需要較長時間
- 某些複雜的格式可能無法完美保留
- 檔案大小限制為 10MB
"""

# 啟動伺服器
if __name__ == "__main__":
    # 確保輸出目錄存在
    os.makedirs(OUTPUT_PATH, exist_ok=True)
    
    import uvicorn
    from starlette.applications import Starlette
    from starlette.routing import Route, Mount
    from mcp.server.sse import SseServerTransport
    
    # 啟動 MCP 伺服器
    print(f"啟動PPT翻譯服務器 在端口 {args.port}")
    
    # 創建 SSE 傳輸
    sse = SseServerTransport("/mcp/")
    
    # 定義 SSE 連接處理函數
    async def handle_sse(request):
        async with sse.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await mcp._mcp_server.run(
                streams[0], 
                streams[1],
                mcp._mcp_server.create_initialization_options()
            )
    
    # 定義健康檢查端點
    async def health_check(request):
        from starlette.responses import JSONResponse
        return JSONResponse({"status": "ok"})
    
    # 創建 Starlette 應用
    starlette_app = Starlette(
        routes=[
            # SSE 端點
            Route("/sse", endpoint=handle_sse, methods=["GET"]),
            Mount("/mcp/", app=sse.handle_post_message),
            # 添加健康檢查端點
            Route("/health", endpoint=health_check, methods=["GET"]),
        ]
    )
    
    # 使用 uvicorn 啟動應用
    uvicorn.run(starlette_app, host="0.0.0.0", port=args.port) 