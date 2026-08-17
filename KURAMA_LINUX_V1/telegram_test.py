import os
from typing import Annotated, Literal, TypedDict
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    filters,
)

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

# Load environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# ==========================================
# 1. TOOL DEFINITION FOR FILES/IMAGES
# ==========================================

@tool
def prepare_file_delivery(
    file_path: str, file_type: Literal["photo", "document"]
) -> str:
    """Call this tool whenever you need to send a local image or file to the user.
    Args:
        file_path: Absolute or relative local path to the file or image.
        file_type: Use 'photo' for images (JPG/PNG), and 'document' for PDFs, TXT, ZIP, etc.
    """
    if not os.path.exists(file_path):
        return f"ERROR: File '{file_path}' does not exist on the server."
    return f"SEND_FILE|{file_type}|{file_path}"

tools = [prepare_file_delivery]

# ==========================================
# 2. LANGGRAPH WORKFLOW SETUP
# ==========================================

class GraphState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

# Bind LLM with the file dispatching tool
llm = ChatGroq(model="llama-3.1-8b-instant", temperature=0.7).bind_tools(tools)

def call_model(state: GraphState):
    """Executes the LLM node."""
    response = llm.invoke(state["messages"])
    return {"messages": [response]}

def should_continue(state: GraphState):
    """Routes to tools if a tool call was generated, otherwise ends."""
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "tools"
    return END

# Build Graph
workflow = StateGraph(GraphState)
workflow.add_node("agent", call_model)
workflow.add_node("tools", ToolNode(tools))

workflow.add_edge(START, "agent")
workflow.add_conditional_edges("agent", should_continue, ["tools", END])
workflow.add_edge("tools", "agent")

graph = workflow.compile()

# ==========================================
# 3. TELEGRAM BOT HANDLER
# ==========================================

async def handle_telegram_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reads incoming messages, runs LangGraph workflow, and dispatches text/files."""
    if not update.message or not update.message.text:
        return

    user_text = update.message.text
    chat_id = update.effective_chat.id

    # Send typing status
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    # Run LangGraph workflow asynchronously
    inputs = {"messages": [HumanMessage(content=user_text)]}
    result = await graph.ainvoke(inputs)

    text_to_reply = ""
    files_to_send = []

    # Parse message history for final output and triggered files
    for msg in result["messages"]:
        if isinstance(msg, ToolMessage) and msg.content.startswith("SEND_FILE"):
            _, file_type, path = msg.content.split("|", 2)
            files_to_send.append({"type": file_type, "path": path})
        elif msg.type == "ai" and msg.content:
            text_to_reply = msg.content

    # Reply with text answer if present
    if text_to_reply:
        await update.message.reply_text(text_to_reply)

    # Dispatch files/photos attached by the tool
    for file_info in files_to_send:
        file_path = file_info["path"]
        file_type = file_info["type"]
        
        try:
            with open(file_path, "rb") as file_data:
                if file_type == "photo":
                    await update.message.reply_photo(photo=file_data)
                else:
                    await update.message.reply_document(document=file_data)
        except Exception as e:
            await update.message.reply_text(f"⚠️ Failed to send '{file_path}': {str(e)}")

# ==========================================
# 4. BOT ENTRYPOINT
# ==========================================

def main():
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is missing.")

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Catch any text message (excluding command triggers)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_telegram_message))
    
    print("🤖 Telegram LangGraph Bot started successfully...")
    app.run_polling()

if __name__ == "__main__":
    main()