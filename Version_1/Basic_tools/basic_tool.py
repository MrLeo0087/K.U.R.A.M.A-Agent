from langchain.tools import tool
from typing import Optional
import platform,requests,json,psutil,os

from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

@tool
def get_current_time():
    """Return the current time and date formatted as a string"""
    return datetime.now().strftime("%A, %B,%d, %Y, %H:%M:%S")


@tool
def get_weather(city: str = "Nepalgunj"):
    """
    Fetches weather for a city. Input MUST be a string (e.g., 'London').
    If no city is known, use 'Nepalgunj'.
    """
    api_key = os.getenv('WEATHER_API')
    base_url = 'http://api.openweathermap.org/data/2.5/weather'

    if not city or str(city).strip() == "":
        city = "Nepalganj"
    
    city = city.strip()
    if "nepalg" in city.lower():
        params = {
            'lat': 28.05,
            'lon': 81.62,
            'appid': api_key,
            'units': 'metric'
        }
    else:
        params = {
            'q': f"{city}",
            'appid': api_key,
            'units': 'metric'
        }

    try:
        response = requests.get(base_url, params=params)
        data = response.json()

        if data.get('cod') == '404' and "lat" not in params:
            params['q'] = f"{city},NP"
            response = requests.get(base_url, params=params)
            data = response.json()

        if data.get('cod') != 200:
            return f"Error: {data.get('message', 'City not found')}"
        
        name = data['name']
        temp = data['main']['temp']
        desc = data['weather'][0]['description']
        humidity = data['main']['humidity']

        return f"Current weather in {name}: {temp}°C with {desc}. Humidity: {humidity}%."
    
    except Exception as e:
        return f"Request failed: {str(e)}"
    
