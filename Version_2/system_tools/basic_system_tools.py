from langchain.tools import tool
from typing import Optional
import platform

import psutil
from datetime import datetime


@tool
def get_system_info(need: Optional[str] = "all"):
    """
    Returns system information based on what you need.
    
    Parameters:
    - need: What information to return. Options: 'cpu', 'ram', 'os','disk','battery' 'all' (default: 'all')
    
    Examples:
    - "What's my RAM?" → need='ram'
    - "Check CPU usage" → need='cpu'
    - "What OS am I on?" → need='os'
    -"what is my Local Disk C condition?" → need='disk'
    -'what bettery remain?' → need='battery' 
    - "System stats" → need='all'
    """
    need = need.lower() if need else "all"

    if need == 'cpu':
        cpu = psutil.cpu_percent(interval=1)
        return f"CPU Usage: {cpu}%"
  
    elif need == 'ram':
        ram = psutil.virtual_memory().percent
        ram_used = psutil.virtual_memory().used / (1024**3)
        ram_total = psutil.virtual_memory().total / (1024**3)
        return f"RAM Usage: {ram}% ({ram_used:.2f} GB / {ram_total:.2f} GB used)"
    
    # Get OS info
    elif need == 'os':
            os_name = platform.system()
            os_version = platform.release()
            return f"Operating System: {os_name} {os_version}"
        
    elif need == 'disk':
            try:
                # Get C: drive info
                disk_c = psutil.disk_usage('C:/')
                disk_c_total = disk_c.total / (1024**3)
                disk_c_used = disk_c.used / (1024**3)
                disk_c_free = disk_c.free / (1024**3)
                disk_c_percent = disk_c.percent
                
                result = f"""Disk C: Usage
        - Used: {disk_c_used:.2f} GB
        - Free: {disk_c_free:.2f} GB
        - Total: {disk_c_total:.2f} GB
        - Usage: {disk_c_percent}%"""
                
                # Try to get D: drive (might not exist)
                try:
                    disk_d = psutil.disk_usage('D:/')
                    disk_d_total = disk_d.total / (1024**3)
                    disk_d_used = disk_d.used / (1024**3)
                    disk_d_free = disk_d.free / (1024**3)
                    disk_d_percent = disk_d.percent
                    
                    result += f"""

        Disk D: Usage
        - Used: {disk_d_used:.2f} GB
        - Free: {disk_d_free:.2f} GB
        - Total: {disk_d_total:.2f} GB
        - Usage: {disk_d_percent}%"""
                except:
                    # D: drive doesn't exist
                    pass
                
                return result
            
            except Exception as e:
                return f"Error getting disk info: {e}"
            
    elif need == 'battery':
        battery = psutil.sensors_battery()

        if battery:
            return f"Battery : {battery.percent}% \nPlugged In: {battery.power_plugged}"


    else:     
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory().percent
        os_name = platform.system()
        os_version = platform.release()
        
        return f"""System Information:
- CPU Usage: {cpu}%
- RAM Usage: {ram}%
- OS: {os_name} {os_version}"""

