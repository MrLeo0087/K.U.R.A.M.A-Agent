from langchain.tools import tool
from typing import Optional
from langchain_ollama import ChatOllama 
from langchain_core.prompts import ChatPromptTemplate
import webbrowser,os,smtplib
import requests


import re
import urllib

from dotenv import load_dotenv

load_dotenv()

@tool
def youtube_play(query: str):
    """
Advanced tool for play video on youtube.. it can play or watch any video on youtube. it play video on youtube
"""
    query = query.lower().strip()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    # Extract the actual song name
    search_term = query.replace("play", "").replace("watch", "").replace("on youtube", "").strip()
    if not search_term:
        return "Error: No song name provided."

    encoded_search = urllib.parse.quote(search_term)
    url = f"https://www.youtube.com/results?search_query={encoded_search}"
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        # Look for the "videoId":"XXXXXXXXXXX" pattern which is more stable in modern YouTube HTML
        video_ids = re.findall(r'"videoId":"([^"]{11})"', response.text)
        
        if not video_ids:
            # Fallback to your original regex if the first one fails
            video_ids = re.findall(r"watch\?v=(\S{11})", response.text)

        if video_ids:
            video_url = f"https://www.youtube.com/watch?v={video_ids[0]}&autoplay=1"
            webbrowser.open(video_url)
            return f"SUCCESS: Now playing '{search_term}'."
        else:
            # If no ID found, open the search page so the user isn't left with nothing
            webbrowser.open(url)
            return f"I couldn't autoplay, but I've opened the search results for '{search_term}' for you."
            
    except Exception as e:
        return f"Technical Error: {str(e)}"
    
@tool
def open_browser(target: str):
    """
    Opens any website or search engine in the browser.
    The 'target' can be a full URL (https://google.com) or just a name (facebook).
    """
    if isinstance(target, dict):
        target = target.get("target") or target.get("url") or target.get("name") or str(target)

    target = str(target).strip().lower()


    if not target.startswith(("http://", "https://")):
        if "." in target:
            url = f"https://www.{target}"
        else:
            # If it's just a word (facebook), search or add .com
            url = f"https://www.{target}.com/" 
            # OR use: url = f"https://www.{target}.com"
    else:
        url = target

    try:
        webbrowser.open(url)
        return f"🚀 Action: Browser opened to {url}"
    except Exception as e:
        return f"❌ Failed to open browser: {str(e)}"
    

from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from langchain_core.output_parsers import StrOutputParser

# @tool(return_direct=True)
llm = ChatOllama(model='qwen2.5:3b', temperature=0) 
# branch file - internet_tools/basic_internet_tools.py

@tool
def send_email(target: str, subject: str, body: str, file_path: Optional[str] = None):
    r"""
    Sends an email with an optional file attachment.
    
    Args:
        target: The EXACT recipient email address.
        subject: The subject line of the email.
        body: The full body/content of the email.
        file_path: Optional. Full path to file attachment.
    """
    SENDER_MAIL = os.getenv('SENDER_MAIL')
    SENDER_PASSWORD = os.getenv('SENDER_PASSWORD')

    signature = "\n\nBest regards,\nMr. Leo"

    full_body = body.rstrip() + signature

    # NO MORE INNER LLM - agent itself writes the body
    message = MIMEMultipart()
    message['From'] = SENDER_MAIL
    message['To'] = target
    message['Subject'] = subject
    message.attach(MIMEText(full_body, 'plain'))

    if file_path and os.path.exists(file_path):
        try:
            filename = os.path.basename(file_path)
            with open(file_path, "rb") as attachment:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename={filename}")
            message.attach(part)
        except Exception as e:
            return f"❌ Attachment Error: {e}"

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(SENDER_MAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_MAIL, target, message.as_string())
        return f"✅ SUCCESS: Email sent to {target}"
    except Exception as e:
        return f"❌ Mail Error: {e}"
    
from langchain_community.tools import DuckDuckGoSearchRun
