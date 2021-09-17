from typing import Optional, Tuple

IO_BUFFER_SIZE: int


class JobCapsule:
    pass


def begin_signature(file_size: int = -1, strong_len: int = 0) -> JobCapsule:
    pass


def iter_job(job_capsule: JobCapsule, input_data: bytes, eof: Optional[bool] = None) -> Tuple[bytes, bool]:
    pass
