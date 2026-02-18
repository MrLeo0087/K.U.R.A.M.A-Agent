from langchain.tools import tool 
import json,time,pyautogui
import os,webbrowser
from typing import Optional 
from datetime import datetime

CONTACT_FILE = 'messanger_list.json'

def save_list(file):
    with open(CONTACT_FILE,'w') as f:
        json.dump(file,f,indent=4)
    return True

def load_facebook_contacts():
    """Load saved Facebook contacts from file."""
    try:
        if os.path.exists(CONTACT_FILE):
            with open(CONTACT_FILE, 'r') as f:
                return json.load(f)
        return {}
    except Exception as e:
        print(f"Error loading contacts: {e}")
        return {}

messanger_contact = load_facebook_contacts()   


@tool
def make_facebook_list(nickname: str, facebook_id: str, real_name: str):
    """
    Use this tool to save a Facebook contact into the messenger list.
    
    Args:
        nickname: A short, simple identifier (e.g., 'boss', 'mom', 'bestie').
        facebook_id: The username or numeric ID found in their profile URL.
        real_name: The full legal name of the person (default to 'Not provided').

    Examples of how to extract data:
    - "save facebook contact nickname partner id praks234 full name prakash" 
      -> nickname="partner", facebook_id="praks234", real_name="prakash"
    - "add my friend dalli, her facebook is sunita.12 and name is Sunita Mahatara" 
      -> nickname="dalli", facebook_id="sunita.12", real_name="Sunita Mahatara"
    - "save boss with id 10002345" 
      -> nickname="boss", facebook_id="10002345", real_name="Not provided"
    """
    global messanger_contact

    print(f"DEBUG: Attempting to save {nickname}...")

    stored_key = list(messanger_contact.keys())

    if nickname in stored_key:
        return f"Nickname already in list, Try different nickname"


    messanger_contact[nickname] = {
        'facebook_id':facebook_id,
        'real_name':real_name,
        'save_date':datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    if save_list(messanger_contact):
        return f"✅ Saved contact!\n\nNickname: {nickname}\nFacebook ID: {facebook_id}\nReal Name: {real_name or 'Not provided'}\n\nYou can now say: 'send message to {nickname}'"
    
    else:
        return f"Cannot save list .. Try again"
    

from typing import Union, List

@tool
def delete_facebook_list(nickname: Union[str, List[str]]):
    """
    Use this tool to delete one or more contacts from the facebook list.
    Args:
        nickname: Can be a single name (string) or multiple names (list).
    """
    global messanger_contact

    if isinstance(nickname, str):
        names_to_delete = [nickname]
    else:
        names_to_delete = nickname

    results = []
    
    for name in names_to_delete:
        target = str(name).lower().strip()
        
        if target in messanger_contact:
            del messanger_contact[target]
            results.append(f"✅ Deleted '{target}'")
        else:
            results.append(f"❌ '{target}' not found")

    if save_list(messanger_contact):
        return "\n".join(results)
    else:
        return "❌ Failed to save changes to the file."
        
@tool
def view_list():
    """
   use this tool for view list of facebook contact. this function return all avaliable list 
   Args:
        nickname : short name of persong like (dad,partner,dalli,sathi)

    """
    global messanger_contact
    if not messanger_contact:
        return "📭 No contacts saved yet.\n\nUse 'save facebook contact' to add people!"
    
    result = "👥 **Saved Facebook Contacts:**\n\n"
    for nickname, info in messanger_contact.items():
        real_name = info.get('real_name', 'N/A')
        facebook_id = info.get('facebook_id', 'N/A')
        result += f"• **{nickname}**\n"
        result += f"  Name: {real_name}\n"
        result += f"  ID: {facebook_id}\n\n"
    
    return result

@tool
def send_message(nickname:str,task:str,message:Optional[str] = None):
    """
    Use this tool to send a message, make a voice call, or start a video call.
    
    Args:
        nickname: The short name of the contact (e.g., dad, partner).
        task: The action to perform ('message', 'call', or 'videocall').
        message: The text to send (ONLY required if task is 'message').

    Example:
        user_query = call partner {nickname: 'partner',task: 'call', message: None}
        user_query = video call to  partner {nickname: 'partner',task: 'videocall', message: None}
        user_query = message partner {nickname: 'partner',task: 'message', message: 'i am ok'}
    """

    global messanger_contact

    if isinstance(nickname, list):
        nickname = nickname[0]

    task = task.lower().strip()
    nickname = nickname.lower().strip()

    if nickname not in messanger_contact:
        return f"❌ Nickname '{nickname}' not found in contacts."

    fb_id = messanger_contact[nickname]['facebook_id'] 
    URLS = f'https://www.facebook.com/messages/t/{fb_id}'

    if task == 'message':
        if not message:
            return f"what message send to {nickname}"
        try:
            webbrowser.open(URLS)
            time.sleep(6)
            pyautogui.leftClick(1202, 1134) 
            time.sleep(2)
            pyautogui.write(message, interval=0.1)
            pyautogui.press('enter') 
            return f"✅ Message sent to {nickname}!"

        except Exception as e:
            return f"Error: {e}"
        
    if task == 'videocall':
        try:
            webbrowser.open(URLS)
            time.sleep(6)
            pyautogui.leftClick(1202, 1134) 
            time.sleep(2)
            pyautogui.leftClick(1270,288)
            time.sleep(4)
            pyautogui.leftClick(299,548)
            time.sleep(2)
            pyautogui.leftClick(311,725)
            time.sleep(3)
            return f"Video call to {nickname} complete!"
        
        except Exception as e:
            return f"Error: {e}"

    if task == 'call':
        try:
            webbrowser.open(URLS)
            time.sleep(6)
            pyautogui.leftClick(1202, 1134) 
            time.sleep(2)
            pyautogui.leftClick(1216,276)
            time.sleep(1)
            return f"Voice call to {nickname} complete!"
        
        except Exception as e:
            return f"Error: {e}"

    
    return f"Task '{task}' completed."