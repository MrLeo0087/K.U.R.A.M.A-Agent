# K.U.R.A.M.A.

### **Kura Manager Agent**

*A sophisticated, LangGraph-powered orchestration layer for seamless Human-Computer Interaction.*

---

## 📌 Overview

**K.U.R.A.M.A.** (Knowledge-based Universal Remote & Assistant Manager Agent) is an advanced autonomous agent designed to bridge the gap between natural language and operating system control. By leveraging **LangChain** for tool orchestration and **LangGraph** for complex state management, KURAMA moves beyond simple "commands" to understand intent, manage multi-step workflows, and provide a humanized interface for your local machine.

---

## 🛠 Features

### 🎙️ Multi-Modal Interface

* **Input:** Supports **Voice** (STT) and **Text** (CLI/GUI).
* **Output:** Responses via **Voice** (TTS),  **Text** , and **Execution** (Task completion).
* **Humanized Interaction:** Uses context-aware LLMs to provide conversational feedback rather than robotic status updates.

### 💻 System & Workspace Automation

* **App Orchestration:** Launch and terminate local applications.
* **System Controls:** Direct manipulation of system settings (Volume, Brightness, Mute, Sleep, and Media controls).
* **File Architect:** Create folders, manage directories, and generate file content dynamically.
* **Document Synthesis:** Draft professional applications, letters, and reports based on minimal user prompts.

### 🌐 Web & Communication Intelligence

* **Advanced Browsing:** Open/close tabs, navigate to URLs, and perform deep-search queries across multiple search engines.
* **Social Connectivity:** Integrated support for sending  **Emails** ,  **WhatsApp messages** , and initiating calls via automated UI interaction or API bridges.

### ✨ "Next-Gen" (Interesting) Features

* **Self-Correction:** If a tool fails (e.g., a browser tab doesn't open), the agent uses LangGraph to catch the error and retry with a different strategy.
* **Contextual Memory:** Remembers previous tasks within a session (e.g., "Now send that file to my boss").
* **Autonomous Planning:** Instead of one-to-one commands, you can give a goal: *"I'm starting my workday."* KURAMA will open Slack, your IDE, start your "Focus" playlist, and check your calendar.

---

## 🏗 Architecture

KURAMA is built on a "Plan-and-Execute" loop:

1. **Perception:** Captures input (Voice/Text).
2. **Reasoning (LangGraph):** The agent determines the state and which tool to call.
3. **Action (LangChain Tools):** Executes local Python scripts to interact with the OS (PyAutoGUI, OS, SMTP, etc.).
4. **Verification:** Confirms the task success and reports back in a humanized tone.---


## 📜 Usage Examples

* **Voice:** *"Kurama, I need to write a formal leave application for tomorrow and email it to my manager."*
* **Text:** `open photoshop and find a lo-fi playlist on youtube`
* **Voice:** *"Mute the volume and close all browser tabs."*

# Note

***Idea and plan can update in future***
