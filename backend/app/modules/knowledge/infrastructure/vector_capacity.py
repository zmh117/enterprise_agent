"""读取 Qdrant 存储卷的可用容量；只作保守暂停，不自动删除数据腾空间。"""

from pathlib import Path
import shutil

from app.modules.knowledge.domain.vector_contract import VectorError


class VectorCapacity:
    def __init__(self, storage_path: Path, *, reserve_bytes: int = 2 * 1024**3) -> None:
        if (
            not storage_path.is_absolute()
            or type(reserve_bytes) is not int
            or reserve_bytes < 256 * 1024**2
        ):
            raise VectorError("knowledge_vector_capacity_config_invalid")
        self.storage_path = storage_path
        self.reserve_bytes = reserve_bytes

    def check(self, remaining_points: int) -> None:
        if type(remaining_points) is not int or not 0 <= remaining_points <= 2_000_000:
            raise VectorError("knowledge_vector_expected_count_invalid")
        try:
            free = shutil.disk_usage(self.storage_path).free
        except OSError:
            raise VectorError("knowledge_vector_capacity_unavailable") from None
        # 1024 维数值外为 payload/索引/写放大预留余量；不是容量保证。
        if free < self.reserve_bytes + remaining_points * 16 * 1024:
            raise VectorError("knowledge_vector_capacity_low")
