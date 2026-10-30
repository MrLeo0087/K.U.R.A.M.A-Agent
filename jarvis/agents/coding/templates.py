"""Project templates (0 tokens): the kind of project is picked by MEANING (local model), the template gives the
files, their purpose, requirements and how to run it; the AI then writes only the code of the main files, briefly.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Template:
    kind: str
    title: str
    files: dict[str, str]  # path -> what it holds (the AI writes these; README/requirements come from here)
    requirements: list[str] = field(default_factory=list)
    run: str = "python main.py"
    torch: bool = False  # install the CPU-only PyTorch wheels (no GPU here; ~200 MB instead of ~2 GB)
    examples: tuple[str, ...] = ()


TEMPLATES: dict[str, Template] = {t.kind: t for t in (
    Template("web", "Website (HTML + CSS + JS)",
             {"index.html": "the page; links style.css and script.js", "style.css": "clean, responsive styling",
              "script.js": "the page's behaviour"}, [], "python -m http.server 8000",
             examples=("set up a web development project", "make a website", "create a landing page with html css",
                       "build a portfolio website", "html css javascript project")),
    Template("fastapi", "FastAPI web API",
             {"main.py": "the FastAPI app and its routes", "models.py": "the data models (pydantic)"},
             ["fastapi", "uvicorn"], "uvicorn main:app --reload",
             examples=("create a fastapi project for a todo app", "make a rest api", "build a backend api with fastapi")),
    Template("flask", "Flask web app",
             {"app.py": "the Flask app and its routes", "templates/index.html": "the main page",
              "static/style.css": "styling"}, ["flask"], "python app.py",
             examples=("set up a flask app", "make a flask website", "simple web app with flask")),
    Template("streamlit", "Streamlit app",
             {"app.py": "the Streamlit app"}, ["streamlit"], "streamlit run app.py",
             examples=("build a streamlit dashboard", "make a streamlit app", "data dashboard project")),
    Template("cnn", "PyTorch CNN training",
             {"model.py": "the CNN model", "data.py": "dataset + DataLoaders (torchvision, downloads automatically)",
              "train.py": "training loop with validation accuracy, saves the best model; small defaults for CPU",
              "predict.py": "load the saved model and predict one image"},
             ["torch", "torchvision", "tqdm"], "python train.py", torch=True,
             examples=("setup a cnn model training project", "create a pytorch project to train an image classifier",
                       "train a cnn on mnist", "image classification project with pytorch", "deep learning cnn project",
                       "set up a cnn retrain project", "make a yolo object detection project")),
    Template("ml", "Machine learning (scikit-learn)",
             {"train.py": "load data, train and evaluate a model, save it", "predict.py": "use the saved model"},
             ["scikit-learn", "pandas", "joblib"], "python train.py",
             examples=("make a machine learning project", "train a classifier with scikit-learn",
                       "regression model project", "predict house prices project")),
    Template("data", "Data analysis (pandas)",
             {"analysis.py": "load, clean, analyse and plot the data; saves charts to output/"},
             ["pandas", "matplotlib"], "python analysis.py",
             examples=("start a data analysis project with pandas", "analyse a csv file", "make charts from data")),
    Template("bot", "Telegram bot",
             {"bot.py": "the bot (token from the BOT_TOKEN environment variable)", ".env.example": "BOT_TOKEN="},
             ["python-telegram-bot"], "python bot.py",
             examples=("new project for a telegram bot", "make a telegram bot", "chatbot for telegram")),
    Template("cli", "Python program",
             {"main.py": "the program, with a main() function"}, [], "python main.py",
             examples=("make a new project", "start a new python project", "build me a small app",
                       "create a python script project", "command line tool project")),
)}


def pick(description: str) -> Template:
    """The template whose example requests are closest in meaning (cli when unsure or the model is off)."""
    from jarvis.core import semantic
    table = {k: t.examples for k, t in TEMPLATES.items()}
    best = semantic.best_of(description, "project_kinds", table)
    return TEMPLATES[best[0]] if best and best[1] >= 0.70 else TEMPLATES["cli"]
