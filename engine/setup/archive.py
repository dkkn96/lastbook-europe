"""Read a split release ZIP without making a second copy of the download."""

import bisect
import io
import os
from contextlib import ExitStack, contextmanager


class _Parts(io.RawIOBase):
    def __init__(self, files):
        self.files = files
        self.offsets = [0]
        for file in files:
            self.offsets.append(self.offsets[-1] + os.fstat(file.fileno()).st_size)
        self.position = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def seek(self, offset, whence=os.SEEK_SET):
        if whence == os.SEEK_CUR:
            offset += self.position
        elif whence == os.SEEK_END:
            offset += self.offsets[-1]
        elif whence != os.SEEK_SET:
            raise ValueError('Invalid seek origin.')
        if offset < 0:
            raise OSError('Cannot seek before the start of the map archive.')
        self.position = offset
        return offset

    def tell(self):
        return self.position

    def readinto(self, buffer):
        if not buffer or self.position >= self.offsets[-1]:
            return 0
        index = bisect.bisect_right(self.offsets, self.position) - 1
        part = self.files[index]
        part.seek(self.position - self.offsets[index])
        length = min(len(buffer), self.offsets[index + 1] - self.position)
        read = part.readinto(memoryview(buffer)[:length])
        if not read:
            raise OSError('A part of the map archive ended before its declared size.')
        self.position += read
        return read


@contextmanager
def open_parts(paths):
    with ExitStack() as stack:
        files = [stack.enter_context(open(path, 'rb')) for path in paths]
        reader = stack.enter_context(io.BufferedReader(_Parts(files)))
        yield reader
