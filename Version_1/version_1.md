# K.U.R.A.M.A. (V1.0)

### **Kura Manager Agent**

*An Intelligent OS Orchestration Layer built with LangChain.*

---

## Project Concept

**K.U.R.A.M.A.** is a local autonomous agent designed to transform natural language into actionable system commands. In this first version, the agent acts as a high-speed execution bridge between the user and their PC, utilizing a suite of specialized tools to handle communication, media, and system management.

---

## 🛠 Feature Set (V1.0)

### 🖥️ System & Application Control

* **App Launcher:** Opens any local software (Photoshop, VS Code, etc.) via Start Menu automation.
* **System Diagnostics:** Retrieves real-time hardware status and system information.
* **Media Control:** Execute basic hardware controls like volume adjustment and playback toggles.

### 📧 Communication & Social

* **Email Engine:** Automated SMTP delivery for sending professional emails with attachments.
* **Messenger Integration:** A custom contact management system to save, view, and delete Facebook contacts.
* **Social Tasking:** Automated browser navigation to send messages or initiate voice/video calls on Facebook Messenger.

### 🌐 Web & Utility

* **YouTube Autoplay:** Direct deep-linking to play music or videos based on song titles or keywords.
* **Weather Intelligence:** Location-aware weather reporting using OpenWeatherMap API.
* **Temporal Awareness:** Real-time date and time synchronization.
* **Browser Orchestration:** intelligent URL handling and web navigation.

---

## ⚙️ Technical Architecture (V1.0)

In its current iteration, KURAMA operates as a  **Single-Turn Agent** .

* **Logic Engine:** LangChain (Tool-calling Agent).
* **Local LLM:** Ollama (Qwen 2.5 3B).
* **Automation:** PyAutoGUI & Webbrowser modules.
* **Data Storage:** JSON-based local persistence for contact lists.

---

## ⚠️ Limitations (V1.0)

* **Stateless Execution:** This version has  **no conversational memory** . Every request is treated as a new task. It cannot remember what you said in the previous sentence.
* **Screen Specificity:** PyAutoGUI tools rely on local screen coordinates; performance may vary based on monitor resolution.
* **Single Tasking:** Optimized for executing one tool at a time rather than complex, multi-step workflows.

---

## 🚀 Upcoming in V2 (Roadmap)

* **Long-Term Memory:** Integrating `LangGraph` for stateful conversations and multi-turn reasoning.
* **File Architect:** New tools for reading, writing, and searching local files and document contents.
* **Deep Web Search:** Integration with DuckDuckGo or Tavily for real-time internet research.
* **Enhanced Input/Output:** Adding Speech-to-Text (STT) and Text-to-Speech (TTS) for a full hands-free experience.

---

## 📥 Installation

1. **Clone the Repository:**
   **Bash**

   ```
   git clone https://github.com/your-username/kurama-v1.git
   ```
2. **Environment Configuration:**
   Create a `.env` file to securely store your credentials:
   **Plaintext**

   ```
   SENDER_MAIL=your_email@gmail.com
   SENDER_PASSWORD=your_app_password
   WEATHER_API=your_openweathermap_api_key
   ```
3. **Install Dependencies:**
   **Bash**

   ```
   pip install -r requirements.txt
   ```
4. Install Ollama and run **ollama pull qwen2.5:3b**

---

## 📜 Usage Example

* *"Open Photoshop and play some Lo-Fi music on YouTube."*
* *"What is the weather in Nepalgunj right now?"*
* *"Send an email to [Email] regarding the project update."*
