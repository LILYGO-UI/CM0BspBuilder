from __future__ import annotations

import shutil
import struct
import uuid
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path


SECTOR_SIZE = 512
LINUX_GPT_TYPE = uuid.UUID("0fc63daf-8483-4772-8e79-3d69d8477de4")


class ImageError(RuntimeError):
    pass


@dataclass(frozen=True)
class Partition:
    index: int
    scheme: str
    type_code: str
    start_lba: int
    sectors: int
    name: str = ""

    @property
    def start_bytes(self) -> int:
        return self.start_lba * SECTOR_SIZE

    @property
    def size_bytes(self) -> int:
        return self.sectors * SECTOR_SIZE

    @property
    def end_bytes(self) -> int:
        return self.start_bytes + self.size_bytes

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["start_bytes"] = self.start_bytes
        result["size_bytes"] = self.size_bytes
        return result


class ImageSource:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        if not self.path.is_file():
            raise ImageError(f"image source not found: {self.path}")

        self.zip_member: zipfile.ZipInfo | None = None
        if zipfile.is_zipfile(self.path):
            with zipfile.ZipFile(self.path) as archive:
                members = [
                    item
                    for item in archive.infolist()
                    if not item.is_dir() and item.filename.lower().endswith(".img")
                ]
                if len(members) != 1:
                    raise ImageError(
                        f"expected exactly one .img in {self.path}, found {len(members)}"
                    )
                self.zip_member = members[0]
                self.image_name = Path(self.zip_member.filename).name
                self.image_size = self.zip_member.file_size
        else:
            self.image_name = self.path.name
            self.image_size = self.path.stat().st_size

    @property
    def compressed(self) -> bool:
        return self.zip_member is not None

    def read_prefix(self, size: int = 2 * 1024 * 1024) -> bytes:
        if self.zip_member is not None:
            with zipfile.ZipFile(self.path) as archive:
                with archive.open(self.zip_member) as source:
                    return source.read(size)
        with self.path.open("rb") as source:
            return source.read(size)

    def extract_image(self, destination: str | Path) -> Path:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise ImageError(f"refusing to overwrite extracted image: {destination}")

        if self.zip_member is None:
            return self.path

        with zipfile.ZipFile(self.path) as archive:
            with archive.open(self.zip_member) as source, destination.open("xb") as output:
                shutil.copyfileobj(source, output, length=8 * 1024 * 1024)
        if destination.stat().st_size != self.image_size:
            raise ImageError("extracted image size does not match ZIP metadata")
        return destination


def parse_partitions(prefix: bytes, image_size: int) -> list[Partition]:
    if len(prefix) < SECTOR_SIZE or prefix[510:512] != b"\x55\xaa":
        raise ImageError("image does not contain a valid MBR signature")

    entries: list[tuple[int, int, int, int]] = []
    for index in range(4):
        offset = 446 + index * 16
        type_code = prefix[offset + 4]
        start_lba, sectors = struct.unpack_from("<II", prefix, offset + 8)
        if type_code and sectors:
            entries.append((index + 1, type_code, start_lba, sectors))

    if any(type_code == 0xEE for _, type_code, _, _ in entries):
        partitions = _parse_gpt(prefix)
    else:
        partitions = [
            Partition(index, "mbr", f"0x{type_code:02x}", start_lba, sectors)
            for index, type_code, start_lba, sectors in entries
        ]

    for partition in partitions:
        if partition.start_bytes < 0 or partition.end_bytes > image_size:
            raise ImageError(
                f"partition {partition.index} exceeds image bounds: "
                f"end={partition.end_bytes}, image={image_size}"
            )
    if not partitions:
        raise ImageError("image partition table is empty")
    return partitions


def _parse_gpt(prefix: bytes) -> list[Partition]:
    header_offset = SECTOR_SIZE
    if prefix[header_offset : header_offset + 8] != b"EFI PART":
        raise ImageError("protective MBR found but GPT header is invalid")

    header = struct.unpack_from("<8sIIIIQQQQ16sQIII", prefix, header_offset)
    entries_lba = header[10]
    entry_count = header[11]
    entry_size = header[12]
    if entry_size < 128 or entry_count > 4096:
        raise ImageError("unsupported GPT partition-entry layout")

    entries_offset = entries_lba * SECTOR_SIZE
    entries_end = entries_offset + entry_count * entry_size
    if entries_end > len(prefix):
        raise ImageError(
            f"read prefix is too small for GPT entries; need at least {entries_end} bytes"
        )

    partitions: list[Partition] = []
    for index in range(entry_count):
        offset = entries_offset + index * entry_size
        type_bytes = prefix[offset : offset + 16]
        if type_bytes == b"\0" * 16:
            continue
        type_guid = uuid.UUID(bytes_le=bytes(type_bytes))
        first_lba, last_lba = struct.unpack_from("<QQ", prefix, offset + 32)
        if last_lba < first_lba:
            raise ImageError(f"invalid GPT extent for partition {index + 1}")
        name_bytes = prefix[offset + 56 : offset + min(entry_size, 128)]
        name = name_bytes.decode("utf-16-le", errors="replace").rstrip("\0")
        partitions.append(
            Partition(
                index + 1,
                "gpt",
                str(type_guid),
                first_lba,
                last_lba - first_lba + 1,
                name,
            )
        )
    return partitions


def select_root_partition(partitions: list[Partition]) -> Partition:
    linux = [
        item
        for item in partitions
        if (item.scheme == "mbr" and item.type_code == "0x83")
        or (item.scheme == "gpt" and item.type_code == str(LINUX_GPT_TYPE))
        or "root" in item.name.lower()
    ]
    if not linux:
        raise ImageError("no Linux root filesystem partition was found")
    return max(linux, key=lambda item: item.size_bytes)


def copy_partition(image: Path, partition: Partition, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise ImageError(f"refusing to overwrite partition image: {destination}")

    remaining = partition.size_bytes
    with image.open("rb") as source, destination.open("xb") as output:
        source.seek(partition.start_bytes)
        while remaining:
            chunk = source.read(min(8 * 1024 * 1024, remaining))
            if not chunk:
                raise ImageError("image ended while copying the root partition")
            output.write(chunk)
            remaining -= len(chunk)
