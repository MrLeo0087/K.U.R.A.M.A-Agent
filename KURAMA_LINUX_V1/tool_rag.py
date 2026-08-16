import os
import sys

# Compute path directly to the TOOLS/GENERAL directory
GENERAL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "TOOLS", "GENERAL")
INTERACTIVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "TOOLS", "INTERACTIVE")
sys.path.append(GENERAL_DIR)
sys.path.append(INTERACTIVE_DIR)

from TOOLS.GENERAL.general_tools import GENERAL_TOOLS_LIST
from TOOLS.INTERACTIVE.interactive_tools import INTERACTIVE_TOOLS

from typing import Dict
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document
from dotenv import load_dotenv

load_dotenv()

embedding_model = OllamaEmbeddings(model='nomic-embed-text:latest')

ALL_TOOLS = list(GENERAL_TOOLS_LIST+INTERACTIVE_TOOLS)

TOOLS_REGISTER : Dict[str,callable] = {t.name:t for t in ALL_TOOLS}

# document =[
#     Document(
#         page_content=f'{t.name}:{t.description}',
#         metadata = {'name': t.name},
#     )
#     for t in ALL_TOOLS
# ]
document = []
for t in ALL_TOOLS:
    # Extract parameter names from args_schema if available
    args_info = ""
    if hasattr(t, "args") and t.args:
        args_info = ", ".join(t.args.keys())
    
    # Enrich the document content
    content = (
        f"Tool Name: {t.name}\n"
        f"Description: {t.description}\n"
        f"Parameters: {args_info}\n"
    )
    
    document.append(
        Document(
            page_content=content,
            metadata={"name": t.name}
        )
    )

vector_store = Chroma.from_documents(
    documents=document,
    embedding=embedding_model,
    collection_name= 'KURAMA_TOOLS'
)
if __name__=='__main__':
    while True:
        user = input('Enter your query: ')
        # Replace similarity_search with MMR search
        results = vector_store.max_marginal_relevance_search(
            user, 
            k=3, 
            fetch_k=10  # Evaluates top 10 candidates before picking top 3 diverse matches
        )
        matched_tool_names = [doc.metadata["name"] for doc in results]

        print(matched_tool_names)

