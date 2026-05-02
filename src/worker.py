from rq import Worker
from rq.job import Job

from .logger import REQUEST_ID_CTX, setup_logging


class CustomWorker(Worker):
    def prepare_job_execution(
        self, job: Job, remove_from_intermediate_queue: bool = False
    ) -> None:
        setup_logging()
        REQUEST_ID_CTX.set(job.meta.get("request_id", "system"))
        return super().prepare_job_execution(job, remove_from_intermediate_queue)
