import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import pyarrow as pa
import pyarrow.fs as pafs
import pyarrow.parquet as pq

from erp_platform.config import Settings


@dataclass(frozen=True)
class Storage:
    """A filesystem plus a root path; every method takes paths relative to the root."""

    fs: pafs.FileSystem
    root: str

    def _path(self, relative: str) -> str:
        return f"{self.root}/{relative}"

    def write_parquet(self, relative: str, table: pa.Table) -> None:
        path = self._path(relative)
        self.fs.create_dir(path.rsplit("/", 1)[0], recursive=True)
        # A local file written in place could be left half-written by a crash, so write beside
        # it and rename. Object stores publish an object only when the upload completes.
        target = path + ".tmp" if isinstance(self.fs, pafs.LocalFileSystem) else path
        pq.write_table(table, target, filesystem=self.fs)
        if target != path:
            self.fs.move(target, path)

    def read_parquet(self, relative: str) -> pa.Table:
        return pq.read_table(self._path(relative), filesystem=self.fs)

    def write_json(self, relative: str, value: object) -> None:
        path = self._path(relative)
        self.fs.create_dir(path.rsplit("/", 1)[0], recursive=True)
        target = path + ".tmp" if isinstance(self.fs, pafs.LocalFileSystem) else path
        with self.fs.open_output_stream(target) as out:
            out.write(json.dumps(value, indent=2, sort_keys=True).encode())
        if target != path:
            self.fs.move(target, path)

    def read_json(self, relative: str) -> dict | None:
        """Return the stored object, or None when the file does not exist."""
        path = self._path(relative)
        if self.fs.get_file_info(path).type == pafs.FileType.NotFound:
            return None
        with self.fs.open_input_stream(path) as src:
            return json.loads(src.read())

    def list_files(self, relative: str = "") -> list[str]:
        """Return every file under `relative`, as paths relative to the root, sorted."""
        base = self._path(relative).rstrip("/")
        infos = self.fs.get_file_info(pafs.FileSelector(base, allow_not_found=True, recursive=True))
        prefix = self.root + "/"
        return sorted(
            info.path.removeprefix(prefix) for info in infos if info.type == pafs.FileType.File
        )


def open_storage(settings: Settings) -> Storage:
    """Turn RAW_URI and the S3_* settings into a filesystem and root path."""
    uri = settings.raw_uri
    if not uri.startswith("s3://"):
        root = Path(uri).resolve()
        root.mkdir(parents=True, exist_ok=True)
        return Storage(pafs.LocalFileSystem(), root.as_posix())
    parsed = urlparse(uri)
    options: dict[str, str] = {}
    if settings.s3_endpoint_url:
        endpoint = urlparse(settings.s3_endpoint_url)
        options["endpoint_override"] = endpoint.netloc
        options["scheme"] = endpoint.scheme
    if settings.s3_access_key_id and settings.s3_secret_access_key:
        options["access_key"] = settings.s3_access_key_id
        options["secret_key"] = settings.s3_secret_access_key
    if settings.s3_region:
        options["region"] = settings.s3_region
    root = f"{parsed.netloc}{parsed.path}".rstrip("/")
    return Storage(pafs.S3FileSystem(**options), root)
