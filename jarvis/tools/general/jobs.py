"""jobs: list, check, cancel or resume background jobs in one tool (safe).

Merged from list_jobs, job_result, cancel_job and resume_job (their old names still work as aliases).
"""
from __future__ import annotations

from typing import Literal

from jarvis.core.registry import alias, tool
from jarvis.tools.general.cancel_job import cancel_job
from jarvis.tools.general.job_result import job_result
from jarvis.tools.general.list_jobs import list_jobs
from jarvis.tools.general.resume_job import resume_job


@tool(group="jobs", safety="safe",
      description="KURAMA's jobs. Its job LIST (things the user wants KURAMA to do later, not run yet): add, edit, "
                  "remove, start (run the waiting ones now, or one). Background jobs: list, result, cancel, pause, "
                  "resume.")
def jobs(action: Literal["list", "add", "edit", "remove", "start", "result", "cancel", "pause", "resume"] = "list",
         job: str = "", text: str = "") -> str:
    """Manage KURAMA's job list and background jobs.

    Args:
        action: list = the job list + running jobs; add = keep a job for later (text = what to do; nothing runs);
            edit = change job `job` to `text`; remove = drop job `job` ("done" = all finished ones); start = work
            on the waiting jobs now (or just `job`); result = what job N produced (ALWAYS check it here, never do
            the job again yourself); cancel / pause / resume = a background job.
        job: The job's number (list number or background job id), or words from its title.
        text: For add / edit: what the job should do, in the user's words (several jobs: separate them with ";").
    """
    from jarvis.core import jobqueue
    if action == "add":
        return jobqueue.add(text or job)
    if action == "edit":
        return jobqueue.edit(job, text)
    if action == "remove":
        return jobqueue.remove(job)
    if action == "start":
        return jobqueue.start(job)
    if action == "result":
        if (listed := jobqueue.result(job)) is not None and not job.strip().startswith("#"):
            return listed  # the job LIST's numbers first ("#12" = a background job id)
        if not job.strip().lstrip("#").isdigit():
            return "error: give the job's number, e.g. 12"
        return job_result(int(job.strip().lstrip("#")))
    if action == "cancel":
        return cancel_job(job)
    if action == "resume":
        return resume_job(job)
    if action == "pause":
        from jarvis.core import longjobs
        return longjobs.pause(job)
    running = list_jobs()
    return jobqueue.show() + ("\n\nBackground jobs:\n" + running if running != "no background jobs" else "")


alias("list_jobs", "jobs", action="list")
alias("job_result", "jobs", lambda a: {"job": str(a.get("job_id", a.get("job", "")))}, action="result")
alias("cancel_job", "jobs", action="cancel")
alias("resume_job", "jobs", action="resume")
