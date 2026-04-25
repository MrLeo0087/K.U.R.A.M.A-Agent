import sys
sys.path.append('..')

import re
import ast
import asyncio
import aiohttp
from pathlib import Path

from langchain_groq import ChatGroq
from langchain_core.output_parsers import StrOutputParser
from NODE.state import KuramaState
from prompt import image_refiner_prompt
from NODE.state import code_generator
from dotenv import load_dotenv
import os

load_dotenv()

GROQ_API  = os.getenv("GROQ_API_KEY")
BASE_URL  = "https://broad-moon-2502.lifejorney1500.workers.dev/"
# BASE_URL  = "https://image-api.satorugojo0087.workers.dev/"
# BASE_URL  = "https://image-ai.iamleo0087.workers.dev/"

IMAGE_DIR = r"D:\My Future\Project\Gen_AI\02_K.U.R.A.M.A\Version_4\Image"
CODE_DIR  = r"D:\My Future\Project\Gen_AI\02_K.U.R.A.M.A\Version_4\generate_content"


# ============================================================
#  IMAGE GENERATION
# ============================================================

async def fetch_image(session, prompt, index):
    try:
        async with session.get(BASE_URL, params={"prompt": prompt}) as response:
            if response.status == 200:
                image_bytes = await response.read()

                clean = re.sub(r'[^\w\s]', '', prompt)[:30].strip().replace(' ', '_')
                filename = os.path.join(IMAGE_DIR, f"image_{index}_{clean}.jpg")

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
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_image(session, prompt, i) for i, prompt in enumerate(prompts)]
        return await asyncio.gather(*tasks)


def run(prompts: list[str]):
    return asyncio.run(generate_images(prompts))


# ============================================================
#  TEMPLATE
# ============================================================

import uuid
from datetime import datetime

def template(task, prompt, llm_name):
    tag = task.content.split(',')[0].strip().lower()

    def node(state: KuramaState):
        try:
            context = ""
            if task.depends_on:
                for parent_id in task.depends_on:
                    parent_result = state['results'].get(parent_id, "")
                    context += f"Previous result: {parent_result}\n"

            query        = state['query']
            task_content = task.content
            task_id      = task.id
            short_id     = str(uuid.uuid4())[:4]
            timestamp    = datetime.now().strftime('%Y%m%d_%H%M%S')

            Path(CODE_DIR).mkdir(parents=True, exist_ok=True)
            if tag == 'generate code':
                llm            = ChatGroq(model=llm_name, api_key=GROQ_API)
                structured_llm = llm.with_structured_output(code_generator)
                chain          = prompt | structured_llm
                result         = chain.invoke({
                    'query'  : query,
                    'task'   : task_content,
                    'context': context[:500]
                })
                name = result.name
                if '.' not in name:
                    name = f"{name}.py"

                if name.endswith('.py'):
                    try:
                        ast.parse(result.code)
                    except SyntaxError as e:
                        print(f"⚠️ Syntax warning: {str(e)}")

                filename = f"{Path(name).stem}_{short_id}{Path(name).suffix}"
                filepath = os.path.join(CODE_DIR, filename)
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(result.code)

            else:
                llm    = ChatGroq(model=llm_name, api_key=GROQ_API)
                chain  = prompt | llm | StrOutputParser()
                result = chain.invoke({
                    'query'  : query,
                    'task'   : task_content,
                    'context': context[:500]
                })

                filename = f"{tag.replace(' ', '_')}_{timestamp}_{short_id}.txt"
                filepath = os.path.join(CODE_DIR, filename)
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(result)

            print(f"✅ Saved: {filepath}")
            return {'results': {task_id: f"{tag.replace('_', ' ').title()} generated successfully. Saved as {filename}"}}

        except SyntaxError as e:
            print(f"❌ Syntax Error: {str(e)}")
            return {'results': {task.id: f"Generated code has syntax error: {str(e)}"}}

        except Exception as e:
            print(f"❌ Exception details: {str(e)}")
            return {'results': {task.id: f"Error: {str(e)}"}}

    return node

# ============================================================
#  CREATE NODE FACTORY
# ============================================================

def make_create_node(task):
    tag = task.content.split(',')[0].strip().lower()

    if tag == 'generate image':
        def node(state: KuramaState):
            try:
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
                    result = f"Image generated successfully"  # ✅ no path
                else:
                    result = f"Image generation failed"

                return {'results': {task_id: result}}

            except Exception as e:
                return {'results': {task.id: f"Image error: {str(e)}"}}

        return node

    elif tag == 'generate letter':
        from prompt import letter_prompt
        return template(task, letter_prompt, 'llama-3.1-8b-instant')

    elif tag == 'generate story':
        from prompt import story_prompt
        return template(task, story_prompt, 'llama-3.3-70b-versatile')

    elif tag == 'generate poem':
        from prompt import poem_prompt
        return template(task, poem_prompt, 'llama-3.3-70b-versatile')

    elif tag == 'generate essay':
        from prompt import essay_prompt
        return template(task, essay_prompt, 'llama-3.1-8b-instant')

    elif tag == 'generate caption':
        from prompt import caption_prompt
        return template(task, caption_prompt, 'llama-3.1-8b-instant')

    elif tag == 'generate report':
        from prompt import report_prompt
        return template(task, report_prompt, 'llama-3.3-70b-versatile')

    elif tag == 'generate email':
        from prompt import email_prompt
        return template(task, email_prompt, 'llama-3.1-8b-instant')

    elif tag == 'generate bio':
        from prompt import bio_prompt
        return template(task, bio_prompt, 'llama-3.1-8b-instant')

    elif tag == 'generate script':
        from prompt import script_prompt
        return template(task, script_prompt, 'llama-3.3-70b-versatile')

    elif tag == 'generate code':
        from prompt import code_prompt
        return template(task, code_prompt, 'openai/gpt-oss-120b')

    else:
        from prompt import create_general_prompt
        return template(task, create_general_prompt, 'llama-3.1-8b-instant')