import struct
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path

from cm0_bsp_builder.image import (
    ImageError,
    ImageSource,
    LINUX_GPT_TYPE,
    parse_partitions,
    select_root_partition,
)


def mbr_image(size: int = 8 * 1024 * 1024) -> bytes:
    image = bytearray(size)
    image[510:512] = b"\x55\xaa"
    struct.pack_into("<B3sB3sII", image, 446, 0, b"\0" * 3, 0x0C, b"\0" * 3, 2048, 1024)
    struct.pack_into("<B3sB3sII", image, 462, 0, b"\0" * 3, 0x83, b"\0" * 3, 4096, 8192)
    return bytes(image)


class ImageTests(unittest.TestCase):
    def test_mbr_selects_largest_linux_partition(self):
        data = mbr_image()
        partitions = parse_partitions(data[: 2 * 1024 * 1024], len(data))
        self.assertEqual(len(partitions), 2)
        self.assertEqual(select_root_partition(partitions).index, 2)
        self.assertEqual(partitions[1].type_code, "0x83")

    def test_gpt_linux_partition(self):
        size = 16 * 1024 * 1024
        data = bytearray(size)
        data[510:512] = b"\x55\xaa"
        struct.pack_into("<B3sB3sII", data, 446, 0, b"\0" * 3, 0xEE, b"\0" * 3, 1, size // 512 - 1)
        header = struct.pack(
            "<8sIIIIQQQQ16sQIII",
            b"EFI PART",
            0x00010000,
            92,
            0,
            0,
            1,
            size // 512 - 1,
            34,
            size // 512 - 34,
            uuid.uuid4().bytes_le,
            2,
            128,
            128,
            0,
        )
        data[512 : 512 + len(header)] = header
        entry_offset = 2 * 512
        data[entry_offset : entry_offset + 16] = LINUX_GPT_TYPE.bytes_le
        data[entry_offset + 16 : entry_offset + 32] = uuid.uuid4().bytes_le
        struct.pack_into("<QQQ", data, entry_offset + 32, 2048, 8191, 0)
        name = "rootfs".encode("utf-16-le")
        data[entry_offset + 56 : entry_offset + 56 + len(name)] = name

        partitions = parse_partitions(data[: 2 * 1024 * 1024], len(data))
        root = select_root_partition(partitions)
        self.assertEqual(root.scheme, "gpt")
        self.assertEqual(root.name, "rootfs")

    def test_zip_source_reads_img_without_extracting(self):
        data = mbr_image()
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "image.zip"
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("factory.img", data)
            source = ImageSource(archive_path)
            self.assertTrue(source.compressed)
            self.assertEqual(source.image_name, "factory.img")
            self.assertEqual(source.image_size, len(data))
            partitions = parse_partitions(source.read_prefix(), source.image_size)
            self.assertEqual(select_root_partition(partitions).index, 2)

    def test_rejects_out_of_bounds_partition(self):
        data = bytearray(mbr_image())
        struct.pack_into("<I", data, 462 + 12, 0xFFFFFFFF)
        with self.assertRaises(ImageError):
            parse_partitions(data[: 2 * 1024 * 1024], len(data))


if __name__ == "__main__":
    unittest.main()

