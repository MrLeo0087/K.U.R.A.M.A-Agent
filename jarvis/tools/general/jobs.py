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
      description="Background jobs: list them, show one's result, cancel one, or resume an interrupted writing job.")
def jobs(action: Literal["list", "result", "cancel", "resume"] = "list", job: str = "") -> str:
    """Manage background jobs.

    Args:
        action: list = all jobs and progress, result = a job's output, cancel = stop one, resume = continue one.
        job: The job's id or words from its title (cancel with no job = the latest running one).
    """
    if action == "result":
        if not job.strip().lstrip("#").isdigit():
            return "error: give the job's number, e.g. 12"
        return job_result(int(job.strip().lstrip("#")))
    if action == "cancel":
        return cancel_job(job)
    if action == "resume":
        return resume_job(job)
    return list_jobs()


alias("list_jobs", "jobs", action="list")
alias("job_result", "jobs", lambda a: {"job": str(a.get("job_id", a.get("job", "")))}, action="result")
alias("cancel_job", "jobs", action="cancel")
alias("resume_job", "jobs", action="resume")
