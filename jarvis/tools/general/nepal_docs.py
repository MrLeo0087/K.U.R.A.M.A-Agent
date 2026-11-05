"""nepal_docs: answers about Nepal's laws, legal processes, government services and fees, and Nepal general
knowledge (citizenship, passport, marriage and divorce, traffic rules and fines, land, the constitution, districts)
from the owner's Nepal documents service (core/nepaldocs.py). It takes 5-15 s, so it runs as a background job and
the answer arrives in the chat by itself (safe)."""
from __future__ import annotations

from jarvis.core.registry import tool


@tool(group="nepal", safety="safe", max_chars=4000,
      description="Nepal laws, legal processes, government services and fees, and Nepal general knowledge "
                  "(citizenship, passport, marriage, divorce, traffic rules and fines, land, the constitution, "
                  "districts), answered from Nepal's official documents. Not for live news or prices (web).")
def nepal_docs(question: str) -> str:
    """Ask the Nepal documents.

    Args:
        question: The question as the user asked it (any language).
    """
    from jarvis.core import jobs, nepaldocs
    if not nepaldocs.settings()[0]:
        return "error: the Nepal documents service isn't set up (KURAMA_RAG_API_URL in .env)."

    def work(ctx) -> str:
        ctx.progress("Searching the Nepal documents")
        answer = nepaldocs.ask(question, status=lambda m: m and ctx.progress(m[:120]))
        if ctx.job.origin == "telegram":  # the phone gets the answer as a message (send_output reads the file)
            from jarvis.core import writer
            p = writer.output_path(ctx.job.title)
            p.write_text(answer + "\n", encoding="utf-8")
            ctx.set_output(p)
        ctx.progress("» " + answer)  # the chat shows (and speaks) this as the reply
        return answer

    title = "Nepal documents: " + " ".join(question.split())[:50]
    job = jobs.get_manager().submit(title, "nepal_docs", work, question)
    return (f"Looking that up in the Nepal documents (job #{job.id}). The answer will appear here in a few "
            "seconds.")
