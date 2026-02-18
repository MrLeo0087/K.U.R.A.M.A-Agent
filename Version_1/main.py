print("Importing Library .... ")
import sys
import asyncio
import json
from langchain_ollama import ChatOllama
from langchain_classic.agents import AgentExecutor, create_tool_calling_agent

# --- 1. STANDARD IMPORTS ---
from promt import main_prompt
from Basic_tools.basic_tool import get_current_time, get_weather
from system_tools.basic_system_tools import get_system_info
from internet_tools.basic_internet_tools import open_browser, youtube_play, send_email
from internet_tools.messanger_auto import (
    make_facebook_list, delete_facebook_list, view_list, send_message
)
from local_computer_tools.basic_laptop_control import basic_control
from local_computer_tools.app_open import open_app

print("Model Loading ..... ")
model_name = 'qwen2.5:3b'
# model_name = 'qwen2.5:1.5b'
model = ChatOllama(model=model_name, temperature=0,num_ctx=2048)
print("Model Loaded")


    # List tools directly now that they are imported above
tools = [
        get_current_time,
        get_weather,
        get_system_info,
        open_browser,
        youtube_play,
        send_email,
        make_facebook_list,
        delete_facebook_list,
        view_list,
        send_message,
        basic_control,
        open_app
    ]

agent = create_tool_calling_agent(model, tools, main_prompt)

agent_executor = AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=False,
        handle_parsing_errors=True,
        return_intermediate_steps=False,
        max_iterations=5
    )

async def chat_loop():
    print("Warming up...")
    await agent_executor.ainvoke({"input": "hi"})
    print("Ready! ✅\n")

    while True:
        user_query = await asyncio.to_thread(input, "\n[USER]: ")

        # Simplified exit logic
        if user_query.lower() in ['exit', 'quit', 'bye']:
            print("👋 Goodbye!")
            break

        print(" KURAMA IS THINKING...")
        showing_answer = False

        async for event in agent_executor.astream_events(
            {'input': user_query},
            version="v2"
        ):
            kind = event["event"]
            if kind == "on_tool_start":
                print(f"🔧 Using: {event['name']}")
                print(f"   👉 Arguments: {json.dumps(event['data'].get('input'))}")

            if kind == "on_tool_end":
                output = event["data"].get("output")
                if output: print(f"   ✓ Tool Result: {output}")

            if kind == "on_chat_model_stream":
                content = event["data"]["chunk"].content
                if content:
                    if not showing_answer:
                        print(f"\n[K.U.R.A.M.A]: ", end="")
                        showing_answer = True
                    print(content, end='', flush=True)

        print("\n" + "-"*50)

if __name__ == "__main__":
    asyncio.run(chat_loop())