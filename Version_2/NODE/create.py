import sys
sys.path.append('..')

from langchain_groq import ChatGroq
from langchain_core.output_parsers import StrOutputParser
from state import KuramaState
from ddgs import DDGS
from dotenv import load_dotenv
from NODE.prompt import image_refiner_prompt
import os
import time

load_dotenv()

GROQ_API = os.getenv("GROQ_API_KEY")
import asyncio
import aiohttp
from pathlib import Path

# BASE_URL = "https://image-api.satorugojo0087.workers.dev/"  #SATURO
# BASE_URL = "https://image-ai.iamleo0087.workers.dev/"  #MR_LEO
BASE_URL = "https://broad-moon-2502.lifejorney1500.workers.dev/"  #LIFE_JOURNEY


async def fetch_image(session, prompt, index):
    """Fetch a single image for a given prompt."""
    try:
        async with session.get(BASE_URL, params={"prompt": prompt}) as response:
            if response.status == 200:
                image_bytes = await response.read()
                clean_prompt = prompt[:20].replace(' ', '_').replace('"', '').replace("'", '').replace(',', '')
                filename = rf"D:\My Future\Project\Gen_AI\02_K.U.R.A.M.A\Version_2\Image\image_{index}_{clean_prompt}.jpg"
                Path(filename).write_bytes(image_bytes)
                print(f"✅ [{index}] Saved: {filename}")
                return {"index": index, "prompt": prompt, "file": filename, "success": True}
            else:
                text = await response.text()
                print(f"❌ [{index}] Failed: {text}")
                return {"index": index, "prompt": prompt, "error": text, "success": False}

    except Exception as e:
        print(f"❌ [{index}] Exception: {str(e)}")
        return {"index": index, "prompt": prompt, "error": str(e), "success": False}


async def generate_images(prompts: list[str]):
    """Generate multiple images concurrently."""
    async with aiohttp.ClientSession() as session:
        tasks = [
            fetch_image(session, prompt, i)
            for i, prompt in enumerate(prompts)
        ]
        results = await asyncio.gather(*tasks)
    return results


def run(prompts: list[str]):
    """Main entry point — call this from your code."""
    return asyncio.run(generate_images(prompts))


# --------------- template ---------------------

llm = ChatGroq(model='llama-3.1-8b-instant', api_key=GROQ_API)

def template(task,prompt,llm_name):
    llm = ChatGroq(model=llm_name, api_key=GROQ_API)
    def node(state: KuramaState):
        context = ""
        if task.depends_on:
            for parent_id in task.depends_on:
                parent_result = state['results'].get(parent_id, "")
                context += f"Previous result: {parent_result}\n"

        query = state['query']
        task_content = task.content    
        task_id = task.id              
            
        chain = prompt | llm | StrOutputParser()
        result = chain.invoke({'query': query, 'task': task_content,'context':context[:500]})
        
        return {'results': {task_id: result}}
    return node

def make_create_node(task):
    tag = task.content.split(',')[0].strip().lower()

    if tag == 'generate image':
        def node(state: KuramaState):
            context = ""
            if task.depends_on:
                for parent_id in task.depends_on:
                    parent_result = state['results'].get(parent_id, "")
                    context += f"Previous result: {parent_result}\n"

            query        = state['query']
            task_content = task.content
            task_id      = task.id

            refine_llm   = ChatGroq(model='llama-3.1-8b-instant', api_key=GROQ_API)
            refine_chain = image_refiner_prompt | refine_llm | StrOutputParser()
            refine_query = refine_chain.invoke({'query': query, 'task': task_content})

            results_list = run([refine_query])
            result_info  = results_list[0]

            if result_info['success']:
                result = f"Image created successfully: {task_content}"
            else:
                result = f"Image generation failed: {result_info['error']}"

            return {'results': {task_id: result}}
        return node

    elif tag == 'generate letter':
        from NODE.prompt import letter_prompt
        return template(task, letter_prompt, 'llama-3.1-8b-instant')

    elif tag == 'generate story':
        from NODE.prompt import story_prompt
        return template(task, story_prompt, 'llama-3.3-70b-versatile')

    elif tag == 'generate poem':
        from NODE.prompt import poem_prompt
        return template(task, poem_prompt, 'llama-3.3-70b-versatile')

    elif tag == 'generate essay':
        from NODE.prompt import essay_prompt
        return template(task, essay_prompt, 'llama-3.1-8b-instant')

    elif tag == 'generate caption':
        from NODE.prompt import caption_prompt
        return template(task, caption_prompt, 'llama-3.1-8b-instant')

    elif tag == 'generate report':
        from NODE.prompt import report_prompt
        return template(task, report_prompt, 'llama-3.3-70b-versatile')

    elif tag == 'generate email':
        from NODE.prompt import email_prompt
        return template(task, email_prompt, 'llama-3.1-8b-instant')

    elif tag == 'generate bio':
        from NODE.prompt import bio_prompt
        return template(task, bio_prompt, 'llama-3.1-8b-instant')

    elif tag == 'generate script':
        from NODE.prompt import script_prompt
        return template(task, script_prompt, 'llama-3.3-70b-versatile')

    elif tag == 'generate code':
        from NODE.prompt import code_prompt
        return template(task, code_prompt, 'openai/gpt-oss-120b')

    else:
        from NODE.prompt import create_general_prompt
        return template(task, create_general_prompt, 'llama-3.1-8b-instant')