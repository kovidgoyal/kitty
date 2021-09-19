from typing import Callable, Tuple

IO_BUFFER_SIZE: int


class JobCapsule:
    pass


class SignatureCapsule:
    pass


class RsyncError(Exception):
    pass


def begin_create_signature(file_size: int = -1, strong_len: int = 0) -> Tuple[JobCapsule, int, int]:
    pass


def begin_load_signature() -> Tuple[JobCapsule, SignatureCapsule]:
    pass


def build_hash_table(sig: SignatureCapsule) -> None:
    pass


def begin_create_delta(sig: SignatureCapsule) -> JobCapsule:
    pass


def begin_patch(callback: Callable[[memoryview, int], int]) -> JobCapsule:
    pass


def iter_job(job_capsule: JobCapsule, input_data: bytes, output_buf: bytearray) -> Tuple[bool, int, int]:
    pass
